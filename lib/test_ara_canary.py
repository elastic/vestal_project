"""The canary scorer over stored conversations: route grading through the harness matcher, policy questions, problems."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ara_canary as K  # noqa: E402


def conv(cid, tool=None, tokens=(1000, 200, 300), extra_round=False):
    steps = [{"type": "tool_call", "tool_id": tool, "params": {}, "results": [{"type": "other", "data": {}}]}] if tool else []
    rnd = {"status": "completed", "input": {"message": "q"}, "steps": steps, "trace_id": f"tr-{cid}", "time_to_last_token": 900,
           "model_usage": {"input_tokens": tokens[0], "cached_input_tokens": tokens[1], "output_tokens": tokens[2], "llm_calls": 2}}
    return {"id": cid, "agent_id": "tina-compliance", "rounds": [rnd, dict(rnd)] if extra_round else [rnd]}


RUN = {"run_id": "r1", "run_label": "canary-x1", "run_at": "2026-11-11T06:00:00Z", "workflow_execution_id": "x1", "triggered_by": "task_manager",
       "change_id": None, "agent_id": "tina-compliance", "testset_version": "canary-v1"}
Q_ROUTE = {"id": "c-1", "type": "agent", "category": "straightforward", "input": "Any structuring on 476?", "expected": [{"tool_id": "cortex.structuring_deposits"}]}
Q_ESC = {"id": "c-2", "type": "agent", "category": "out_of_scope", "input": "Call the customer.", "expected": [{"tool_id": "cortex.escalate"}]}
Q_POL = {"id": "c-3", "type": "policy", "input": "What is the filing deadline?"}


def test_route_questions_are_graded_by_the_harness_matcher_and_carry_the_canary_fields():
    ok = K.score_question(Q_ROUTE, conv("a", "cortex.structuring_deposits"), RUN)
    assert ok["status"] == "graded" and ok["route_correct"] is True and ok["escalated"] is False
    assert (ok["workflow_execution_id"], ok["triggered_by"], ok["run_label"], ok["testset_version"]) == ("x1", "task_manager", "canary-x1", "canary-v1")
    assert (ok["input_tokens"], ok["cached_input_tokens"], ok["output_tokens"], ok["tool_call_count"]) == (1000, 200, 300, 1) and ok["trace_id"] == "tr-a"
    bad = K.score_question(Q_ROUTE, conv("b", "cortex.escalate"), RUN)
    assert bad["route_correct"] is False and bad["escalated"] is True
    esc = K.score_question(Q_ESC, conv("c", "cortex.escalate"), RUN)
    assert esc["route_correct"] is True and esc["escalated"] is True


def test_policy_question_has_null_route_fields_and_the_given_retrieval():
    d = K.score_question(Q_POL, conv("p", "cortex.policy_search"), RUN, {"recall_at_5": 0.8, "ndcg_at_5": 0.7, "lexical_recall_at_5": 0.6})
    assert d["route_correct"] is None and d["expected_route"] is None and d["observed_route"] is None and d["escalated"] is None
    assert d["retrieval"]["ndcg_at_5"] == 0.7 and d["category"] == "policy_retrieval" and d["input_tokens"] == 1000


def test_a_conversation_with_two_rounds_is_unscorable():
    d = K.score_question(Q_ROUTE, conv("x", extra_round=True), RUN)
    assert d["status"] == "unscorable" and "exactly one round" in d["reason"]


def raw(qid, cid, **kw):
    return {"question_id": qid, "conversation_id": cid, "workflow_execution_id": "x1", "triggered_by": "task_manager", "change_id": "chg-1",
            "run_label": "canary-x1", "testset_version": "canary-v1", "at": "2026-11-11T06:00:00Z", **kw}


def test_score_run_writes_complete_runs_only():
    convs = {"a": conv("a", "cortex.structuring_deposits"), "b": conv("b", "cortex.escalate"), "p": conv("p", "cortex.policy_search")}
    docs, problems = K.score_run([Q_ROUTE, Q_ESC, Q_POL], [raw("c-1", "a"), raw("c-2", "b"), raw("c-3", "p")], convs.get, {"c-3": {"ndcg_at_5": 0.5}})
    assert problems == [] and [d["question_id"] for d in docs] == ["c-1", "c-2", "c-3"] and {d["change_id"] for d in docs} == {"chg-1"}
    docs, problems = K.score_run([Q_ROUTE, Q_ESC], [raw("c-1", "a"), raw("c-2", "gone")], convs.get)
    assert len(docs) == 1 and any("c-2: conversation gone unreadable" in p for p in problems)
    docs, problems = K.score_run([Q_ROUTE, Q_ESC], [raw("c-1", "a")], convs.get)
    assert any("c-2: no row" in p for p in problems)
    assert K.score_run([Q_ROUTE], [], convs.get) == ([], ["the execution wrote no rows"])


def test_an_agent_question_without_a_category_is_an_error_not_an_uncategorised_row():
    import pytest
    for bad in ({k: v for k, v in Q_ROUTE.items() if k != "category"}, dict(Q_ROUTE, category=None), dict(Q_ROUTE, category="nonsense")):
        with pytest.raises(ValueError):
            K.score_question(bad, conv("a", "cortex.structuring_deposits"), RUN)
