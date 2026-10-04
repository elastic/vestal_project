"""
test_m3_libs.py — smoke tests for M3 library additions.

Covers all pure-Python functions (no LLM calls, no ES connection).
Run with: python -m pytest lib/test_m3_libs.py -v
or:        python lib/test_m3_libs.py
"""

from __future__ import annotations

import sys
import os
import pathlib

# Ensure lib/ is on the path when run directly
sys.path.insert(0, os.path.dirname(__file__))


# ── ara_metrics new additions ─────────────────────────────────────────────────

def _block_tiktoken(monkeypatch):
    """Make `import tiktoken` raise ImportError, so token_count takes its fallback."""
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "tiktoken":
            raise ImportError("tiktoken blocked for this test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)


def test_token_count_basic(monkeypatch):
    """The fallback is words x 1.3, rounded down. With tiktoken installed (as in the
    sandboxes) token_count uses cl100k_base instead, so the fallback is forced here."""
    from ara_metrics import token_count
    _block_tiktoken(monkeypatch)
    result = token_count("hello world foo bar")
    # 4 words * 1.3 = 5.2 → 5
    assert result == 5, f"Expected 5, got {result}"


def test_token_count_tokenizer_positive():
    """Whichever tokenizer is installed, a non-empty text has a positive count."""
    from ara_metrics import token_count
    assert token_count("hello world foo bar") > 0


def test_token_count_empty():
    from ara_metrics import token_count
    assert token_count("") == 0


def test_count_tokens_approx_alias():
    """count_tokens_approx must give same result as token_count (backward compat)."""
    from ara_metrics import token_count, count_tokens_approx
    text = "the quick brown fox jumps over the lazy dog"
    assert token_count(text) == count_tokens_approx(text)


def test_context_fit_within():
    """context_fit compares against token_count, whichever tokenizer it uses."""
    from ara_metrics import context_fit, token_count
    text = "one two three four five"
    tc = token_count(text)
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


def test_strategy_router_ships_filter_first():
    # Lab 3.1 Build 2: Tina's shipped router checks filters and figures first, so a
    # multi-hop query that asks for a figure goes to advanced. The learner fixes the order.
    from tina.strategy_router import strategy_router
    result = strategy_router("compare the amounts", {"multi_hop": True, "has_filter_intent": False,
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


class _FakeInference:
    """es.inference stand-in: fails `fail` times with `exc`, then answers."""

    def __init__(self, fail, exc):
        self.fail, self.exc, self.calls = fail, exc, 0

    def inference(self, **kwargs):
        self.calls += 1
        if self.calls <= self.fail:
            raise self.exc
        return {"completion": [{"result": "summary"}]}


class _FakeES:
    def __init__(self, inference):
        self.inference = inference


def _summarize_with(fake):
    import ara_pack
    saved = (ara_pack.es_client, ara_pack.REMOTE_BACKOFF_S)
    ara_pack.es_client, ara_pack.REMOTE_BACKOFF_S = (lambda: _FakeES(fake)), (0, 0)
    try:
        return ara_pack.summarize_first([{"text": "a long passage"}], "q", "completion", 50)
    finally:
        ara_pack.es_client, ara_pack.REMOTE_BACKOFF_S = saved


def test_summarize_first_retries_then_raises():
    """Principle 8: an outage is retried twice, then raised; never the original text."""
    import ara_pack
    fake = _FakeInference(3, ConnectionError("Connection timed out"))
    try:
        _summarize_with(fake)
    except ara_pack.RemoteCallFailed:
        pass
    else:
        raise AssertionError("summarize_first returned instead of raising")
    assert fake.calls == 3, fake.calls


def test_summarize_first_recovers_on_retry():
    fake = _FakeInference(2, ConnectionError("Connection reset"))
    out = _summarize_with(fake)
    assert out[0]["body"] == "summary" and fake.calls == 3


def test_summarize_first_raises_rejected_request_at_once():
    class Rejected(Exception):
        status_code = 400

    fake = _FakeInference(5, Rejected("bad request"))
    try:
        _summarize_with(fake)
    except Rejected:
        pass
    else:
        raise AssertionError("a 400 was not raised")
    assert fake.calls == 1, fake.calls


def test_import_ara_attrib():
    import ara_attrib  # noqa: F401


def _support_with(fake):
    import ara_attrib
    import tina.client
    saved = (tina.client.es_client, ara_attrib.REMOTE_BACKOFF_S)
    tina.client.es_client, ara_attrib.REMOTE_BACKOFF_S = (lambda: _FakeES(fake)), (0, 0)
    try:
        return ara_attrib.support("a claim", "a passage", "completion")
    finally:
        tina.client.es_client, ara_attrib.REMOTE_BACKOFF_S = saved


def test_support_retries_then_raises():
    """Principle 8: a failed support() call is raised, never returned as neutral."""
    import ara_pack
    fake = _FakeInference(3, ConnectionError("Connection timed out"))
    try:
        _support_with(fake)
    except ara_pack.RemoteCallFailed:
        pass
    else:
        raise AssertionError("support returned a verdict for a failed call")
    assert fake.calls == 3, fake.calls


def test_support_recovers_on_retry():
    fake = _FakeInference(2, ConnectionError("Connection reset"))
    assert _support_with(fake) == "neutral" and fake.calls == 3


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


# ── 3.4 dev attribution set and score_attribution ─────────────────────────────

_DEV_ATTR = pathlib.Path(__file__).resolve().parent.parent / "data/dev-sets/m3/track-3-4/dev-attribution-answers.json"


def _dev_attr():
    import json
    return json.loads(_DEV_ATTR.read_text())


def test_dev_attribution_labels_consistent():
    """Each label is backed by the passage text: a supported claim's passage carries
    it, an UNSUPPORTED claim is carried by none, and claims split as the harness does."""
    from ara_attrib import split_claims
    records = _dev_attr()
    totals = {"supported": 0, "unsupported": 0, "conflict": 0}
    for r in records:
        assert split_claims(r["answer_text"]) == r["claims"], r["answer_id"]
        ids = {p["passage_id"] for p in r["passages"]}
        for i, _claim in enumerate(r["claims"]):
            expected = r["expected_attribution"][f"claim_{i}"]
            carriers = [p for p in r["passages"] if i in p["supports_claims"]]
            if expected == "UNSUPPORTED":
                totals["unsupported"] += 1
                assert not carriers, (r["answer_id"], i)
            else:
                totals["supported"] += 1
                assert expected in ids and any(p["passage_id"] == expected for p in carriers)
                if len(carriers) > 1:
                    totals["conflict"] += 1
                    assert next(p for p in r["passages"] if p["passage_id"] == expected)["source_type"] == "policy"
    assert totals == {"supported": 12, "unsupported": 4, "conflict": 2}, totals


def test_score_attribution_matches_labels():
    import ara_attrib
    records = _dev_attr()
    key = {tuple(r["claims"]): r["expected_attribution"] for r in records}

    def oracle(claims, passages):
        assert all("supports_claims" not in p for p in passages)  # labels stay out of reach
        return {i: key[tuple(claims)][f"claim_{i}"] for i in range(len(claims))}

    s = ara_attrib.score_attribution(records, oracle)
    assert s["supported_accuracy"] == 1.0 and s["unsupported_recall"] == 1.0
    assert s["conflict"]["total"] == 2 and s["conflict"]["policy_passage"] == 2

    def first_passage(claims, passages):  # never UNSUPPORTED, memo first on conflicts
        return [passages[0]["passage_id"] for _ in claims]

    s = ara_attrib.score_attribution(records, first_passage)
    assert s["unsupported_recall"] == 0.0 and not s["returned_any_unsupported"]
    assert s["conflict"]["memo_passage"] == 2
