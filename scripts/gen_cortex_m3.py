#!/usr/bin/env python3
"""gen_cortex_m3.py — build-time generator for the Module 3 Cortex Bank data sets.

Run once, output committed, reviewed as content.  Never run at track setup:
the gold sections and questions in these files are curated content that
``private/validate_heldout.py`` (grading standard T9) validates before any
grader is written against them.

    python3 scripts/gen_cortex_m3.py                # full build
    python3 scripts/gen_cortex_m3.py --smoke        # 2 docs per bucket, 10 memos
    python3 scripts/gen_cortex_m3.py --only sar     # one data set
    python3 scripts/gen_cortex_m3.py --validate     # re-run T9 checks, no API calls

Produces, under ``data/``:

    cortex-sar-narratives/bucket_{1k,3k,8k,20k,40k}.jsonl   40 SAR narratives
    cortex-sar-passages/passages.jsonl                      section-level split
    cortex-investigations/investigations.jsonl               24 wire-fraud reports
    cortex-investigation-facts.json                          pre-computed fact index
    cortex-cases/cases.jsonl                                 120 case memos (full)
    cortex-cases/cortex-cases.ndjson                         6-field bulk-load file
    cortex-cases-questions.json                              40 intent-labelled questions
    dev-sets/m3/track-3-1/dev-queries-sar.json               40 (8 per bucket)
    dev-sets/m3/track-3-1/dev-queries-investigations.json    8
    dev-sets/m3/track-3-3/dev-queries.json                   20
    dev-sets/m3/track-3-4/dev-claim-questions.json           10

Design notes that matter for correctness
----------------------------------------
*Gold literal uniqueness.*  Every currency figure that appears anywhere in the
corpus is drawn from one global allocator that never issues the same formatted
string twice, so no two documents can share an amount by construction.  The
only currency figures exempt are the regulatory constants in
``REG_CONSTANTS`` ($10,000 CTR threshold and friends), which are *supposed* to
repeat and are never used as gold literals.  Model-emitted figures are rewritten
to document-owned allocations by :func:`sanitize_amounts`.  A final
:func:`enforce_gold_uniqueness` pass scans the assembled corpus for every gold
literal — amount, entity, and date — and rewrites any occurrence found outside
its owning document.  That pass is the airtight guarantee; the allocator just
keeps it from having much work to do.

*Length control.*  Prose sections are generated in parallel against word
targets, so a document's length is only approximately known until it is
assembled.  Each document therefore carries a deterministic exhibit section
(transaction ledger, wire detail listing, alert disposition log) that acts as
the elastic buffer: :func:`fit_to_budget` adds or removes exhibit rows to land
inside the bucket's token target.  The header, key finding, and conclusion are
never trimmed.

*Coherence across calls.*  A 40k-token narrative is 25+ model calls.  Every
call receives the same deterministic case dossier (subjects, accounts, amounts,
dates, typology, counterparties), which is the shared ground truth that keeps
independently generated sections agreeing with each other.

*Reproducibility.*  ``random.seed(42)`` plus a per-document derived RNG, so
parallel execution cannot change any allocation.  Model responses are cached on
disk by prompt hash (``ARA_GEN_CACHE``), so a re-run after a crash is cheap and
produces the same corpus.
"""

from __future__ import annotations

import argparse
import concurrent.futures as futures
import hashlib
import json
import os
import random
import re
import sys
import threading
import time
from datetime import date, timedelta
from pathlib import Path

# ── Configuration ─────────────────────────────────────────────────────────────

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "data"

SEED = 42
GENERATOR_VERSION = "1.0.0"

# Overridable so the script is reproducible on any Vertex project.
GEN_MODEL = os.environ.get("ARA_GEN_MODEL", "gemini-3.1-pro-preview")
# Bump when the request configuration changes, to invalidate the response cache.
REQUEST_CONFIG_ID = "tb0-text-v2"
GCP_PROJECT = os.environ.get("ARA_GEN_GCP_PROJECT", "elastic-sa")
GCP_LOCATION = os.environ.get("ARA_GEN_GCP_LOCATION", "global")

CACHE_DIR = Path(
    os.environ.get("ARA_GEN_CACHE", str(Path.home() / ".cache" / "ara-gen-cortex-m3"))
)
MAX_WORKERS = int(os.environ.get("ARA_GEN_WORKERS", "14"))
MAX_RETRIES = 4

BUCKETS = {
    "bucket_1k": 1_000,
    "bucket_3k": 3_000,
    "bucket_8k": 8_000,
    "bucket_20k": 20_000,
    "bucket_40k": 40_000,
}
BUCKET_ORDER = ["bucket_1k", "bucket_3k", "bucket_8k", "bucket_20k", "bucket_40k"]
SARS_PER_BUCKET = 8
QUESTIONS_PER_SAR = 3          # spec asks for 2; see MANIFEST_NOTES
N_INVESTIGATIONS = 24
N_CASES_PER_CELL = 8           # 5 case types x 3 risk tiers x 8 = 120
N_CASE_QUESTIONS = 40

CASE_TYPES = ["structuring", "wire_fraud", "sanctions", "kyc_gap", "elder_exploitation"]
RISK_TIERS = ["low", "medium", "high"]
INV_OUTCOMES = ["closed_no_action", "referred_to_fincen", "criminal_referral", "ongoing"]

# Currency figures that are regulatory constants: they repeat across documents on
# purpose and are never gold literals.
REG_CONSTANTS = {
    "$10,000", "$10,000.00", "$5,000", "$5,000.00", "$3,000", "$3,000.00",
    "$2,000", "$2,000.00", "$1,000", "$1,000.00", "$25,000", "$25,000.00",
    "$250,000", "$250,000.00", "$100,000", "$100,000.00", "$50,000", "$50,000.00",
    "$500", "$500.00", "$200", "$200.00", "$1,500", "$1,500.00",
}

# Names retired by the M3 rework spec (section 8) — lint fails on any of them.
FORBIDDEN_NAME_FRAGMENTS = ["acme", "meridian", "northstar", "novalux"]
# Never let a vendor or model name leak into learner-facing corpus text.
FORBIDDEN_TOKEN_RE = re.compile(
    r"\b(gpt-|claude-|gemini-|haiku|anthropic|openai)\b", re.IGNORECASE
)

MANIFEST_NOTES = [
    "Deviation from 06-rework-M3.md section 8: the spec says two questions per SAR "
    "narrative and 16 questions across the investigation reports. This generator "
    "emits three per narrative (24 per bucket) and one per report (24 total) "
    "because track 3.1 challenge 02 needs 8 public dev questions plus 10 held-out "
    "questions per bucket and 8 plus 10 for investigations; the spec's counts are "
    "one and two short respectively. Extras are spare, not required.",
    "Field aliases: SAR records carry both section_id ('sar-NNN-kf', the spec's "
    "label for the gold section) and key_finding_section_id (the real passage id in "
    "cortex-sar-passages that dev sets and checks reference). Case records carry "
    "both filing_date (06 section 4 / the bulk-load file) and date_opened (the "
    "Phase 0 task brief), and both case_id and doc_id, with identical values.",
    "Dev-set query objects carry relevant_ids, relevant_passage_ids, and "
    "relevant_doc_ids so they satisfy every gold_field contract in "
    "lib/ara_metrics.precision_at_k without the consumer having to remap.",
    "cortex-cases/cortex-cases.ndjson holds only the six fields track 3.3 "
    "challenge 02 maps and bulk-loads (case_id, case_type, risk_tier, filing_date, "
    "title, body). Gold literals and contamination labels stay in cases.jsonl so "
    "they are never indexed into the learner's index.",
]

# ── Token counting ────────────────────────────────────────────────────────────

_ENC = None
_ENC_LOCK = threading.Lock()


def token_count(text: str) -> int:
    """Token count used for every budget in this generator.

    cl100k_base when tiktoken is importable, else a calibrated word-count
    approximation.  The same convention ``ara_metrics.token_count`` uses, so the
    bucket labels mean the same thing to the learner, the check, and this file.
    """
    global _ENC
    if _ENC is None:
        with _ENC_LOCK:
            if _ENC is None:
                try:
                    import tiktoken
                    _ENC = tiktoken.get_encoding("cl100k_base")
                except Exception:
                    _ENC = False
    if _ENC:
        return len(_ENC.encode(text))
    return int(len(text.split()) * 1.33) + 1


# ── Unique-literal allocators ─────────────────────────────────────────────────


class AmountBank:
    """Issues plausible BSA/AML currency figures, never the same string twice."""

    def __init__(self, rng: random.Random) -> None:
        self._rng = rng
        self._seen = set(a.replace("$", "").replace(",", "") for a in REG_CONSTANTS)
        self._lock = threading.Lock()

    def _issue(self, lo: int, hi: int, round_cents: bool) -> str:
        with self._lock:
            for _ in range(10_000):
                dollars = self._rng.randint(lo, hi)
                cents = 0 if round_cents else self._rng.randint(1, 99)
                key = "%d.%02d" % (dollars, cents)
                if key in self._seen:
                    continue
                self._seen.add(key)
                return "${:,}.{:02d}".format(dollars, cents)
        raise RuntimeError("AmountBank exhausted")

    def ranged(self, lo: int, hi: int, round_prob: float = 0.0) -> str:
        return self._issue(lo, hi, round_cents=self._rng.random() < round_prob)

    def reserve(self, formatted: str) -> None:
        """Claim a figure computed outside the allocator so it is never reissued."""
        with self._lock:
            self._seen.add(formatted.replace("$", "").replace(",", ""))

    def gold(self, scale: str = "commercial") -> str:
        """The distinctive gold figure, sized to who the subject is.

        A $2.9M loss on a retail customer is not a plausible compliance
        document, so retail subjects get retail magnitudes.
        """
        if scale == "retail":
            return self._issue(18_000, 420_000, round_cents=False)
        return self._issue(90_000, 2_600_000, round_cents=False)

    def decoy(self, small: bool = False) -> str:
        """A supporting figure for ledgers, exhibits, and narrative colour."""
        if small:
            return self._issue(410, 9_980, round_cents=self._rng.random() < 0.35)
        return self._issue(1_100, 880_000, round_cents=self._rng.random() < 0.30)


# What the named figures in each typology actually are.  Handing the model a
# labelled figure ("an individual sub-threshold cash deposit: $9,412.18") instead
# of a bare list is what stops a structuring narrative from describing deposits
# "clustered between $4,499.73 and $6,148.68", which is not structuring.
AMOUNT_SPECS = {
    "structuring": [
        ("the aggregate cash volume deposited during the review period", "aggregate"),
        ("an individual sub-threshold cash deposit", "sub_threshold"),
        ("a second individual sub-threshold cash deposit", "sub_threshold"),
        ("a third individual sub-threshold cash deposit", "sub_threshold"),
        ("the largest single outbound transfer that followed the deposits", "mid"),
    ],
    # wire_fraud is special-cased in signature_amounts(): its figures are
    # arithmetically derived from the wire amount rather than drawn
    # independently, because frozen + residual must equal the wire.
    "wire_fraud": [
        ("the fraudulent outbound wire amount", "aggregate"),
        ("the amount frozen at the receiving institution", "mid"),
        ("the residual loss to the customer after recovery efforts", "mid"),
    ],
    "sanctions": [
        ("the aggregate value of the screened transactions under review", "aggregate"),
        ("the payment blocked and reported", "mid"),
        ("the declared value of the shipment named in the trade documents", "mid"),
        ("a second payment held pending resolution of the name match", "mid"),
    ],
    "kyc_gap": [
        ("the aggregate activity conducted on the deficient file", "aggregate"),
        ("the unverified initial funding amount", "mid"),
        ("the largest single transaction with no source-of-funds evidence", "mid"),
        ("the balance held when the file deficiency was identified", "mid"),
    ],
    "elder_exploitation": [
        ("the aggregate amount withdrawn during the review period", "aggregate"),
        ("a single withdrawal directed by the accompanying party", "small_series"),
        ("a second withdrawal directed by the accompanying party", "small_series"),
        ("a third withdrawal directed by the accompanying party", "small_series"),
        ("the balance remaining after the withdrawals", "mid"),
    ],
}


def signature_amounts(case_type: str, bank: AmountBank, scale: str) -> list:
    """Labelled figures for one document, sized to the typology and the subject."""
    if case_type == "wire_fraud":
        wire = (bank.ranged(60_000, 520_000) if scale == "retail"
                else bank.ranged(300_000, 4_200_000))
        cents = int(wire.split(".")[1])
        total = float(wire.replace("$", "").replace(",", ""))
        frozen = round(total * (0.08 + (cents % 28) / 100.0), 2)
        residual = round(total - frozen, 2)
        frozen_s = "${:,.2f}".format(frozen)
        residual_s = "${:,.2f}".format(residual)
        bank.reserve(frozen_s)
        bank.reserve(residual_s)
        return [
            {"label": "the fraudulent outbound wire amount", "amount": wire,
             "kind": "aggregate"},
            {"label": "the amount frozen at the receiving institution, a part of the "
                      "wire amount and not a separate transfer",
             "amount": frozen_s, "kind": "mid"},
            {"label": "the residual loss to the customer, which is the wire amount "
                      "less the amount frozen",
             "amount": residual_s, "kind": "mid"},
        ]
    out = []
    for label, kind in AMOUNT_SPECS[case_type]:
        if kind == "aggregate":
            # Non-round cents: the aggregate doubles as the gold literal in the
            # investigation reports, where the diverted sum and the wire amount
            # are the same figure.
            amt = (bank.ranged(60_000, 520_000) if scale == "retail"
                   else bank.ranged(300_000, 4_200_000))
        elif kind == "sub_threshold":
            amt = bank.ranged(8_200, 9_850)
        elif kind == "small_series":
            amt = bank.ranged(1_500, 9_500, 0.25)
        else:
            amt = (bank.ranged(5_000, 180_000, 0.2) if scale == "retail"
                   else bank.ranged(20_000, 900_000, 0.2))
        out.append({"label": label, "amount": amt, "kind": kind})
    return out


FIRST_NAMES = [
    "Adrian", "Alina", "Amara", "Anders", "Benedict", "Beatriz", "Callum", "Camila",
    "Cyrus", "Damaris", "Dashiell", "Delia", "Desmond", "Eamon", "Elowen", "Ephraim",
    "Esperanza", "Fenwick", "Florentina", "Gabriel", "Genevieve", "Gideon", "Halcyon",
    "Harriet", "Ignatius", "Imani", "Isadora", "Jasper", "Juno", "Kenji", "Kirsten",
    "Lachlan", "Leocadia", "Lorcan", "Magnus", "Marisol", "Mattias", "Nadia",
    "Nikolai", "Oriana", "Osman", "Percival", "Philippa", "Quentin", "Rafferty",
    "Rosalind", "Rudolpho", "Sabine", "Saoirse", "Séverin", "Solveig", "Tamsin",
    "Thaddeus", "Ulises", "Valentina", "Verity", "Wilhelmina", "Xiomara", "Yusuf",
    "Zephyrine",
]
LAST_NAMES = [
    "Abernathy", "Ashworth", "Balogun", "Bellweather", "Braithwaite", "Calloway",
    "Cárdenas", "Chanthavong", "Cromwell", "Dalrymple", "Delacroix", "Eriksson",
    "Fairweather", "Fontaine", "Galbraith", "Grimaldi", "Hallstrom", "Harkness",
    "Ibarra", "Jankowski", "Kaminski", "Kirkpatrick", "Larkspur", "Lindqvist",
    "Macallister", "Marchetti", "Nakashima", "Oyelaran", "Pemberton", "Petrosyan",
    "Quintanilla", "Ravensworth", "Rosenthal", "Saltonstall", "Schuyler", "Sinclair",
    "Stavropoulos", "Thackeray", "Tillingham", "Underhill", "Vandermeer", "Vasquez",
    "Wainwright", "Whitlock", "Wolcott", "Yarborough", "Zaleski", "Zimmerman",
    "Okonkwo", "Beaumont", "Castellanos", "Duvall", "Fitzgerald", "Hawthorne",
]
COMPANY_FIRST = [
    "Anvil", "Aperture", "Ardent", "Bastion", "Beacon", "Bluewater", "Bramblewood",
    "Bright Harbor", "Cardinal", "Cascadia", "Cedarline", "Clearspan", "Coastal Ridge",
    "Copperfield", "Cornerstone", "Crescent", "Driftwood", "Eastbrook", "Emberline",
    "Fairmount", "Falcon Crest", "Fieldstone", "Foxglove", "Glenhaven", "Granite Point",
    "Greystone", "Harborview", "Hearthstone", "Highfield", "Ironwood", "Jasperline",
    "Kestrel", "Lakebridge", "Lanternhill", "Larkfield", "Limestone", "Mapleford",
    "Marblehead", "Millpond", "Oakhurst", "Obsidian", "Orchard Gate", "Pinnacle Ridge",
    "Quarrystone", "Redstone", "Riverbend", "Saltmarsh", "Sandpiper", "Silverthorn",
    "Slateford", "Stonebridge", "Summit Gate", "Thistledown", "Tidewater", "Umberfield",
    "Vantage Point", "Waterstone", "Westmarch", "Wheatfield", "Windlass",
]
COMPANY_CORE = [
    "Trading", "Logistics", "Holdings", "Ventures", "Consulting", "Imports",
    "Exports", "Freight", "Commodities", "Distribution", "Management", "Capital",
    "Industrial Supply", "Textiles", "Equipment", "Fabrication", "Marine Services",
    "Produce", "Metals", "Machinery",
]
COMPANY_SUFFIX = ["LLC", "Inc.", "Group LLC", "Partners LP", "Corp.", "Enterprises LLC",
                  "Holdings Ltd.", "Trading Co."]


class EntityBank:
    """Issues unique person and company names from the compliance domain."""

    def __init__(self, rng: random.Random) -> None:
        self._rng = rng
        self._seen = set()
        self._lock = threading.Lock()

    @staticmethod
    def _forbidden(name: str) -> bool:
        low = name.lower()
        return any(frag in low for frag in FORBIDDEN_NAME_FRAGMENTS)

    def person(self) -> str:
        with self._lock:
            for _ in range(10_000):
                name = "%s %s" % (
                    self._rng.choice(FIRST_NAMES), self._rng.choice(LAST_NAMES)
                )
                if name in self._seen or self._forbidden(name):
                    continue
                self._seen.add(name)
                return name
        raise RuntimeError("EntityBank person pool exhausted")

    def company(self) -> str:
        with self._lock:
            for _ in range(10_000):
                name = "%s %s %s" % (
                    self._rng.choice(COMPANY_FIRST),
                    self._rng.choice(COMPANY_CORE),
                    self._rng.choice(COMPANY_SUFFIX),
                )
                if name in self._seen or self._forbidden(name):
                    continue
                self._seen.add(name)
                return name
        raise RuntimeError("EntityBank company pool exhausted")


class DateBank:
    """Issues dates; gold dates come from a reserved window and never repeat."""

    GOLD_START = date(2024, 4, 1)
    GOLD_END = date(2024, 11, 29)
    FILL_WINDOWS = [(date(2023, 1, 9), date(2024, 3, 28)), (date(2025, 1, 6), date(2025, 6, 27))]

    def __init__(self, rng: random.Random) -> None:
        self._rng = rng
        self._gold_used = set()
        self._lock = threading.Lock()

    def gold_date(self) -> str:
        span = (self.GOLD_END - self.GOLD_START).days
        with self._lock:
            for _ in range(10_000):
                d = self.GOLD_START + timedelta(days=self._rng.randint(0, span))
                if d.weekday() >= 5 or d in self._gold_used:
                    continue
                self._gold_used.add(d)
                return d.isoformat()
        raise RuntimeError("DateBank gold window exhausted")

    def reserve_gold(self, n: int) -> list:
        """Reserve all gold dates up front.

        Every other date in the corpus is then drawn around them but never
        equal to one, so a supporting date in document A can never collide with
        document B's gold date and trigger a rewrite that breaks A's chronology.
        """
        return [self.gold_date() for _ in range(n)]

    def fill_date(self) -> str:
        lo, hi = self._rng.choice(self.FILL_WINDOWS)
        span = (hi - lo).days
        for _ in range(200):
            d = lo + timedelta(days=self._rng.randint(0, span))
            if d.weekday() < 5 and d not in self._gold_used:
                return d.isoformat()
        return lo.isoformat()

    def window(self, around_iso: str, n: int, before: int = 150,
               after: int = 25) -> list:
        """n weekdays around a gold date, none of them a reserved gold date."""
        anchor = date(*(int(p) for p in around_iso.split("-")))
        picked = set()
        span = before + after
        for _ in range(n * 60):
            if len(picked) >= n:
                break
            d = anchor - timedelta(days=before) + timedelta(days=self._rng.randint(0, span))
            if d.weekday() < 5 and d not in self._gold_used:
                picked.add(d)
        return sorted(d.isoformat() for d in picked)

    def after_gold(self, around_iso: str, lo: int = 21, hi: int = 70) -> str:
        """A date shortly after a gold date: when the report was filed."""
        anchor = date(*(int(p) for p in around_iso.split("-")))
        for _ in range(400):
            d = anchor + timedelta(days=self._rng.randint(lo, hi))
            if d.weekday() < 5 and d not in self._gold_used:
                return d.isoformat()
        return (anchor + timedelta(days=hi)).isoformat()


def dot(name: str) -> str:
    """'' if the name already ends a sentence, else '.' — 'Vertex Inc.' not 'Inc..'"""
    return "" if name.rstrip().endswith(".") else "."


def prose_date(iso: str) -> str:
    """2024-05-14 -> 'May 14, 2024' — the form gold dates take inside narratives."""
    y, m, d = (int(p) for p in iso.split("-"))
    months = ["January", "February", "March", "April", "May", "June", "July",
              "August", "September", "October", "November", "December"]
    return "%s %d, %d" % (months[m - 1], d, y)


# ── Opus-authored domain banks ────────────────────────────────────────────────

CASE_TYPE_PROFILE = {
    "structuring": {
        "label": "structuring / CTR avoidance",
        "vocabulary": [
            "cash deposits held just below the currency transaction reporting threshold",
            "sequential same-day deposits across multiple branches",
            "CTR avoidance", "smurfing through third-party depositors",
            "sub-threshold ATM and night-drop activity",
            "aggregated daily cash activity that would otherwise have been reportable",
        ],
        "red_flags": [
            "deposits clustered between $8,400 and $9,800",
            "branch rotation within a single business day",
            "customer questions about reporting thresholds at the teller line",
            "cash deposits immediately followed by same-amount outbound transfers",
        ],
        "typology": (
            "a customer breaking cash into sub-threshold increments to defeat "
            "currency transaction reporting"
        ),
    },
    "wire_fraud": {
        "label": "wire fraud",
        "vocabulary": [
            "outbound wire transfer", "SWIFT code and correspondent routing",
            "business email compromise", "a vendor payment instruction change",
            "beneficiary account at a receiving institution", "a wire recall request",
        ],
        "red_flags": [
            "a lookalike sender domain differing by one character",
            "urgency language overriding the dual-approval control",
            "a beneficiary name that does not match the invoicing vendor",
            "a funds transfer initiated minutes before the wire cutoff",
        ],
        "typology": (
            "funds induced out of a customer account by deception and moved by wire "
            "to a beneficiary the customer never intended to pay"
        ),
    },
    "sanctions": {
        "label": "sanctions / OFAC",
        "vocabulary": [
            "OFAC Specially Designated Nationals list screening",
            "a blocked property report", "a sanctioned jurisdiction nexus",
            "the fifty percent ownership rule", "a name-match false positive",
            "sectoral sanctions identifications",
        ],
        "red_flags": [
            "a counterparty address in a comprehensively sanctioned jurisdiction",
            "shipping documents re-routed through a transshipment hub",
            "an intermediate owner holding exactly forty-nine percent",
            "payment references stripped of originator detail",
        ],
        "typology": (
            "exposure to a sanctioned party or jurisdiction that screening either "
            "missed or flagged and the business escalated incorrectly"
        ),
    },
    "kyc_gap": {
        "label": "KYC / CDD deficiency",
        "vocabulary": [
            "a missing beneficial ownership certification",
            "an expired government identification document",
            "unverified source of funds", "an incomplete customer due diligence file",
            "a stale periodic review", "a customer identification program exception",
        ],
        "red_flags": [
            "an account opened on a documentary exception that was never cleared",
            "a beneficial owner attestation dated after the first funding",
            "an occupation field left blank on a high-risk account",
            "declared activity that bears no relation to observed activity",
        ],
        "typology": (
            "a due diligence file that cannot support the risk rating the account "
            "was given"
        ),
    },
    "elder_exploitation": {
        "label": "elder financial exploitation",
        "vocabulary": [
            "power of attorney abuse", "a sudden change of account beneficiary",
            "unusually large withdrawals directed by a caregiver",
            "diminished capacity indicators noted by branch staff",
            "an Adult Protective Services referral", "a romance-scam typology",
        ],
        "red_flags": [
            "a new joint signer added weeks before the withdrawals began",
            "an accompanying party answering questions on the customer's behalf",
            "withdrawals that break a decades-long transaction pattern",
            "the customer unable to explain the purpose of a large transfer",
        ],
        "typology": (
            "an older accountholder's funds being moved by or for someone who has "
            "acquired influence over the account"
        ),
    },
}

# Named SAR section bank.  ``coarse`` maps each kind onto the five-value
# section_type enum that cortex-sar-passages exposes.
SAR_SECTIONS = {
    "activity_overview": {
        "title": "Activity Overview",
        "coarse": "activity",
        "brief": (
            "Summarise the suspicious activity in regulatory register: the reporting "
            "period, the aggregate amount, the account and channel, and the typology "
            "suspected. State what prompted the review (an automated monitoring alert, "
            "a branch referral, or a law-enforcement inquiry). Do not resolve the case "
            "here; this section frames it."
        ),
    },
    "subject_background": {
        "title": "Subject Background and Relationship History",
        "coarse": "background",
        "brief": (
            "Describe the subject's relationship with Cortex Bank and Trust: when the "
            "relationship opened, the products held, the declared occupation or line of "
            "business, the expected activity profile recorded at onboarding, and the "
            "risk rating carried before this review. Contrast declared activity with "
            "observed activity."
        ),
    },
    "account_profile": {
        "title": "Account Profile and Baseline Activity",
        "coarse": "background",
        "brief": (
            "Profile the account or accounts involved: opening balances, typical monthly "
            "credit and debit volume before the review period, the mix of channels used, "
            "and the statistical baseline the monitoring system held. Quantify how far "
            "the review-period activity departs from that baseline."
        ),
    },
    "transaction_analysis": {
        "title": "Transaction Analysis",
        "coarse": "activity",
        "brief": (
            "Walk the transaction pattern in analytical detail: sequencing, timing "
            "relative to business hours and reporting cutoffs, the relationship between "
            "credits and debits, velocity, and the structural features that make the "
            "pattern suspicious rather than merely unusual."
        ),
    },
    "counterparty_analysis": {
        "title": "Counterparty and Beneficiary Analysis",
        "coarse": "activity",
        "brief": (
            "Analyse the counterparties: who received or sent the funds, what is known "
            "about them from public filings and internal records, how long those "
            "relationships have existed, and whether the commercial rationale offered "
            "for the payments is supportable."
        ),
    },
    "geographic_risk": {
        "title": "Geographic and Jurisdictional Risk Assessment",
        "coarse": "activity",
        "brief": (
            "Assess the geography: the branches, states, and where relevant the foreign "
            "jurisdictions touched by the activity; distance between the customer's "
            "residence or place of business and the transaction locations; and the "
            "jurisdictional risk factors the compliance framework assigns."
        ),
    },
    "kyc_review": {
        "title": "Customer Due Diligence File Review",
        "coarse": "background",
        "brief": (
            "Report what the due diligence file did and did not contain: identification "
            "documents and their currency, beneficial ownership certification, source of "
            "funds and source of wealth evidence, the date of the last periodic review, "
            "and any documentary exceptions outstanding."
        ),
    },
    "alert_history": {
        "title": "Prior Alert and Disposition History",
        "coarse": "background",
        "brief": (
            "Recount earlier monitoring alerts on this relationship, the scenario that "
            "generated each, the analyst disposition, and the rationale recorded for "
            "closing them. Say plainly where a prior disposition now looks wrong in "
            "light of the current review."
        ),
    },
    "interview_summary": {
        "title": "Interview Summary",
        "coarse": "activity",
        "brief": (
            "Summarise interviews with the relationship manager, branch staff, and where "
            "applicable the customer: what each was asked, what each said, and where "
            "accounts diverge from the transaction record. Attribute statements to roles, "
            "never to named bank employees."
        ),
    },
    "negative_news": {
        "title": "Adverse Media and Public Record Research",
        "coarse": "activity",
        "brief": (
            "Report adverse media and public record research: corporate registry filings, "
            "civil litigation, liens and judgments, regulatory actions, and media "
            "coverage. Distinguish confirmed matches from unresolved possible matches and "
            "say what was done to resolve each."
        ),
    },
    "channel_analytics": {
        "title": "Channel, Device, and Session Analytics",
        "coarse": "activity",
        "brief": (
            "Report the digital evidence: originating addresses and their geography, "
            "device fingerprints, session timing, authentication events, failed login "
            "attempts, and profile changes made shortly before the activity. Say what the "
            "evidence supports and what it rules out."
        ),
    },
    "related_parties": {
        "title": "Related Party Network Analysis",
        "coarse": "activity",
        "brief": (
            "Map the network around the subject: shared addresses, telephone numbers, "
            "signatories, registered agents, and common beneficiaries across otherwise "
            "unrelated accounts, and what the overlap implies about coordination."
        ),
    },
    "policy_reference": {
        "title": "Applicable Policy and Regulatory Reference",
        "coarse": "background",
        "brief": (
            "Tie the activity to the governing framework in general terms: the Bank "
            "Secrecy Act reporting obligation, the relevant internal Cortex Bank and "
            "Trust monitoring and escalation policies by subject rather than by number, "
            "and the thresholds that apply. Regulatory threshold figures such as the "
            "$10,000 currency transaction reporting threshold may be cited."
        ),
    },
    "escalation": {
        "title": "Internal Escalation and Committee Deliberation",
        "coarse": "background",
        "brief": (
            "Describe the escalation path: who referred the case onward and when, what "
            "the review committee considered, what dissent was recorded, and the decision "
            "reached on filing. Refer to roles and committees, not to named employees."
        ),
    },
    "remediation": {
        "title": "Remediation and Account Restriction Actions",
        "coarse": "conclusion",
        "brief": (
            "State the actions taken: holds, restrictions, channel limitations, enhanced "
            "monitoring rules applied, relationship review or exit decisions, and the "
            "monitoring commitments that follow this filing."
        ),
    },
    "law_enforcement": {
        "title": "Law Enforcement Coordination and Information Sharing",
        "coarse": "conclusion",
        "brief": (
            "Describe coordination in procedural terms: any grand jury subpoena or "
            "written request received, section 314(b) information sharing with another "
            "institution, and what was provided. Do not invent case numbers for outside "
            "agencies beyond those supplied to you."
        ),
    },
    "prior_sar": {
        "title": "Prior Filing Continuity Assessment",
        "coarse": "background",
        "brief": (
            "Assess continuity with earlier filings on this relationship: what the prior "
            "filing covered, what has changed, and why the activity is being reported as "
            "continuing rather than as a new pattern."
        ),
    },
    "narrative_detail": {
        "title": "Detailed Chronology",
        "coarse": "activity",
        "brief": (
            "Give a dated chronology of the review period in prose, day by day or week "
            "by week, tying each entry to the transaction record. Keep it factual and "
            "avoid restating the analysis."
        ),
    },
}

# Section order used to grow a narrative.  The first four and the last two are
# always present; the middle expands with the bucket.
# A filed SAR reads in stages: overview, who the subject is, what the file held,
# what the transactions did, who the counterparties were, what the evidence
# showed, then policy, escalation, and actions.  Generated sections are sorted
# by this rank before assembly so a "Subject Background" section can never end
# up after the key finding.
SAR_STAGE_RANK = {
    "activity_overview": 0,
    "subject_background": 1,
    "account_profile": 1,
    "kyc_review": 2,
    "alert_history": 2,
    "prior_sar": 2,
    "transaction_analysis": 3,
    "narrative_detail": 3,
    "counterparty_analysis": 4,
    "geographic_risk": 4,
    "related_parties": 4,
    "channel_analytics": 5,
    "negative_news": 5,
    "interview_summary": 6,
    "policy_reference": 7,
    "escalation": 8,
    "remediation": 9,
    "law_enforcement": 9,
}
# The key finding follows the evidence sections and precedes policy and actions.
KF_AFTER_RANK = 6

SAR_CORE_OPENING = ["activity_overview", "subject_background"]
SAR_EXPANSION = [
    "account_profile", "transaction_analysis", "counterparty_analysis",
    "kyc_review", "alert_history", "geographic_risk", "narrative_detail",
    "interview_summary", "channel_analytics", "negative_news",
    "related_parties", "policy_reference", "prior_sar", "escalation",
]
SAR_CORE_CLOSING = ["remediation", "law_enforcement"]

INV_SECTIONS = [
    ("case_summary", "Case Summary", "background",
     "Open the investigation report with the referral: how the matter came to the "
     "Financial Intelligence Unit, the date opened, the customer and the account, the "
     "amount at issue, and the question the investigation had to answer."),
    ("allegation", "Allegation and Referral Source", "background",
     "State the allegation precisely and its source — the customer, a correspondent "
     "bank's recall notice, an automated alert, or a law-enforcement inquiry — and what "
     "the referring party claimed happened."),
    ("timeline", "Timeline of Events", "activity",
     "Give a dated chronology from the first contact by the fraudster through discovery "
     "and reporting. Tie each step to evidence in the record."),
    ("tracing", "Funds Tracing", "activity",
     "Trace the funds hop by hop: the originating debit, the beneficiary institution, "
     "any onward movement, conversion to cash or other instruments, and where the trail "
     "ends. Be explicit about which hops are documented and which are inferred."),
    ("beneficiary", "Beneficiary and Counterparty Analysis", "activity",
     "Analyse the receiving party: account opening date relative to the transfer, the "
     "stated business purpose, registry and public-record research, and the pattern of "
     "credits and debits on the receiving account."),
    ("evidence", "Interviews and Documentary Evidence", "activity",
     "Summarise the interviews conducted and the documents obtained — email headers, "
     "invoices, call recordings, authentication logs — and what each establishes."),
    ("recovery", "Recovery and Indemnification Efforts", "activity",
     "Describe recovery: the recall or indemnity request sent, the receiving "
     "institution's response, funds frozen versus funds returned, the residual loss, and "
     "any insurance or customer reimbursement decision."),
]
INV_FINDING_SECTION = ("findings", "Findings and Disposition", "key_finding")

# Deterministic exhibit builders act as the length buffer for every narrative.
EXHIBIT_KINDS = ["exhibit_ledger", "exhibit_wire_detail", "exhibit_alert_log"]

CHANNELS_RETAIL = ["Branch teller", "Night drop", "ATM deposit", "Mobile deposit"]
CHANNELS_COMMERCIAL = ["Branch teller", "Night drop", "ATM deposit", "Mobile deposit",
                       "Cash vault", "Commercial courier"]
# A ledger row has to be internally plausible: a wire room does not take cash
# deposits and a night drop does not sell official checks.
CHANNEL_INSTRUMENTS = {
    "Branch teller": ["Cash deposit", "Cash withdrawal", "Official check purchase",
                      "Money order purchase", "Currency exchange"],
    "Night drop": ["Cash deposit"],
    "ATM deposit": ["Cash deposit", "Cash withdrawal"],
    "Cash vault": ["Cash deposit", "Cash withdrawal"],
    "Commercial courier": ["Cash deposit"],
    "Mobile deposit": ["Check deposit"],
}
ALERT_SCENARIOS = ["Sub-threshold cash aggregation", "Rapid movement of funds",
                   "Velocity change versus baseline", "High-risk geography credit",
                   "Round-dollar outbound wire", "Structuring pattern detection",
                   "Beneficiary first-use", "Dormant account reactivation"]
DISPOSITIONS = ["Closed - documented business purpose", "Closed - no further action",
                "Escalated to Financial Intelligence Unit", "Closed - duplicate alert",
                "Escalated for enhanced due diligence"]

SYSTEM_PREAMBLE = (
    "You are an experienced BSA/AML compliance writer producing SYNTHETIC, entirely "
    "FICTIONAL training documents for Cortex Bank and Trust, a fictional US community "
    "bank. These documents are used as a search corpus in a technical certification "
    "course. Nothing you write describes real people, real companies, or real events.\n\n"
    "Register and conventions:\n"
    "- Write in the register of a filed Suspicious Activity Report narrative or a bank "
    "Financial Intelligence Unit investigation report: precise, measured, third person, "
    "past tense, no rhetorical flourish, no speculation presented as fact.\n"
    "- Refer to the filing institution as 'Cortex Bank and Trust'. Refer to bank staff "
    "by role ('the relationship manager', 'the reviewing analyst'), never by name.\n"
    "- Hedge appropriately: 'the activity is consistent with', 'no legitimate business "
    "purpose was identified', 'the customer was unable to substantiate'.\n"
    "- Do not use markdown headings, bullet lists, bold, or tables. Continuous prose in "
    "short paragraphs only. The section heading is added for you.\n"
    "- Do not open with a restatement of the section title.\n\n"
    "Hard constraints:\n"
    "- Use ONLY the currency figures supplied to you in the case dossier. Do not invent "
    "any other dollar amount. Where you need to describe a magnitude without a supplied "
    "figure, write it in words ('a low six-figure sum', 'several thousand dollars').\n"
    "- Regulatory threshold figures ($10,000 currency transaction reporting, $5,000 "
    "suspicious activity reporting, $3,000 funds transfer recordkeeping) may be cited.\n"
    "- Use ONLY the names supplied in the dossier for subjects, counterparties, and "
    "businesses. Do not invent additional company or person names.\n"
    "- Never mention any AI model, vendor, or product name.\n"
    "- Never use the company names Acme, Meridian, Northstar, or Novalux.\n\n"
    "Style failures to avoid:\n"
    "- The dossier labels every figure with what it is, so that you use each figure "
    "correctly. Never quote a label back. Do not write sentences that merely restate a "
    "label, such as 'The amount frozen at the receiving institution was $13,644.00.'\n"
    "- Do not enumerate the dossier's red flags as a list or say 'red flags observed "
    "included'. Work the ones that matter into the analysis as findings.\n"
    "- Do not cite every figure you were given. Cite the ones the section is actually "
    "about."
)


# ── Model client ──────────────────────────────────────────────────────────────


class Generator:
    """Cached, retrying, thread-safe wrapper over one Vertex AI model."""

    def __init__(self, offline: bool = False) -> None:
        self.offline = offline
        self._client = None
        self._lock = threading.Lock()
        self.calls = 0
        self.cache_hits = 0
        self.failures = []
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def _ensure_client(self):
        if self._client is None:
            with self._lock:
                if self._client is None:
                    from google import genai
                    self._client = genai.Client(
                        vertexai=True, project=GCP_PROJECT, location=GCP_LOCATION
                    )
        return self._client

    @staticmethod
    def _cache_path(key: str) -> Path:
        return CACHE_DIR / key[:2] / (key + ".json")

    def generate(self, prompt: str, max_tokens: int, temperature: float,
                 as_json: bool = False, label: str = "") -> str:
        # ``cfg`` is part of the cache key so a change in request configuration
        # invalidates stale responses instead of silently serving them.
        payload = json.dumps(
            {"m": GEN_MODEL, "p": prompt, "t": temperature, "x": max_tokens,
             "j": as_json, "cfg": REQUEST_CONFIG_ID},
            sort_keys=True,
        )
        key = hashlib.sha256(payload.encode()).hexdigest()
        path = self._cache_path(key)
        if path.exists():
            with self._lock:
                self.cache_hits += 1
            return json.loads(path.read_text())["text"]
        if self.offline:
            raise RuntimeError("offline mode: cache miss for %s" % (label or key[:8]))

        from google.genai import types
        # Deliberately NOT setting response_mime_type="application/json": on this
        # model that flag re-enables reasoning regardless of thinking_budget, and
        # the reasoning then consumes the whole output budget, so every JSON call
        # returns a string truncated mid-token.  Asking for JSON in the prompt and
        # parsing a fenced block is both cheaper and reliable.
        cfg = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        )
        client = self._ensure_client()
        last = None
        for attempt in range(MAX_RETRIES):
            try:
                resp = client.models.generate_content(
                    model=GEN_MODEL, contents=prompt, config=cfg
                )
                text = (resp.text or "").strip()
                if not text:
                    raise RuntimeError("empty response")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({"text": text}))
                with self._lock:
                    self.calls += 1
                return text
            except Exception as exc:  # noqa: BLE001 - deliberate catch-all with retry
                last = exc
                time.sleep(min(2 ** attempt * 1.5, 20) + random.random())
        with self._lock:
            self.failures.append({"label": label, "error": "%s: %s" % (type(last).__name__, last)})
        raise RuntimeError("generation failed for %s: %s" % (label, last))


# ── Deterministic exhibit builders ────────────────────────────────────────────


EXHIBIT_TITLES = {
    "exhibit_ledger": "Exhibit A - Transaction Ledger Extract",
    "exhibit_wire_detail": "Exhibit B - Funds Transfer Detail Listing",
    "exhibit_alert_log": "Exhibit C - Monitoring Alert Disposition Log",
}
EXHIBIT_INTROS = {
    "exhibit_ledger": ("The following is a representative extract of the individual items "
                       "reviewed. Amounts are as posted; the subtotal covers only the "
                       "items exhibited here, not the full review period."),
    "exhibit_wire_detail": ("The following listing sets out the funds transfers reviewed, "
                            "as recorded by the wire room."),
    "exhibit_alert_log": ("The following log lists the monitoring alerts raised on this "
                          "relationship and the disposition recorded for each."),
}


def build_exhibit(kind: str, dossier: dict, n_rows: int) -> str:
    """Deterministic exhibit body: a pure function of (kind, dossier, n_rows).

    Purity matters because :func:`fit_to_budget` rebuilds an exhibit many times
    while converging on the bucket target.  Anything drawn from a shared RNG
    here would make the final document depend on the iteration count.  Amounts
    are indexed out of the document's pre-allocated pool, never popped, so the
    allocator is not drained by the convergence loop.
    """
    cash = dossier["ledger_amounts"]
    wires = dossier["wire_amounts"]
    dates = dossier["activity_dates"]
    cps = dossier["counterparties"]
    off = EXHIBIT_KINDS.index(kind) * 311
    items = []
    channels = (CHANNELS_COMMERCIAL if dossier.get("scale") == "commercial"
                else CHANNELS_RETAIL)
    if kind == "exhibit_ledger":
        for i in range(n_rows):
            chan = channels[(off + i * 5) % len(channels)]
            instruments = CHANNEL_INSTRUMENTS[chan]
            items.append((
                dates[(off + i * 3) % len(dates)], chan,
                instruments[(off + i * 7) % len(instruments)],
                cash[(off + i) % len(cash)],
            ))
        items.sort(key=lambda r: r[0])
        rows = ["Date        Channel               Instrument              Amount"]
        running = 0.0
        for d, chan, inst, amt in items:
            running += float(amt.replace("$", "").replace(",", ""))
            rows.append("%-11s %-21s %-23s %s" % (d, chan, inst, amt))
        rows.append("Subtotal for the items exhibited above: ${:,.2f}".format(running))
    elif kind == "exhibit_wire_detail":
        for i in range(n_rows):
            items.append((
                dates[(off + i * 3) % len(dates)],
                "Outbound" if (off + i) % 3 else "Inbound",
                cps[(off + i) % len(cps)][:34],
                wires[(off + i) % len(wires)],
            ))
        items.sort(key=lambda r: r[0])
        rows = ["Value date  Direction  Beneficiary / Originator            Amount"]
        rows += ["%-11s %-10s %-35s %s" % r for r in items]
    else:
        for i in range(n_rows):
            items.append((
                dates[(off + i * 3) % len(dates)],
                ALERT_SCENARIOS[(off + i * 5) % len(ALERT_SCENARIOS)],
                DISPOSITIONS[(off + i * 7) % len(DISPOSITIONS)],
            ))
        items.sort(key=lambda r: r[0])
        rows = ["Alert date  Scenario                            Disposition"]
        rows += ["%-11s %-35s %s" % r for r in items]
    return "%s\n\n%s" % (EXHIBIT_INTROS[kind], "\n".join(rows))


# ── Amount and token hygiene ──────────────────────────────────────────────────

AMOUNT_RE = re.compile(r"\$\s?\d{1,3}(?:,\d{3})*(?:\.\d{2})?|\$\s?\d+(?:\.\d{2})?")


def _norm_amount(raw: str) -> str:
    return raw.replace(" ", "")


def sanitize_amounts(text: str, allowed: set, bank: AmountBank, memo: dict) -> str:
    """Rewrite every currency figure that the document does not own.

    ``allowed`` holds the document's own allocations plus ``REG_CONSTANTS``.
    Anything else the model produced is remapped to a fresh globally unique
    allocation, memoised per document so the same stray figure stays consistent
    within the narrative.
    """
    def repl(match):
        raw = _norm_amount(match.group(0))
        if raw in allowed:
            return raw
        bare = raw.rstrip(".")
        if bare in allowed:
            return bare
        if raw not in memo:
            memo[raw] = bank.decoy(small=len(raw.replace(",", "")) <= 6)
            allowed.add(memo[raw])
        return memo[raw]

    return AMOUNT_RE.sub(repl, text)


def scrub_forbidden(text: str, bank: EntityBank) -> str:
    """Replace retired company names and any leaked vendor token."""
    out = text
    for frag in FORBIDDEN_NAME_FRAGMENTS:
        pattern = re.compile(r"\b%s\b[\w.,'-]*" % re.escape(frag), re.IGNORECASE)
        if pattern.search(out):
            out = pattern.sub(bank.company(), out)
    out = FORBIDDEN_TOKEN_RE.sub("the reviewing system", out)
    return out


def _new_exhibit(kind: str, dossier: dict, n_rows: int) -> dict:
    return {
        "kind": kind, "title": EXHIBIT_TITLES[kind], "coarse": "activity",
        "body": build_exhibit(kind, dossier, n_rows), "rows": n_rows,
    }


def fit_to_budget(sections: list, target: int, dossier: dict, protected: set) -> list:
    """Land a document inside ~8 percent of its bucket target.

    Grows or shrinks the exhibit sections first; only then trims trailing
    paragraphs from unprotected prose.  Never touches a protected section.
    """
    def total(secs):
        return sum(token_count(s["body"]) for s in secs)

    lo, hi = int(target * 0.92), int(target * 1.08)

    # Grow: extend the last exhibit, adding a new exhibit kind once one is long.
    guard = 0
    while total(sections) < lo and guard < 400:
        guard += 1
        ex = [s for s in sections if s["kind"].startswith("exhibit_")]
        if not ex:
            sections.append(_new_exhibit(EXHIBIT_KINDS[0], dossier, 6))
            continue
        tail = ex[-1]
        deficit = lo - total(sections)
        tail["rows"] += max(4, min(150, int(deficit / 22)))
        tail["body"] = build_exhibit(tail["kind"], dossier, tail["rows"])
        if tail["rows"] > 90 and len(ex) < len(EXHIBIT_KINDS):
            sections.append(_new_exhibit(EXHIBIT_KINDS[len(ex)], dossier, 8))

    # Shrink: pull exhibit rows, then drop exhibits, then trim prose tails.
    guard = 0
    while total(sections) > hi and guard < 600:
        guard += 1
        ex = [s for s in sections if s["kind"].startswith("exhibit_")]
        if ex:
            tail = ex[-1]
            if tail["rows"] > 4:
                excess = total(sections) - hi
                tail["rows"] = max(4, tail["rows"] - max(2, int(excess / 22)))
                tail["body"] = build_exhibit(tail["kind"], dossier, tail["rows"])
                continue
            sections.remove(tail)
            continue
        trimmable = [s for s in sections if s["kind"] not in protected
                     and len(s["body"].split("\n\n")) > 2]
        if not trimmable:
            break
        victim = trimmable[-1]
        paras = victim["body"].split("\n\n")
        victim["body"] = "\n\n".join(paras[:-1])
    return sections


def rebuild_doc(doc: dict, gold_section_kinds: set) -> None:
    """Re-derive ``body``, ``key_finding``, and ``token_count`` from ``_sections``.

    Called after :func:`enforce_gold_uniqueness` rewrites section text, so the
    concatenated body, the standalone gold-section field, and the passages
    derived from the sections can never drift apart.
    """
    sections = doc["_sections"]
    doc["body"] = "\n\n".join(
        (("## %s\n\n%s" % (s["title"], s["body"])) if s["title"] else s["body"])
        for s in sections
    )
    doc["token_count"] = token_count(doc["body"])
    for s in sections:
        if s["kind"] in gold_section_kinds:
            doc["key_finding"] = s["body"]
            break


# ── SAR narratives ────────────────────────────────────────────────────────────


def plan_sars(bank: AmountBank, ents: EntityBank, dates: DateBank,
              rng: random.Random, per_bucket: int, gold_dates: list) -> list:
    """Allocate every literal for every SAR before a single API call is made."""
    plans = []
    idx = 0
    for b_i, bucket in enumerate(BUCKET_ORDER):
        target = BUCKETS[bucket]
        for j in range(per_bucket):
            idx += 1
            doc_id = "sar-%03d" % idx
            drng = random.Random("%d|%s|%s" % (SEED, doc_id, "sar"))
            case_type = CASE_TYPES[(b_i * per_bucket + j) % len(CASE_TYPES)]
            risk_tier = RISK_TIERS[(idx + b_i) % len(RISK_TIERS)]
            profile = CASE_TYPE_PROFILE[case_type]

            # Multi-customer above 20k, per the bucket description.
            n_subjects = 1 if target < 20_000 else (3 if target < 40_000 else 5)
            subjects = []
            for s in range(n_subjects):
                is_biz = drng.random() < (0.5 if case_type in ("wire_fraud", "sanctions") else 0.3)
                subjects.append({
                    "name": ents.company() if is_biz else ents.person(),
                    "kind": "business" if is_biz else "individual",
                    "account": "%d-%05d-%d" % (drng.randint(10, 89),
                                               drng.randint(10000, 99999), s + 1),
                })
            counterparties = [ents.company() for _ in range(2 + n_subjects)]
            scale = "retail" if all(s["kind"] == "individual" for s in subjects) \
                else "commercial"

            gold_amount = bank.gold(scale)
            gold_entity = ents.company() if drng.random() < 0.6 else ents.person()
            gold_date = gold_dates[idx - 1]
            gold_account = "%d-%05d-9" % (drng.randint(10, 89), drng.randint(10000, 99999))

            labelled = signature_amounts(case_type, bank, scale)
            aggregate = next(a["amount"] for a in labelled if a["kind"] == "aggregate")
            named = [a["amount"] for a in labelled]
            n_ledger = 40 if target <= 3_000 else (
                90 if target <= 8_000 else (420 if target <= 20_000 else 1_200))
            ledger = [bank.decoy(small=True) for _ in range(n_ledger)]
            wires = [bank.decoy() for _ in range(max(12, n_ledger // 4))]

            # The review window brackets the gold date, so the narrative's
            # chronology and its determinative event cannot contradict.
            n_dates = 14 if target <= 8_000 else (60 if target <= 20_000 else 90)
            activity_dates = dates.window(gold_date, n_dates,
                                          before=150 if target <= 8_000 else 300)
            filing_date = dates.after_gold(gold_date)

            # How many prose sections to plan, and how long each should be.
            # FIXED_TOKENS is the header + key finding + filing determination,
            # which are written deterministically or separately and are not part
            # of the prose budget.
            if target <= 1_000:
                section_words, prose_share = 200, 0.98
            elif target <= 3_000:
                section_words, prose_share = 520, 0.95
            elif target <= 8_000:
                section_words, prose_share = 700, 0.92
            elif target <= 20_000:
                section_words, prose_share = 900, 0.84
            else:
                section_words, prose_share = 1_000, 0.76

            fixed_tokens = 430
            prose_budget = max(300, int(target * prose_share) - fixed_tokens)
            n_prose = max(2, int(round(prose_budget / (section_words * 1.33))))

            kinds = list(SAR_CORE_OPENING)[:n_prose]
            pool = list(SAR_EXPANSION)
            while len(kinds) < n_prose - len(SAR_CORE_CLOSING):
                kinds.append(pool[(len(kinds) - len(SAR_CORE_OPENING)) % len(pool)])
            kinds += [k for k in SAR_CORE_CLOSING if len(kinds) < n_prose]

            plans.append({
                "doc_id": doc_id, "bucket": bucket, "target": target,
                "case_type": case_type, "risk_tier": risk_tier,
                "filing_date": filing_date, "subjects": subjects,
                "counterparties": counterparties, "profile": profile,
                "gold_amount": gold_amount, "gold_entity": gold_entity,
                "gold_date": gold_date, "gold_account": gold_account,
                "labelled_amounts": labelled, "aggregate_amount": aggregate,
                "scale": scale,
                "named_amounts": named, "ledger_amounts": ledger,
                "wire_amounts": wires,
                "activity_dates": activity_dates, "section_kinds": kinds,
                "section_words": section_words, "bank": bank,
                "fiu_case": "FIU-%s-%04d" % (filing_date[:4], 1700 + idx),
            })
    return plans


def dossier_text(plan: dict) -> str:
    subs = "\n".join(
        "  - %s (%s), Cortex Bank and Trust account %s" % (s["name"], s["kind"], s["account"])
        for s in plan["subjects"]
    )
    amts = "\n".join("  - %s: %s" % (a["label"], a["amount"])
                     for a in plan["labelled_amounts"])
    dates = plan["activity_dates"]
    return (
        "CASE DOSSIER (the only facts, names, and figures you may use)\n"
        "Internal case reference: %(case)s\n"
        "Suspected typology: %(typ)s (%(label)s)\n"
        "Risk tier assigned: %(tier)s\n"
        "Review period: %(start)s through %(end)s\n"
        "Report date: %(filing)s\n"
        "Subjects of the report:\n%(subs)s\n"
        "Counterparties and related businesses: %(cps)s\n"
        "Dates inside the review period you may cite: %(dates)s\n"
        "Currency figures you may cite, each with what it IS. Use each figure only for\n"
        "the thing it is labelled as, and when you state a total or an aggregate use the\n"
        "figure labelled 'aggregate':\n%(amts)s\n"
        "Red flags observed in this case: %(flags)s\n"
        % {
            "case": plan["fiu_case"],
            "typ": plan["profile"]["typology"],
            "label": plan["profile"]["label"],
            "tier": plan["risk_tier"],
            "start": prose_date(dates[0]),
            "end": prose_date(dates[-1]),
            "filing": prose_date(plan["filing_date"]),
            "subs": subs,
            "cps": "; ".join(plan["counterparties"]),
            "dates": ", ".join(prose_date(d) for d in dates[:9]),
            "amts": amts,
            "flags": "; ".join(plan["profile"]["red_flags"]),
        }
    )


def sar_section_prompt(plan: dict, kind: str, ordinal: int, subject: dict) -> str:
    spec = SAR_SECTIONS[kind]
    return (
        "%s\n\n%s\n"
        "SECTION TO WRITE: %s\n"
        "Primary subject for this section: %s (account %s)\n"
        "What this section must do: %s\n\n"
        "Length: approximately %d words. Continuous prose, no headings, no lists.\n"
        "This is section %d of a longer report; do not summarise the whole case and do "
        "not draw the filing conclusion here."
        % (SYSTEM_PREAMBLE, dossier_text(plan), spec["title"],
           subject["name"], subject["account"], spec["brief"],
           plan["section_words"], ordinal)
    )


def sar_key_finding_prompt(plan: dict) -> str:
    subject = plan["subjects"][0]
    return (
        "%s\n\n%s\n"
        "TASK: write the single KEY FINDING paragraph of this report, then three "
        "questions that can only be answered from that paragraph.\n\n"
        "The key finding paragraph must:\n"
        "- be one paragraph of 110 to 170 words, in the same regulatory register;\n"
        "- state the determinative fact the reviewing analyst established;\n"
        "- contain these three literals VERBATIM and exactly once each, written into the "
        "prose naturally, never introduced by a label such as 'the amount', 'the entity "
        "name', or 'the date':\n"
        "    %s  (the sum the finding establishes)\n"
        "    %s  (the party the sum is attributable to)\n"
        "    %s  (the date the finding fixes)\n"
        "- tie all three together: the sum moved to or through that party on that "
        "date, or was established as attributable to it on that date;\n"
        "- name the receiving or holding account %s;\n"
        "- read as the paragraph an investigator would point to as the finding of the "
        "report, not as a summary of it.\n\n"
        "The three questions must each be answerable ONLY from that paragraph, must "
        "name the subject %s so they are unambiguous across a corpus of similar "
        "reports, and must target one literal each: the first the amount, the second "
        "the entity, the third the date. Each answer is a short sentence that contains "
        "the literal verbatim.\n\n"
        "Return JSON only, with this exact shape:\n"
        '{"key_finding": "...", "questions": [{"text": "...", "answer": "...", '
        '"gold_literal": "..."}, {...}, {...}]}'
        % (SYSTEM_PREAMBLE, dossier_text(plan), plan["gold_amount"], plan["gold_entity"],
           prose_date(plan["gold_date"]), plan["gold_account"], subject["name"])
    )


def fallback_key_finding(plan: dict) -> dict:
    subject = plan["subjects"][0]["name"]
    kf = (
        "The reviewing analyst established that %s of the activity under review is "
        "directly attributable to %s%s On %s, funds in that amount left the subject's "
        "relationship with Cortex Bank and Trust and settled to account %s held in that "
        "name, and the customer was unable to identify any goods, services, or "
        "contractual obligation that would explain the payment. No records produced by "
        "%s during the review substantiate a commercial relationship with that "
        "counterparty, and the transfer is inconsistent with the activity profile "
        "recorded for the account at onboarding. This finding is the basis on which the "
        "activity is reported as suspicious."
        % (plan["gold_amount"], plan["gold_entity"], dot(plan["gold_entity"]),
           prose_date(plan["gold_date"]), plan["gold_account"], subject)
    )
    return {
        "key_finding": kf,
        "questions": [
            {"text": "In the Cortex Bank and Trust report on %s, what amount did the "
                     "reviewing analyst attribute to the counterparty named in the key "
                     "finding?" % subject,
             "answer": "The reviewing analyst attributed %s to that counterparty."
                       % plan["gold_amount"],
             "gold_literal": plan["gold_amount"]},
            {"text": "Which counterparty received the attributed funds in the Cortex "
                     "Bank and Trust report on %s?" % subject,
             "answer": "The funds settled to an account held by %s%s"
                       % (plan["gold_entity"], dot(plan["gold_entity"])),
             "gold_literal": plan["gold_entity"]},
            {"text": "On what date did the attributed funds leave the %s relationship "
                     "at Cortex Bank and Trust?" % subject,
             "answer": "The funds left the relationship on %s."
                       % prose_date(plan["gold_date"]),
             "gold_literal": prose_date(plan["gold_date"])},
        ],
    }


def parse_json_response(text: str):
    """Parse JSON the model wrapped in prose or a fenced block."""
    text = (text or "").strip()
    if "```" in text:
        m = re.search(r"```[a-zA-Z]*\s*\n(.*?)\n?```", text, re.S)
        if m:
            text = m.group(1).strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    for op, cl in (("{", "}"), ("[", "]")):
        i, j = text.find(op), text.rfind(cl)
        if i != -1 and j > i:
            try:
                return json.loads(text[i:j + 1])
            except Exception:
                continue
    raise ValueError("no JSON object found in response")


def build_sar_tasks(plans: list) -> list:
    tasks = []
    for plan in plans:
        for i, kind in enumerate(plan["section_kinds"]):
            subject = plan["subjects"][i % len(plan["subjects"])]
            tasks.append({
                "id": "%s|sec|%d" % (plan["doc_id"], i),
                "prompt": sar_section_prompt(plan, kind, i + 1, subject),
                "max_tokens": int(plan["section_words"] * 2.2) + 700,
                "temperature": 0.92, "json": False,
                "label": "%s %s" % (plan["doc_id"], kind),
            })
        tasks.append({
            "id": "%s|kf" % plan["doc_id"],
            "prompt": sar_key_finding_prompt(plan),
            "max_tokens": 2600, "temperature": 0.7, "json": True,
            "label": "%s key_finding" % plan["doc_id"],
        })
    return tasks


_ASK_AMOUNT = re.compile(
    r"\b(what (?:amount|sum|total|figure)|how much|what was the (?:amount|sum|total)|"
    r"dollar (?:amount|figure)|aggregate)\b", re.IGNORECASE)
_ASK_DATE = re.compile(
    r"\b(on what date|what date|when did|when was|on which date|what day)\b",
    re.IGNORECASE)
_ASK_ENTITY = re.compile(
    r"\b(which (?:entity|party|company|counterparty|beneficiary|firm|business)|"
    r"who (?:received|held|was)|what (?:entity|party|company|counterparty|beneficiary)|"
    r"to whom|name of the)\b", re.IGNORECASE)


def assign_literal_kinds(texts: list) -> list:
    """Pair each question with the literal it actually asks for.

    One literal per question, so three questions always cover amount, entity,
    and date exactly once.  Classification wins where it is confident;
    unclassified questions take whatever kind is left, in order.
    """
    order = ["amount", "entity", "date"]
    guessed = []
    for t in texts:
        if _ASK_DATE.search(t):
            guessed.append("date")
        elif _ASK_ENTITY.search(t):
            guessed.append("entity")
        elif _ASK_AMOUNT.search(t):
            guessed.append("amount")
        else:
            guessed.append(None)
    assigned, taken = [None] * len(texts), set()
    for i, kind in enumerate(guessed):
        if kind and kind not in taken:
            assigned[i] = kind
            taken.add(kind)
    spare = [k for k in order if k not in taken]
    for i in range(len(assigned)):
        if assigned[i] is None:
            assigned[i] = spare.pop(0) if spare else order[i % len(order)]
    return assigned


def assemble_sar(plan: dict, out: dict, ents: EntityBank) -> dict:
    allowed = set(REG_CONSTANTS)
    allowed.update(plan["named_amounts"])
    allowed.update(plan["ledger_amounts"])
    allowed.add(plan["gold_amount"])
    memo = {}

    kf_raw = out.get("%s|kf" % plan["doc_id"])
    kf = None
    if kf_raw:
        try:
            parsed = parse_json_response(kf_raw)
            body = (parsed.get("key_finding") or "").strip()
            qs = parsed.get("questions") or []
            ok = (
                plan["gold_amount"] in body
                and plan["gold_entity"] in body
                and prose_date(plan["gold_date"]) in body
                and len(qs) >= QUESTIONS_PER_SAR
            )
            if ok:
                kf = {"key_finding": body, "questions": qs[:QUESTIONS_PER_SAR]}
        except Exception:
            kf = None
    repaired = kf is None
    if kf is None:
        kf = fallback_key_finding(plan)

    # Gold literals are pinned to the key finding: the questions carry them
    # verbatim regardless of what the model wrote in its answer strings.  The
    # pairing is driven by what each question actually asks, not by its position
    # in the response, so a reordered response cannot leave a "which party..."
    # question holding a dollar amount as its gold literal.
    literals = {"amount": plan["gold_amount"], "entity": plan["gold_entity"],
                "date": prose_date(plan["gold_date"])}
    texts = [(q.get("text") or "").strip() for q in kf["questions"]]
    kinds = assign_literal_kinds(texts)
    questions = []
    for qi, q in enumerate(kf["questions"]):
        kind = kinds[qi]
        lit = literals[kind]
        answer = (q.get("answer") or "").strip()
        if lit not in answer:
            answer = ("%s The value recorded in the key finding is %s."
                      % (answer, lit)).strip()
        questions.append({
            "question_id": "q-%s-%d" % (plan["doc_id"], qi + 1),
            "text": texts[qi],
            "answer": answer,
            "gold_literal": lit,
            "literal_kind": kind,
            "hop": "single",
        })

    sections = []
    header = (
        "Filing institution: Cortex Bank and Trust\n"
        "Internal case reference: %s\n"
        "Report filed: %s\n"
        "Suspected activity: %s\n"
        "Risk tier: %s\n"
        "Subjects of this report:\n%s\n"
        "Review period: %s through %s\n"
        "Aggregate amount of activity reviewed: %s"
        % (plan["fiu_case"], prose_date(plan["filing_date"]),
           plan["profile"]["label"], plan["risk_tier"],
           "\n".join("  %s (%s), account %s" % (s["name"], s["kind"], s["account"])
                     for s in plan["subjects"]),
           prose_date(plan["activity_dates"][0]),
           prose_date(plan["activity_dates"][-1]),
           plan["aggregate_amount"])
    )
    sections.append({"kind": "header", "title": "Report Header",
                     "coarse": "header", "body": header, "rows": 0})

    # The key finding is sanitized like any other section: the model may have put
    # an invented figure alongside the pinned literals, and an invented figure in
    # the gold section is the one place a cross-document collision would be
    # hardest to see.
    kf_body = sanitize_amounts(scrub_forbidden(kf["key_finding"], ents),
                               allowed, plan["bank"], memo)

    repeats = {k for k in plan["section_kinds"]
               if plan["section_kinds"].count(k) > 1}
    multi = len(plan["subjects"]) > 1
    prose = []
    for i, kind in enumerate(plan["section_kinds"]):
        raw = out.get("%s|sec|%d" % (plan["doc_id"], i))
        if not raw:
            continue
        spec = SAR_SECTIONS[kind]
        subject = plan["subjects"][i % len(plan["subjects"])]
        title = spec["title"]
        if multi and kind in repeats:
            title = "%s - %s" % (title, subject["name"])
        body = scrub_forbidden(raw.strip(), ents)
        body = sanitize_amounts(body, allowed, plan["bank"], memo)
        prose.append({"kind": kind, "title": title, "coarse": spec["coarse"],
                      "body": body, "rows": 0,
                      "_rank": SAR_STAGE_RANK.get(kind, 5), "_ord": i})
    prose.sort(key=lambda s: (s["_rank"], s["_ord"]))
    kf_pos = sum(1 for s in prose if s["_rank"] <= KF_AFTER_RANK)
    kf_pos = min(max(kf_pos, 1), len(prose))
    sections += prose[:kf_pos]
    sections.append({"kind": "key_finding", "title": "Key Finding",
                     "coarse": "key_finding", "body": kf_body, "rows": 0})
    sections += prose[kf_pos:]

    conclusion = (
        "Cortex Bank and Trust is filing this report because the activity described "
        "above is consistent with %s and no legitimate business purpose was identified "
        "for it. The determination rests on the key finding recorded above. The "
        "relationship has been placed under enhanced monitoring, the monitoring "
        "scenarios that generated the underlying alerts have been retuned for this "
        "customer segment, and a relationship review has been scheduled. Supporting "
        "documentation is retained in internal case file %s and is available to law "
        "enforcement on request."
        % (plan["profile"]["typology"], plan["fiu_case"])
    )
    sections.append({"kind": "conclusion", "title": "Filing Determination",
                     "coarse": "conclusion", "body": conclusion, "rows": 0})

    dossier = {
        "ledger_amounts": plan["ledger_amounts"],
        "wire_amounts": plan["wire_amounts"],
        "activity_dates": plan["activity_dates"],
        "counterparties": plan["counterparties"],
        "scale": plan["scale"],
    }
    sections = fit_to_budget(sections, plan["target"], dossier,
                             protected={"header", "key_finding", "conclusion"})
    for s in sections:
        if s["kind"].startswith("exhibit_"):
            allowed.update(_norm_amount(a) for a in AMOUNT_RE.findall(s["body"]))

    kf_index = next(i for i, s in enumerate(sections) if s["kind"] == "key_finding")
    doc = {
        "doc_id": plan["doc_id"],
        "case_type": plan["case_type"],
        "risk_tier": plan["risk_tier"],
        "filing_date": plan["filing_date"],
        "subject_name": plan["subjects"][0]["name"],
        "subject_account": plan["subjects"][0]["account"],
        "subject_count": len(plan["subjects"]),
        "case_reference": plan["fiu_case"],
        "section_id": "%s-kf" % plan["doc_id"],
        "key_finding_section_id": "%s-section-%d" % (plan["doc_id"], kf_index + 1),
        "bucket": plan["bucket"],
        "bucket_target_tokens": plan["target"],
        "gold_amount": plan["gold_amount"],
        "gold_entity": plan["gold_entity"],
        "gold_date": prose_date(plan["gold_date"]),
        "gold_date_iso": plan["gold_date"],
        "gold_account": plan["gold_account"],
        "questions": questions,
        "_sections": sections,
        "_repaired_key_finding": repaired,
    }
    rebuild_doc(doc, {"key_finding"})
    return doc


def derive_passages(sar: dict) -> list:
    passages = []
    for i, s in enumerate(sar["_sections"]):
        title = s["title"] or "Exhibit"
        sid = "%s-section-%d" % (sar["doc_id"], i + 1)
        passages.append({
            "doc_id": sid,
            "narrative_id": sar["doc_id"],
            "section_id": sid,
            "section_index": i,
            "section_title": title,
            "section_type": s["coarse"],
            "section_kind": s["kind"],
            "is_key_finding": s["kind"] == "key_finding",
            "key_finding_id": ("%s-kf" % sar["doc_id"]) if s["kind"] == "key_finding" else None,
            "case_type": sar["case_type"],
            "risk_tier": sar["risk_tier"],
            "filing_date": sar["filing_date"],
            "bucket": sar["bucket"],
            "body": "%s\n\n%s" % (title, s["body"]) if s["title"] else s["body"],
            "token_count": token_count(s["body"]),
        })
    return passages


# ── Investigation reports ─────────────────────────────────────────────────────


def plan_investigations(bank: AmountBank, ents: EntityBank, dates: DateBank,
                        rng: random.Random, n: int, gold_dates: list) -> list:
    plans = []
    for i in range(n):
        idx = i + 1
        doc_id = "inv-%03d" % idx
        drng = random.Random("%d|%s|inv" % (SEED, doc_id))
        target = 3_000 + int((i / max(1, n - 1)) * 3_000)
        victim_is_biz = drng.random() < 0.75
        subject = ents.company() if victim_is_biz else ents.person()
        scale = "commercial" if victim_is_biz else "retail"
        gold_entity = ents.company()
        key_date = gold_dates[i]
        labelled = signature_amounts("wire_fraud", bank, scale)
        # In a wire fraud report the fraudulent wire amount and the sum
        # established as diverted are one figure, so the gold literal is the
        # aggregate rather than a fifth competing number.
        gold_amount = labelled[0]["amount"]
        labelled[0] = dict(labelled[0],
                           label="the fraudulent outbound wire amount, which is also "
                                 "the sum the investigation established as diverted")
        named = [a["amount"] for a in labelled]
        account = "%d-%05d-1" % (drng.randint(10, 89), drng.randint(10000, 99999))
        subject_kind = "business" if victim_is_biz else "individual"
        activity_dates = dates.window(key_date, 12, before=120, after=20)
        date_opened = dates.after_gold(key_date, lo=2, hi=18)
        plans.append({
            "doc_id": doc_id,
            "case_type": "wire_fraud",
            "subject_name": subject,
            "subject_kind": subject_kind,
            "subject_account": account,
            # dossier_text() is shared with the SAR path and reads `subjects`.
            "subjects": [{"name": subject, "kind": subject_kind, "account": account}],
            "date_opened": date_opened,
            "outcome": INV_OUTCOMES[i % len(INV_OUTCOMES)],
            "counterparties": [gold_entity] + [ents.company() for _ in range(2)],
            "profile": CASE_TYPE_PROFILE["wire_fraud"],
            "gold_amount": gold_amount,
            "gold_entity": gold_entity,
            "key_date": key_date,
            "labelled_amounts": labelled,
            "scale": scale,
            "aggregate_amount": next(a["amount"] for a in labelled
                                     if a["kind"] == "aggregate"),
            "named_amounts": named,
            "ledger_amounts": [bank.decoy(small=True) for _ in range(30)],
            "wire_amounts": [bank.decoy() for _ in range(16)],
            "activity_dates": activity_dates,
            "target": target,
            "fiu_case": "FIU-WIRE-%04d" % (2400 + idx),
            "section_words": 620,
            "bank": bank,
            "risk_tier": RISK_TIERS[i % 3],
            "filing_date": date_opened,
        })
    return plans


def inv_section_prompt(plan: dict, key: str, title: str, brief: str, ordinal: int) -> str:
    return (
        "%s\n\n%s\n"
        "You are writing a Cortex Bank and Trust Financial Intelligence Unit WIRE FRAUD "
        "INVESTIGATION REPORT (an internal investigative product, not a filed SAR). "
        "Investigation outcome recorded for this case: %s.\n\n"
        "SECTION TO WRITE: %s\n"
        "What this section must do: %s\n\n"
        "Length: approximately %d words. Continuous prose, no headings, no lists.\n"
        "This is section %d of the report; do not state the final findings here."
        % (SYSTEM_PREAMBLE, dossier_text(plan), plan["outcome"], title, brief,
           plan["section_words"], ordinal)
    )


def inv_finding_prompt(plan: dict) -> str:
    return (
        "%s\n\n%s\n"
        "TASK: write the FINDINGS AND DISPOSITION section of this wire fraud "
        "investigation report, then one question answerable only from it.\n\n"
        "The section must:\n"
        "- run 150 to 220 words in the same investigative register;\n"
        "- state what the investigation established, and record the disposition '%s';\n"
        "- treat the diverted sum as ONE figure: it is the fraudulent wire amount. You "
        "may mention the residual loss once if it reads naturally; do not list the other "
        "figures and do not describe them as separate diversions;\n"
        "- contain these literals VERBATIM and exactly once each, written into the prose "
        "naturally and never introduced by a label such as 'the amount' or 'the date': "
        "%s (the sum established as diverted), %s (the party it was diverted to), and %s "
        "(the date the investigation fixed as determinative);\n"
        "The question must name the subject %s, be answerable only from this section, "
        "and ask for the diverted amount. The answer is a short sentence containing the "
        "amount verbatim.\n\n"
        "Return JSON only: {\"findings\": \"...\", \"question\": {\"text\": \"...\", "
        "\"answer\": \"...\"}}"
        % (SYSTEM_PREAMBLE, dossier_text(plan), plan["outcome"], plan["gold_amount"],
           plan["gold_entity"], prose_date(plan["key_date"]), plan["subject_name"])
    )


def build_inv_tasks(plans: list) -> list:
    tasks = []
    for plan in plans:
        for i, (key, title, _coarse, brief) in enumerate(INV_SECTIONS):
            tasks.append({
                "id": "%s|sec|%d" % (plan["doc_id"], i),
                "prompt": inv_section_prompt(plan, key, title, brief, i + 1),
                "max_tokens": int(plan["section_words"] * 2.2) + 700,
                "temperature": 0.9, "json": False,
                "label": "%s %s" % (plan["doc_id"], key),
            })
        tasks.append({
            "id": "%s|find" % plan["doc_id"],
            "prompt": inv_finding_prompt(plan),
            "max_tokens": 2200, "temperature": 0.7, "json": True,
            "label": "%s findings" % plan["doc_id"],
        })
    return tasks


def assemble_investigation(plan: dict, out: dict, ents: EntityBank) -> dict:
    allowed = set(REG_CONSTANTS)
    allowed.update(plan["named_amounts"])
    allowed.update(plan["ledger_amounts"])
    allowed.add(plan["gold_amount"])
    memo = {}

    raw = out.get("%s|find" % plan["doc_id"])
    findings, question = None, None
    if raw:
        try:
            parsed = parse_json_response(raw)
            body = (parsed.get("findings") or "").strip()
            q = parsed.get("question") or {}
            if (plan["gold_amount"] in body and plan["gold_entity"] in body
                    and prose_date(plan["key_date"]) in body and q.get("text")):
                findings, question = body, q
        except Exception:
            findings = None
    repaired = findings is None
    if findings is None:
        findings = (
            "The investigation established that %s was diverted from the %s relationship "
            "to an account held by %s, and fixed %s as the determinative date on which "
            "the diversion completed and became irrecoverable through ordinary recall "
            "channels. Documentary evidence obtained during the investigation supports "
            "that conclusion; no evidence was found that the subject authorised the "
            "payment to that beneficiary. The matter is recorded with the disposition "
            "'%s'."
            % (plan["gold_amount"], plan["subject_name"], plan["gold_entity"],
               prose_date(plan["key_date"]), plan["outcome"])
        )
        question = {
            "text": "In the Cortex Bank and Trust wire fraud investigation of %s, what "
                    "amount did the investigation establish as diverted to the "
                    "beneficiary?" % plan["subject_name"],
            "answer": "The investigation established that %s was diverted."
                      % plan["gold_amount"],
        }
    answer = (question.get("answer") or "").strip()
    if plan["gold_amount"] not in answer:
        answer = ("%s The amount established was %s." % (answer, plan["gold_amount"])).strip()

    sections = []
    header = (
        "Cortex Bank and Trust - Financial Intelligence Unit\n"
        "Investigation report: %s\n"
        "Date opened: %s\n"
        "Subject: %s (%s), account %s\n"
        "Matter type: wire fraud\n"
        "Disposition: %s"
        % (plan["fiu_case"], prose_date(plan["date_opened"]), plan["subject_name"],
           plan["subject_kind"], plan["subject_account"], plan["outcome"])
    )
    sections.append({"kind": "header", "title": "Report Header", "coarse": "header",
                     "body": header, "rows": 0})
    for i, (key, title, coarse, _brief) in enumerate(INV_SECTIONS):
        raw_sec = out.get("%s|sec|%d" % (plan["doc_id"], i))
        if not raw_sec:
            continue
        body = scrub_forbidden(raw_sec.strip(), ents)
        body = sanitize_amounts(body, allowed, plan["bank"], memo)
        sections.append({"kind": key, "title": title, "coarse": coarse,
                         "body": body, "rows": 0})
    findings = sanitize_amounts(scrub_forbidden(findings, ents), allowed,
                                plan["bank"], memo)
    sections.append({"kind": "findings", "title": INV_FINDING_SECTION[1],
                     "coarse": "key_finding", "body": findings, "rows": 0})

    dossier = {
        "ledger_amounts": plan["ledger_amounts"],
        "wire_amounts": plan["wire_amounts"],
        "activity_dates": plan["activity_dates"],
        "counterparties": plan["counterparties"],
        "scale": plan["scale"],
    }
    sections = fit_to_budget(sections, plan["target"], dossier,
                             protected={"header", "findings"})
    doc = {
        "doc_id": plan["doc_id"],
        "case_type": "wire_fraud",
        "risk_tier": plan["risk_tier"],
        "subject_name": plan["subject_name"],
        "subject_account": plan["subject_account"],
        "date_opened": plan["date_opened"],
        "outcome": plan["outcome"],
        "case_reference": plan["fiu_case"],
        "section_id": "%s-kf" % plan["doc_id"],
        "gold_amount": plan["gold_amount"],
        "gold_entity": plan["gold_entity"],
        "key_date": prose_date(plan["key_date"]),
        "key_date_iso": plan["key_date"],
        "questions": [{
            "question_id": "q-%s-1" % plan["doc_id"],
            "text": (question.get("text") or "").strip(),
            "answer": answer,
            "gold_literal": plan["gold_amount"],
            "literal_kind": "amount",
            "hop": "single",
        }],
        "_sections": sections,
        "_repaired_findings": repaired,
    }
    rebuild_doc(doc, {"findings"})
    return doc


def fact_index_prompt(report: dict) -> str:
    return (
        "You are the extraction stage of an offline fact-index pipeline over Cortex Bank "
        "and Trust wire fraud investigation reports. These reports are synthetic training "
        "data. Read the report and emit one structured record.\n\n"
        "Rules:\n"
        "- summary: 2 to 3 sentences, self-contained, and it MUST state the diverted "
        "amount %s, the beneficiary %s, and the date %s verbatim.\n"
        "- answers_questions: 4 to 6 short natural-language questions this report answers, "
        "phrased as a compliance analyst would type them into a search box.\n"
        "- key_entities: the subject, the beneficiary, and other named parties.\n"
        "- topics: 3 to 5 short lowercase snake_case topic tags.\n"
        "- amounts: every currency figure material to the finding, verbatim, with %s first.\n"
        "- dates: the material dates in YYYY-MM-DD form.\n"
        "- Invent nothing. Every value must come from the report.\n\n"
        "Return JSON only: {\"summary\": \"...\", \"answers_questions\": [...], "
        "\"key_entities\": [...], \"topics\": [...], \"amounts\": [...], \"dates\": [...]}\n\n"
        "REPORT (%s):\n%s"
        % (report["gold_amount"], report["gold_entity"], report["key_date"],
           report["gold_amount"], report["doc_id"], report["body"])
    )


def assemble_fact_record(report: dict, raw: str) -> dict:
    rec = None
    if raw:
        try:
            parsed = parse_json_response(raw)
            if parsed.get("summary"):
                rec = parsed
        except Exception:
            rec = None
    if rec is None:
        rec = {
            "summary": ("The Cortex Bank and Trust Financial Intelligence Unit "
                        "investigated a wire fraud affecting %s and established that %s "
                        "was diverted to %s. The determinative date was %s. The matter "
                        "was recorded with the disposition '%s'."
                        % (report["subject_name"], report["gold_amount"],
                           report["gold_entity"], report["key_date"], report["outcome"])),
            "answers_questions": [
                "how much was diverted in the %s wire fraud" % report["subject_name"],
                "who received the funds diverted from %s" % report["subject_name"],
                "when did the %s wire fraud complete" % report["subject_name"],
                "what was the outcome of the %s investigation" % report["subject_name"],
            ],
            "key_entities": [report["subject_name"], report["gold_entity"]],
            "topics": ["wire_fraud", "funds_tracing", report["outcome"]],
            "amounts": [report["gold_amount"]],
            "dates": [report["key_date_iso"]],
        }
    summary = rec.get("summary", "")
    for lit in (report["gold_amount"], report["gold_entity"], report["key_date"]):
        if lit not in summary:
            summary = "%s The record establishes %s." % (summary, lit)
    amounts = [a for a in rec.get("amounts") or [] if isinstance(a, str)]
    if report["gold_amount"] not in amounts:
        amounts.insert(0, report["gold_amount"])
    dates = [d for d in rec.get("dates") or [] if isinstance(d, str)]
    if report["key_date_iso"] not in dates:
        dates.insert(0, report["key_date_iso"])
    entities = [e for e in rec.get("key_entities") or [] if isinstance(e, str)]
    for e in (report["subject_name"], report["gold_entity"]):
        if e not in entities:
            entities.append(e)
    return {
        "doc_id": report["doc_id"],
        "report_id": report["doc_id"],
        "subject_name": report["subject_name"],
        "outcome": report["outcome"],
        "date_opened": report["date_opened"],
        "summary": summary.strip(),
        "answers_questions": [q for q in rec.get("answers_questions") or []
                              if isinstance(q, str)][:6],
        "key_entities": entities,
        "topics": [t for t in rec.get("topics") or [] if isinstance(t, str)][:5] or ["wire_fraud"],
        "amounts": amounts,
        "dates": dates,
        "token_count": token_count(summary),
    }


# ── Case memos ────────────────────────────────────────────────────────────────


def plan_cases(bank: AmountBank, ents: EntityBank, dates: DateBank,
               rng: random.Random, per_cell: int) -> list:
    """5 types x 3 tiers x per_cell memos, each contaminated by one other type.

    Contamination is rotated so every type is contaminated by each of the other
    four types an equal number of times: that even spread is what holds the
    unfiltered precision@10 baseline down near 0.50 instead of letting one type
    dominate the confusions.
    """
    plans = []
    n = 0
    for t_i, ctype in enumerate(CASE_TYPES):
        others = [c for c in CASE_TYPES if c != ctype]
        seq = 0
        for tier in RISK_TIERS:
            for k in range(per_cell):
                n += 1
                seq += 1
                doc_id = "case-%s-%03d" % (ctype.replace("_", "-"), seq)
                drng = random.Random("%d|%s|case" % (SEED, doc_id))
                contaminant = others[(seq - 1) % len(others)]
                own = CASE_TYPE_PROFILE[ctype]
                foreign = CASE_TYPE_PROFILE[contaminant]
                terms = [foreign["vocabulary"][(seq + i) % len(foreign["vocabulary"])]
                         for i in range(3)]
                # Elder financial exploitation is a personal-account typology:
                # a commercial LLC subject makes the memo implausible and
                # inflates the figures out of range.
                is_biz = drng.random() < 0.45 and ctype != "elder_exploitation"
                scale = "commercial" if is_biz else "retail"
                labelled = signature_amounts(ctype, bank, scale)
                # One headline figure per memo: the aggregate IS the
                # determinative figure, so the memo cannot present two
                # competing central numbers.
                gold = labelled[0]["amount"]
                labelled[0] = dict(labelled[0],
                                   label=labelled[0]["label"]
                                   + " - this is the determinative figure for this case")
                plans.append({
                    "doc_id": doc_id,
                    "case_id": doc_id,
                    "case_type": ctype,
                    "risk_tier": tier,
                    "case_number": "CX-%s-%04d" % (2024, n),
                    "filing_date": dates.fill_date(),
                    "customer_name": ents.company() if is_biz else ents.person(),
                    "customer_kind": "business" if is_biz else "individual",
                    "account": "%d-%05d-1" % (drng.randint(10, 89), drng.randint(10000, 99999)),
                    "gold_amount": gold,
                    "labelled_amounts": labelled,
                    "support_amounts": [a["amount"] for a in labelled],
                    "contaminant": contaminant,
                    "contaminant_terms": terms,
                    "own_profile": own,
                    "foreign_profile": foreign,
                    "words": drng.randint(250, 470),
                    "seq": seq,
                })
    return plans


def case_prompt(plan: dict) -> str:
    own = plan["own_profile"]
    return (
        "%s\n\n"
        "TASK: write one internal Cortex Bank and Trust COMPLIANCE CASE MEMO.\n\n"
        "Case facts (use only these):\n"
        "  Case number: %s\n"
        "  Case type: %s (%s)\n"
        "  Risk tier: %s\n"
        "  Date opened: %s\n"
        "  Customer: %s (%s), account %s\n"
        "  The determinative figure at the centre of this case: %s\n"
        "  Every figure available to you, each with what it IS. The determinative figure\n"
        "  above is the first of them; use each figure only for the thing it is labelled\n"
        "  as, and do not introduce any other total:\n%s\n"
        "  Red flags to draw on: %s\n\n"
        "Structure the memo as continuous prose of approximately %d words in three "
        "movements, with no headings:\n"
        "  1. What was observed and how the case arose.\n"
        "  2. The analysis: why the observed activity fits %s. Cite %s exactly once as "
        "the determinative figure, attributed to this customer.\n"
        "  3. A 'related typology considered' movement of 60 to 90 words: state that the "
        "reviewing analyst also considered whether the activity was instead %s, and use "
        "ALL THREE of these phrases naturally while explaining why that reading was "
        "ultimately not adopted: %s. Write this movement as genuine analysis, not as a "
        "disclaimer.\n\n"
        "Also produce a title: 6 to 12 words naming the customer and what was actually "
        "OBSERVED, with no case number. The title must NOT name the case type or its "
        "typology. Do not use any of these words in the title: structuring, structured, "
        "CTR avoidance, sub-threshold, smurfing, wire fraud, business email compromise, "
        "sanctions, sanctioned, OFAC, KYC, know your customer, due diligence, elder, "
        "elderly, exploitation. Describe the observation instead, for example 'Repeated "
        "same-day cash deposits by Redstone Freight across three branches'. The title is "
        "indexed for search and a title that names the typology would give the answer "
        "away.\n\n"
        "Return JSON only: {\"title\": \"...\", \"body\": \"...\"}"
        % (SYSTEM_PREAMBLE, plan["case_number"], plan["case_type"], own["label"],
           plan["risk_tier"], prose_date(plan["filing_date"]), plan["customer_name"],
           plan["customer_kind"], plan["account"], plan["gold_amount"],
           "\n".join("    - %s: %s" % (a["label"], a["amount"])
                     for a in plan["labelled_amounts"]),
           "; ".join(own["red_flags"][:3]),
           plan["words"], own["typology"], plan["gold_amount"],
           plan["foreign_profile"]["typology"], "; ".join('"%s"' % t
                                                          for t in plan["contaminant_terms"]))
    )


def assemble_case(plan: dict, raw: str, ents: EntityBank, bank: AmountBank) -> dict:
    allowed = set(REG_CONSTANTS)
    allowed.update(plan["support_amounts"])
    allowed.add(plan["gold_amount"])
    memo = {}
    title, body = None, None
    if raw:
        try:
            parsed = parse_json_response(raw)
            title = (parsed.get("title") or "").strip()
            body = (parsed.get("body") or "").strip()
        except Exception:
            body = None
    repaired = not body
    if not body:
        own, foreign = plan["own_profile"], plan["foreign_profile"]
        title = "%s review - %s" % (own["label"].split(" / ")[0].title(),
                                    plan["customer_name"])
        body = (
            "Cortex Bank and Trust opened case %s on %s following a monitoring referral "
            "on the account of %s (account %s). The reviewing analyst examined the "
            "activity against the customer's recorded profile and identified %s. The "
            "activity is consistent with %s. The determinative figure established in "
            "this review is %s, attributed to this customer over the review period, with "
            "supporting items of %s. The relationship carries a %s risk tier.\n\n"
            "The reviewing analyst also considered whether the activity was instead %s. "
            "That reading would have required %s, %s, and %s to be present in a pattern "
            "the record does not support, and it was therefore not adopted. The case is "
            "retained in the %s queue for disposition."
            % (plan["case_number"], prose_date(plan["filing_date"]),
               plan["customer_name"], plan["account"], own["red_flags"][0],
               own["typology"], plan["gold_amount"],
               " and ".join(plan["support_amounts"][:2]), plan["risk_tier"],
               foreign["typology"], plan["contaminant_terms"][0],
               plan["contaminant_terms"][1], plan["contaminant_terms"][2],
               plan["case_type"])
        )
    body = scrub_forbidden(body, ents)
    body = sanitize_amounts(body, allowed, bank, memo)
    if plan["gold_amount"] not in body:
        body = ("%s\n\nThe determinative figure established in this review is %s."
                % (body, plan["gold_amount"]))
    present = [t for t in plan["contaminant_terms"] if t.lower() in body.lower()]
    if len(present) < 2:
        foreign = plan["foreign_profile"]
        body = ("%s\n\nThe reviewing analyst also considered whether the activity was "
                "instead %s, weighing %s, %s, and %s before setting that reading aside."
                % (body, foreign["typology"], plan["contaminant_terms"][0],
                   plan["contaminant_terms"][1], plan["contaminant_terms"][2]))
        present = plan["contaminant_terms"]
    if not title:
        title = "Compliance review - %s" % plan["customer_name"]
    return {
        "doc_id": plan["doc_id"],
        "case_id": plan["case_id"],
        "case_type": plan["case_type"],
        "risk_tier": plan["risk_tier"],
        "case_number": plan["case_number"],
        "filing_date": plan["filing_date"],
        "date_opened": plan["filing_date"],
        "customer_name": plan["customer_name"],
        "title": title,
        "body": body,
        "cross_type_vocabulary": plan["contaminant"],
        "cross_type_terms": plan["contaminant_terms"],
        "cross_type_terms_present": present,
        "gold_amount": plan["gold_amount"],
        "word_count": len(body.split()),
        "token_count": token_count(body),
        "_repaired": repaired,
    }


# ── Case intent questions ─────────────────────────────────────────────────────


def plan_case_questions(cases: list, rng: random.Random) -> list:
    """40 intent-labelled questions: 20 advanced, 12 naive, 8 agentic.

    Every question carries both a relevance set (``relevant_doc_ids``, the memos
    the intent selects, always 16 or more so precision@10 is reachable) and a
    single gold literal in one primary document, so the same question grades
    filtered precision in 3.3 and answer accuracy in 3.C.
    """
    by_type = {}
    for c in cases:
        by_type.setdefault(c["case_type"], []).append(c)

    specs = []
    # 20 advanced: 10 case_type only, 5 case_type + 2-tier set, 5 case_type + date window.
    for i in range(10):
        ctype = CASE_TYPES[i % len(CASE_TYPES)]
        specs.append({"pattern": "advanced", "case_type": ctype, "tiers": None, "window": None})
    for i in range(5):
        ctype = CASE_TYPES[i % len(CASE_TYPES)]
        specs.append({"pattern": "advanced", "case_type": ctype,
                      "tiers": ["medium", "high"] if i % 2 == 0 else ["low", "medium"],
                      "window": None})
    for i in range(5):
        ctype = CASE_TYPES[i % len(CASE_TYPES)]
        specs.append({"pattern": "advanced", "case_type": ctype, "tiers": None,
                      "window": ("2023-01-01", "2024-12-31") if i % 2 == 0
                                else ("2023-06-01", "2025-12-31")})
    for i in range(12):
        specs.append({"pattern": "naive", "case_type": CASE_TYPES[i % len(CASE_TYPES)],
                      "tiers": None, "window": None})
    for i in range(8):
        specs.append({"pattern": "agentic", "case_type": CASE_TYPES[i % len(CASE_TYPES)],
                      "tiers": None, "window": None})

    out = []
    used_primary = set()
    for qi, spec in enumerate(specs):
        ctype = spec["case_type"]
        pool = by_type[ctype]
        rel = [c for c in pool
               if (spec["tiers"] is None or c["risk_tier"] in spec["tiers"])
               and (spec["window"] is None
                    or spec["window"][0] <= c["filing_date"] <= spec["window"][1])]
        if len(rel) < 12:
            rel = list(pool)
            spec["tiers"], spec["window"] = None, None
        candidates = [c for c in rel if c["doc_id"] not in used_primary] or rel
        primary = candidates[qi % len(candidates)]
        used_primary.add(primary["doc_id"])
        second = None
        if spec["pattern"] == "agentic":
            alt = [c for c in rel if c["doc_id"] != primary["doc_id"]]
            second = alt[(qi * 7) % len(alt)]
        out.append({
            "question_id": "q-case-%03d" % (qi + 1),
            "intent_label": ctype,
            "retrieval_pattern": spec["pattern"],
            "intent": {
                "case_type": ctype,
                "risk_tier": spec["tiers"],
                "date_from": spec["window"][0] if spec["window"] else None,
                "date_to": spec["window"][1] if spec["window"] else None,
            },
            "_primary": primary,
            "_second": second,
            "relevant_doc_ids": sorted(c["doc_id"] for c in rel),
        })
    return out


def case_question_prompt(batch: list) -> str:
    lines = []
    for q in batch:
        p = q["_primary"]
        extra = ""
        if q["_second"] is not None:
            s = q["_second"]
            extra = (" SECOND DOCUMENT (this question must require both): customer %s, "
                     "figure %s." % (s["customer_name"], s["gold_amount"]))
        intent = q["intent"]
        scope = ["case type %s" % intent["case_type"]]
        if intent["risk_tier"]:
            scope.append("risk tier in %s" % " or ".join(intent["risk_tier"]))
        if intent["date_from"]:
            scope.append("opened between %s and %s" % (intent["date_from"], intent["date_to"]))
        lines.append(
            "- id %s | pattern %s | scope: %s | primary document: customer %s, "
            "title '%s', determinative figure %s.%s"
            % (q["question_id"], q["retrieval_pattern"], "; ".join(scope),
               p["customer_name"], p["title"], p["gold_amount"], extra)
        )
    return (
        "You are writing search questions a Cortex Bank and Trust compliance analyst "
        "would type when looking through the bank's internal case memo corpus. The corpus "
        "is synthetic training data: 120 memos across five case types (structuring, "
        "wire_fraud, sanctions, kyc_gap, elder_exploitation) and three risk tiers.\n\n"
        "Write one question per item below. Rules by pattern:\n"
        "- naive: ask for the one determinative figure in the primary document, naming "
        "the customer so exactly one memo can answer it.\n"
        "- advanced: ask a question whose natural scope is the stated filter (case type, "
        "and risk tier or date window when stated) AND which ends by asking for the "
        "determinative figure in the primary document, naming that customer. The question "
        "must read as one natural analyst question, not two bolted together.\n"
        "- agentic: require facts from BOTH named documents in one question, so no single "
        "memo answers it.\n\n"
        "CRITICAL: never name the case type in the question text. Do not use the words "
        "'structuring', 'wire fraud', 'sanctions', 'OFAC', 'KYC', 'know your customer', "
        "'due diligence', or 'elder' (or 'elderly', 'exploitation'), and do not use a "
        "close paraphrase of the typology such as 'sub-threshold cash scheme' or "
        "'business email compromise'. Describe the activity in the analyst's own plain "
        "words instead. The filter carries the case type; if the question names it, the "
        "filter adds nothing and the exercise it supports is void.\n\n"
        "Every question: one sentence, 15 to 40 words, no case numbers, no invented "
        "figures, phrased as a question. Never mention the words 'primary document'.\n\n"
        "Items:\n%s\n\n"
        "Return JSON only: an array of objects "
        "{\"question_id\": \"...\", \"text\": \"...\"}"
        % "\n".join(lines)
    )


def finalize_case_questions(specs: list, texts: dict) -> list:
    out = []
    for q in specs:
        p, s = q["_primary"], q["_second"]
        text = texts.get(q["question_id"])
        if not text:
            if s is not None:
                text = ("Across the Cortex case memos, what determinative figures were "
                        "established for %s and for %s?" % (p["customer_name"],
                                                            s["customer_name"]))
            else:
                text = ("In the Cortex %s case memos, what determinative figure was "
                        "established for %s?" % (q["intent_label"].replace("_", " "),
                                                 p["customer_name"]))
        item = {
            "question_id": q["question_id"],
            "text": text,
            "intent_label": q["intent_label"],
            "retrieval_pattern": q["retrieval_pattern"],
            "intent": q["intent"],
            "gold_doc_ids": [p["doc_id"]] + ([s["doc_id"]] if s is not None else []),
            "gold_literal": p["gold_amount"],
            "gold_literals": [p["gold_amount"]] + ([s["gold_amount"]] if s is not None else []),
            "hop": "multi" if s is not None else "single",
            "relevant_doc_ids": q["relevant_doc_ids"],
        }
        out.append(item)
    return out


def claim_question_prompt(cases: list, policy_ids: list) -> str:
    lines = []
    for c in cases:
        lines.append("- memo %s | case type %s | customer %s | determinative figure %s"
                     % (c["doc_id"], c["case_type"], c["customer_name"], c["gold_amount"]))
    return (
        "You are preparing a claim-attribution development set for a Cortex Bank and "
        "Trust compliance assistant. The assistant answers over two synthetic corpora: "
        "internal case memos, and the bank's BSA/AML policy library (policy document ids "
        "%s, covering structuring red flags, KYC due diligence, CTR versus SAR filing, "
        "beneficial ownership, transaction monitoring, sanctions screening, escalation, "
        "customer risk assessment, wire transfer red flags, and elder financial "
        "exploitation among others).\n\n"
        "Write one question per memo below. Each question must:\n"
        "- be answerable by combining the named memo with the bank's policy library, so a "
        "good answer contains at least one claim grounded in the memo and at least one "
        "claim grounded in policy;\n"
        "- name the customer so the memo is unambiguous;\n"
        "- ask something a compliance analyst would actually ask, such as whether the "
        "activity met a filing obligation or which control should have caught it;\n"
        "- be one sentence of 15 to 35 words, with no invented figures.\n\n"
        "Memos:\n%s\n\n"
        "Return JSON only: an array of "
        "{\"doc_id\": \"...\", \"text\": \"...\", \"policy_topic\": \"a short lowercase "
        "topic naming the policy area the policy-grounded claim comes from\"}"
        % (", ".join(policy_ids[:6]) + ", ...", "\n".join(lines))
    )


# ── T9 structural validation ──────────────────────────────────────────────────


def enforce_gold_uniqueness(corpora: dict, ents: EntityBank, bank: AmountBank) -> dict:
    """Make every gold literal unique to its owning document.

    Scans every body in the corpus for every other document's gold literals and
    rewrites the foreign occurrences.  Amounts and entities get fresh globally
    unique allocations; dates get shifted out of the reserved gold window.  Runs
    to a fixed point so substitutes cannot reintroduce a collision.
    """
    docs = []
    for name, items in corpora.items():
        for d in items:
            docs.append((name, d))

    owners = {}
    for name, d in docs:
        for field in ("gold_amount", "gold_entity", "gold_date", "key_date"):
            lit = d.get(field)
            if lit:
                owners.setdefault(lit, (d["doc_id"], field))

    report = {"collisions": 0, "rewrites": []}
    for _ in range(4):
        collisions = 0
        for name, d in docs:
            # Sections are the unit of rewrite where they exist, so the body,
            # the gold-section field, and the derived passages stay in step.
            targets = d.get("_sections") or [d]
            touched = False
            for sec in targets:
                text = sec["body"]
                for lit, (owner_id, field) in owners.items():
                    if owner_id == d["doc_id"] or len(lit) < 6 or lit not in text:
                        continue
                    if field == "gold_amount":
                        sub = bank.decoy()
                    elif field == "gold_entity":
                        sub = ents.company()
                    else:
                        # Shift 400 days back: that lands inside DateBank's fill
                        # windows, which are disjoint from the reserved gold
                        # window, so the substitute can never be a gold date.
                        y, m, dd = _parse_prose_date(lit)
                        sub = prose_date((date(y, m, dd) - timedelta(days=400)).isoformat())
                    text = text.replace(lit, sub)
                    collisions += 1
                    report["rewrites"].append({
                        "in_doc": d["doc_id"], "literal": lit,
                        "owned_by": owner_id, "replaced_with": sub,
                    })
                if text != sec["body"]:
                    sec["body"] = text
                    touched = True
            if touched:
                if d.get("_sections"):
                    rebuild_doc(d, {"key_finding", "findings"})
                else:
                    d["token_count"] = token_count(d["body"])
                    if "word_count" in d:
                        d["word_count"] = len(d["body"].split())
        report["collisions"] += collisions
        if collisions == 0:
            break
    return report


_MONTHS = ["January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December"]


def _parse_prose_date(text: str):
    m = re.match(r"([A-Za-z]+) (\d{1,2}), (\d{4})", text)
    if not m:
        return (2024, 1, 1)
    return (int(m.group(3)), _MONTHS.index(m.group(1)) + 1, int(m.group(2)))


def validate(sars: list, passages: list, investigations: list, facts: list,
             cases: list, case_questions: list, dev_sets: dict = None,
             verbose: bool = True) -> dict:
    """The T9 structural checks the private validate_heldout.py delegates to."""
    failures, warnings = [], []

    def check(label, ok, detail=""):
        if ok:
            if verbose:
                print("  \033[32mPASS\033[0m  %s" % label)
        else:
            if verbose:
                print("  \033[31mFAIL\033[0m  %s%s" % (label, (": " + detail) if detail else ""))
            failures.append(label)

    def warn(label, ok, detail=""):
        if not ok:
            if verbose:
                print("  \033[33mWARN\033[0m  %s%s" % (label, (": " + detail) if detail else ""))
            warnings.append("%s: %s" % (label, detail))

    print("\n=== counts ===")
    check("sar_count", len(sars) == len(BUCKET_ORDER) * SARS_PER_BUCKET,
          "found %d" % len(sars))
    for b in BUCKET_ORDER:
        n = sum(1 for s in sars if s["bucket"] == b)
        check("sar_%s_count" % b, n == SARS_PER_BUCKET, "found %d" % n)
    check("investigation_count", len(investigations) == N_INVESTIGATIONS,
          "found %d" % len(investigations))
    check("fact_index_count", len(facts) == len(investigations), "found %d" % len(facts))
    check("case_count", len(cases) == len(CASE_TYPES) * len(RISK_TIERS) * N_CASES_PER_CELL,
          "found %d" % len(cases))
    check("case_question_count", len(case_questions) == N_CASE_QUESTIONS,
          "found %d" % len(case_questions))
    cell = {}
    for c in cases:
        cell[(c["case_type"], c["risk_tier"])] = cell.get((c["case_type"], c["risk_tier"]), 0) + 1
    check("case_cells_balanced",
          all(v == N_CASES_PER_CELL for v in cell.values()) and len(cell) == 15,
          "cells=%d" % len(cell))

    print("\n=== gold literals unique to their documents (T9.1) ===")
    all_docs = [("sar", s) for s in sars] + [("inv", i) for i in investigations] \
        + [("case", c) for c in cases]
    lit_owner = {}
    dupes = []
    for _, d in all_docs:
        for field in ("gold_amount", "gold_entity", "gold_date", "key_date"):
            lit = d.get(field)
            if not lit:
                continue
            if lit in lit_owner and lit_owner[lit] != d["doc_id"]:
                dupes.append((lit, lit_owner[lit], d["doc_id"]))
            lit_owner[lit] = d["doc_id"]
    check("gold_literals_not_shared_between_docs", not dupes,
          "; ".join("%s owned by %s and %s" % t for t in dupes[:4]))

    leaks = []
    for _, d in all_docs:
        for lit, owner in lit_owner.items():
            if owner == d["doc_id"] or len(lit) < 6:
                continue
            if lit in d["body"]:
                leaks.append((lit, owner, d["doc_id"]))
    check("no_gold_literal_appears_in_a_foreign_document", not leaks,
          "; ".join("%s (owner %s) found in %s" % t for t in leaks[:4]))

    print("\n=== gold literals present in their own gold section (T9.2) ===")
    missing = []
    for s in sars:
        for lit in (s["gold_amount"], s["gold_entity"], s["gold_date"]):
            if lit not in s["key_finding"]:
                missing.append("%s missing %s" % (s["doc_id"], lit))
    for i in investigations:
        for lit in (i["gold_amount"], i["gold_entity"], i["key_date"]):
            if lit not in i["key_finding"]:
                missing.append("%s missing %s" % (i["doc_id"], lit))
    for c in cases:
        if c["gold_amount"] not in c["body"]:
            missing.append("%s missing %s" % (c["doc_id"], c["gold_amount"]))
    check("gold_literal_in_own_gold_section", not missing, "; ".join(missing[:4]))

    print("\n=== single-document answerability (T9.3) ===")
    bad = []
    for s in sars:
        for q in s["questions"]:
            if q["hop"] != "single":
                continue
            others = [o for o in sars if o["doc_id"] != s["doc_id"]
                      and q["gold_literal"] in o["body"]]
            if others:
                bad.append("%s answerable from %s" % (q["question_id"], others[0]["doc_id"]))
    check("sar_questions_single_document_answerable", not bad, "; ".join(bad[:4]))

    multi = [q for q in case_questions if q["hop"] == "multi"]
    check("two_hop_questions_exist", len(multi) >= 4, "found %d" % len(multi))
    no_single = []
    for q in multi:
        for c in cases:
            if all(lit in c["body"] for lit in q["gold_literals"]):
                no_single.append("%s fully answerable from %s" % (q["question_id"], c["doc_id"]))
    check("two_hop_questions_have_no_single_document_answer", not no_single,
          "; ".join(no_single[:4]))

    print("\n=== passages ===")
    by_narrative = {}
    for p in passages:
        by_narrative.setdefault(p["narrative_id"], []).append(p)
    check("every_sar_has_passages", len(by_narrative) == len(sars),
          "found %d" % len(by_narrative))
    check("passage_ids_unique",
          len({p["section_id"] for p in passages}) == len(passages))
    kf_ok, kf_bad = 0, []
    pass_by_id = {p["section_id"]: p for p in passages}
    for s in sars:
        p = pass_by_id.get(s["key_finding_section_id"])
        if p is None or not p["is_key_finding"] or s["gold_amount"] not in p["body"]:
            kf_bad.append(s["doc_id"])
        else:
            kf_ok += 1
    check("key_finding_section_id_resolves_to_the_gold_passage", not kf_bad,
          "bad: %s" % ",".join(kf_bad[:5]))
    check("every_narrative_has_exactly_one_key_finding_passage",
          all(sum(1 for p in ps if p["is_key_finding"]) == 1
              for ps in by_narrative.values()))

    print("\n=== bucket token targets ===")
    for b in BUCKET_ORDER:
        vals = [s["token_count"] for s in sars if s["bucket"] == b]
        if not vals:
            continue
        target = BUCKETS[b]
        lo, hi = min(vals), max(vals)
        inside = all(target * 0.85 <= v <= target * 1.15 for v in vals)
        check("%s_within_15pct_of_%d" % (b, target), inside,
              "range %d-%d" % (lo, hi))

    print("\n=== fact index beats raw reports on size ===")
    raw_avg = sum(i["token_count"] for i in investigations) / max(1, len(investigations))
    fact_avg = sum(f["token_count"] for f in facts) / max(1, len(facts))
    reduction = 1 - (fact_avg / raw_avg) if raw_avg else 0
    check("fact_index_at_least_60pct_smaller_than_raw_reports", reduction >= 0.60,
          "reduction %.2f (raw %.0f, fact %.0f)" % (reduction, raw_avg, fact_avg))
    fact_missing = [f["doc_id"] for f in facts
                    if not any(f["doc_id"] == i["doc_id"] and i["gold_amount"] in f["summary"]
                               for i in investigations)]
    check("fact_summary_carries_the_gold_amount", not fact_missing,
          ",".join(fact_missing[:5]))

    print("\n=== case corpus contamination ===")
    weak = [c["doc_id"] for c in cases if len(c["cross_type_terms_present"]) < 2]
    check("every_memo_carries_at_least_two_foreign_type_terms", not weak,
          "%d weak: %s" % (len(weak), ",".join(weak[:5])))
    spread = {}
    for c in cases:
        spread[(c["case_type"], c["cross_type_vocabulary"])] = \
            spread.get((c["case_type"], c["cross_type_vocabulary"]), 0) + 1
    check("contamination_spread_across_all_type_pairs", len(spread) == 20,
          "pairs=%d" % len(spread))
    if spread:
        warn("contamination_evenly_distributed",
             max(spread.values()) - min(spread.values()) <= 2,
             "counts %d-%d" % (min(spread.values()), max(spread.values())))

    print("\n=== precision@10 reachability for filtered queries ===")
    short = [q["question_id"] for q in case_questions if len(q["relevant_doc_ids"]) < 12]
    check("every_case_question_has_at_least_12_relevant_docs", not short,
          ",".join(short[:5]))
    # If a question names its own case type, an unfiltered semantic query already
    # finds the right type and the filtered-precision exercise measures nothing.
    type_words = re.compile(
        r"\b(structuring|structured cash|wire fraud|sanction\w*|ofac|kyc|"
        r"know your customer|due diligence|elder\w*|exploitation|"
        r"business email compromise|sub-?threshold)\b", re.IGNORECASE)
    leaky = [q["question_id"] for q in case_questions if type_words.search(q["text"])]
    warn("case_questions_do_not_name_their_case_type", not leaky,
         "%d of %d leak: %s" % (len(leaky), len(case_questions), ",".join(leaky[:6])))
    # `title` is indexed as `text`, so a title naming its own typology is a
    # high-weight lexical signal that only correct-type memos carry. That
    # asymmetry lifts unfiltered precision out of the 0.40-0.60 band the
    # filtered-retrieval exercise needs, so it is a hard failure.
    leaky_titles = [c["doc_id"] for c in cases if type_words.search(c["title"])]
    check("case_titles_do_not_name_their_case_type", not leaky_titles,
          "%d of %d leak, e.g. %s" % (len(leaky_titles), len(cases),
                                      ", ".join(leaky_titles[:4])))
    odd = [c["doc_id"] for c in cases if c["case_type"] == "elder_exploitation"
           and re.search(r"(LLC|Inc\.|Corp\.|Ltd\.|LP|Co\.|Group|Enterprises|Holdings"
                         r"|Partners)", c["customer_name"])]
    check("elder_exploitation_subjects_are_individuals", not odd,
          "%d business subjects: %s" % (len(odd), ",".join(odd[:4])))

    if dev_sets:
        print("\n=== dev sets ===")
        known_passages = {p["section_id"] for p in passages}
        known_docs = {d["doc_id"] for _, d in all_docs}
        expected = {"track-3-1/dev-queries-sar": 40,
                    "track-3-1/dev-queries-investigations": 8,
                    "track-3-3/dev-queries": 20,
                    "track-3-4/dev-claim-questions": 10}
        for name, rows in sorted(dev_sets.items()):
            if name in expected:
                check("devset_%s_count" % name.replace("/", "_"),
                      len(rows) == expected[name],
                      "found %d, expected %d" % (len(rows), expected[name]))
            dangling, empty = [], []
            for q in rows:
                if not (q.get("query_text") or "").strip():
                    empty.append(q["query_id"])
                for rid in q.get("relevant_ids", []):
                    if rid not in known_passages and rid not in known_docs:
                        dangling.append("%s -> %s" % (q["query_id"], rid))
            check("devset_%s_ids_resolve" % name.replace("/", "_"), not dangling,
                  "; ".join(dangling[:4]))
            check("devset_%s_no_empty_query_text" % name.replace("/", "_"), not empty,
                  ",".join(empty[:4]))
        sar_dev = dev_sets.get("track-3-1/dev-queries-sar") or []
        per_bucket = {}
        for q in sar_dev:
            per_bucket[q.get("bucket")] = per_bucket.get(q.get("bucket"), 0) + 1
        check("devset_3_1_has_8_questions_per_bucket",
              all(per_bucket.get(b) == 8 for b in BUCKET_ORDER),
              str(per_bucket))
        # The public dev set must not consume questions the held-out set needs.
        sar_used = {q["question_id"] for q in sar_dev}
        spare_by_bucket = {}
        for s in sars:
            spare_by_bucket[s["bucket"]] = spare_by_bucket.get(s["bucket"], 0) + sum(
                1 for q in s["questions"] if q["question_id"] not in sar_used)
        check("at_least_10_heldout_sar_questions_per_bucket_remain",
              all(spare_by_bucket.get(b, 0) >= 10 for b in BUCKET_ORDER),
              str(spare_by_bucket))
        inv_used = {q["question_id"]
                    for q in (dev_sets.get("track-3-1/dev-queries-investigations") or [])}
        inv_spare = sum(1 for r in investigations for q in r["questions"]
                        if q["question_id"] not in inv_used)
        check("at_least_10_heldout_investigation_questions_remain", inv_spare >= 10,
              "spare=%d" % inv_spare)
        dev_33_ids = {q["question_id"]
                      for q in (dev_sets.get("track-3-3/dev-queries") or [])}
        check("at_least_20_heldout_case_questions_remain",
              len(case_questions) - len(dev_33_ids) >= 20,
              "spare=%d" % (len(case_questions) - len(dev_33_ids)))

    print("\n=== retired names and vendor tokens ===")
    hits = []
    for _, d in all_docs:
        low = d["body"].lower()
        for frag in FORBIDDEN_NAME_FRAGMENTS:
            if re.search(r"\b%s" % frag, low):
                hits.append("%s contains '%s'" % (d["doc_id"], frag))
        if FORBIDDEN_TOKEN_RE.search(d["body"]):
            hits.append("%s contains a vendor token" % d["doc_id"])
    check("no_retired_names_or_vendor_tokens_in_corpus", not hits, "; ".join(hits[:4]))

    print()
    if failures:
        print("RESULT: \033[31mFAIL\033[0m — %d check(s) failed: %s"
              % (len(failures), failures))
    else:
        print("RESULT: \033[32mPASS\033[0m — all %s structural checks passed%s"
              % ("T9", " (%d warning(s))" % len(warnings) if warnings else ""))
    return {"failures": failures, "warnings": warnings}


# ── Output ────────────────────────────────────────────────────────────────────


def write_jsonl(path: Path, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        for r in rows:
            fh.write(json.dumps({k: v for k, v in r.items() if not k.startswith("_")},
                                ensure_ascii=False) + "\n")


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def clean(rows: list) -> list:
    return [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]


def token_stats(rows: list) -> dict:
    vals = sorted(r["token_count"] for r in rows)
    if not vals:
        return {}
    return {"min": vals[0], "max": vals[-1],
            "mean": round(sum(vals) / len(vals), 1),
            "total": sum(vals)}


def manifest(dataset: str, rows: list, extra: dict) -> dict:
    m = {
        "dataset": dataset,
        "generator": "scripts/gen_cortex_m3.py",
        "generator_version": GENERATOR_VERSION,
        "seed": SEED,
        "model": GEN_MODEL,
        "document_count": len(rows),
        "token_stats": token_stats(rows),
        "synthetic": True,
        "notes": MANIFEST_NOTES,
    }
    m.update(extra)
    return m


# ── Orchestration ─────────────────────────────────────────────────────────────


def run_tasks(gen: Generator, tasks: list, desc: str) -> dict:
    out = {}
    if not tasks:
        return out
    done = [0]
    lock = threading.Lock()
    t0 = time.time()

    def work(t):
        try:
            return t["id"], gen.generate(t["prompt"], t["max_tokens"], t["temperature"],
                                         as_json=t["json"], label=t["label"])
        except Exception as exc:  # noqa: BLE001
            print("  !! %s failed: %s" % (t["label"], str(exc)[:160]))
            return t["id"], None

    with futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        for key, text in ex.map(work, tasks):
            out[key] = text
            with lock:
                done[0] += 1
                if done[0] % 25 == 0 or done[0] == len(tasks):
                    el = time.time() - t0
                    print("  %s %d/%d  (%.0fs elapsed, %d cache hits)"
                          % (desc, done[0], len(tasks), el, gen.cache_hits))
    return out


def load_existing():
    sars = []
    for b in BUCKET_ORDER:
        p = DATA / "cortex-sar-narratives" / ("%s.jsonl" % b)
        if p.exists():
            sars += [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    pp = DATA / "cortex-sar-passages" / "passages.jsonl"
    passages = [json.loads(l) for l in pp.read_text().splitlines() if l.strip()] \
        if pp.exists() else []
    ip = DATA / "cortex-investigations" / "investigations.jsonl"
    invs = [json.loads(l) for l in ip.read_text().splitlines() if l.strip()] \
        if ip.exists() else []
    fp = DATA / "cortex-investigation-facts.json"
    facts = json.loads(fp.read_text()) if fp.exists() else []
    cp = DATA / "cortex-cases" / "cases.jsonl"
    cases = [json.loads(l) for l in cp.read_text().splitlines() if l.strip()] \
        if cp.exists() else []
    qp = DATA / "cortex-cases-questions.json"
    cqs = json.loads(qp.read_text()) if qp.exists() else []
    dev = {}
    for name in ("track-3-1/dev-queries-sar", "track-3-1/dev-queries-investigations",
                 "track-3-3/dev-queries", "track-3-4/dev-claim-questions"):
        dp = DATA / "dev-sets" / "m3" / (name + ".json")
        if dp.exists():
            dev[name] = json.loads(dp.read_text())
    return sars, passages, invs, facts, cases, cqs, dev


def policy_doc_ids() -> list:
    corpus = DATA / "cortex-corpus"
    ids = []
    if corpus.exists():
        for p in sorted(corpus.glob("policy-*.md")):
            parts = p.stem.split("-")
            ids.append("-".join(parts[:2]))
    return ids


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--only", choices=["all", "sar", "inv", "cases", "devsets"],
                    default="all")
    ap.add_argument("--smoke", action="store_true",
                    help="2 SARs per bucket, 4 investigations, 15 memos")
    ap.add_argument("--validate", action="store_true",
                    help="re-run T9 checks on the committed output, no API calls")
    ap.add_argument("--workers", type=int, default=None)
    args = ap.parse_args()

    global MAX_WORKERS
    if args.workers:
        MAX_WORKERS = args.workers

    if args.validate:
        sars, passages, invs, facts, cases, cqs, dev = load_existing()
        res = validate(sars, passages, invs, facts, cases, cqs, dev)
        return 1 if res["failures"] else 0

    per_bucket = 2 if args.smoke else SARS_PER_BUCKET
    n_inv = 4 if args.smoke else N_INVESTIGATIONS
    per_cell = 1 if args.smoke else N_CASES_PER_CELL

    random.seed(SEED)
    rng = random.Random(SEED)
    bank = AmountBank(random.Random(SEED + 1))
    ents = EntityBank(random.Random(SEED + 2))
    dates = DateBank(random.Random(SEED + 3))
    gen = Generator()

    print("gen_cortex_m3 v%s  model=%s  seed=%d  workers=%d"
          % (GENERATOR_VERSION, GEN_MODEL, SEED, MAX_WORKERS))
    print("cache: %s" % CACHE_DIR)

    # Plan everything first: all literal allocation is sequential and seeded.
    # Every gold date is reserved before any other date is drawn, so no
    # supporting date anywhere in the corpus can equal another document's gold
    # date.  See DateBank.reserve_gold.
    n_sar = per_bucket * len(BUCKET_ORDER)
    gold_dates = dates.reserve_gold(n_sar + n_inv)
    sar_plans = plan_sars(bank, ents, dates, rng, per_bucket, gold_dates[:n_sar])
    inv_plans = plan_investigations(bank, ents, dates, rng, n_inv, gold_dates[n_sar:])
    case_plans = plan_cases(bank, ents, dates, rng, per_cell)

    tasks = []
    if args.only in ("all", "sar"):
        tasks += build_sar_tasks(sar_plans)
    if args.only in ("all", "inv"):
        tasks += build_inv_tasks(inv_plans)
    if args.only in ("all", "cases"):
        for p in case_plans:
            tasks.append({"id": "%s|memo" % p["doc_id"], "prompt": case_prompt(p),
                          "max_tokens": 2600, "temperature": 0.95, "json": True,
                          "label": "%s memo" % p["doc_id"]})

    print("\nphase 1: %d prose/JSON generations" % len(tasks))
    out = run_tasks(gen, tasks, "generated")

    print("\nphase 2: assembling documents")
    sars = [assemble_sar(p, out, ents) for p in sar_plans] if args.only in ("all", "sar") else []
    invs = [assemble_investigation(p, out, ents) for p in inv_plans] \
        if args.only in ("all", "inv") else []
    cases = [assemble_case(p, out.get("%s|memo" % p["doc_id"]), ents, bank)
             for p in case_plans] if args.only in ("all", "cases") else []

    print("\nphase 3: uniqueness enforcement across the assembled corpus")
    uniq = enforce_gold_uniqueness({"sar": sars, "inv": invs, "case": cases}, ents, bank)
    print("  rewrote %d foreign gold-literal occurrence(s)" % uniq["collisions"])

    print("\nphase 4: dependent generations (fact index, question text)")
    dep = []
    for r in invs:
        dep.append({"id": "%s|facts" % r["doc_id"], "prompt": fact_index_prompt(r),
                    "max_tokens": 2400, "temperature": 0.4, "json": True,
                    "label": "%s facts" % r["doc_id"]})
    case_q_specs = plan_case_questions(cases, rng) if cases else []
    for i in range(0, len(case_q_specs), 8):
        batch = case_q_specs[i:i + 8]
        dep.append({"id": "caseq|%d" % i, "prompt": case_question_prompt(batch),
                    "max_tokens": 3000, "temperature": 0.8, "json": True,
                    "label": "case questions %d" % i})
    claim_cases = cases[::max(1, len(cases) // 10)][:10] if cases else []
    if claim_cases:
        dep.append({"id": "claimq", "prompt": claim_question_prompt(claim_cases, policy_doc_ids()),
                    "max_tokens": 3000, "temperature": 0.8, "json": True,
                    "label": "claim questions"})
    dep_out = run_tasks(gen, dep, "generated")

    facts = [assemble_fact_record(r, dep_out.get("%s|facts" % r["doc_id"])) for r in invs]

    q_texts = {}
    for i in range(0, len(case_q_specs), 8):
        raw = dep_out.get("caseq|%d" % i)
        if not raw:
            continue
        try:
            for item in parse_json_response(raw):
                if item.get("question_id") and item.get("text"):
                    q_texts[item["question_id"]] = item["text"].strip()
        except Exception:
            pass
    case_questions = finalize_case_questions(case_q_specs, q_texts)

    print("\nphase 5: passages, dev sets, manifests")
    passages = []
    for s in sars:
        passages += derive_passages(s)

    # ── dev sets ──
    dev_sar, dev_inv = [], []
    n = 0
    for b in BUCKET_ORDER:
        bucket_sars = [s for s in sars if s["bucket"] == b]
        for s in bucket_sars:
            q = s["questions"][0]
            n += 1
            dev_sar.append({
                "query_id": "dev-3-1-%02d" % n,
                "query_text": q["text"],
                "relevant_ids": [s["key_finding_section_id"]],
                "relevant_passage_ids": [s["key_finding_section_id"]],
                "relevant_doc_ids": [s["doc_id"]],
                "bucket": b,
                "narrative_id": s["doc_id"],
                "gold_literal": q["gold_literal"],
                "question_id": q["question_id"],
            })
    for i, r in enumerate(invs[:8] if len(invs) >= 8 else invs):
        q = r["questions"][0]
        dev_inv.append({
            "query_id": "dev-3-1-inv-%02d" % (i + 1),
            "query_text": q["text"],
            "relevant_ids": [r["doc_id"]],
            "relevant_doc_ids": [r["doc_id"]],
            "gold_literal": q["gold_literal"],
            "question_id": q["question_id"],
            "outcome": r["outcome"],
        })

    # The public 3.3 dev set is the 20 filter-intent ("advanced") questions; the
    # remaining 20 stay clean for the track's private held-out set.
    dev_33 = []
    adv = [q for q in case_questions if q["retrieval_pattern"] == "advanced"]
    others = [q for q in case_questions if q["retrieval_pattern"] != "advanced"]
    chosen = (adv + others)[:20]
    for i, q in enumerate(chosen):
        dev_33.append({
            "query_id": "dev-3-3-%02d" % (i + 1),
            "query_text": q["text"],
            "relevant_ids": q["relevant_doc_ids"],
            "relevant_doc_ids": q["relevant_doc_ids"],
            "intent_label": q["intent_label"],
            "intent": q["intent"],
            "retrieval_pattern": q["retrieval_pattern"],
            "gold_doc_ids": q["gold_doc_ids"],
            "gold_literal": q["gold_literal"],
            "question_id": q["question_id"],
        })

    dev_34 = []
    claim_items = {}
    raw = dep_out.get("claimq")
    if raw:
        try:
            for item in parse_json_response(raw):
                if item.get("doc_id") and item.get("text"):
                    claim_items[item["doc_id"]] = item
        except Exception:
            pass
    for i, c in enumerate(claim_cases):
        item = claim_items.get(c["doc_id"], {})
        text = item.get("text") or (
            "For the Cortex case memo on %s, did the activity meet the bank's filing "
            "obligation, and which control should have detected it?" % c["customer_name"])
        dev_34.append({
            "query_id": "dev-3-4-%02d" % (i + 1),
            "query_text": text,
            "relevant_ids": [c["doc_id"]],
            "relevant_doc_ids": [c["doc_id"]],
            "case_type": c["case_type"],
            "policy_topic": item.get("policy_topic", c["case_type"]),
            "gold_literal": c["gold_amount"],
            "expected_claim_sources": ["cortex-cases", "cortex-policies"],
            "note": ("A grounded answer carries at least one claim attributable to the "
                     "memo and at least one attributable to the policy library."),
        })

    print("\nphase 6: T9 structural validation")
    dev_sets = {
        "track-3-1/dev-queries-sar": dev_sar,
        "track-3-1/dev-queries-investigations": dev_inv,
        "track-3-3/dev-queries": dev_33,
        "track-3-4/dev-claim-questions": dev_34,
    }
    res = validate(sars, passages, invs, facts, cases, case_questions, dev_sets)

    print("\nphase 7: writing files")
    if sars:
        for b in BUCKET_ORDER:
            rows = [s for s in sars if s["bucket"] == b]
            if rows:
                write_jsonl(DATA / "cortex-sar-narratives" / ("%s.jsonl" % b), rows)
        write_json(DATA / "cortex-sar-narratives" / "manifest.json",
                   manifest("cortex-sar-narratives", clean(sars), {
                       "buckets": {b: BUCKETS[b] for b in BUCKET_ORDER},
                       "files": ["%s.jsonl" % b for b in BUCKET_ORDER],
                       "questions_per_narrative": QUESTIONS_PER_SAR,
                       "question_count": sum(len(s["questions"]) for s in sars),
                       "repaired_key_findings": sum(1 for s in sars
                                                    if s["_repaired_key_finding"]),
                   }))
        write_jsonl(DATA / "cortex-sar-passages" / "passages.jsonl", passages)
        write_json(DATA / "cortex-sar-passages" / "manifest.json",
                   manifest("cortex-sar-passages", passages, {
                       "files": ["passages.jsonl"],
                       "derived_from": "cortex-sar-narratives",
                       "section_types": sorted({p["section_type"] for p in passages}),
                   }))
    if invs:
        write_jsonl(DATA / "cortex-investigations" / "investigations.jsonl", invs)
        write_json(DATA / "cortex-investigations" / "manifest.json",
                   manifest("cortex-investigations", clean(invs), {
                       "files": ["investigations.jsonl"],
                       "outcomes": sorted({r["outcome"] for r in invs}),
                       "question_count": sum(len(r["questions"]) for r in invs),
                       "repaired_findings": sum(1 for r in invs if r["_repaired_findings"]),
                   }))
        write_json(DATA / "cortex-investigation-facts.json", facts)
    if cases:
        write_jsonl(DATA / "cortex-cases" / "cases.jsonl", cases)
        ndjson = DATA / "cortex-cases" / "cortex-cases.ndjson"
        ndjson.parent.mkdir(parents=True, exist_ok=True)
        with ndjson.open("w") as fh:
            for c in cases:
                fh.write(json.dumps({
                    "case_id": c["case_id"], "case_type": c["case_type"],
                    "risk_tier": c["risk_tier"], "filing_date": c["filing_date"],
                    "title": c["title"], "body": c["body"],
                }, ensure_ascii=False) + "\n")
        write_json(DATA / "cortex-cases" / "manifest.json",
                   manifest("cortex-cases", clean(cases), {
                       "files": ["cases.jsonl", "cortex-cases.ndjson"],
                       "bulk_load_file": "cortex-cases.ndjson",
                       "bulk_load_fields": ["case_id", "case_type", "risk_tier",
                                            "filing_date", "title", "body"],
                       "case_types": CASE_TYPES, "risk_tiers": RISK_TIERS,
                       "per_cell": per_cell,
                       "repaired_memos": sum(1 for c in cases if c["_repaired"]),
                   }))
        write_json(DATA / "cortex-cases-questions.json", case_questions)
    if dev_sar:
        write_json(DATA / "dev-sets" / "m3" / "track-3-1" / "dev-queries-sar.json", dev_sar)
    if dev_inv:
        write_json(DATA / "dev-sets" / "m3" / "track-3-1" / "dev-queries-investigations.json",
                   dev_inv)
    if dev_33:
        write_json(DATA / "dev-sets" / "m3" / "track-3-3" / "dev-queries.json", dev_33)
    if dev_34:
        write_json(DATA / "dev-sets" / "m3" / "track-3-4" / "dev-claim-questions.json", dev_34)

    print("\n=== summary ===")
    print("  model calls        : %d (cache hits %d)" % (gen.calls, gen.cache_hits))
    print("  generation failures: %d" % len(gen.failures))
    for f in gen.failures[:8]:
        print("    - %s: %s" % (f["label"], f["error"][:120]))
    print("  sar narratives     : %d  (%d passages)" % (len(sars), len(passages)))
    print("  investigations     : %d  (fact records %d)" % (len(invs), len(facts)))
    print("  case memos         : %d  (questions %d)" % (len(cases), len(case_questions)))
    print("  dev sets           : 3-1 sar %d, 3-1 inv %d, 3-3 %d, 3-4 %d"
          % (len(dev_sar), len(dev_inv), len(dev_33), len(dev_34)))
    print("  gold-literal rewrites: %d" % uniq["collisions"])
    return 1 if res["failures"] else 0


if __name__ == "__main__":
    sys.exit(main())
