"""Offline tests for ara_eval.py. Judge outputs are shaped like the Phase 0 r5 GPT-6 Sol outputs:
the reference prompt starts with a scale value, the naive prompt with prose ("Unfaithful.") or an
off-scale number ("5/5")."""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import ara_eval as E  # noqa: E402


def test_parse_score_first_token_clamp_and_snap():
    assert E.parse_score("1 - every claim is in passage 2.") == (1.0, False)
    assert E.parse_score("0.5 Partly: the second claim has no support.") == (0.5, False)
    assert E.parse_score("Unfaithful.") == (None, True)
    assert E.parse_score("5/5 highly relevant") == (1.0, True)  # clamped
    assert E.parse_score("0.7 mostly") == (0.5, True)  # snapped to the nearest scale value
    assert E.parse_score("0.75") == (0.5, True)  # a tie snaps down
    assert E.parse_score("-1") == (0.0, True)
    assert E.parse_score(".5 half") == (0.5, False)  # the value is on the scale, however it is written
    assert E.parse_score("3", scale=(0.0, 0.25, 0.5, 0.75, 1.0)) == (1.0, True)


def test_judge_gate_names_defect_types_never_records():
    key = {"h1": "unfaithful_to_context", "h2": "faithful_but_off_question", "h3": "wrong_context_retrieved",
           "h4": "no_defect"}
    good = {"h1": {"faithfulness": 0, "answer_relevance": 1, "context_precision": 1},
            "h2": {"faithfulness": 1, "answer_relevance": 0, "context_precision": 1},
            "h3": {"faithfulness": 1, "answer_relevance": 1, "context_precision": 0},
            "h4": {"faithfulness": 1, "answer_relevance": 1, "context_precision": 1}}
    g = E.judge_gate([good] * 5, key, flag_margin=0.5, control_min=1.0, k=4)
    assert g["passed"] and g["message"] == ""
    # r5's off-question record also scored faithfulness 0: its own metric is not lowest by the margin
    two = dict(good, h2={"faithfulness": 0, "answer_relevance": 0, "context_precision": 1})
    g = E.judge_gate([two] * 5, key, flag_margin=0.5, control_min=1.0, k=4)
    assert not g["passed"] and g["missed_types"] == ["faithful_but_off_question"] and "h2" not in g["message"]
    # a missing score (an unparseable output) fails that record in that run; 4 of 5 still pass at k=4
    runs = [good] * 4 + [dict(good, h4={"faithfulness": None, "answer_relevance": 1, "context_precision": 1})]
    assert E.judge_gate(runs, key, 0.5, 1.0, k=4)["passed"]
    assert not E.judge_gate(runs, key, 0.5, 1.0, k=5)["passed"]


def _pool():
    pool, key = {}, {}
    for i in range(40):
        qid = f"p{i:02d}"
        pool[qid] = {"kind": "policy" if i < 10 else "agent"}
        key[qid] = ("straightforward", "ambiguous", "time_window_edge", "cross_domain", "adversarial", "out_of_scope")[i % 6]
    return pool, key


def test_coverage_passes_a_representative_set_and_names_what_is_missing():
    pool, key = _pool()
    shares = {"straightforward": 0.4, "ambiguous": 0.2, "time_window_edge": 0.2, "cross_domain": 0.1,
              "adversarial": 0.05, "out_of_scope": 0.05}
    ids = [q for q in pool if key[q] in ("straightforward", "ambiguous", "time_window_edge", "cross_domain")][:20]
    ts = [{"question_id": q, "category": key[q]} for q in ids]
    assert E.coverage(ts, pool, key, shares) == [], E.coverage(ts, pool, key, shares)
    happy = [{"question_id": q, "category": "straightforward"} for q in pool if key[q] == "straightforward"]
    fails = " ".join(E.coverage(happy, pool, key, shares))
    assert "ambiguous, time_window_edge, cross_domain" in fails and "only straightforward" in fails
    assert "7 questions; it needs 18 to 30" in fails
    wrong = [dict(q, category="ambiguous") for q in ts]
    assert any("category labels match" in f for f in E.coverage(wrong, pool, key, shares))
    assert any("not in the question pool" in f for f in E.coverage(ts + [{"question_id": "zz", "category": "ambiguous"}], pool, key, shares))


def test_category_means_report_none_for_an_empty_category():
    m = E.category_means({"a": 1, "b": 0.5, "c": 0}, {"a": "straightforward", "b": "straightforward", "c": "ambiguous"})
    assert m["straightforward"] == 0.75 and m["ambiguous"] == 0.0 and m["out_of_scope"] is None


def _rec(qid, cat, ok, calls=2, inp=30000, cached=15000, out=600, page=None):
    route = [{"tool_id": "cortex.read_page", "page_fetch_ok": page}] if page is not None else []
    return {"question_id": qid, "category": cat, "expected_route": [{}], "route_correct": ok, "observed_route": route,
            "tool_call_count": calls, "input_tokens": inp, "cached_input_tokens": cached, "output_tokens": out}


CARD = {"price_fresh_input": 2.0, "price_cached_input": 0.2, "price_output": 8.0}


def test_aggregates_in_points_tokens_and_cost():
    recs = [_rec("q1", "straightforward", True), _rec("q2", "straightforward", False),
            _rec("q3", "ambiguous", True, page=True), {"question_id": "p1", "expected_route": None}]
    a = E.aggregates(recs, CARD)
    assert a["questions"] == 3 and a["routing_accuracy_overall"] == 66.7
    assert a["routing_accuracy"]["straightforward"] == 50.0 and a["routing_accuracy"]["ambiguous"] == 100.0
    assert a["routing_accuracy"]["out_of_scope"] is None
    assert a["cached_share"] == 0.5 and a["fresh_input_tokens_per_question"] == 15000
    assert abs(a["cost_per_question"] - (15000 * 2.0 + 15000 * 0.2 + 600 * 8.0) / 1e6) < 1e-12
    assert a["page_fetch_share"]["ambiguous"] == 1.0 and a["page_fetch_share"]["straightforward"] is None


BUDGET = {"min_gain_points": 5, "large_gain_points": 15, "category_drop_limit_points": 10,
          "tool_call_limit_pct_small": 10, "tool_call_limit_pct_large": 30,
          "cost_limit_pct_small": 10, "cost_limit_pct_large": 30}


def _agg(acc: dict, calls: float, cost: float) -> dict:
    full = {c: acc.get(c) for c in E.CATEGORIES}
    vals = [v for v in acc.values()]
    return {"routing_accuracy": full, "routing_accuracy_overall": sum(vals) / len(vals),
            "tool_calls_per_question": calls, "cost_per_question": cost}


def test_decide_follows_the_rule_table_in_order():
    before = _agg({"straightforward": 80, "ambiguous": 40}, 2.0, 0.040)
    ship = _agg({"straightforward": 80, "ambiguous": 60}, 2.1, 0.042)  # gain 10 (small): +5 % calls, +5 % cost
    assert E.decide(before, ship, BUDGET)[:2] == (True, "quality_gain_within_budget")
    drop = _agg({"straightforward": 60, "ambiguous": 100}, 2.0, 0.040)  # gain 20, but a category falls 20
    assert E.decide(before, drop, BUDGET)[1] == "category_regression_over_budget"
    flat = _agg({"straightforward": 80, "ambiguous": 44}, 2.0, 0.040)  # gain 2
    assert E.decide(before, flat, BUDGET)[1] == "no_quality_gain"
    calls = _agg({"straightforward": 80, "ambiguous": 60}, 2.4, 0.040)  # +20 % calls over the small limit
    assert E.decide(before, calls, BUDGET)[1] == "tool_call_regression_over_budget"
    big = _agg({"straightforward": 90, "ambiguous": 70}, 2.4, 0.050)  # gain 20 (large): +20 % calls, +25 % cost
    ok, reason, inputs = E.decide(before, big, BUDGET)
    assert (ok, reason) == (True, "quality_gain_within_budget") and inputs["limits"] == "large"
    cost = _agg({"straightforward": 80, "ambiguous": 60}, 2.0, 0.046)  # +15 % cost, small limits
    assert E.decide(before, cost, BUDGET)[1] == "token_cost_regression_over_budget"


if __name__ == "__main__":
    for k, fn in sorted(globals().items()):
        if k.startswith("test_"):
            fn()
            print(f"  ok    {k}")
