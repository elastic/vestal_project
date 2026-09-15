"""
test_m3_libs.py — smoke tests for M3 library additions.

Covers all pure-Python functions (no LLM calls, no ES connection).
Run with: python -m pytest lib/test_m3_libs.py -v
or:        python lib/test_m3_libs.py
"""

from __future__ import annotations

import sys
import os

# Ensure lib/ is on the path when run directly
sys.path.insert(0, os.path.dirname(__file__))


# ── ara_metrics new additions ─────────────────────────────────────────────────

def test_token_count_basic():
    from ara_metrics import token_count
    result = token_count("hello world foo bar")
    # 4 words * 1.3 = 5.2 → 5
    assert result == 5, f"Expected 5, got {result}"


def test_token_count_empty():
    from ara_metrics import token_count
    assert token_count("") == 0


def test_count_tokens_approx_alias():
    """count_tokens_approx must give same result as token_count (backward compat)."""
    from ara_metrics import token_count, count_tokens_approx
    text = "the quick brown fox jumps over the lazy dog"
    assert token_count(text) == count_tokens_approx(text)


def test_context_fit_within():
    from ara_metrics import context_fit
    # 5 words * 1.3 = 6 (rounded down to 6)
    text = "one two three four five"
    tc = int(len(text.split()) * 1.3)  # 6
    assert context_fit(text, tc) is True
    assert context_fit(text, tc - 1) is False


def test_precision_at_k_default_gold_field():
    from ara_metrics import precision_at_k
    results = [{"query_id": "q1", "retrieved_ids": ["a", "b", "c"]}]
    queries = [{"query_id": "q1", "relevant_ids": ["a", "z"]}]
    p = precision_at_k(results, queries, k=3)
    # 1 hit in 3 retrieved → 1/3
    assert abs(p - 1 / 3) < 1e-6


def test_precision_at_k_passage_level():
    from ara_metrics import precision_at_k
    results = [{"query_id": "q1", "retrieved_ids": ["doc-1-p2", "doc-2-p1"]}]
    queries = [{"query_id": "q1", "relevant_passage_ids": ["doc-1-p2", "doc-1-p3"]}]
    p = precision_at_k(results, queries, k=2, gold_field="relevant_passage_ids")
    # 1 hit in 2 retrieved → 0.5
    assert abs(p - 0.5) < 1e-6


# ── ara_attrib pure-Python functions ─────────────────────────────────────────

def test_split_claims_numbers():
    from ara_attrib import split_claims
    answer = "The policy requires a 30-day notice period. That is nice. Great!"
    claims = split_claims(answer)
    # First sentence has a number, should be included
    assert any("30" in c for c in claims)


def test_split_claims_no_assertions():
    from ara_attrib import split_claims
    # Purely rhetorical sentences should be dropped
    answer = "Great! Wow. Interesting."
    claims = split_claims(answer)
    assert claims == []


def test_split_claims_multiple():
    from ara_attrib import split_claims
    answer = (
        "The coverage limit is $1,000,000. "
        "Claims must be filed within 90 days. "
        "This is a general statement."
    )
    claims = split_claims(answer)
    assert len(claims) >= 2  # at least the two numeric sentences


def test_split_claims_named_entity():
    from ara_attrib import split_claims
    answer = "John Smith approved the filing on Monday."
    claims = split_claims(answer)
    # Has entity "John" / "Smith" mid-sentence
    assert len(claims) >= 1


# ── tina.strategy_router pure-Python ─────────────────────────────────────────

def test_strategy_router_agentic_multi_hop():
    from tina.strategy_router import strategy_router
    result = strategy_router("what happened", {"multi_hop": True, "has_filter_intent": False,
                                                "asks_for_figure": False, "has_case_id": False})
    assert result == "agentic"


def test_strategy_router_agentic_case_id():
    from tina.strategy_router import strategy_router
    result = strategy_router("case 12345", {"multi_hop": False, "has_filter_intent": False,
                                             "asks_for_figure": False, "has_case_id": True})
    assert result == "agentic"


def test_strategy_router_advanced():
    from tina.strategy_router import strategy_router
    result = strategy_router("how much", {"multi_hop": False, "has_filter_intent": False,
                                           "asks_for_figure": True, "has_case_id": False})
    assert result == "advanced"


def test_strategy_router_naive():
    from tina.strategy_router import strategy_router
    result = strategy_router("tell me about compliance", {"multi_hop": False, "has_filter_intent": False,
                                                          "asks_for_figure": False, "has_case_id": False})
    assert result == "naive"


# ── tina.guardrails pure-Python functions ─────────────────────────────────────

def test_confidence_fallback_triggers():
    from tina.guardrails import confidence_fallback
    answer = "I think the answer is X. I'm not certain about Y. It may be Z."
    should_fallback, reason = confidence_fallback(answer)
    assert should_fallback is True
    assert "fallback" in reason


def test_confidence_fallback_single_hedge():
    from tina.guardrails import confidence_fallback
    answer = "I think the premium is $500 per year."
    should_fallback, reason = confidence_fallback(answer)
    # One hedge → not a fallback
    assert should_fallback is False


def test_confidence_fallback_no_hedge():
    from tina.guardrails import confidence_fallback
    answer = "The premium is $500 per year according to the policy."
    should_fallback, reason = confidence_fallback(answer)
    assert should_fallback is False


def test_scope_check_in_scope():
    from tina.guardrails import scope_check
    in_scope, reason = scope_check("What is the deductible for property damage?", "financial_compliance_tina")
    assert in_scope is True


def test_scope_check_out_of_scope():
    from tina.guardrails import scope_check
    in_scope, reason = scope_check("Give me a recipe for chocolate cake", "financial_compliance_tina")
    assert in_scope is False
    assert "recipe" in reason


def test_guardrail_hooks_registry():
    from tina.guardrails import GUARDRAIL_HOOKS
    assert "validate_output" in GUARDRAIL_HOOKS
    assert "confidence_fallback" in GUARDRAIL_HOOKS
    assert "scope_check" in GUARDRAIL_HOOKS
    assert callable(GUARDRAIL_HOOKS["confidence_fallback"])


# ── tina __init__ exports ─────────────────────────────────────────────────────

def test_tina_exports_strategy_router():
    import tina
    assert hasattr(tina, "strategy_router")
    assert callable(tina.strategy_router)


def test_tina_exports_guardrail_hooks():
    import tina
    assert hasattr(tina, "GUARDRAIL_HOOKS")
    assert isinstance(tina.GUARDRAIL_HOOKS, dict)


# ── Import smoke tests (no calls) ─────────────────────────────────────────────

def test_import_ara_pack():
    import ara_pack  # noqa: F401


def test_import_ara_attrib():
    import ara_attrib  # noqa: F401


def test_import_ara_metrics():
    import ara_metrics  # noqa: F401


# ── Runner ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {fn.__name__}: {exc}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
