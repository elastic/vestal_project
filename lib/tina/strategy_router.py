"""
tina/strategy_router.py — default pluggable strategy router for ARA M3.

M3 pedagogical purpose:
  Track 3.3 introduces the idea that different query types warrant different
  retrieval strategies.  This module ships the *reference* implementation of
  the router that learners study and then replace with their own version.

  Learners are expected to:
    1. Understand the three strategy tiers (naive / advanced / agentic).
    2. Build a feature extractor that produces the ``features`` dict.
    3. Replace or extend this router with smarter classification logic.

No LLM calls — pure Python rule-based logic.  The learner's replacement may
call an LLM; this reference stays deterministic for reproducibility.
"""

from __future__ import annotations


def strategy_router(query: str, features: dict) -> str:
    """Default pluggable strategy router — learners replace this in track 3.3.

    M3 pedagogical purpose:
        This is the pluggable slot for query-routing in the M3 capstone.  The
        reference implementation here shows the decision logic students should
        understand before writing their own.  The three tiers map to tracks
        3.1 (naive), 3.2 (advanced with filters/rerank), and 3.3 (agentic
        multi-hop), letting learners see how strategy selection connects to the
        broader ARA architecture.

    features keys:
        has_filter_intent (bool): Query mentions a specific type, tier, or case id
                                  that suggests a filtered retrieval is needed.
        asks_for_figure   (bool): Query asks for a specific number, amount, or date.
        multi_hop         (bool): Query likely needs facts from more than one document.
        has_case_id       (bool): Query mentions a specific case number or identifier.

    Returns one of:
        ``'naive'``    — simple semantic or BM25 lookup; one-shot retrieval.
        ``'advanced'`` — filter + rerank; still single-hop but more precise.
        ``'agentic'``  — multi-step retrieval with tool calls or sub-queries.

    Decision logic (reference):
        agentic  when multi_hop OR has_case_id (needs cross-document reasoning)
        advanced when has_filter_intent OR asks_for_figure (precision matters)
        naive    otherwise (general informational query)

    Args:
        query:    The raw user query string (available for custom classifiers).
        features: Feature dict produced by the learner's feature extractor.

    Returns:
        Strategy name string.
    """
    if features.get("multi_hop") or features.get("has_case_id"):
        return "agentic"
    if features.get("has_filter_intent") or features.get("asks_for_figure"):
        return "advanced"
    return "naive"
