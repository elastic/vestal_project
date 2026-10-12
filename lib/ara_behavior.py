"""ara_behavior.py - run a question set through an agent and grade each route (22 section 1).

Shared by the BEHAVIOR checks (held-out sets, root, tina-runtime key) and by ara-ab-behavior.py,
the learner's dev helper. A case is

    {"id": "b1-03", "input": "...", "expected": [{"tool_id": "cortex.x", "params": {"account_id": "476"}}],
     "forbid": ["cortex.y"]}

and is graded on its route and structured literals only (09 section 5a): never on answer text.

A case whose converse call gets no usable answer is retried while the budget allows. If it still
has none, its result carries "error" and the caller must not grade the set: a failed remote call is
never credited and never dropped (R-P8). The checks turn that into ara_grade.unreachable().
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

from agent_builder import (AB, ABError, internal_calls, route_matches, route_record, splice_delegated,
                           trace_calls)

TRACE_BUDGET_S = 30  # 22 section 1: sub-agent calls are read from traces, polling up to 30 s


def poll_spans(fetch, trace_id: str, budget_s: float = TRACE_BUDGET_S, poll_s: float = 2.0) -> list[dict]:
    """All spans of one trace once they stop arriving: the root span is present and two reads in a
    row return the same count (probe-42: complete 5 to 10 s after converse returned). fetch(trace_id)
    returns the span documents; an outage in it raises and is the caller's to handle."""
    end = time.monotonic() + budget_s
    last_n, spans = -1, []
    while True:
        spans = fetch(trace_id) or []
        rooted = any(not sp.get("parent_span_id") for sp in spans)
        if rooted and len(spans) == last_n:
            return spans
        last_n = len(spans)
        if time.monotonic() + poll_s > end:
            return spans
        time.sleep(poll_s)


def run_case(ab: AB, agent_id: str, case: dict, deadline_at: float | None = None, attempts: int = 2,
             spans=None) -> dict:
    """One case. spans, when given, is fetch(trace_id) -> span documents: a route that delegates
    (run_subagent) then gets the specialist's own calls spliced in from the trace."""
    t0 = time.monotonic()
    last = None
    for attempt in range(attempts):
        try:
            resp = ab.converse(agent_id, case["input"])
            record = route_record(resp)
            if spans is not None and resp.get("trace_id") and any(c["tool_id"] == "run_subagent" for c in record):
                record = splice_delegated(record, trace_calls(poll_spans(spans, resp["trace_id"]), agent_id))
            ok, reason = route_matches(case.get("expected") or [], record, case.get("forbid") or [])
            if not ok and not record and any(s.get("type") == "ask_user_question" for s in resp.get("steps") or []):
                # t4c-probe1: on a request with no account, Tina asked the analyst a question instead of acting
                reason = (f"expected {(case.get('expected') or [{}])[0].get('tool_id')}, but Tina asked the analyst "
                          "a question instead of calling a tool")
            return {"id": case["id"], "passed": ok, "reason": reason, "route": record,
                    "internal": internal_calls(resp), "conversation_id": resp.get("conversation_id"),
                    "trace_id": resp.get("trace_id"), "seconds": round(time.monotonic() - t0, 1)}
        except ABError as e:
            last = e
            # another attempt needs at least one typical converse (about 20 s) before the deadline
            if deadline_at is not None and time.monotonic() + 22 > deadline_at:
                break
            time.sleep(1 + attempt)
    return {"id": case["id"], "passed": False, "reason": "no answer", "route": [], "internal": [],
            "error": f"{type(last).__name__}: {last}", "seconds": round(time.monotonic() - t0, 1)}


def run_cases(ab: AB, agent_id: str, cases: list[dict], concurrency: int = 3,
              deadline_at: float | None = None, spans=None) -> list[dict]:
    """Every case, at most `concurrency` in flight, results in the input order."""
    with ThreadPoolExecutor(max(1, concurrency)) as pool:
        return list(pool.map(lambda c: run_case(ab, agent_id, c, deadline_at, spans=spans), cases))


def route_text(record: list[dict], show_params: bool = True) -> str:
    """One line a learner reads: tool ids in call order with their structured parameters."""
    if not record:
        return "no tool called"
    parts = []
    for c in record:
        params = {k: v for k, v in (c.get("params") or {}).items() if not isinstance(v, (dict, list))}
        shown = ", ".join(f"{k}={v}" for k, v in params.items() if len(str(v)) <= 40) if show_params else ""
        if c["tool_id"] == "run_subagent":
            parts.append(f"delegate to {c['params'].get('agent_id')}")
            continue
        name = f"{c['agent_id']}: {c['tool_id']}" if c.get("agent_id") else c["tool_id"]
        parts.append(f"{name}({shown})" if shown else name)
    return " -> ".join(parts)


def expected_text(case: dict) -> str:
    parts = []
    for e in case.get("expected") or []:
        if e["tool_id"] == "run_subagent":
            parts.append(f"delegate to {(e.get('params') or {}).get('agent_id')}")
            continue
        shown = ", ".join(f"{k}={v}" for k, v in (e.get("params") or {}).items())
        name = f"{e['agent_id']}: {e['tool_id']}" if e.get("agent_id") else e["tool_id"]
        parts.append(f"{name}({shown})" if shown else name)
    text = " -> ".join(parts) or "no custom tool"
    if case.get("forbid"):
        text += f"; never {', '.join(case['forbid'])}"
    return text


# ── Held-out runs that outlast one check (D-15) ───────────────────────────────
# Instruqt stops a check at about 60 s, and six converse calls take 30 to 50 s on their own. A
# BEHAVIOR check therefore starts the held-out run as a detached root process keyed by a
# fingerprint of what it grades, waits for it inside its own deadline, and grades the record when
# it is there. If the run outlasts the wait, the check ends with no grade and asks for another
# Check; the run carries on, and the next Check grades its record. A change to any graded object
# changes the fingerprint and starts a fresh run. A record with an outage is never graded: the
# next Check starts the run again (R-P8).

import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import pathlib  # noqa: E402
import subprocess  # noqa: E402

STALE_RUN_S = 300  # a run with no record after this long is treated as dead and started again


def fingerprint(*objects) -> str:
    return hashlib.sha256(json.dumps(objects, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _read(path: pathlib.Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def write_json(path: pathlib.Path, data: dict) -> None:
    """Root-only, by rename, so a reader never sees half a record."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True, default=str)
    os.replace(tmp, path)


def ensure_run(record: pathlib.Path, fp: str, runner: list[str], wait_s: float, poll_s: float = 1.0) -> tuple[dict | None, float]:
    """The finished record for fingerprint fp, or None if the run is still going after wait_s.
    Starts `runner + [fp, started]` (detached, root) when no live run for fp exists. A finished
    record with an outage counts as no record: the run starts again. The runner must write
    {"fingerprint": fp, "started": started, ...} to `record`. Returns (record, seconds since start)."""
    start_p = record.with_suffix(".start")
    now = time.time()
    rec = _read(record)
    if rec and rec.get("fingerprint") == fp and not rec.get("outage"):
        return rec, now - float(rec.get("started", now))
    st = _read(start_p)
    live = (st and st.get("fingerprint") == fp and now - float(st.get("started", 0)) < STALE_RUN_S
            and not (rec and rec.get("fingerprint") == fp and float(rec.get("started", 0)) >= float(st["started"])))
    if not live:
        st = {"fingerprint": fp, "started": now}
        write_json(start_p, st)
        subprocess.Popen(runner + [fp, repr(now)], stdin=subprocess.DEVNULL,
                         stdout=open(os.environ.get("ARA_BEHAVIOR_LOG", "/var/log/ara-behavior.log"), "a"), stderr=subprocess.STDOUT,
                         start_new_session=True, close_fds=True)
    started = float(st["started"])
    end = time.monotonic() + wait_s
    while True:
        rec = _read(record)
        if rec and rec.get("fingerprint") == fp and float(rec.get("started", 0)) >= started:
            return rec, time.time() - started
        if time.monotonic() + poll_s > end:
            return None, time.time() - started
        time.sleep(poll_s)
