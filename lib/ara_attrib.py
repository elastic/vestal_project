"""
ara_attrib.py — claim-level attribution utilities for ARA M3 tracks.

M3 pedagogical purpose:
  Track 3.4 teaches learners to audit LLM answers at the claim level rather
  than treating the whole answer as a pass/fail.  Real RAG systems need to
  know *which* facts are grounded, which are fabricated, and whether numbers
  in the answer actually appear in the retrieved passages.

Public items:
  split_claims          — deterministic sentence-level claim extractor (no LLM)
  support               — single-claim grounding check via EIS completion
  attribution_record    — full attribution run returning a structured dict
  remote_call           — one Elasticsearch or inference call, retried twice on an
                          outage, then raised (the 3.4 notebook harnesses use it)
  score_attribution     — the Build 1 check's scoring, run on a labelled dev set

Route B only: all LLM calls use the Elasticsearch _inference API.
No ARA_MODEL_FAST/STRONG.  No hardcoded model names.
"""

from __future__ import annotations

import os
import re
import sys
import time
from typing import Optional

from ara_pack import REMOTE_ATTEMPTS, REMOTE_BACKOFF_S, RemoteCallFailed, is_remote_failure


def remote_call(label: str, fn, *args, **kwargs):
    """Call ``fn(*args, **kwargs)``: two retries with a short backoff on an outage.

    Grading standard 09 principle 8, as the 3.4 checks apply it: a call that still
    fails raises ``RemoteCallFailed``, and a request the endpoint rejected (a 4xx other
    than 401, 403, 408, 429) is raised at once, unchanged. Nothing falls back to other
    input, so the notebook and the Check see the same failure.
    """
    last: Exception | None = None
    for attempt in range(REMOTE_ATTEMPTS):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - outages are retried, then raised
            if not is_remote_failure(exc):
                raise
            last = exc
            if attempt < REMOTE_ATTEMPTS - 1:
                wait = REMOTE_BACKOFF_S[min(attempt, len(REMOTE_BACKOFF_S) - 1)]
                print(f"[ara_attrib] {label} call failed ({type(exc).__name__}); "
                      f"retry {attempt + 1} of {REMOTE_ATTEMPTS - 1} in {wait:.0f} s",
                      file=sys.stderr, flush=True)
                time.sleep(wait)
    raise RemoteCallFailed(
        f"{label} endpoint unreachable after {REMOTE_ATTEMPTS} attempts "
        f"({type(last).__name__}: {str(last)[:160]}). Wait a moment and run it again."
    ) from last


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

SUPPORT_LABELS = ("supports", "contradicts", "neutral")


def support_verdict(raw: str) -> str:
    """The verdict in a support() reply: its leading word, after any whitespace,
    punctuation, quotes or markdown, matched exactly against the three labels the
    prompt asks for. A reply that leads with anything else ("neutral" explained with
    the word support, "does not support", "partially supports") is neutral, never
    supports. Kept identical in _ara34.py and vestal lib/ara_attrib.py."""
    match = re.match(r"[^a-z]*([a-z]+)", (raw or "").lower())
    word = match.group(1) if match else ""
    return word if word in SUPPORT_LABELS else "neutral"


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

    A failed call is retried twice, then ``RemoteCallFailed`` is raised. It never
    returns a verdict it did not get: "neutral" for a failed call would read as
    "no passage supports this" (grading standard 09 principle 8).

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
    es = es_client()
    resp = remote_call(
        "completion", es.inference.inference,
        inference_id=completion_id,
        body={
            "input": prompt,
            "task_settings": {"temperature": 0},
        },
    )
    return support_verdict(resp["completion"][0]["result"] or "")


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


# ── Scoring an attributor on labelled answers ─────────────────────────────────

# The keys attribute() is handed. The labels stay out of its reach, as in the check.
LEARNER_PASSAGE_KEYS = ("passage_id", "source_type", "text", "score")


def _normalize_mapping(returned, claim_count: int) -> dict:
    """Accept dict[int], dict['0'], dict['claim_0'], or a list (the check's rules)."""
    out: dict = {}
    if isinstance(returned, dict):
        for key, value in returned.items():
            index = None
            if isinstance(key, int):
                index = key
            elif isinstance(key, str):
                text = key.strip()
                if text.startswith("claim_"):
                    text = text[len("claim_"):]
                if text.isdigit():
                    index = int(text)
            if index is not None and 0 <= index < claim_count:
                out[index] = "UNSUPPORTED" if value is None else str(value)
    elif isinstance(returned, (list, tuple)):
        for index, value in enumerate(returned[:claim_count]):
            if isinstance(value, dict):
                value = value.get("passage_id") or value.get("attributed_to")
            out[index] = "UNSUPPORTED" if value is None else str(value)
    return out


def score_attribution(records: list, attribute) -> dict:
    """Score ``attribute(claims, passages)`` on labelled answers, as the Build 1 check does.

    Each record carries ``claims``, ``passages`` (with ``supports_claims``) and
    ``expected_attribution``, the shape of the dev set
    ``dev-attribution-answers.json``. attribute() sees only the passage keys the
    check hands it. A claim is a conflict claim when more than one passage carries it.

    Returns supported accuracy, unsupported recall, the conflict counts by where the
    attributor sent each conflict claim, whether UNSUPPORTED was ever returned, and
    one row per claim.
    """
    supported_total = supported_correct = 0
    unsupported_total = unsupported_correct = 0
    conflict = {"total": 0, "policy_passage": 0, "memo_passage": 0, "unsupported": 0,
                "both_passages": 0, "missing": 0, "other": 0}
    any_unsupported = False
    rows = []
    for record in records:
        claims = list(record["claims"])
        passages = [{k: p[k] for k in LEARNER_PASSAGE_KEYS if k in p}
                    for p in record["passages"]]
        mapping = _normalize_mapping(attribute(claims, passages), len(claims))
        by_id = {p["passage_id"]: p for p in record["passages"]}
        for index, claim in enumerate(claims):
            expected = record["expected_attribution"][f"claim_{index}"]
            got = mapping.get(index, "")
            any_unsupported = any_unsupported or got == "UNSUPPORTED"
            carriers = [pid for pid, p in by_id.items()
                        if index in (p.get("supports_claims") or [])]
            is_conflict = expected != "UNSUPPORTED" and len(carriers) > 1
            if expected == "UNSUPPORTED":
                unsupported_total += 1
                unsupported_correct += int(got == "UNSUPPORTED")
            else:
                supported_total += 1
                supported_correct += int(got == expected)
            if is_conflict:
                conflict["total"] += 1
                memo_ids = {pid for pid in carriers if by_id[pid]["source_type"] != "policy"}
                if got == expected:
                    conflict["policy_passage"] += 1
                elif got in memo_ids:
                    conflict["memo_passage"] += 1
                elif got == "UNSUPPORTED":
                    conflict["unsupported"] += 1
                elif got == "":
                    conflict["missing"] += 1
                elif sum(1 for pid in carriers if pid in got) >= 2:
                    conflict["both_passages"] += 1
                else:
                    conflict["other"] += 1
            rows.append({"answer_id": record.get("answer_id", ""), "claim_index": index,
                         "claim": claim, "expected": expected, "returned": got,
                         "conflict": is_conflict})
    return {
        "supported_accuracy": supported_correct / max(supported_total, 1),
        "supported_correct": supported_correct, "supported_total": supported_total,
        "unsupported_recall": unsupported_correct / max(unsupported_total, 1),
        "unsupported_correct": unsupported_correct, "unsupported_total": unsupported_total,
        "conflict": conflict,
        "returned_any_unsupported": any_unsupported,
        "per_claim": rows,
    }
