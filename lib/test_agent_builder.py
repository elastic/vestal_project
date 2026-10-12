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
