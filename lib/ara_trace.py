"""ara_trace.py - the trace reader (28 section 1, 6.1/6.2/6.4/6.C checks). Pure functions over span documents.

Spans are the `_source` of traces-agent_builder.otel-* documents (shape: m6/platform-recheck.md, probe 0-e): flat
`name`, `span_id`, `parent_span_id`, `trace_id`, `@timestamp` (start, ISO), `duration` (nanoseconds), `status`, and an
`attributes` object whose keys are dotted (`gen_ai.tool.name`). Nested or flat (ES|QL row) layouts both read.
Grader plumbing: no learner helper reads traces for the learner. Harness numbers never come from here (28 section 1).

    get(span, path)               one field by dotted path, flat or nested
    tree_order(spans)             spans parent-first, siblings by start time
    rounds(spans)                 trace_id -> spans
    tool_call(span)               a tool span as name, arguments, result text, outcome, status
    result_outcome(status, text)  'validation_error' | 'tool_error_in_ok_result' | 'empty_result' | 'ok'
    model_call(span)              a model span: input, cache_read, fresh (input - cache_read), output tokens
    summarize_round(spans)        spans, tool calls, model calls, tokens by type, failing and costly span
    tool_outcomes(spans)          per-tool counts: calls, errors, empty, error_in_ok
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

TITLE = "generate_title"


def get(doc: dict, path: str, default: Any = None) -> Any:
    """doc[path] when the key is stored flat, else descend, trying every dotted prefix as one key."""
    if path in doc:
        return doc[path]
    parts = path.split(".")
    for i in range(1, len(parts)):
        head = ".".join(parts[:i])
        if head in doc and isinstance(doc[head], dict):
            v = get(doc[head], ".".join(parts[i:]), _MISSING)
            if v is not _MISSING:
                return v
    return default


_MISSING = object()


def parse_ts(value: Any) -> datetime:
    """An ISO string (with Z) or epoch milliseconds -> aware UTC datetime."""
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
    s = str(value).replace("Z", "+00:00")
    d = datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def start(span: dict) -> datetime:
    return parse_ts(get(span, "@timestamp"))


def duration_ms(span: dict) -> float:
    return float(get(span, "duration", 0) or 0) / 1e6


def status(span: dict) -> str:
    s = get(span, "status")
    if isinstance(s, dict):
        s = s.get("code")
    return str(s or "Unset").capitalize()


def tree_order(spans: list[dict]) -> list[dict]:
    """Depth-first, parents before children, siblings by start time then span id (ties are deterministic)."""
    ids = {s.get("span_id") for s in spans}
    kids: dict[Any, list[dict]] = defaultdict(list)
    for s in spans:
        p = s.get("parent_span_id")
        kids[p if p in ids else None].append(s)
    out: list[dict] = []

    def walk(parent: Any) -> None:
        for s in sorted(kids.get(parent, []), key=lambda x: (start(x), str(x.get("span_id")))):
            out.append(s)
            walk(s.get("span_id"))

    walk(None)
    return out


def rounds(spans: list[dict]) -> dict[str, list[dict]]:
    by: dict[str, list[dict]] = defaultdict(list)
    for s in spans:
        by[str(s.get("trace_id"))].append(s)
    return dict(by)


def _json(text: Any) -> Any:
    if isinstance(text, (dict, list)):
        return text
    try:
        return json.loads(text) if isinstance(text, str) and text.strip() else None
    except ValueError:
        return None


_FAILED_STATES = ("failed", "error", "timed_out", "cancelled", "canceled")
_UPSTREAM_ERROR = re.compile(r"Warning: Target URL returned error [45]\d\d")   # the page reader answers 200 and says so in its text (observed, probe P1)


def _is_error(obj: Any) -> bool:
    """An error the tool hands back as its result: an error object, a failed workflow execution, an HTTP step that answered 4xx/5xx,
    or the page reader's upstream-error warning. The first, second and fourth shapes are observed: the page reader's warning text
    arrives as an Ok span (T-A recording, probe P1) and a failed workflow as an Ok span with execution.status "failed" and no `error`
    key (probe A1a). The HTTP-step status >= 400 rule is INFERRED, NOT OBSERVED: no recording or probe has shown such a step."""
    if isinstance(obj, dict):
        if obj.get("type") == "error" or isinstance(obj.get("error"), (dict, str)) and obj.get("error"):
            return True
        if str(obj.get("status", "")).lower() in _FAILED_STATES and ("workflow_id" in obj or "execution_id" in obj):
            return True
        if isinstance(obj.get("status"), int) and obj["status"] >= 400 and "statusText" in obj:
            return True
        if isinstance(obj.get("data"), str) and _UPSTREAM_ERROR.search(obj["data"]):
            return True
        return any(_is_error(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_is_error(v) for v in obj)
    return False


def _has_content(obj: Any) -> bool:
    """True when a result carries any row, resource, hit or non-empty scalar below its type tags."""
    if isinstance(obj, dict):
        return any(_has_content(v) for k, v in obj.items() if k not in ("type", "tool_result_id", "columns"))
    if isinstance(obj, list):
        return any(_has_content(v) for v in obj)
    return obj not in (None, "", 0, False)


def result_outcome(span_status: str, text: Any) -> str:
    """Classify a tool span. The platform marks a span Error when it rejects the call itself (a parameter the tool
    cannot accept, read as validation_error); a failure the tool or its workflow returns as its result sits under an Ok
    span; there is no row-count field, so an empty result is read from the result content."""
    if span_status == "Error":
        return "validation_error"
    obj = _json(text)
    if obj is None:
        return "empty_result" if not str(text or "").strip() else "ok"
    if _is_error(obj):
        return "tool_error_in_ok_result"
    return "ok" if _has_content(obj) else "empty_result"


def is_tool(span: dict) -> bool:
    return str(span.get("name", "")).startswith("execute_tool") and bool(get(span, "attributes.gen_ai.tool.name"))


def is_model(span: dict) -> bool:
    return get(span, "attributes.gen_ai.operation.name") == "chat" or str(span.get("name", "")).startswith("chat ")


def tool_call(span: dict) -> dict:
    args = get(span, "attributes.gen_ai.tool.call.arguments")
    result = get(span, "attributes.gen_ai.tool.call.result")
    st = status(span)
    return {"span_id": span.get("span_id"), "tool": get(span, "attributes.gen_ai.tool.name"),
            "arguments": _json(args) if _json(args) is not None else args,
            "result": _json(result) if _json(result) is not None else result,
            "result_chars": len(result) if isinstance(result, str) else len(json.dumps(result or "")),
            "status": st, "outcome": result_outcome(st, result), "duration_ms": duration_ms(span)}


def model_call(span: dict) -> dict:
    i = int(get(span, "attributes.gen_ai.usage.input_tokens", 0) or 0)
    c = int(get(span, "attributes.gen_ai.usage.cache_read.input_tokens", 0) or 0)
    return {"span_id": span.get("span_id"), "model": get(span, "attributes.gen_ai.response.model")
            or get(span, "attributes.gen_ai.request.model"),
            "input_tokens": i, "cache_read_tokens": c, "fresh_input_tokens": i - c,
            "output_tokens": int(get(span, "attributes.gen_ai.usage.output_tokens", 0) or 0),
            "duration_ms": duration_ms(span)}


def _under_title(span: dict, by_id: dict) -> bool:
    seen, cur = set(), span
    while cur is not None and cur.get("span_id") not in seen:
        seen.add(cur.get("span_id"))
        if str(cur.get("name")) == TITLE:
            return True
        cur = by_id.get(cur.get("parent_span_id"))
    return False


def summarize_round(spans: list[dict]) -> dict:
    """One round's trace. Title-generation model calls are reported apart (`title_tokens`) and are never the
    costly span. failing: the first tool call, in time order, whose outcome is not ok. costly: the agent's
    model call with the most input tokens, with the tool span nearest before it whose result was largest."""
    ordered = tree_order(spans)
    by_id = {s.get("span_id"): s for s in spans}
    tools = [tool_call(s) for s in sorted(spans, key=lambda x: (start(x), str(x.get("span_id")))) if is_tool(s)]
    models, title = [], {"input_tokens": 0, "cache_read_tokens": 0, "fresh_input_tokens": 0, "output_tokens": 0}
    for s in sorted(spans, key=lambda x: (start(x), str(x.get("span_id")))):
        if not is_model(s):
            continue
        m = model_call(s)
        if _under_title(s, by_id):
            for k in title:
                title[k] += m[k]
        else:
            models.append(m)
    tokens = {k: sum(m[k] for m in models) for k in ("input_tokens", "cache_read_tokens", "fresh_input_tokens", "output_tokens")}
    failing = next((t for t in tools if t["outcome"] != "ok"), None)
    costly = max(models, key=lambda m: (m["input_tokens"], -models.index(m)), default=None)
    cause = None
    if costly:
        t0 = start(by_id[costly["span_id"]])
        before = [t for t in tools if start(by_id[t["span_id"]]) <= t0]
        big = max(before, key=lambda t: t["result_chars"], default=None)
        cause = {"span_id": big["span_id"], "tool": big["tool"], "result_chars": big["result_chars"]} if big else None
    calls = Counter((t["tool"], json.dumps(t["arguments"], sort_keys=True, default=str)) for t in tools)
    root = next((s for s in ordered if not s.get("parent_span_id")), ordered[0] if ordered else {})
    return {"trace_id": root.get("trace_id"), "conversation_id": get(root, "attributes.gen_ai.conversation.id"),
            "span_count": len(spans), "span_order": [s.get("span_id") for s in ordered],
            "duration_ms": duration_ms(root) if root else 0.0, "tool_calls": tools, "model_calls": models,
            "tokens": tokens, "title_tokens": title,
            "failing": failing, "costly": costly, "costly_preceding_tool": cause,
            "repeated_calls": {f"{k[0]} {k[1]}": n for k, n in calls.items() if n > 1}}


def tool_outcomes(spans: list[dict]) -> dict[str, dict]:
    """Per tool over a window: calls, errors (status Error), empty results, error objects inside Ok results."""
    out: dict[str, Counter] = defaultdict(Counter)
    for s in spans:
        if not is_tool(s):
            continue
        t = tool_call(s)
        c = out[t["tool"]]
        c["calls"] += 1
        c["errors"] += t["outcome"] == "validation_error"
        c["empty"] += t["outcome"] == "empty_result"
        c["error_in_ok"] += t["outcome"] == "tool_error_in_ok_result"
    return {k: {"calls": v["calls"], "errors": v["errors"], "empty": v["empty"], "error_in_ok": v["error_in_ok"]}
            for k, v in sorted(out.items())}


def join_run_record(record: dict, spans: list[dict]) -> list[dict]:
    """The spans of a run record's round: by trace_id (P5), else by the conversation id (includeRealIds on)."""
    tid = record.get("trace_id")
    if tid:
        return [s for s in spans if s.get("trace_id") == tid]
    cid = record.get("conversation_id")
    return [s for s in spans if cid and get(s, "attributes.gen_ai.conversation.id") == cid]
