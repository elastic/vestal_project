"""Fixture-ledger tests for ara_ledger.py: both proposal orders, both applied with the second not confirming (28 s3 acceptance 1)."""
import copy
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ara_ledger as G  # noqa: E402
import ara_loop as L  # noqa: E402
from ara_eval import CATEGORIES  # noqa: E402

START = {"tina-compliance": {"id": "tina-compliance", "configuration": {"instructions": "HARDENING\nBe brief.", "tools": [{"tool_ids": ["a"]}]}},
         "cortex.policy_search": {"id": "cortex.policy_search", "description": "Search policy. Search twice."}}
P1 = {"proposal_id": "prop-review-1", "kind": "improvement", "proposal_type": "attach_tool", "target": "tina-compliance",
      "change": {"tool_id": "cortex.account_history"}, "evidence": [], "expected_effect": {"metric": "routing_accuracy", "category": "cross_domain"}}
P2 = {"proposal_id": "prop-review-2", "kind": "improvement", "proposal_type": "tool_description_change", "target": "cortex.policy_search",
      "change": {"field": "description", "text": "Search once."}, "evidence": [], "expected_effect": {"metric": "tool_calls", "category": "all"}}
PROPS = {"prop-review-1": P1, "prop-review-2": P2}


def e(at, action, pid, **kw):
    return {"at": f"2026-11-11T10:{at:02d}:00Z", "action": action, "proposal_id": pid, **kw}


def after_apply(state, pid):
    s = copy.deepcopy(state)
    s[PROPS[pid]["target"]] = L.apply_change(s[PROPS[pid]["target"]], PROPS[pid])
    return s


def good_ledger(order=("prop-review-1", "prop-review-2")):
    entries, state, t = [], copy.deepcopy(START), 0
    for pid in order:
        tgt = PROPS[pid]["target"]
        entries += [e(t, "candidate", pid), e(t + 1, "gate", pid, gate={"decision": "pass"}),
                    e(t + 2, "apply", pid, snapshot={tgt: copy.deepcopy(state[tgt])}),
                    e(t + 3, "remeasure", pid, outcome="confirmed", run_label=f"remeasure-{pid}")]
        state = after_apply(state, pid)
        t += 10
    return entries, state


def test_replay_both_orders_reach_the_same_state():
    s = []
    for order in (("prop-review-1", "prop-review-2"), ("prop-review-2", "prop-review-1")):
        entries, want = good_ledger(order)
        state, steps, problems = G.replay(START, entries, PROPS)
        assert state == want and not problems and [x["proposal_id"] for x in steps] == list(order)
        assert G.check_ledger(START, entries, PROPS, production=want) == []
        s.append(state)
    assert s[0] == s[1]


def test_rollback_of_the_second_keeps_the_first():
    entries, _ = good_ledger()
    entries[-1]["outcome"] = "not_confirmed"
    entries.append(e(50, "rollback", "prop-review-2"))
    state, _, problems = G.replay(START, entries, PROPS)
    assert not problems
    assert state["tina-compliance"] == after_apply(START, "prop-review-1")["tina-compliance"]
    assert state["cortex.policy_search"] == START["cortex.policy_search"]
    assert G.check_ledger(START, entries, PROPS, production=state) == []


def test_rollback_of_the_first_keeps_the_second_on_a_disjoint_object():
    entries, _ = good_ledger()
    entries[3]["outcome"] = "not_confirmed"
    entries.append(e(50, "rollback", "prop-review-1"))
    state, _, problems = G.replay(START, entries, PROPS)
    assert not problems and state["tina-compliance"] == START["tina-compliance"]
    assert state["cortex.policy_search"]["description"].endswith("Search once.")


def test_rollback_on_a_shared_object_is_reported():
    p3 = dict(P1, proposal_id="p3", proposal_type="instruction_change", change={"field": "configuration.instructions", "text": "X"})
    props = {"prop-review-1": P1, "p3": p3}
    entries = [e(0, "apply", "prop-review-1", snapshot={"tina-compliance": START["tina-compliance"]}),
               e(2, "apply", "p3", snapshot={"tina-compliance": after_apply(START, "prop-review-1")["tina-compliance"]}),
               e(4, "rollback", "prop-review-1")]
    _, _, problems = G.replay(START, entries, props)
    assert any(p.startswith("rollback_clobbers") for p in problems)


def test_check_ledger_names_each_break():
    entries, state = good_ledger()
    no_gate = [x for x in entries if not (x["action"] == "gate" and x["proposal_id"] == "prop-review-1")]
    assert any("no gate entry" in p for p in G.check_ledger(START, no_gate, PROPS))
    bad = copy.deepcopy(entries)
    bad[2]["snapshot"] = {"tina-compliance": {"id": "forged"}}
    assert any("snapshot" in p for p in G.check_ledger(START, bad, PROPS))
    left = copy.deepcopy(entries)
    left[-1]["outcome"] = "not_confirmed"
    assert any("not rolled back" in p for p in G.check_ledger(START, left, PROPS))
    assert any("not the replayed state" in p for p in G.check_ledger(START, entries, PROPS, production=START))
    assert any("no such proposal" in p for p in G.check_ledger(START, entries, {}))


def agg(acc=80.0, tools=3.0):
    ra = {c: acc for c in CATEGORIES}
    return {"routing_accuracy": ra, "routing_accuracy_overall": acc, "tool_calls_per_question": tools, "cost_per_question": 0.01, "ndcg_at_5": 0.7}


def test_remeasure_outcome_by_tolerance():
    thr = {"remeasure_tolerance_points": 3.0, "remeasure_tolerance_pct": 5.0}
    assert G.remeasure_outcome(P1, agg(85.0), agg(83.0), thr) == "confirmed"
    assert G.remeasure_outcome(P1, agg(85.0), agg(80.0), thr) == "not_confirmed"
    assert G.remeasure_outcome(P2, agg(tools=2.0), agg(tools=2.05), thr) == "confirmed"
    assert G.remeasure_outcome(P2, agg(tools=2.0), agg(tools=2.4), thr) == "not_confirmed"
    assert G.remeasure_outcome(P1, agg(), agg(), {}) == "not_confirmed"


def test_check_ledger_recomputes_the_outcome():
    entries, state = good_ledger()
    runs = {"prop-review-1": {"candidate": agg(85.0), "remeasure": agg(70.0)}}
    problems = G.check_ledger(START, entries, PROPS, gate_runs=runs, thresholds={"remeasure_tolerance_points": 3.0})
    assert any("the ledger says confirmed, the numbers say not_confirmed" in p for p in problems)


def test_comparison_label_follows_the_last_confirmed_remeasure():
    entries, _ = good_ledger()
    ledger = entries[:4] + [e(9, "candidate", "prop-review-2")] + entries[4:]
    ledger.sort(key=lambda x: x["at"])
    assert G.comparison_label(ledger, "prop-review-1") == "m6-baseline"
    assert G.comparison_label(ledger, "prop-review-2") == "remeasure-prop-review-1"
    ledger.insert(5, e(5, "rollback", "prop-review-1"))
    ledger.sort(key=lambda x: x["at"])
    assert G.comparison_label(ledger, "prop-review-2") == "m6-baseline"


def test_server_managed_fields_do_not_make_production_differ():
    import ara_ledger as G
    start = {"tina-compliance": {"id": "tina-compliance", "configuration": {"instructions": "a"}, "created_at": "t0", "updated_at": "t0", "permissions": {"x": 1}}}
    prod = {"tina-compliance": {"id": "tina-compliance", "configuration": {"instructions": "a"}, "created_at": "t1", "updated_at": "t9", "permissions": {"x": 2}}}
    assert G.check_ledger(start, [], {}, prod) == []
    prod["tina-compliance"]["configuration"]["instructions"] = "changed"
    assert G.check_ledger(start, [], {}, prod) == ["production's tina-compliance is not the replayed state"]


def counted(a, **counts):
    a = dict(a)
    a["category_counts"] = {c: counts.get(c, 83) for c in a["routing_accuracy"]}
    return a


def test_small_category_remeasure_is_judged_in_questions():
    thr = {"remeasure_tolerance_points": 2.0}
    pa = {**P1, "expected_effect": {"metric": "routing_accuracy", "category": "ambiguous"}}
    cand = counted(agg(85.7), ambiguous=7)
    cand["routing_accuracy"]["ambiguous"] = 85.7
    one = counted(agg(85.7), ambiguous=7); one["routing_accuracy"]["ambiguous"] = 71.4    # one question lower: 14.3 points
    two = counted(agg(85.7), ambiguous=7); two["routing_accuracy"]["ambiguous"] = 57.1    # two questions lower
    up = counted(agg(85.7), ambiguous=7); up["routing_accuracy"]["ambiguous"] = 100.0      # one question higher
    assert G.remeasure_outcome(pa, cand, one, thr) == "confirmed"
    assert G.remeasure_outcome(pa, cand, up, thr) == "confirmed"
    assert G.remeasure_outcome(pa, cand, two, thr) == "not_confirmed"
    # the same one-question gap in a large category stays on the points tolerance
    pl = {**P1, "expected_effect": {"metric": "routing_accuracy", "category": "straightforward"}}
    big, bigger = counted(agg(85.0), straightforward=46), counted(agg(85.0), straightforward=46)
    bigger["routing_accuracy"]["straightforward"] = 82.6    # one of 46: 2.2 points
    assert G.remeasure_outcome(pl, big, bigger, thr) == "not_confirmed"
    # without counts, or a missing tolerance, nothing changes
    assert G.remeasure_outcome(pa, agg(85.7), agg(71.4), thr) == "not_confirmed"
    assert G.remeasure_outcome(pa, cand, one, {}) == "not_confirmed"
    # the overall target never uses the question rule
    pall = {**P1, "expected_effect": {"metric": "routing_accuracy", "category": "all"}}
    assert G.remeasure_outcome(pall, counted(agg(85.0), cross_domain=8), counted(agg(82.0), cross_domain=8), thr) == "not_confirmed"
