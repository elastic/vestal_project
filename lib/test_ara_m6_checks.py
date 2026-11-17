import copy
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ara_m6_checks as C  # noqa: E402
import ara_proposal_schema as PS  # noqa: E402
import ara_tracepack as TP  # noqa: E402

KEY = {"failing_span_id": "a" * 16, "failure_class": "validation_error", "costly_span_id": "b" * 16, "costly_cause": "repeated_tool_call", "costly_input_tokens": 4200}


def tool(q="FROM cortex-cases | WHERE id == ?id | LIMIT 5", **kw):
    t = {"id": "cortex.case_lookup", "type": "esql", "description": "Look up a case.", "configuration": {"query": q, "params": {"id": {"type": "keyword", "description": "id"}}}}
    t.update(kw); return t


def test_diagnose_names_fields_not_answers():
    rec = dict(KEY, failure_class="empty_result", costly_input_tokens=4199)
    msgs = C.diagnose(rec, KEY)
    assert len(msgs) == 2 and not any("validation_error" in m or "4200" in m for m in msgs)
    assert C.diagnose(KEY, KEY) == [] and len(C.diagnose({}, KEY)) == 5


def test_tool_artifact_only_the_query_may_change():
    o = tool()
    assert C.tool_artifact(tool("FROM cortex-cases | WHERE case_id == ?id | LIMIT 5"), o) == []
    assert "unchanged" in C.tool_artifact(tool("FROM  cortex-cases |  WHERE id == ?id\n| LIMIT 5"), o)[0]
    assert any("description" in m for m in C.tool_artifact(tool("FROM x | LIMIT 1", description="other"), o))
    n = tool("FROM x | LIMIT 1"); n["updated_at"] = "now"
    assert C.tool_artifact(n, o) == []
    n = tool("FROM x | LIMIT 1"); n["configuration"]["params"]["id"]["type"] = "text"
    assert any("configuration" in m for m in C.tool_artifact(n, o))


def test_gap_tool():
    assert C.gap_tool_artifact(tool(), "cortex-cases") == []
    assert C.gap_tool_artifact(tool("FROM cortex-cases | LIMIT 3"))  # no parameter
    assert C.gap_tool_artifact(tool(type="index_search"))
    assert any("cortex-accounts" in m for m in C.gap_tool_artifact(tool(), "cortex-accounts"))


def test_evaluator_artifact():
    a = {"configuration": {"enable_elastic_capabilities": False, "tools": [{"tool_ids": ["t1", "t2"]}]}}
    tools = {"t1": tool("FROM cortex-eval-runs | LIMIT 50"), "t2": tool("FROM traces-agent_builder.otel-default | STATS n = COUNT(*) BY name")}
    assert C.evaluator_artifact(a, tools) == []
    assert C.evaluator_artifact({"tool_ids": ["t1"]}, tools)
    assert any("capabilities" in m for m in C.evaluator_artifact({"configuration": {"tools": [{"tool_ids": ["t1", "t2"]}]}}, tools))
    assert C.evaluator_artifact({"tool_ids": ["t1", "platform.core.search"]}, tools)
    tools["t2"] = tool("FROM cortex-eval-runs")
    assert any("no bound" in m for m in C.evaluator_artifact(a, tools))
    tools["t2"] = tool("FROM cortex-eval-runs | LIMIT 500")
    assert any("no bound" in m for m in C.evaluator_artifact(a, tools))
    tools["t2"] = tool("FROM cortex-fraud-cases | LIMIT 5")
    assert any("does not read" in m for m in C.evaluator_artifact(a, tools))
    assert C.evaluator_artifact(dict(a, skill_ids=["s"]), {"t1": tools["t1"], "t2": tool("FROM cortex-eval-runs | LIMIT 1")})


def test_learner_schema_check_accepts_the_reference_and_rejects_loose_ones():
    assert C.learner_schema_check(PS.SCHEMA) == []
    assert any("accepts an invalid" in m for m in C.learner_schema_check({"type": "object"}))
    assert any("rejects a valid" in m for m in C.learner_schema_check({"type": "object", "required": ["nope"]}))
    assert "not valid JSON Schema" in C.learner_schema_check({"type": 5})[0]


def test_gate_equality_and_post_exec():
    g = {"a": 1, "b": " x  y "}
    assert C.gate_equals_key(g, {"b": "x y", "a": 1}) == []
    assert C.gate_equals_key({"a": 2}, {"a": 1, "c": 3}) and "a differs" in C.gate_equals_key({"a": 2}, {"a": 1})[0]
    assert C.post_exec_artifact(["cortex-answer-audit"]) == [] and C.post_exec_artifact([]) and C.post_exec_artifact(["x", "cortex-answer-audit"])


def test_tiers():
    assert C.tier(False, False, False, False, False, False) == 0
    assert C.tier(True, False, True, True, True, True) == 25
    assert C.tier(True, True, False, True, True, True) == 50 and C.tier(True, True, True, False, True, True) == 50 and C.tier(True, True, True, True, False, True) == 50
    assert C.tier(True, True, True, True, True, False) == 75 and C.tier(True, True, True, True, True, True) == 100
    assert C.passed(75) and not C.passed(50)
    g = C.grade_json("C2", "model_pin_no_model_change", {"class": "embedding_staleness"}, {}, {"affected_metric": "ndcg_at_5_policy", "baseline": 0.71, "degraded": 0.52, "after": 0.7}, {}, {}, {}, "m6-v1.0", "c", 100)
    assert g["schema"] == "6c-1" and g["behavior_measurement"]["after"] == 0.7 and json.dumps(g)


def test_gap_card_match_needs_id_params_and_index():
    card = {"tool_id": "cortex.counterparty_lookup", "index": "cortex-wire-transfers", "params": {"counterparty_bank": "string"}}
    ok = {"id": "cortex.counterparty_lookup", "type": "esql", "description": "d",
          "configuration": {"query": "FROM cortex-wire-transfers | WHERE counterparty_bank == ?counterparty_bank", "params": {"counterparty_bank": {"type": "string"}}}}
    assert C.gap_card_match(ok, card) == []
    bad = dict(ok, configuration={"query": ok["configuration"]["query"], "params": {"bank": {"type": "string"}}})
    assert any("parameters" in m for m in C.gap_card_match(bad, card))
    assert any("id" in m for m in C.gap_card_match(dict(ok, id="cortex.other"), card))


def test_windows_check_names_the_window_never_the_answer():
    key = [{"type": "retrieval_drift", "signal": "s1", "change_point_date": "2026-10-05"}, {"type": "behavior_shift", "signal": "s3", "change_point_date": "2026-10-20"}]
    good = [{"change_point_date": "2026-10-20", "type": "behavior_shift", "signal": "s3"}, {"change_point_date": "2026-10-06", "type": "retrieval_drift", "signal": "s1"}]
    assert C.windows_check(good, key) == []
    wrong = [dict(good[0], signal="s1"), good[1]]
    assert C.windows_check(wrong, key) == ["window 1: the signal does not match the type's evidence"]
    assert "window 1: no incident begins near that date" in C.windows_check([dict(good[0], change_point_date="2026-10-12"), good[1]], key)
    assert any("record 2 windows" in m for m in C.windows_check(good[:1], key))


def test_grounding_needs_real_evidence_from_the_patterns_conversations():
    key = {"patterns": {"double_search": {"target": "cortex.policy_search", "types": ["tool_description_change"], "conversation_ids": ["c1", "c2"]},
                        "needless_question": {"target": "tina-compliance", "types": ["instruction_change"], "conversation_ids": ["c3"]}},
           "live": ["double_search", "needless_question"]}
    p = [{"target": "cortex.policy_search", "proposal_type": "tool_description_change", "evidence": [{"conversation_id": "c1"}]},
         {"target": "tina-compliance", "proposal_type": "instruction_change", "evidence": [{"conversation_id": "c3"}]}]
    assert C.grounding(p, key) == ([], ["double_search", "needless_question"])
    made_up = [dict(p[0], evidence=[{"conversation_id": "zz"}]), p[1]]
    probs, named = C.grounding(made_up, key)
    assert named == ["needless_question"] and len(probs) == 2
    assert any("data change" in m for m in C.grounding(p + [{"proposal_type": "data_change"}], key)[0])


def test_monitor_rejects_literals_and_late_or_noisy_rules():
    assert C.monitor_literals("FROM cortex-eval-runs | WHERE run_label == \"canary-ab12cd34\"")
    assert C.monitor_literals("FROM cortex-eval-runs | WHERE @timestamp > \"2026-11-12\"")
    assert C.monitor_literals("FROM cortex-eval-runs | STATS a = AVG(routing_accuracy_overall) BY run_label") == []
    assert C.monitor_verdict(2, [0, 0, 0], 0, 8, "06:36", "07:00") == []
    msgs = C.monitor_verdict(0, [1, 0, 0], 2, 4, "07:30", "07:00")
    assert len(msgs) == 5


def test_grounding_known_conversations_are_not_made_up():
    key = {"patterns": {"p": {"target": "t", "types": ["tool_query_change"], "conversation_ids": ["c1"]}}, "live": ["p"]}
    prop = {"target": "t", "proposal_type": "tool_query_change", "evidence": [{"conversation_id": "c1"}, {"conversation_id": "real-elsewhere"}]}
    probs, named = C.grounding([prop], key, min_patterns=1)
    assert any("not in the week" in x for x in probs)
    probs, named = C.grounding([prop], key, min_patterns=1, known={"c1", "real-elsewhere"})
    assert named == ["p"] and not probs


def test_grounding_counts_a_conversation_the_traces_show_with_the_pattern():
    key = {"patterns": {"double_search": {"target": "cortex.policy_search", "types": ["tool_description_change"], "conversation_ids": ["k1"]},
                        "unattached_tool": {"target": "tina-compliance", "types": ["attach_tool"], "conversation_ids": ["u1"]}},
           "live": ["double_search", "unattached_tool"]}
    ev = lambda c: [{"conversation_id": c}]  # noqa: E731
    props = [{"target": "tina-compliance", "proposal_type": "attach_tool", "evidence": ev("u1")},
             {"target": "cortex.policy_search", "proposal_type": "tool_description_change", "evidence": ev("organic")}]
    known = {"k1", "u1", "organic"}
    probs, named = C.grounding(props, key, known=known)
    assert named == ["unattached_tool"] and probs  # without the traces' answer the organic round is not the pack's
    probs, named = C.grounding(props, key, known=known, shown={"double_search": {"organic"}})
    assert (probs, named) == ([], ["double_search", "unattached_tool"])
    # a shown set never lends evidence to another pattern or to a proposal with the wrong target/type
    wrong = [dict(props[1], target="cortex.case_correspondence")] + props[:1]
    assert C.grounding(wrong, key, known=known, shown={"double_search": {"organic"}})[1] == ["unattached_tool"]
    # wrong proposal type on the right target, and a cited conversation that is neither the pack's nor shown, still miss
    wrong_type = [dict(props[1], proposal_type="instruction_change")] + props[:1]
    assert C.grounding(wrong_type, key, known=known, shown={"double_search": {"organic"}})[1] == ["unattached_tool"]
    wrong_id = [dict(props[1], evidence=ev("somewhere-else"))] + props[:1]
    probs, named = C.grounding(wrong_id, key, known=known | {"somewhere-else"}, shown={"double_search": {"organic"}})
    assert named == ["unattached_tool"] and probs
    made_up = [dict(props[1], evidence=ev("not-in-the-stream"))] + props[:1]
    probs, named = C.grounding(made_up, key, known=known, shown={"double_search": set()})
    assert any("not in the week" in m for m in probs) and named == ["unattached_tool"]
    assert C.shown_ids({"values": [["a"], ["b"], [None], []]}) == {"a", "b"}
    q = C.SHOWN_ESQL["double_search"]
    assert "calls >= 2" in q and "cortex.policy_search" in q and 'attributes.gen_ai.operation.name == "execute_tool"' in q


def test_shown_ids_refuses_an_answer_without_values():
    import pytest
    for bad in (None, {}, {"error": "x"}, {"values": None}, "x"):
        with pytest.raises(ValueError):
            C.shown_ids(bad)
    assert C.shown_ids({"values": []}) == set()
