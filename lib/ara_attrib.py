"""
ara_attrib.py — claim-level attribution utilities for ARA M3 tracks.

M3 pedagogical purpose:
  Track 3.4 teaches learners to audit LLM answers at the claim level rather
  than treating the whole answer as a pass/fail.  Real RAG systems need to
  know *which* facts are grounded, which are fabricated, and whether numbers
  in the answer actually appear in the retrieved passages.

Three public items:
  split_claims          — deterministic sentence-level claim extractor (no LLM)
  support               — single-claim grounding check via EIS completion
  attribution_record    — full attribution run returning a structured dict

Route B only: all LLM calls use the Elasticsearch _inference API.
No ARA_MODEL_FAST/STRONG.  No hardcoded model names.
"""

from __future__ import annotations

import os
import re
from typing import Optional


# ── Pure-Python helpers ───────────────────────────────────────────────────────

# Patterns that indicate a sentence is a concrete factual claim
_NUMBER_RE = re.compile(r"\b\d[\d,.%$€£¥]*\b")
_DATE_RE = re.compile(
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|"
    r"Dec(?:ember)?|\d{4})\b",
    re.IGNORECASE,
)
# Absolute assertions: "is", "are", "was", "were", "must", "cannot", "always", etc.
_ABSOLUTE_RE = re.compile(
    r"\b(?:is|are|was|were|must|cannot|can not|always|never|only|all|none|every)\b",
    re.IGNORECASE,
)
# Proper-noun heuristic: any token starting with an uppercase letter (not start of sentence)
_ENTITY_RE = re.compile(r"(?<=[.?!]\s)[A-Z][a-z]+|(?<=[\s,;:])([A-Z][a-z]{2,})")


def split_claims(answer: str) -> list[str]:
    """Split an answer string into individual factual claims.

    M3 pedagogical purpose:
      Before grounding-checking an answer, learners need to decompose it.
      This function gives them a deterministic, reproducible splitter so
      check scripts and notebooks agree on the claim list.

    A "claim" is a sentence that contains a concrete assertion — specifically
    at least one of:
      - a number or numeric figure
      - a date or year reference
      - an absolute-assertion verb or adverb (is, are, must, never, only…)
      - an apparent named entity (title-case word mid-sentence)

    Sentences that are purely rhetorical ("Great question!") or purely
    connective ("In summary,") are dropped.

    Pure Python — no LLM call.  Deterministic on the same input.

    Args:
        answer: The full LLM answer string.

    Returns:
        List of claim strings, one per qualifying sentence.
    """
    # Split on sentence-ending punctuation followed by whitespace or end-of-string
    raw_sentences = re.split(r"(?<=[.?!])\s+", answer.strip())

    claims = []
    for sent in raw_sentences:
        sent = sent.strip()
        if len(sent) < 10:
            continue
        if (
            _NUMBER_RE.search(sent)
            or _DATE_RE.search(sent)
            or _ABSOLUTE_RE.search(sent)
            or _ENTITY_RE.search(sent)
        ):
            claims.append(sent)
    return claims


# ── EIS-backed grounding check ────────────────────────────────────────────────

def support(claim: str, passage: str, completion_id: str) -> str:
    """Check whether a passage supports, contradicts, or is neutral to a claim.

    M3 pedagogical purpose:
      Learners use this as the atomic unit of claim-level attribution.  Each
      claim from split_claims is tested against each retrieved passage to find
      the best supporting evidence.

    Calls the EIS completion endpoint ``completion_id`` at temperature 0.
    Prompt:
      "Does the following passage support, contradict, or have no bearing on
       this claim? Answer with one word: supports, contradicts, or neutral."

    On any error (network, parsing): returns ``"neutral"`` and prints a warning.
    Never raises.

    Args:
        claim:         A single factual claim string.
        passage:       A retrieved passage to test against the claim.
        completion_id: EIS inference endpoint id for the completion model.

    Returns:
        One of ``"supports"``, ``"contradicts"``, or ``"neutral"``.
    """
    from tina.client import es_client

    prompt = (
        "Does the following passage support, contradict, or have no bearing "
        "on this claim? Answer with one word: supports, contradicts, or neutral.\n\n"
        f"Claim: {claim}\n\n"
        f"Passage: {passage}"
    )
    try:
        es = es_client()
        resp = es.inference.inference(
            inference_id=completion_id,
            body={
                "input": prompt,
                "task_settings": {"temperature": 0},
            },
        )
        raw: str = resp["completion"][0]["result"].strip().lower()
        if "support" in raw:
            return "supports"
        elif "contradict" in raw:
            return "contradicts"
        else:
            return "neutral"
    except Exception as exc:
        print(f"[ara_attrib.support] warning: inference call failed, returning neutral. {exc}")
        return "neutral"


# ── Attribution record ────────────────────────────────────────────────────────

def attribution_record(
    answer: str,
    claims: list[str],
    passages: list[dict],
    completion_id: str,
) -> dict:
    """Run claim-level attribution for an answer against retrieved passages.

    M3 pedagogical purpose:
      This is the full attribution pipeline learners build in track 3.4.
      The output schema is what the check script grades: attribution_rate,
      unsupported_claims, and fabrication_detected are the three key signals.

    For each claim, the function:
      1. Tests the claim against every passage using ``support()``.
      2. Picks the passage with the best result (prefers "supports" over
         "contradicts" over "neutral").
      3. Detects fabrication: if the claim contains a number that does not
         appear verbatim in ANY passage text, it is a fabrication candidate.

    Args:
        answer:        Full LLM answer string.
        claims:        List of claim strings (from split_claims or custom).
        passages:      List of retrieved passage dicts; each must have at least
                       a ``text`` or ``body`` field, and optionally ``doc_id``.
        completion_id: EIS inference endpoint id for the completion model.

    Returns:
        {
          "answer": str,
          "claims": [
            {
              "text": str,
              "support": "supports|contradicts|neutral",
              "attributed_to": doc_id or None,
              "passage_text": str or None
            }
          ],
          "attribution_rate": float,   # fraction of claims that are "supports"
          "unsupported_claims": [str], # claims with support == "neutral" or "contradicts"
          "fabrication_detected": bool # True if any claim has a number absent from all passages
        }
    """
    all_passage_text = " ".join(
        p.get("text") or p.get("body", "") for p in passages
    )

    claim_records = []
    for claim_text in claims:
        best_verdict = "neutral"
        best_doc_id: Optional[str] = None
        best_passage_text: Optional[str] = None

        for p in passages:
            p_text = p.get("text") or p.get("body", "")
            verdict = support(claim_text, p_text, completion_id)
            if verdict == "supports":
                best_verdict = "supports"
                best_doc_id = p.get("doc_id") or p.get("_id")
                best_passage_text = p_text
                break  # First "supports" wins; avoid unnecessary inference calls
            elif verdict == "contradicts" and best_verdict == "neutral":
                best_verdict = "contradicts"
                best_doc_id = p.get("doc_id") or p.get("_id")
                best_passage_text = p_text

        claim_records.append(
            {
                "text": claim_text,
                "support": best_verdict,
                "attributed_to": best_doc_id if best_verdict == "supports" else None,
                "passage_text": best_passage_text if best_verdict == "supports" else None,
            }
        )

    # Fabrication detection: number in claim absent from all passages
    fabrication_detected = False
    for cr in claim_records:
        numbers_in_claim = _NUMBER_RE.findall(cr["text"])
        for num in numbers_in_claim:
            # Strip commas/decimals for loose matching
            num_clean = re.sub(r"[,]", "", num)
            if num_clean not in re.sub(r"[,]", "", all_passage_text):
                fabrication_detected = True
                break
        if fabrication_detected:
            break

    supported_count = sum(1 for cr in claim_records if cr["support"] == "supports")
    total = len(claim_records)
    attribution_rate = supported_count / total if total > 0 else 0.0
    unsupported = [cr["text"] for cr in claim_records if cr["support"] != "supports"]

    return {
        "answer": answer,
        "claims": claim_records,
        "attribution_rate": attribution_rate,
        "unsupported_claims": unsupported,
        "fabrication_detected": fabrication_detected,
    }


# ── Convenience re-export of _NUMBER_RE for test use ─────────────────────────
_number_re = _NUMBER_RE
