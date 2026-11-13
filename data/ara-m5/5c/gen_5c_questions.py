#!/usr/bin/env python3
"""5.C question and correspondence additions (07 section 2.2): six SAR-citation questions (S1) and six
regulation questions whose cited page is a regulator-library page (S2), plus the regulator replies the S2 questions quote.

Deterministic. Reads ara-m5-pages/ for each page's title line. Writes, beside this file:
    pool-additions.json        pool-schema items (same shape as the 5.3 pool), ids q-c01..q-c12, root-only in the track
    regulator-replies.ndjson   cortex-case-correspondence rows (S2 start state): one regulator reply per S2 question
needs_live_check: that Tina reads the pasted URL under the reference hardening block (plan.md section 3).
"""
from __future__ import annotations

import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
PAGES = HERE.parent.parent.parent / "ara-m5-pages"
BASE = "https://raw.githubusercontent.com/elastic/vestal_project/m5-v1.0/ara-m5-pages/"
SAR_TOOLS = ["cortex.sar_search", "cortex.sar_passages"]
SAR_RULE = {"source": "tool:cortex.sar_search", "quote": "Use it when an analyst asks what a past SAR said about a pattern, a typology or the facts of a filing."}

SAR_QUESTIONS = [
    "What did past SARs say about cash deposits kept just under the reporting threshold?",
    "What have past SARs said about wire requests that came from a spoofed executive email?",
    "Show me how past SARs described a sanctions screening hit on a counterparty.",
    "What did past SARs say about customers who would not provide identification?",
    "How did past SARs describe a relative or caregiver withdrawing money from an older customer's account?",
    "Which past SARs mention a shell company, and what did they say about it?",
]

# (case id, page slug, question tail, regulator, subject of the reply)
REG = [
    ("case-structuring-001", "fincen-ctr-and-structuring-31-cfr-1010-311-314", "which transactions in currency the bank had to report", "FinCEN, Office of Compliance"),
    ("case-structuring-002", "fincen-ctr-and-structuring-31-cfr-1010-311-314", "what the regulation says about breaking up a cash deposit", "FinCEN, Office of Compliance"),
    ("case-wire-fraud-001", "fincen-sar-rule-31-cfr-1020-320", "when the bank had to file a Suspicious Activity Report", "FinCEN, Office of Compliance"),
    ("case-kyc-gap-001", "fincen-record-retention-31-cfr-1010-430", "how long the bank has to keep the records", "FinCEN, Office of Compliance"),
    ("case-sanctions-001", "occ-sar-rule-12-cfr-21-11", "how many days the bank had to file after it detected the facts", "Office of the Comptroller of the Currency, Enforcement"),
    ("case-elder-exploitation-001", "fincen-monetary-instruments-31-cfr-1010-415", "what records the bank must keep for a cash purchase of a cashier's check", "FinCEN, Office of Compliance"),
]


def title_line(slug: str) -> str:
    first = (PAGES / f"{slug}.md").read_text(encoding="utf-8").splitlines()[0]
    assert first.startswith("# "), slug
    return first[2:].strip()


def main() -> int:
    items, replies = [], []
    for i, q in enumerate(SAR_QUESTIONS, 1):
        items.append({"id": f"q-c{i:02d}", "type": "agent", "category": "straightforward", "kind": "case", "source": "5c S1",
                      "input": q, "expected": [{"any_of": SAR_TOOLS}], "rule": [SAR_RULE], "accounts": [],
                      "forbid": ["cortex.file_sar"]})
    for j, (case, slug, tail, who) in enumerate(REG, 1):
        url = BASE + slug + ".md"
        qid = f"q-c{len(SAR_QUESTIONS) + j:02d}"
        items.append({"id": qid, "type": "agent", "category": "straightforward", "kind": "extension", "source": "5c S2",
                      "input": f"The regulator's reply on {case} cites {url}. Read that page and tell me {tail}.",
                      "expected": [{"tool_id": "cortex.read_page", "params": {"url": url}}],
                      "rule": [{"source": "plugin:regulatory-citation", "quote": "Read the pinned page with the `cortex.read_page` tool"}],
                      "accounts": [], "page": {"url": url, "title_line": title_line(slug)}})
        replies.append({"corr_id": f"corr-reg-{case.removeprefix('case-')}-01", "case_id": case,
                        "case_type": case.removeprefix("case-").rsplit("-", 1)[0].replace("-", "_"), "risk_tier": "high",
                        "from_party": who, "received_at": f"2026-10-{10 + j:02d}T14:00:00Z",
                        "body": f"Re: {case}. We have reviewed your filing. The requirement that applies is set out at {url}. "
                                f"Please read it before you answer our follow-up questions."})
    (HERE / "pool-additions.json").write_text(json.dumps({"_doc": __doc__.strip().splitlines()[0], "version": "5c-1",
                                                           "questions": items}, indent=2) + "\n", encoding="utf-8")
    (HERE / "regulator-replies.ndjson").write_text("".join(json.dumps(r) + "\n" for r in replies), encoding="utf-8")
    print(len(items), "items,", len(replies), "replies")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
