"""Offline tests for ara_eval_run.py with a fake Agent Builder client."""
from __future__ import annotations

import pathlib
import sys
import threading

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import agent_builder as A  # noqa: E402
import ara_eval_run as H  # noqa: E402


def resp(*tools, trace="t1", ask=False, text="ok"):
    steps = [{"type": "tool_call", "tool_id": t, "params": p, "results": []} for t, p in tools]
    if ask:
        steps.append({"type": "ask_user_question"})
    return {"conversation_id": "c-" + text, "trace_id": trace, "steps": steps, "response": {"message": text},
            "model_usage": {"input_tokens": 1000, "cached_input_tokens": 400, "output_tokens": 50, "llm_calls": 2}}


class Fake:
    def __init__(self, script):
        self.script, self.calls, self.lock, self.deleted = script, {}, threading.Lock(), []

    def converse_timed(self, agent_id, text):
        with self.lock:
            n = self.calls[text] = self.calls.get(text, 0) + 1
        r = self.script[text]
        step = r[min(n, len(r)) - 1] if isinstance(r, list) else r
        if isinstance(step, Exception):
            raise step
        return step, 1200

    def delete_conversation(self, cid):
        self.deleted.append(cid)


POOL = H.load_pool({"questions": [
    {"id": "q1", "type": "agent", "input": "dep 476", "expected": [{"tool_id": "cortex.structuring_deposits", "params": {"account_id": "476"}}]},
    {"id": "q2", "type": "policy", "input": "policy?", "expected": [{"tool_id": "cortex.policy_search"}]},
    {"id": "q3", "type": "agent", "input": "open a case", "expect_ask": True, "expected": [], "forbid": ["cortex.open_case"]},
    {"id": "q4", "type": "agent", "input": "both", "ordering": "any",
     "expected": [{"tool_id": "cortex.policy_search"}, {"tool_id": "cortex.sar_search"}]}]})
TS = [{"question_id": q, "category": "straightforward"} for q in ("q1", "q2", "q3", "q4")]
KEY = {"q1": "straightforward", "q2": "ambiguous", "q3": "ambiguous", "q4": "cross_domain"}
GOOD = {"dep 476": resp(("cortex.structuring_deposits", {"account_id": "476"})),
        "policy?": resp(("cortex.policy_search", {})),
        "open a case": resp(ask=True, text="Which account?"),
        "both": resp(("cortex.sar_search", {}), ("cortex.policy_search", {}))}
NOSLEEP = dict(sleep=lambda s: None)


def test_run_records_route_match_usage_and_trace():
    seen = []
    recs = H.run_testset(Fake(GOOD), "tina", TS, POOL, KEY, concurrency=2, writer=seen.append, **NOSLEEP)
    assert [r["question_id"] for r in recs] == ["q1", "q2", "q3", "q4"]
    assert all(r["status"] == "graded" and r["matched"] for r in recs)
    assert len(seen) == 4
    r = recs[0]
    assert r["trace_id"] == "t1" and r["input_tokens"] == 1000 and r["cached_input_tokens"] == 400
    assert r["fresh_input_tokens"] == 600 and r["output_tokens"] == 50 and r["latency_ms"] == 1200
    assert r["category"] == "straightforward" and recs[1]["category"] == "ambiguous"
    assert recs[1]["label_category"] == "straightforward"  # the learner's label is kept apart from the key's
    assert H.exit_code(recs) == 0


def test_a_wrong_route_is_graded_false_not_unreachable():
    bad = dict(GOOD, **{"dep 476": resp(("cortex.policy_search", {}))})
    recs = H.run_testset(Fake(bad), "tina", TS, POOL, KEY, **NOSLEEP)
    assert recs[0]["status"] == "graded" and recs[0]["matched"] is False
    assert H.summarize(recs, KEY)["routing_accuracy"]["straightforward"] == 0.0


def test_outage_retried_then_succeeds():
    script = dict(GOOD, **{"policy?": [A.ABError("503", 503), A.RemoteCallFailed("timeout"), GOOD["policy?"]]})
    f = Fake(script)
    recs = H.run_testset(f, "tina", TS, POOL, KEY, **NOSLEEP)
    assert recs[1]["status"] == "graded" and recs[1]["matched"] and f.calls["policy?"] == 3


def test_outage_after_retries_is_never_graded_and_exit_code_says_so():
    script = dict(GOOD, **{"policy?": A.ABError("429", 429)})
    f = Fake(script)
    recs = H.run_testset(f, "tina", TS, POOL, KEY, **NOSLEEP)
    r = recs[1]
    assert f.calls["policy?"] == 3 and r["status"] == "unreachable" and r["matched"] is None and r["route_correct"] is None
    s = H.summarize(recs, KEY)
    assert s["ungraded"] == 1 and s["unreachable"] == 1 and s["routing_accuracy"]["ambiguous"] == 1.0  # q3 only
    assert H.exit_code(recs) == H.EXIT_NO_GRADE


def test_4xx_is_refused_not_retried_and_faults_are_ours():
    f = Fake(dict(GOOD, **{"dep 476": ValueError("converse tina: HTTP 400 bad agent"), "policy?": RuntimeError("boom")}))
    recs = H.run_testset(f, "tina", TS, POOL, KEY, **NOSLEEP)
    assert recs[0]["status"] == "refused" and f.calls["dep 476"] == 1 and recs[0]["matched"] is None
    assert recs[1]["status"] == "error" and f.calls["policy?"] == 1


def test_unknown_question_id_is_an_error_record():
    recs = H.run_testset(Fake(GOOD), "tina", [{"question_id": "nope"}], POOL, KEY, **NOSLEEP)
    assert recs[0]["status"] == "error" and H.exit_code(recs) == H.EXIT_NO_GRADE


def test_a_route_cut_at_the_delegation_is_graded_on_the_coordinators_calls_without_the_trace():
    pool = H.load_pool([{"id": "s", "type": "agent", "input": "sec", "forbid": ["cortex.open_case"], "expected": [
        {"tool_id": "run_subagent", "params": {"agent_id": "cortex-securities-irregularities"}}]}])
    r = resp(("run_subagent", {"agent_id": "cortex-securities-irregularities"}))

    def broken(fetch, tid):
        raise AssertionError("the trace must not be read for a route cut at the delegation")
    out = H.run_testset(Fake({"sec": r}), "tina", [{"question_id": "s"}], pool, spans=lambda t: [], poll=broken, **NOSLEEP)
    assert out[0]["status"] == "graded" and out[0]["matched"]


def test_delegated_route_needs_the_trace_and_an_incomplete_trace_is_no_grade():
    pool = H.load_pool([{"id": "s", "type": "agent", "input": "sec", "expected": [
        {"tool_id": "run_subagent", "params": {"agent_id": "cortex-securities-irregularities"}},
        {"tool_id": "cortex.wash_trading", "agent_id": "cortex-securities-irregularities"}]}])
    r = resp(("run_subagent", {"agent_id": "cortex-securities-irregularities"}))

    def broken(fetch, tid):
        raise A.ABError("trace incomplete", 503)
    out = H.run_testset(Fake({"sec": r}), "tina", [{"question_id": "s"}], pool, spans=lambda t: [], poll=broken, **NOSLEEP)
    assert out[0]["status"] == "unreachable"
    ok = H.run_testset(Fake({"sec": r}), "tina", [{"question_id": "s"}], pool, spans=lambda t: [], poll=lambda f, t: [], **NOSLEEP)
    assert ok[0]["status"] == "graded" and not ok[0]["matched"]  # the trace was read; the specialist made no call


def test_cleanup_deletes_conversations_and_aggregates_accepts_the_records():
    import ara_eval as E
    f = Fake(GOOD)
    recs = H.run_testset(f, "tina", TS, POOL, KEY, cleanup=True, **NOSLEEP)
    assert len(f.deleted) == 4
    agg = E.aggregates(recs)
    assert agg["questions"] == 4 and agg["routing_accuracy_overall"] == 100.0


def test_jsonl_writer_and_args(tmp_path):
    p = str(tmp_path / "runs.jsonl")
    w = H.jsonl_writer(p)
    H.run_testset(Fake(GOOD), "tina", TS[:2], POOL, KEY, writer=w, **NOSLEEP)
    assert len(open(p).read().splitlines()) == 2
    a = H.parse_args(["--agent", "tina-eval", "--testset", "t.json", "--concurrency", "2"])
    assert (a.agent, a.testset, a.concurrency, a.pool) == ("tina-eval", "t.json", 2, None)
