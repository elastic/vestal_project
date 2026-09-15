"""
tina/guardrails.py — output guardrails for ARA M3 tracks.

M3 pedagogical purpose:
  Track 3.4 teaches learners that production RAG systems need output safety
  layers beyond retrieval quality.  Three guardrails are introduced:

    validate_output      — LLM-backed grounding check (no specific figures
                           in the answer unless they appear in the context)
    confidence_fallback  — heuristic hedge-phrase detector (no LLM)
    scope_check          — heuristic out-of-domain query filter (no LLM)

  ``GUARDRAIL_HOOKS`` is the registry learners extend in the capstone: they add
  their own hooks and see them called automatically by the harness.

Route B only for validate_output; confidence_fallback and scope_check are
pure Python.  No hardcoded model names.
"""

from __future__ import annotations

import os
import re


# ── Grounding guardrail ───────────────────────────────────────────────────────

# Regex to find numeric figures in text
_FIGURE_RE = re.compile(r"\b\d[\d,.%$€£¥]*\b")


def validate_output(answer: str, context: str, completion_id: str) -> tuple[bool, str]:
    """Check if the answer is grounded in the context.

    M3 pedagogical purpose:
        Learners learn that a hallucinated number is worse than no number at
        all in compliance-critical RAG.  This guardrail fires when the LLM
        includes specific figures (amounts, dates, percentages) not present in
        the retrieved context.

    Uses ``completion_id`` at temperature 0 to ask whether all specific figures
    in the answer appear in the context.  Falls back to a heuristic check if
    the LLM call fails (never raises).

    Args:
        answer:        The LLM-generated answer string.
        context:       The packed context that was passed to the LLM.
        completion_id: EIS inference endpoint id for the completion model.

    Returns:
        (is_grounded: bool, explanation: str)
    """
    from tina.client import es_client

    # Fast heuristic: check if any figure in the answer is absent from context
    answer_figures = set(_FIGURE_RE.findall(answer))
    context_text = re.sub(r"[,]", "", context)  # normalise commas in numbers
    missing = [
        fig for fig in answer_figures
        if re.sub(r"[,]", "", fig) not in context_text
    ]
    if missing:
        # Confirm with LLM (may give false-positive on formatting differences)
        prompt = (
            "The following answer may contain specific figures "
            "(numbers, amounts, dates, percentages) that do not appear in the "
            "provided context.  Respond with YES if ALL specific figures in the "
            "answer are supported by the context, or NO if any figure is not.\n\n"
            f"Context:\n{context}\n\nAnswer:\n{answer}\n\nYES or NO:"
        )
        try:
            es = es_client()
            resp = es.inference.inference(
                inference_id=completion_id,
                body={
                    "input": prompt,
                    "task_type": "completion",
                    "task_settings": {"temperature": 0},
                },
            )
            raw = resp["completion"][0]["result"].strip().upper()
            if raw.startswith("NO"):
                return (
                    False,
                    f"Answer contains figure(s) not found in context: {missing}",
                )
            return (True, "All figures appear grounded in the context.")
        except Exception as exc:
            print(
                f"[guardrails.validate_output] warning: LLM call failed, "
                f"using heuristic result. {exc}"
            )
            return (
                False,
                f"Heuristic: figure(s) absent from context: {missing}",
            )

    return (True, "No ungrounded figures detected.")


# ── Confidence fallback guardrail ─────────────────────────────────────────────

_HEDGE_PHRASES = (
    "i think",
    "i believe",
    "it may be",
    "it might be",
    "it could be",
    "not sure",
    "unclear",
    "i'm not certain",
    "i am not certain",
    "possibly",
    "perhaps",
    "probably",
)


def confidence_fallback(answer: str, threshold: float = 0.7) -> tuple[bool, str]:
    """Detect low-confidence answers that should trigger a fallback response.

    M3 pedagogical purpose:
        Learners see that an LLM saying "I think…" or "unclear" is a signal to
        return a canned fallback rather than a hedged answer that erodes user
        trust in a compliance assistant.

    Heuristic: if the answer contains two or more hedging phrases return
    (True, 'fallback').  A single hedge is informational but not a trigger.
    ``threshold`` is reserved for a future calibrated scorer; the reference
    implementation ignores it in favour of the phrase-count heuristic.

    Pure Python — no LLM call.  Deterministic.

    Args:
        answer:    The LLM-generated answer string.
        threshold: Reserved; currently unused (future calibrated scorer).

    Returns:
        (should_fallback: bool, reason: str)
    """
    lower = answer.lower()
    found = [phrase for phrase in _HEDGE_PHRASES if phrase in lower]
    if len(found) >= 2:
        return (True, f"fallback — multiple hedge phrases detected: {found[:3]}")
    if len(found) == 1:
        return (False, f"single hedge phrase present ('{found[0]}') — informational only")
    return (False, "no hedge phrases detected")


# ── Scope check guardrail ─────────────────────────────────────────────────────

# Terms clearly outside the financial-compliance domain of the Tina corpus
_OUT_OF_SCOPE_TERMS = (
    "recipe",
    "cooking",
    "sports",
    "weather",
    "celebrity",
    "movie",
    "music",
    "lyrics",
    "game",
    "joke",
    "poem",
    "travel destination",
    "hotel",
    "flight",
    "restaurant",
)


def scope_check(query: str, corpus_name: str) -> tuple[bool, str]:
    """Check if the query is in scope for the stated corpus.

    M3 pedagogical purpose:
        Learners learn that an out-of-scope query should be rejected before
        retrieval, not after.  Early rejection saves latency and prevents the
        LLM from hallucinating an answer from unrelated passages.

    Heuristic: returns False if the query contains any term clearly outside the
    financial-compliance domain.  ``corpus_name`` is logged in the reason string
    for observability but does not alter the decision in the reference
    implementation — learners may extend it to do corpus-specific checks.

    Pure Python — no LLM call.  Deterministic.

    Args:
        query:       The raw user query string.
        corpus_name: Name of the corpus (e.g. "financial_compliance_tina").

    Returns:
        (in_scope: bool, reason: str)
    """
    lower = query.lower()
    for term in _OUT_OF_SCOPE_TERMS:
        if term in lower:
            return (
                False,
                f"Query appears out of scope for corpus '{corpus_name}': "
                f"found out-of-domain term '{term}'.",
            )
    return (True, f"Query appears in scope for corpus '{corpus_name}'.")


# ── Guardrail hook registry ───────────────────────────────────────────────────

GUARDRAIL_HOOKS: dict[str, object] = {
    "validate_output": validate_output,
    "confidence_fallback": confidence_fallback,
    "scope_check": scope_check,
}
"""Hook registry for the M3 guardrail pipeline.

M3 pedagogical purpose:
    Learners extend this dict to add their own guardrails and see them called
    in sequence by the harness.  The dict preserves insertion order so hooks
    run in the order they are registered.

Keys are hook names (strings); values are callables with the signature of
the corresponding function above.
"""
