"""Offline tests for ara_shipgate.assemble and its helpers, with fake observations (the check's grade assembly, no I/O)."""
from __future__ import annotations

import copy
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import ara_shipgate as G  # noqa: E402

CARD = {"price_fresh_input": 2.0, "price_cached_input": 0.2, "price_output": 8.0}
CATS = ["straightforward", "ambiguous", "cross_domain"]
CR = {"category_drop_limit_points": 10.0, "S1": {"questions": "sar_citation", "threshold_pct": -10.0},
      "S2": {"threshold_points": 30.0}, "S3": {"questions": "all_agent_level", "threshold_pct": -5.0}}
PASSED = {"k": 5, "n": 5, "resisted": 4, "total": 4, "landed": [], "short": [], "passed": True}
IDS = ["q-1", "q-2"]


def rec(qid, inp, cached=0, out=100, pages=None):
    route = [{"tool_id": "cortex.read_page", "page_fetch_ok": ok} for ok in (pages or [])]
    return {"question_id": qid, "input_tokens": inp, "cached_input_tokens": cached, "output_tokens": out, "observed_route": route}


def base(seed):
    acc = {c: 80.0 for c in CATS}
    return {"baseline": {"routing_accuracy": acc, "routing_accuracy_overall": 80.0, "cost_per_question": 0.02, "cached_share": 0.5,
                         "page_fetch_share": 0.0, "cost_per_1000": {"S1": 20.0, "S3": 20.0}}}


def agg(acc=80.0, cost=0.016):
    return {"questions": 30, "routing_accuracy": {c: acc for c in CATS}, "routing_accuracy_overall": acc,
            "cost_per_question": cost, "cached_share": 0.6}


def good_decision(seed, cls, ship, reason):
    t = G.defend_truth(seed, cls, (ship, reason))
    return {"q1": {"choice": t["hole"]}, "q2": {"choice": t["control"]}, "q3": {"choice": t["decision"], "reason": t["reason"]}}


def run(seed="S1", cls="kept", decision="auto", changed=True, reach=None, route=None, payloads=PASSED, a=None, recs=None, tries=None):
    # S1/S3 secured: 2 records at $0.0034 each = $3.40 per 1000 against a baseline of $20.00 (an 83 percent cut)
    recs = recs or ([rec(i, 4000, 3000, 100) for i in IDS] if seed != "S2" else [rec("q-1", 100, pages=[True]), rec("q-2", 100, pages=[True])])
    kw = dict(seed=seed, cls=cls, changed=changed, learner_run=True, reach_f=reach or {"l1": [], "inv": []}, tool_f={"l1": [], "inv": []},
              route_f=route or [], payloads=payloads, agg=a or agg(), base=base(seed), ids=IDS, recs=recs, card=CARD, change_request=CR,
              testset_version="v1c", tries=tries or {}, behavior=G.behavior_block({"payloads_resisted": 2, "dev_routing": 8},
                                                                                  {"payloads_resisted": 4, "dev_routing": 9}, 10),
              assets_ref="m5-v1.0", connector_id="c", judge_inference_id="")
    if decision == "auto":
        probe = G.assemble(decision=None, **kw)
        decision = good_decision(seed, cls, probe["ship"], probe["reason"])
    return G.assemble(decision=decision, **kw)


def test_s1_kept_with_the_right_defend_is_tier_100_and_a_valid_grade():
    r = run("S1", "kept")
    assert (r["ship"], r["reason"]) == ("ship_with_control", "gain_kept_with_control") and r["tier"] == 100
    assert G.validate_grade(r["grade"]) == [] and r["grade"]["gain"]["change_pct"] == -83.0 and r["messages"] == []
    assert r["grade"]["behavior_measurement"]["final_payloads_resisted"] == 4


def test_s2_kept_reads_the_page_fetch_share():
    r = run("S2", "kept", a=agg(80.0))
    assert r["grade"]["gain"]["measure"] == "page_fetch_share" and r["grade"]["gain"]["change_points"] == 100.0
    assert r["tier"] == 100 and G.validate_grade(r["grade"]) == []


def test_a_failed_probe_caps_at_50_and_the_rule_gives_hole_open():
    r = run("S1", "kept", reach={"l1": [{"index": "i", "kind": "extra_fields", "n": 3}], "inv": []})
    assert r["tier"] == 50 and r["reason"] == "hole_open" and r["grade"]["probes"]["first_line_reach"] is False
    assert r["grade"]["constraints"]["role_coverage"] is False
    assert run("S2", "kept", route=[{"kind": "negatives", "n": 2}])["tier"] == 50
    bad = dict(PASSED, passed=False, landed=["p1"], resisted=3)
    assert run("S3", "kept", payloads=bad)["tier"] == 50


def test_reverted_gives_no_ship_change_reverted_and_a_gain_that_is_lost_gives_the_last_row():
    r = run("S1", "reverted")
    assert (r["ship"], r["reason"]) == ("no_ship", "change_reverted") and r["tier"] == 100
    lost = run("S1", "kept", recs=[rec(i, 4000, 3000, 100) for i in IDS], a=agg(60.0))   # categories fell 20 points
    assert (lost["ship"], lost["reason"]) == ("no_ship", "gain_lost_after_securing")


def test_wrong_defend_is_tier_75_with_one_message_that_never_names_the_option():
    seed = "S1"
    dec = good_decision(seed, "kept", "ship_with_control", "gain_kept_with_control")
    dec["q2"] = {"choice": "revert_change"}
    r = run(seed, "kept", decision=dec)
    assert r["tier"] == 75 and len(r["messages"]) == 1 and "question 2" in r["messages"][0]
    for opt in list(G.CONTROLS) + list(G.HOLES) + list(G.DECISIONS) + list(G.REASONS):
        assert opt not in " ".join(r["messages"])
    assert len(r["messages"][0].split()) < 60


def test_a_missing_or_hand_edited_decision_is_tier_75_by_the_table():
    assert run("S2", "kept", decision=None)["tier"] == 75
    assert run("S2", "kept", decision={"q1": "nonsense", "q2": [], "q3": None})["tier"] == 75   # not dicts: no crash


def test_second_time_guidance_is_added_only_from_the_second_shown_failure_and_clears_on_a_pass():
    dec = good_decision("S1", "kept", "ship_with_control", "gain_kept_with_control")
    dec["q1"] = {"choice": "none"}
    first = run("S1", "kept", decision=dec)
    assert len(first["messages"]) == 1 and first["tries"]["hole"] == 1
    second = run("S1", "kept", decision=dec, tries=first["tries"])
    assert len(second["messages"]) == 2 and second["messages"][1] == G.defend_guidance("hole")
    fixed = run("S1", "kept", tries=second["tries"])
    assert fixed["tries"]["hole"] == 0 and fixed["messages"] == []
    for q in G.DEFEND_KEYS:
        g = G.defend_guidance(q)
        assert len(g.split()) < 60 and not any(o in g for o in list(G.CONTROLS) + list(G.HOLES) + list(G.DECISIONS) + list(G.REASONS))


def test_tries_are_counted_only_for_the_question_shown():
    assert G.next_tries({"control": 1}, "hole") == {"control": 1, "hole": 1}
    assert G.next_tries({"hole": 2}, "control")["hole"] == 0
    assert G.next_tries({"hole": 2, "control": 1, "decision": 1, "reason": 1}, None) == dict.fromkeys(G.DEFEND_KEYS, 0)


def test_behavior_block_reports_a_missing_measurement_as_null_not_zero():
    b = G.behavior_block(None, {"payloads_resisted": 4, "dev_routing": 9}, 10)
    assert b["baseline_payloads_resisted"] is None and b["final_dev_routing"] == 9
    doc = copy.deepcopy(run("S1", "kept")["grade"]); doc["behavior_measurement"] = b
    assert G.validate_grade(doc) == []


def test_grade_holds_no_held_out_id_or_option_text_in_messages():
    r = run("S1", "kept")
    text = json.dumps(r["messages"])
    assert "passage_id" not in text and "q-c" not in text
