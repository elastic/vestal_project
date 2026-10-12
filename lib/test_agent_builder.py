"""Offline tests for agent_builder.py and ara_behavior.py (kit item 3, route-record fixtures).

The converse and _execute shapes are the ones the Phase 0 probes recorded (probe-ab r1,
yvpv67cnqr2g): steps[] of tool_call entries with tool_id, params and results; ES|QL results as
type esql_results with columns and values; a Workflow tool result carrying data.execution.
"""
from __future__ import annotations

import json
import pathlib
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import agent_builder as A  # noqa: E402
import ara_behavior as B  # noqa: E402

CONVERSE = {
    "conversation_id": "c1", "trace_id": "t1",
    "steps": [
        {"type": "reasoning", "reasoning": "..."},
        {"type": "tool_call", "tool_id": "write_todos", "params": {}, "results": []},
        {"type": "tool_call", "tool_id": "cortex.structuring_deposits",
         "params": {"account_id": "476", "lookback_days": 7},
         "results": [{"type": "query", "data": {}}, {"type": "esql_results",
                     "data": {"columns": [{"name": "event_id"}], "values": [["wt-000008"]]}}]},
        {"type": "tool_call", "tool_id": "platform.core.search", "params": {}, "results": []},
        {"type": "tool_call", "tool_id": "cortex.open_case",
         "params": {"account_id": "476", "pattern": "structuring", "findings": "x"},
         "results": [{"type": "other", "data": {"execution": {"execution_id": "e1", "status": "completed"}}}]},
    ],
    "response": {"message": "never graded"},
}


def test_route_record_filters_internal_and_reads_execution():
    rec = A.route_record(CONVERSE)
    assert [c["tool_id"] for c in rec] == ["cortex.structuring_deposits", "cortex.open_case"]
    assert rec[0]["ok"] and rec[0]["params"]["account_id"] == "476"
    assert rec[1]["execution_id"] == "e1" and rec[1]["execution_status"] == "completed"
    assert A.internal_calls(CONVERSE) == ["write_todos", "platform.core.search"]


def test_literal_equal():
    assert A.literal_equal("1981", 1981) and A.literal_equal(7, "7") and A.literal_equal(7, 7.0)
    assert not A.literal_equal("1981", "19810") and not A.literal_equal(7, "seven")
    assert A.literal_equal("structuring", " structuring ")


def test_route_matches_order_literals_forbid():
    rec = A.route_record(CONVERSE)
    ok, _ = A.route_matches([{"tool_id": "cortex.structuring_deposits", "params": {"account_id": "476", "lookback_days": 7}}], rec)
    assert ok
    ok, why = A.route_matches([{"tool_id": "cortex.structuring_deposits", "params": {"lookback_days": 3}}], rec)
    assert not ok and "expected" in why
    ok, why = A.route_matches([{"tool_id": "cortex.open_case"}], rec, forbid=["cortex.structuring_deposits"])
    assert not ok and why == "called cortex.structuring_deposits"
    ok, _ = A.route_matches([{"tool_id": "cortex.open_case"}, {"tool_id": "cortex.structuring_deposits"}], rec)
    assert not ok  # order matters
    ok, why = A.route_matches([{"tool_id": "cortex.policy_search"}], [])
    assert not ok and "no tool" in why


def test_esql_rows_and_error():
    body = {"results": CONVERSE["steps"][2]["results"]}
    cols, rows = A.esql_rows(body)
    assert cols == ["event_id"] and rows == [["wt-000008"]]
    assert A.esql_rows({"results": [{"type": "error", "data": {"message": "bad query"}}]}) is None
    assert A.error_text({"results": [{"type": "error", "data": {"message": "bad query"}}]}) == "bad query"


class _Handler(BaseHTTPRequestHandler):
    status = 200
    calls = 0

    def do_POST(self):
        type(self).calls += 1
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        assert body.get("connector_id") == "conn-x"
        out = json.dumps(CONVERSE).encode()
        self.send_response(type(self).status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(out if type(self).status == 200 else b'{"error":"x"}')

    def log_message(self, *a):
        pass


def _server(status):
    _Handler.status, _Handler.calls = status, 0
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_run_cases_pass_and_outage():
    srv = _server(200)
    ab = A.AB(f"http://127.0.0.1:{srv.server_port}", "k", "conn-x", timeout=5)
    cases = [{"id": "a", "input": "q", "expected": [{"tool_id": "cortex.structuring_deposits", "params": {"account_id": "476"}}]},
             {"id": "b", "input": "q", "expected": [{"tool_id": "cortex.policy_search"}]}]
    res = B.run_cases(ab, "tina-compliance", cases, concurrency=2)
    assert [r["passed"] for r in res] == [True, False] and not any(r.get("error") for r in res)
    srv.shutdown()
    srv = _server(503)
    ab = A.AB(f"http://127.0.0.1:{srv.server_port}", "k", "conn-x", timeout=5)
    res = B.run_cases(ab, "tina-compliance", cases[:1], concurrency=1)
    assert res[0]["error"] and not res[0]["passed"] and _Handler.calls == 2  # retried once, never credited
    srv.shutdown()


def test_converse_requires_connector():
    try:
        A.AB("http://x", "k", None).converse("a", "q")
    except ValueError:
        return
    raise AssertionError("converse ran without a connector")


def test_outage_is_ara_grade_outage():
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    import ara_grade
    assert ara_grade.is_outage(A.ABError("x", 503)) and ara_grade.is_outage(A.RemoteCallFailed("x"))
    assert not ara_grade.is_outage(A.ABError("x", 400))


def _span(sid, parent, name, ts, agent=None, tool=None, args=None, status="Ok"):
    a = {}
    if agent:
        a["gen_ai.agent.id"] = agent
    if tool:
        a["gen_ai.tool.name"] = tool
    if args is not None:
        a["gen_ai.tool.call.arguments"] = json.dumps(args)
    return {"span_id": sid, "parent_span_id": parent, "name": name, "@timestamp": ts, "attributes": a,
            "status": {"code": status}}


def test_delegation_route_from_steps_and_trace():
    # shapes from probe-42 r1: run_subagent in converse steps, the specialist's calls only in spans
    resp = {"steps": [
        {"type": "tool_call", "tool_id": "write_todos", "tool_origin": "internal", "params": {}, "results": [{"type": "other"}]},
        {"type": "tool_call", "tool_id": "run_subagent", "tool_origin": "internal",
         "params": {"agent_id": "cortex-securities-irregularities", "prompt": "..."}, "results": [{"type": "other", "data": {}}]}]}
    rec = A.route_record(resp)
    assert [c["tool_id"] for c in rec] == ["run_subagent"] and A.internal_calls(resp) == ["write_todos"]
    spans = [_span("r", None, "invoke_agent Tina", "1", agent="tina-compliance"),
             _span("a", "r", "invoke_agent Tina", "2", agent="tina-compliance"),
             _span("d", "a", "execute_tool run_subagent", "3", tool="run_subagent", args={"agent_id": "x"}),
             _span("s", "d", "invoke_agent Securities", "4", agent="cortex-securities-irregularities"),
             _span("t1", "s", "execute_tool cortex.wash_trading", "5", tool="cortex.wash_trading", args={"lookback_days": 7}),
             _span("t2", "s", "execute_tool attachments.add", "6", tool="attachments.add", args={}),
             _span("t3", "s", "execute_tool cortex.unexplained_wealth", "7", tool="cortex.unexplained_wealth",
                   args={"account_id": "4096", "lookback_days": 30}, status="Error"),
             _span("c1", "a", "execute_tool cortex.structuring_deposits", "8", tool="cortex.structuring_deposits", args={})]
    deleg = A.trace_calls(spans, "tina-compliance")
    assert [(c["tool_id"], c["agent_id"], c["ok"]) for c in deleg] == [
        ("cortex.wash_trading", "cortex-securities-irregularities", True),
        ("cortex.unexplained_wealth", "cortex-securities-irregularities", False)]
    full = A.splice_delegated(rec, deleg)
    want = [{"tool_id": "run_subagent", "params": {"agent_id": "cortex-securities-irregularities"}},
            {"tool_id": "cortex.unexplained_wealth", "agent_id": "cortex-securities-irregularities", "params": {"account_id": 4096}}]
    assert A.route_matches(want, full) == (True, "route matches")
    # the same tool called by the coordinator itself does not satisfy a delegated expectation
    direct = [{"tool_id": "cortex.unexplained_wealth", "params": {"account_id": "4096"}, "agent_id": None}]
    assert not A.route_matches(want[1:], direct)[0]
    # a coordinator-owned case forbids delegation
    assert A.route_matches([], full, forbid=["run_subagent"]) == (False, "called run_subagent")


LIB = str(pathlib.Path(__file__).resolve().parent)


def _runner(tmp_path, record, body: str = "") -> list[str]:
    """A runner that publishes {fingerprint, started, outage?} after an optional delay (env SLEEP)."""
    src = tmp_path / "runner.py"
    src.write_text(
        "import os, sys, time, pathlib\n"
        f"sys.path.insert(0, {LIB!r})\n"
        "import ara_behavior as B\n"
        "fp, started = sys.argv[1], float(sys.argv[2])\n"
        "time.sleep(float(os.environ.get('SLEEP', '0')))\n"
        "if os.path.exists(os.environ.get('DIE', '/nonexistent')):\n"
        "    sys.exit(3)\n"
        "outage = 'Kibana down' if os.path.exists(os.environ['FLAG']) else None\n"
        + body +
        f"B.publish(pathlib.Path({str(record)!r}), {{'fingerprint': fp, 'started': started, 'outage': outage}})\n")
    return [sys.executable, str(src)]


def test_ensure_run_outage_once_then_fresh(tmp_path, monkeypatch):
    # D-15 and R-P8: an outage record is returned once (the check says no grade) and the next call
    # measures again; a finished good record is reused while the fingerprint holds.
    monkeypatch.setenv("ARA_BEHAVIOR_LOG", str(tmp_path / "log"))
    record = tmp_path / "rec.json"
    flag = tmp_path / "flag"
    monkeypatch.setenv("FLAG", str(flag))
    runner = _runner(tmp_path, record)
    flag.write_text("1")
    rec, _ = B.ensure_run(record, "fp1", runner, wait_s=10, poll_s=0.1)
    assert rec and rec["outage"] == "Kibana down"
    flag.unlink()
    rec2, _ = B.ensure_run(record, "fp1", runner, wait_s=10, poll_s=0.1)
    assert rec2 and rec2["outage"] is None and rec2["started"] > rec["started"]
    rec3, _ = B.ensure_run(record, "fp1", runner, wait_s=0.5, poll_s=0.1)
    assert rec3 == rec2


def test_ensure_run_consume_measures_again(tmp_path, monkeypatch):
    monkeypatch.setenv("ARA_BEHAVIOR_LOG", str(tmp_path / "log"))
    monkeypatch.setenv("FLAG", str(tmp_path / "noflag"))
    record = tmp_path / "rec.json"
    runner = _runner(tmp_path, record)
    rec, _ = B.ensure_run(record, "fp1", runner, wait_s=10, poll_s=0.1)
    B.consume(record, "fp1")  # graded and failed: never graded again
    rec2, _ = B.ensure_run(record, "fp1", runner, wait_s=10, poll_s=0.1)
    assert rec2 and rec2["started"] > rec["started"]


def test_ensure_run_kills_superseded_run_and_guards_its_write(tmp_path, monkeypatch):
    monkeypatch.setenv("ARA_BEHAVIOR_LOG", str(tmp_path / "log"))
    monkeypatch.setenv("FLAG", str(tmp_path / "noflag"))
    record = tmp_path / "rec.json"
    runner = _runner(tmp_path, record)
    monkeypatch.setenv("SLEEP", "30")
    rec, _ = B.ensure_run(record, "fp1", runner, wait_s=0.5, poll_s=0.1)
    assert rec is None
    st1 = json.loads(record.with_suffix(".start").read_text())
    assert B._alive(st1)
    monkeypatch.setenv("SLEEP", "0")
    rec2, _ = B.ensure_run(record, "fp2", runner, wait_s=10, poll_s=0.1)
    assert rec2 and rec2["fingerprint"] == "fp2"
    assert not B._alive(st1)  # the fp1 run was killed when fp2 started
    # a late write from a superseded run is refused
    assert not B.publish(record, {"fingerprint": "fp1", "started": st1["started"], "outage": None})
    assert json.loads(record.read_text())["fingerprint"] == "fp2"


def test_ensure_run_restarts_a_dead_run(tmp_path, monkeypatch):
    monkeypatch.setenv("ARA_BEHAVIOR_LOG", str(tmp_path / "log"))
    monkeypatch.setenv("FLAG", str(tmp_path / "noflag"))
    die = tmp_path / "die"
    monkeypatch.setenv("DIE", str(die))
    record = tmp_path / "rec.json"
    runner = _runner(tmp_path, record)
    die.write_text("1")
    rec, _ = B.ensure_run(record, "fp1", runner, wait_s=0.2, poll_s=0.05)
    assert rec is None
    time_limit = 50
    while B._alive(json.loads(record.with_suffix(".start").read_text())) and time_limit:
        import time as _t
        _t.sleep(0.1)
        time_limit -= 1
    die.unlink()
    rec2, _ = B.ensure_run(record, "fp1", runner, wait_s=10, poll_s=0.1)
    assert rec2 and rec2["outage"] is None  # the dead run was detected and started again


def test_poll_spans_incomplete_trace_is_an_outage():
    import ara_grade
    try:
        B.poll_spans(lambda t: [{"span_id": "a", "parent_span_id": "r"}], "t", budget_s=0.3, poll_s=0.1)
    except B.TraceNotReady as e:
        assert ara_grade.is_outage(e)
        return
    raise AssertionError("an unrooted trace was returned as complete")


class _H4(BaseHTTPRequestHandler):
    deleted: list = []

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(n)
        self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"message":"agent tina-compliance not found"}')

    def do_DELETE(self):
        type(self).deleted.append(self.path)
        self.send_response(200)
        self.end_headers()

    def log_message(self, *a):
        pass


def test_run_case_4xx_is_a_learner_miss_and_cleanup_deletes():
    srv = HTTPServer(("127.0.0.1", 0), _H4)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    ab = A.AB(f"http://127.0.0.1:{srv.server_port}", "k", "conn-x", timeout=5)
    r = B.run_case(ab, "tina-compliance", {"id": "a", "input": "q", "expected": [{"tool_id": "x"}]})
    assert not r["passed"] and r.get("learner_error") and not r.get("error") and "refused" in r["reason"]
    srv.shutdown()
    srv = _server(200)
    ab = A.AB(f"http://127.0.0.1:{srv.server_port}", "k", "conn-x", timeout=5)
    deleted = []
    ab.delete_conversation = lambda cid: deleted.append(cid) or 200
    r = B.run_case(ab, "tina-compliance", {"id": "a", "input": "q", "expected": []})
    assert r["conversation_deleted"] and deleted == ["c1"]
    r = B.run_case(ab, "tina-compliance", {"id": "a", "input": "q", "expected": []}, cleanup=False)
    assert "conversation_deleted" not in r and deleted == ["c1"]
    srv.shutdown()


def test_run_outcome_env_and_learner():
    assert A.run_outcome(None)["kind"] == "env"
    assert A.run_outcome({"status": "completed"})["kind"] == "completed"
    assert A.run_outcome({"status": "running"})["kind"] == "env"
    assert A.run_outcome({"status": "waiting_for_input"})["kind"] == "env"
    assert A.run_outcome({"status": "timed_out"})["kind"] == "env"
    fail_429 = {"status": "failed", "stepExecutions": [{"stepId": "rate", "status": "failed",
                                                        "error": "Inference failed: status code 429"}]}
    assert A.run_outcome(fail_429)["kind"] == "env"
    bad = {"status": "failed", "stepExecutions": [{"stepId": "write", "status": "failed",
                                                   "error": "mapper_parsing_exception: failed to parse field [created_at]"}]}
    out = A.run_outcome(bad)
    assert out["kind"] == "learner" and out["step"] == "write" and "mapper_parsing" in out["error"]


def test_env_err_is_narrow():
    """Review F-2: the learner's own errors stay the learner's; real outages stay outages."""
    learner = [
        "line 1:507: mismatched input 'BY' expecting {<EOF>, '|', ','}",       # ES|QL parse position
        "line 3:500: Unknown column [lookback_timeout]",
        "verification_exception: Unknown column [request_timeout_ms]",
        "Unknown field [timeout_s] in step with",
        "mapper_parsing_exception: failed to parse field [amount] of type [float]: '508'",
        "ConnectorExecutionError [401] Invalid API key",
        "index_not_found_exception: no such index [cortex-fraud-cases-500]",
        "verification_exception: Unknown column [timeout]",                      # a field the learner named
        "Unknown input `timeout` in step read",
        "unknown setting [index.search.timeout_ms]",
        "TimeoutErrors_total is not a column",
        "fetch_failed_count is not a column",
        "rejected_execution_count is not a column",
        "circuit_breaking_total is not a column",
        "ECONNABORTEDX is not a code",
    ]
    env = [
        "Inference failed: status code 429",
        "Request failed with status code 503",
        "HTTP 502 from the inference endpoint",
        "ConnectorExecutionError [429] Too Many Requests",
        "503 Service Unavailable",
        "connect ECONNREFUSED 10.0.0.1:443",
        "The request timed out",
        "timeout of 30000ms exceeded",
        "socket hang up",
        "Rate limit exceeded for the model",
        "statusCode: 500",
        "504 Gateway Time-out",                                                  # Review R2-1
        "<center><h1>504 Gateway Time-out</h1></center>",
        "gateway timeout",
        "TimeoutError: The operation was aborted due to timeout",
        "Request aborted: timeout",
        "Timeout waiting for task.",
        '{"error":"timeout"}',
        "Error: ECONNABORTED",
        "TypeError: fetch failed",
        "es_rejected_execution_exception: rejected execution of coordinating operation",
        "circuit_breaking_exception: [parent] Data too large",
    ]
    for text in learner:
        assert not A.ENV_ERR.search(text), text
    for text in env:
        assert A.ENV_ERR.search(text), text
    parse = {"status": "failed", "stepExecutions": [{"stepId": "detect", "status": "failed", "error": learner[0]}]}
    assert A.run_outcome(parse)["kind"] == "learner"
