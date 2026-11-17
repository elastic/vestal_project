"""Offline tests for ara_trace.py on synthetic spans shaped like the probe's (platform-recheck 0-e)."""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ara_trace as T  # noqa: E402


def span(sid, name, parent, t_ms, dur_ms, trace="t1", status=None, **attrs):
    d = {"@timestamp": f"2026-11-01T10:00:{t_ms // 1000:02d}.{t_ms % 1000:03d}Z", "trace_id": trace, "span_id": sid,
         "name": name, "duration": int(dur_ms * 1e6), "attributes": attrs}
    if parent:
        d["parent_span_id"] = parent
    if status:
        d["status"] = {"code": status}
    return d


def tool(sid, parent, t, tool_id, args, result, status=None, trace="t1"):
    return span(sid, f"execute_tool {tool_id}", parent, t, 300, trace, status, **{
        "gen_ai.tool.name": tool_id, "gen_ai.tool.call.arguments": json.dumps(args),
        "gen_ai.tool.call.result": result if isinstance(result, str) else json.dumps(result)})


def llm(sid, parent, t, inp, cache, out, trace="t1", model="m-main"):
    return span(sid, f"chat {model}", parent, t, 900, trace, **{
        "gen_ai.operation.name": "chat", "gen_ai.response.model": model, "gen_ai.usage.input_tokens": inp,
        "gen_ai.usage.cache_read.input_tokens": cache, "gen_ai.usage.output_tokens": out})


BIG = {"results": [{"type": "other", "data": {"resources": [{"content": "x" * 5000}]}}]}


def round_a():
    return [
        span("a0", "invoke_agent Tina", None, 0, 10000, **{"gen_ai.agent.id": "tina-compliance", "gen_ai.conversation.id": "c-1"}),
        span("a1", "generate_title", "a0", 10, 500),
        llm("a2", "a1", 20, 300, 0, 10, model="m-flash"),
        llm("a3", "a0", 1000, 2000, 1500, 100),
        tool("a4", "a0", 2000, "cortex.case_correspondence", {"case_id": "C1"}, BIG),
        llm("a5", "a0", 3000, 9000, 2000, 400),
        tool("a6", "a0", 4000, "cortex.read_page", {"url": "u"}, {"results": [{"type": "error", "data": {"message": "boom"}}]}),
        tool("a7", "a0", 5000, "cortex.sar_search", {"q": "x"}, {"results": [{"type": "esql_results", "data": {"columns": [], "values": []}}]}),
        tool("a8", "a0", 6000, "cortex.case_lookup", {"bad": 1}, "invalid parameter", status="Error"),
        llm("a9", "a0", 7000, 1000, 1000, 50),
    ]


def test_get_flat_and_nested():
    s = {"attributes": {"gen_ai.tool.name": "t"}, "a": {"b": {"c": 1}}}
    assert T.get(s, "attributes.gen_ai.tool.name") == "t" and T.get(s, "a.b.c") == 1
    assert T.get({"attributes.gen_ai.tool.name": "f"}, "attributes.gen_ai.tool.name") == "f"
    assert T.get(s, "nope", 7) == 7


def test_tree_order_parents_first_and_orphans_are_roots():
    order = [s["span_id"] for s in T.tree_order(round_a())]
    assert order[0] == "a0" and order.index("a1") < order.index("a2") and len(order) == 10
    assert T.tree_order([span("x", "n", "gone", 0, 1)])[0]["span_id"] == "x"


def test_outcomes_follow_the_traps():
    assert T.result_outcome("Error", "bad") == "validation_error"
    assert T.result_outcome("Ok", json.dumps({"results": [{"type": "error", "data": {"message": "m"}}]})) == "tool_error_in_ok_result"
    assert T.result_outcome("Ok", json.dumps({"results": [{"type": "esql_results", "data": {"columns": [{"name": "a"}], "values": []}}]})) == "empty_result"
    assert T.result_outcome("Ok", json.dumps({"results": [{"type": "esql_results", "data": {"columns": [], "values": [[1]]}}]})) == "ok"
    assert T.result_outcome("Ok", "") == "empty_result" and T.result_outcome("Ok", "plain text") == "ok"


def test_round_summary():
    r = T.summarize_round(round_a())
    assert r["trace_id"] == "t1" and r["conversation_id"] == "c-1" and r["span_count"] == 10
    assert [t["tool"] for t in r["tool_calls"]] == ["cortex.case_correspondence", "cortex.read_page", "cortex.sar_search", "cortex.case_lookup"]
    assert r["tool_calls"][0]["arguments"] == {"case_id": "C1"}
    # tokens by type, title call apart; fresh = input - cache_read
    assert r["tokens"] == {"input_tokens": 12000, "cache_read_tokens": 4500, "fresh_input_tokens": 7500, "output_tokens": 550}
    assert r["title_tokens"]["input_tokens"] == 300
    assert r["failing"]["span_id"] == "a6" and r["failing"]["outcome"] == "tool_error_in_ok_result"
    assert r["costly"]["span_id"] == "a5" and r["costly"]["input_tokens"] == 9000 and r["costly"]["fresh_input_tokens"] == 7000
    assert r["costly_preceding_tool"]["span_id"] == "a4"
    assert r["duration_ms"] == 10000.0


def test_failing_none_when_all_ok_and_repeats_found():
    spans = [span("r", "invoke_agent Tina", None, 0, 100), llm("m", "r", 1, 10, 0, 1)]
    ok = {"results": [{"type": "x", "data": {"v": [1]}}]}
    for i in range(3):
        spans.append(tool(f"p{i}", "r", 10 + i, "cortex.policy_search", {"q": "same"}, ok))
    r = T.summarize_round(spans)
    assert r["failing"] is None and list(r["repeated_calls"].values()) == [3]


def test_tool_outcomes_and_grouping_and_join():
    spans = round_a() + [tool("b1", None, 0, "cortex.sar_search", {}, {"results": []}, trace="t2")]
    assert set(T.rounds(spans)) == {"t1", "t2"}
    o = T.tool_outcomes(spans)
    assert o["cortex.sar_search"] == {"calls": 2, "errors": 0, "empty": 2, "error_in_ok": 0}
    assert o["cortex.case_lookup"]["errors"] == 1 and o["cortex.read_page"]["error_in_ok"] == 1
    assert len(T.join_run_record({"trace_id": "t2"}, spans)) == 1
    assert len(T.join_run_record({"conversation_id": "c-1"}, spans)) == 1
    assert T.join_run_record({}, spans) == []


def test_timestamp_formats():
    assert T.parse_ts("2026-11-01T10:00:00.500Z") == T.parse_ts(1793527200500)
