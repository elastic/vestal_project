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

from agent_builder import AB, ABError, internal_calls, route_matches, route_record


def run_case(ab: AB, agent_id: str, case: dict, deadline_at: float | None = None, attempts: int = 2) -> dict:
    t0 = time.monotonic()
    last = None
    for attempt in range(attempts):
        try:
            resp = ab.converse(agent_id, case["input"])
            record = route_record(resp)
            ok, reason = route_matches(case.get("expected") or [], record, case.get("forbid") or [])
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
              deadline_at: float | None = None) -> list[dict]:
    """Every case, at most `concurrency` in flight, results in the input order."""
    with ThreadPoolExecutor(max(1, concurrency)) as pool:
        return list(pool.map(lambda c: run_case(ab, agent_id, c, deadline_at), cases))


def route_text(record: list[dict], show_params: bool = True) -> str:
    """One line a learner reads: tool ids in call order with their structured parameters."""
    if not record:
        return "no tool called"
    parts = []
    for c in record:
        params = {k: v for k, v in (c.get("params") or {}).items() if not isinstance(v, (dict, list))}
        shown = ", ".join(f"{k}={v}" for k, v in params.items() if len(str(v)) <= 40) if show_params else ""
        parts.append(f"{c['tool_id']}({shown})" if shown else c["tool_id"])
    return " -> ".join(parts)


def expected_text(case: dict) -> str:
    parts = []
    for e in case.get("expected") or []:
        shown = ", ".join(f"{k}={v}" for k, v in (e.get("params") or {}).items())
        parts.append(f"{e['tool_id']}({shown})" if shown else e["tool_id"])
    text = " -> ".join(parts) or "no custom tool"
    if case.get("forbid"):
        text += f"; never {', '.join(case['forbid'])}"
    return text
