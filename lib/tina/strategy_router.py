"""
tina/strategy_router.py — Tina's current strategy router (ARA M3, lab 3.1 Build 2).

This is the router Tina ships with at the start of lab 3.1. It sends some queries to the
wrong strategy: some that carry more than one feature, because of the order it checks
them in, and a query whose only feature is a case reference. The dev set shows which.
The learner writes the replacement in the lab 3.1 strategy-router notebook; the check
grades that notebook cell, not this module.

No LLM calls; pure Python over the precomputed features dict.
"""

from __future__ import annotations


def strategy_router(query: str, features: dict) -> str:
    """Tina's current router: returns 'naive', 'advanced' or 'agentic'.

    features keys (booleans):
        has_filter_intent  names a case type, risk tier or date range
        asks_for_figure    asks for an amount, count or deadline
        multi_hop          needs facts from separate documents, each needing its own search
        has_case_id        names a case reference

    Args:
        query:    The raw user query string.
        features: The four features for the query.

    Returns:
        ``'naive'`` (one semantic query), ``'advanced'`` (metadata filter plus rerank) or
        ``'agentic'`` (search as a tool in a loop).
    """
    if features.get("has_filter_intent") or features.get("asks_for_figure"):
        return "advanced"
    if features.get("multi_hop") or features.get("has_case_id"):
        return "agentic"
    return "naive"
