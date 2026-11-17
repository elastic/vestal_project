"""Table-driven tests for ara_loop.py: 28 section 3 (proposal spec) and 3.2 (improvement and incident rule tables)."""
import copy
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ara_loop as L  # noqa: E402
from ara_eval import CATEGORIES  # noqa: E402


def agg(acc=80.0, tools=3.0, cost=0.010, ndcg=0.70, **cats):
    ra = {c: acc for c in CATEGORIES}
    ra.update(cats)
    vals = [v for v in ra.values()]
    return {"routing_accuracy": ra, "routing_accuracy_overall": round(sum(vals) / len(vals), 1),
            "tool_calls_per_question": tools, "cost_per_question": cost, "ndcg_at_5": ndcg}


GATE = {"testset_version": "v1.1", "target_scope": "proposal_category", "min_gain_points": 5.0, "min_gain_pct": 10.0,
        "category_drop_limit_points": 5.0, "tool_call_limit_pct": 15.0, "cost_limit_pct": 20.0,
        "incident": {"recovery_tolerance_points": 4.0, "recovery_tolerance_ndcg": 0.05}}


def prop(metric="routing_accuracy", cat="cross_domain", kind="improvement", t="attach_tool"):
    return {"kind": kind, "proposal_type": t, "target": "tina-compliance", "change": {"tool_id": "cortex.account_history"},
            "evidence": [{"conversation_id": "c", "trace_id": "t", "observation": "o"}],
            "expected_effect": {"metric": metric, "category": cat}, "rationale": "never read"}


COMP = agg()
IMPROVE = [
    # name, candidate, proposal, gate edits, expected (decision, reason)
    ("good", agg(cross_domain=90.0), prop(), {}, ("pass", "within_policy")),
    ("gain exactly at the minimum passes", agg(cross_domain=85.0), prop(), {}, ("pass", "within_policy")),
    ("gain just under", agg(cross_domain=84.9), prop(), {}, ("fail", "no_gain")),
    ("category drop beats everything", agg(cross_domain=95.0, ambiguous=74.0, tools=9.0), prop(), {}, ("fail", "category_regression")),
    ("drop equal to the limit is allowed", agg(cross_domain=95.0, ambiguous=75.0), prop(), {}, ("pass", "within_policy")),
    ("tool call rise", agg(cross_domain=95.0, tools=3.6), prop(), {}, ("fail", "tool_call_regression")),
    ("tool call rise at limit passes", agg(cross_domain=95.0, tools=3.45), prop(), {}, ("pass", "within_policy")),
    ("cost rise", agg(cross_domain=95.0, cost=0.0125), prop(), {}, ("fail", "cost_regression")),
    ("tool rule outranks cost rule", agg(cross_domain=95.0, tools=4.0, cost=0.02), prop(), {}, ("fail", "tool_call_regression")),
    ("none disables a limit", agg(cross_domain=95.0, tools=9.0, cost=0.5, ambiguous=0.0),
     prop(), {"tool_call_limit_pct": "none", "cost_limit_pct": None, "category_drop_limit_points": "none"}, ("pass", "within_policy")),
    ("overall scope reads overall gain", agg(acc=84.0), prop(), {"target_scope": "overall"}, ("fail", "no_gain")),
    ("overall scope passes on overall gain", agg(acc=86.0), prop(cat="all"), {}, ("pass", "within_policy")),
    ("efficiency: fall in percent passes", agg(tools=2.6), prop("tool_calls", "all"), {}, ("pass", "within_policy")),
    ("efficiency: small fall fails on pct", agg(tools=2.8), prop("tool_calls", "all"), {}, ("fail", "no_gain")),
    ("cost efficiency", agg(cost=0.0085), prop("cost", "all"), {}, ("pass", "within_policy")),
    ("ndcg gain in points of 0.01", agg(ndcg=0.76), prop("ndcg_at_5", "policy_retrieval"), {}, ("pass", "within_policy")),
    ("ndcg gain under", agg(ndcg=0.74), prop("ndcg_at_5", "policy_retrieval"), {}, ("fail", "no_gain")),
]


def test_improvement_table():
    for name, cand, p, edits, want in IMPROVE:
        gate = {**GATE, **edits}
        d, why, inputs, rows = L.decide(p, COMP, cand, gate)
        assert (d, why) == want, name
        assert [r["rule"] for r in rows][-1] == "otherwise" and sum(r["applies"] for r in rows[:-1]) >= (0 if d == "pass" else 1), name


def test_gain_units():
    assert L.gain(prop(), COMP, agg(cross_domain=90.04), GATE) == 10.0
    assert L.gain(prop("ndcg_at_5", "policy_retrieval"), COMP, agg(ndcg=0.755), GATE) == 5.5
    assert L.gain(prop("tool_calls", "all"), COMP, agg(tools=2.7), GATE) == 10.0
    assert L.gain(prop(), COMP, {**agg(), "routing_accuracy": {**agg()["routing_accuracy"], "cross_domain": None}}, GATE) is None


def test_missing_gain_fails_rather_than_passes():
    cand = agg()
    cand["routing_accuracy"]["cross_domain"] = None
    assert L.decide(prop(), COMP, cand, GATE)[:2] == ("fail", "no_gain")


BASE = agg(acc=82.0, ndcg=0.72)
INCIDENT = [
    ("recovered", agg(acc=81.0, ndcg=0.72), prop("routing_accuracy", "all", "incident_fix"), {}, ("pass", "recovers_within_policy")),
    ("not recovered", agg(acc=60.0), prop("routing_accuracy", "all", "incident_fix"), {"category_drop_limit_points": "none"}, ("fail", "no_recovery")),
    ("category fell more than the limit", agg(acc=82.0, ambiguous=70.0), prop("routing_accuracy", "all", "incident_fix"), {}, ("fail", "category_regression")),
    ("ndcg within tolerance", agg(ndcg=0.69), prop("ndcg_at_5", "policy_retrieval", "incident_fix"), {}, ("pass", "recovers_within_policy")),
    ("ndcg outside tolerance", agg(ndcg=0.60), prop("ndcg_at_5", "policy_retrieval", "incident_fix"), {"category_drop_limit_points": "none"}, ("fail", "no_recovery")),
    ("tool calls above baseline", agg(acc=82.0, ndcg=0.72, tools=3.6), prop("ndcg_at_5", "policy_retrieval", "incident_fix"), {}, ("fail", "tool_call_regression")),
    ("cost above baseline", agg(acc=82.0, ndcg=0.72, cost=0.0125), prop("ndcg_at_5", "policy_retrieval", "incident_fix"), {}, ("fail", "cost_regression")),
    ("category target", agg(acc=82.0, cross_domain=79.0), prop("routing_accuracy", "cross_domain", "incident_fix"), {}, ("pass", "recovers_within_policy")),
    ("no tolerance in the gate fails closed", agg(acc=82.0), prop("routing_accuracy", "all", "incident_fix"), {"incident": {}}, ("fail", "no_recovery")),
]


def test_incident_table_uses_baseline_not_comparison():
    for name, cand, p, edits, want in INCIDENT:
        gate = {**GATE, **edits}
        # a degraded comparison must not matter for an incident fix
        d, why, _, _ = L.decide(p, agg(acc=40.0, ndcg=0.3), cand, gate, baseline=BASE)
        assert (d, why) == want, name


def test_improvement_ignores_baseline():
    d = L.decide(prop(), COMP, agg(cross_domain=90.0), GATE, baseline=agg(acc=0.0))
    assert d[:2] == ("pass", "within_policy")


def test_validate_proposal_table():
    ok = prop()
    assert L.validate_proposal(ok) == []
    cases = {}
    for f in ("kind", "proposal_type", "target", "change", "evidence", "expected_effect"):
        p = copy.deepcopy(ok); del p[f]; cases[f"missing {f}"] = p
    def mut(fn):
        p = copy.deepcopy(ok); fn(p); return p
    cases.update({
        "empty evidence": mut(lambda p: p.update(evidence=[])),
        "evidence without conversation_id": mut(lambda p: p["evidence"][0].pop("conversation_id")),
        "evidence without trace_id": mut(lambda p: p["evidence"][0].pop("trace_id")),
        "unknown kind": mut(lambda p: p.update(kind="other")),
        "unknown type": mut(lambda p: p.update(proposal_type="other")),
        "unknown metric": mut(lambda p: p.update(expected_effect={"metric": "speed", "category": "all"})),
        "category not matching metric": mut(lambda p: p.update(expected_effect={"metric": "ndcg_at_5", "category": "all"})),
        "attach without tool_id": mut(lambda p: p.update(change={})),
        "wrong type target": mut(lambda p: p.update(target=7)),
        "text change without text": mut(lambda p: p.update(proposal_type="instruction_change", change={"field": "instructions"})),
        "data change on improvement": mut(lambda p: p.update(proposal_type="data_change", change={
            "tool_id": "t", "production_source": "a", "candidate_source": "b", "operation": "repoint_alias"})),
    })
    assert len(cases) >= 12
    for name, p in cases.items():
        assert L.validate_proposal(p), name
    good_data = prop(kind="incident_fix", t="data_change")
    good_data["change"] = {"tool_id": "cortex.policy_search", "production_source": "cortex-policies", "candidate_source": "x",
                           "operation": "delete_matching", "query": {"term": {"doc_type": "faq"}}}
    assert L.validate_proposal(good_data) == []
    good_data["change"]["operation"] = "delete_matching"; del good_data["change"]["query"]
    assert L.validate_proposal(good_data) == ["a delete_matching operation needs its query"]
    assert L.validate_proposal("x") == ["a proposal is a JSON object"]


def test_named_proposals_append_and_keep_the_hardening_block():
    import copy
    tina = {"id": "tina-compliance", "configuration": {"instructions": "HARDENING BLOCK\nBe brief."}, "tool_ids": ["a"]}
    p = {"proposal_id": "prop-review-1", "proposal_type": "instruction_change",
         "change": {"field": "configuration.instructions", "text": "Default the window to 90 days."}}
    before = copy.deepcopy(tina)
    out = L.apply_change(tina, p)
    assert out["configuration"]["instructions"] == "HARDENING BLOCK\nBe brief.\nDefault the window to 90 days."
    assert tina == before  # the input is not mutated
    # an evaluator's proposal sets the field
    q = {**p, "proposal_id": "prop-abc"}
    assert L.apply_change(tina, q)["configuration"]["instructions"] == "Default the window to 90 days."


def test_attach_detach_and_missing_field():
    tina = {"tool_ids": ["a"]}
    att = {"proposal_type": "attach_tool", "change": {"tool_id": "cortex.account_history"}}
    out = L.apply_change(tina, att)
    assert out["tool_ids"] == ["a", "cortex.account_history"] and L.apply_change(out, att) == out
    det = {"proposal_type": "detach_tool", "change": {"tool_id": "a"}}
    assert L.apply_change(out, det)["tool_ids"] == ["cortex.account_history"]
    import pytest
    with pytest.raises(KeyError):
        L.apply_change({}, {"proposal_type": "tool_description_change", "change": {"field": "description", "text": "t"}})


def test_attach_detach_in_agent_builders_tool_group():
    tina = {"configuration": {"tools": [{"tool_ids": ["a"]}]}}
    att = {"proposal_type": "attach_tool", "change": {"tool_id": "cortex.account_history"}}
    out = L.apply_change(tina, att)
    assert out["configuration"]["tools"][0]["tool_ids"] == ["a", "cortex.account_history"] and "tool_ids" not in out
    assert tina["configuration"]["tools"][0]["tool_ids"] == ["a"]
    det = {"proposal_type": "detach_tool", "change": {"tool_id": "a"}}
    assert L.apply_change(out, det)["configuration"]["tools"][0]["tool_ids"] == ["cortex.account_history"]


def test_named_query_change_replaces_the_query():
    import ara_loop as L
    defn = {"configuration": {"query": "FROM a | LIMIT 1"}}
    p = {"proposal_id": "prop-review-2", "proposal_type": "tool_query_change", "change": {"field": "configuration.query", "text": "FROM b | LIMIT 2"}}
    assert L.apply_change(defn, p)["configuration"]["query"] == "FROM b | LIMIT 2"


# the question-count rule for small categories (design decision of 2026-11-14): under 15 questions a category regresses only when it loses 2 or more
def counted(a, **counts):
    a = dict(a)
    a["category_counts"] = {c: counts.get(c, 20) for c in CATEGORIES}
    return a


def test_small_category_one_question_is_not_a_regression():
    base = counted(agg(ambiguous=85.7, cross_domain=80.0), ambiguous=7)              # 6 of 7
    one_lost = counted(agg(ambiguous=71.4, cross_domain=90.0), ambiguous=7)           # 5 of 7: a 14.3-point drop, one question
    two_lost = counted(agg(ambiguous=57.1, cross_domain=90.0), ambiguous=7)           # 4 of 7: two questions
    d, why, _, _ = L.decide_improvement(base, one_lost, prop(), GATE)
    assert (d, why) == ("pass", "within_policy")
    d, why, _, _ = L.decide_improvement(base, two_lost, prop(), GATE)
    assert (d, why) == ("fail", "category_regression")


def test_the_one_question_loss_trap_still_fails_on_no_gain():
    base = counted(agg(ambiguous=85.7), ambiguous=7)
    trap = counted(agg(ambiguous=71.4), ambiguous=7)    # the trap proposal gains nothing on its target and loses one ambiguous question
    d, why, _, _ = L.decide_improvement(base, trap, prop(), GATE)
    assert (d, why) == ("fail", "no_gain")


def test_large_category_keeps_the_points_rule():
    base = counted(agg(straightforward=90.0, cross_domain=80.0), straightforward=46)
    cand = counted(agg(straightforward=84.8, cross_domain=90.0), straightforward=46)   # a 5.2-point drop, 2 questions of 46
    assert L.decide_improvement(base, cand, prop(), GATE)[:2] == ("fail", "category_regression")
    edge = counted(agg(straightforward=85.0, cross_domain=90.0), straightforward=46)
    assert L.decide_improvement(base, edge, prop(), GATE)[:2] == ("pass", "within_policy")
    # 15 questions is not small: one question (6.7 points) is a regression
    b15 = counted(agg(ambiguous=80.0), ambiguous=15)
    c15 = counted(agg(ambiguous=73.3, cross_domain=90.0), ambiguous=15)
    assert L.decide_improvement(b15, c15, prop(), GATE)[:2] == ("fail", "category_regression")


def test_without_counts_the_points_rule_applies():
    base, cand = agg(ambiguous=85.7), agg(ambiguous=71.4, cross_domain=90.0)
    assert L.decide_improvement(base, cand, prop(), GATE)[:2] == ("fail", "category_regression")


def test_incident_rule_uses_questions_for_a_small_category():
    base = counted(agg(acc=85.0, ambiguous=85.7), ambiguous=7)
    cand = counted(agg(acc=85.0, ambiguous=71.4), ambiguous=7)
    assert L.decide_incident(base, cand, prop("routing_accuracy", "all", "incident_fix"), GATE)[:2] == ("pass", "recovers_within_policy")
