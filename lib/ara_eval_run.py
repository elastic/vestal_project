"""ara_eval_run.py - the evaluation harness core behind the future ara-eval.py (25 sections 4 and 8.5).

No live call is made here: the Agent Builder client, the span reader and the record writer are injected, so
the same code runs under test, in the checks and from M6.

    load_pool(obj)                         pool.json content -> question_id -> item
    run_question(client, agent_id, q, ...) one record: route, matched, trace_id, usage, status
    run_testset(client, agent_id, ...)     every question, bounded concurrency, writer called per record
    summarize(records, key)                per-category route accuracy by the key; graded, ungraded counts
    exit_code(records)                     0 when every record was graded, else EXIT_NO_GRADE
    parse_args(argv)                       --agent, --testset, --pool, --out, --concurrency (M6 uses these)
    jsonl_writer(path)                     writer that appends one JSON line per record

Status per record: graded; unreachable (an outage or timeout survived every attempt); refused (Kibana
answered 4xx, the learner's input); error (a fault of ours). Only graded records carry `matched`; the others
carry None and are never counted as a pass or a fail (principle 8). Standard library only.
"""
from __future__ import annotations

import argparse
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from agent_builder import ABError, round_usage, route_record, splice_delegated, trace_calls
from ara_eval import CATEGORIES, category_means
from ara_pool_match import match_item

ATTEMPTS = 3  # one call and two retries on a 5xx, 429 or timeout
EXIT_NO_GRADE = 3


def load_pool(obj: dict | list) -> dict:
    """pool.json content (or its question list) -> question_id -> item."""
    items = obj.get("questions") if isinstance(obj, dict) else obj
    return {q["id"]: q for q in items or []}


def _record(q: dict, label: str | None, status: str, **extra: Any) -> dict:
    base = {"question_id": q["id"], "category": label, "kind": q.get("type") or q.get("kind"),
            "status": status, "matched": None, "route_correct": None, "reason": None,
            "route": [], "observed_route": [], "expected_route": None, "trace_id": None,
            "conversation_id": None, "latency_ms": None, "tool_call_count": 0, "llm_calls": 0, "input_tokens": 0,
            "cached_input_tokens": 0, "fresh_input_tokens": 0, "output_tokens": 0}
    base.update(extra)
    return base


def run_question(client: Any, agent_id: str, q: dict, label: str | None = None, attempts: int = ATTEMPTS,
                 spans: Callable | None = None, poll: Callable | None = None, cleanup: bool = False,
                 sleep: Callable = time.sleep) -> dict:
    """One question against one agent. client.converse_timed(agent_id, text) -> (response, ms) raises ABError
    on an outage (retried, then unreachable) and ValueError on a 4xx (refused, not retried). spans is
    fetch(trace_id) -> span documents and poll(fetch, trace_id) -> spans (ara_behavior.poll_spans), both
    needed to splice a delegated route from the trace. The record carries the aggregates() field names."""
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            resp, ms = client.converse_timed(agent_id, q["input"])
        except ABError as e:
            last = e
            if attempt + 1 < attempts:
                sleep(1 + attempt)
            continue
        except ValueError as e:
            return _record(q, label, "refused", reason=f"Kibana refused the question ({str(e)[:160]})")
        except Exception as e:  # noqa: BLE001 - a fault in the measurement is ours, never the learner's
            return _record(q, label, "error", reason=f"{type(e).__name__}: {str(e)[:160]}")
        try:
            record = route_record(resp)
            tid = resp.get("trace_id")
            # The pool's golds are cut at the delegation: a route is graded on the coordinator's own calls, and what a
            # specialist does inside is not part of it. The trace is read (and spliced in) only for an item whose gold
            # names a call made inside a delegation (an expected entry with its own agent_id).
            inside = any("agent_id" in e and e.get("tool_id") != "run_subagent" for e in q.get("expected") or [])
            if inside and spans is not None and poll is not None and tid and any(c["tool_id"] == "run_subagent" for c in record):
                record = splice_delegated(record, trace_calls(poll(spans, tid), agent_id))
        except ABError as e:  # the trace never completed: the route is unknown, so no grade
            last = e
            if attempt + 1 < attempts:
                sleep(1 + attempt)
            continue
        except Exception as e:  # noqa: BLE001
            return _record(q, label, "error", reason=f"{type(e).__name__}: {str(e)[:160]}")
        ok, reason = match_item(q, record, resp)
        usage = round_usage(resp, ms, resp.get("conversation_id"))
        if cleanup and hasattr(client, "delete_conversation") and resp.get("conversation_id"):
            try:
                client.delete_conversation(resp["conversation_id"])
            except Exception:  # noqa: BLE001 - housekeeping, never a grade
                pass
        return _record(q, label, "graded", matched=ok, route_correct=ok, reason=reason, route=record,
                       observed_route=record, expected_route=q.get("expected") or [], trace_id=tid,
                       conversation_id=resp.get("conversation_id"), latency_ms=ms,
                       **{k: usage[k] for k in ("tool_call_count", "llm_calls", "input_tokens", "cached_input_tokens",
                                                "fresh_input_tokens", "output_tokens")})
    return _record(q, label, "unreachable", reason=f"no answer after {attempts} attempts ({type(last).__name__}: {str(last)[:120]})")


def run_testset(client: Any, agent_id: str, testset: list[dict], pool: dict, key: dict | None = None,
                concurrency: int = 3, writer: Callable[[dict], None] | None = None, **kw: Any) -> list[dict]:
    """Run every test-set entry ({"question_id", optional "category" label}) and return the records in test
    order. writer(record) is called once per record as it finishes, under a lock. Each record's category is
    the key's when a key is given (the grade is by the true category), else the learner's label; the label
    stays in `label_category`. A question id outside the pool becomes an error record, not a crash."""
    lock = threading.Lock()

    def one(entry: dict) -> dict:
        qid = entry["question_id"]
        label = entry.get("category")
        if qid not in pool:
            rec = _record({"id": qid}, (key or {}).get(qid, label), "error", reason="question id not in the pool")
        else:
            rec = run_question(client, agent_id, pool[qid], (key or {}).get(qid, label), **kw)
        rec["label_category"] = label
        if writer:
            with lock:
                writer(rec)
        return rec

    with ThreadPoolExecutor(max(1, concurrency)) as ex:
        return list(ex.map(one, testset))


def summarize(records: list[dict], key: dict | None = None) -> dict:
    """Per-category route accuracy (0 to 1, None for a category with no graded record) over graded records,
    the overall share, and how many records were not graded. `key` (question_id -> category) overrides the
    record's own category when given."""
    graded = [r for r in records if r.get("status") == "graded"]
    cats = {r["question_id"]: (key or {}).get(r["question_id"], r.get("category")) for r in graded}
    means = category_means({r["question_id"]: 1.0 if r["matched"] else 0.0 for r in graded}, cats, CATEGORIES)
    return {"questions": len(records), "graded": len(graded), "ungraded": len(records) - len(graded),
            "unreachable": sum(r.get("status") == "unreachable" for r in records),
            "routing_accuracy": means,
            "overall": (sum(bool(r["matched"]) for r in graded) / len(graded)) if graded else None}


def exit_code(records: list[dict]) -> int:
    """Principle 8: any record without a grade means the run is not a grade; the caller exits with this."""
    return 0 if records and all(r.get("status") == "graded" for r in records) else EXIT_NO_GRADE


def jsonl_writer(path: str) -> Callable[[dict], None]:
    def write(rec: dict) -> None:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")
    return write


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="ara-eval.py run")
    p.add_argument("--agent", required=True, help="agent id to evaluate")
    p.add_argument("--testset", required=True, help="test set JSON: a list of {question_id, category}")
    p.add_argument("--pool", help="question pool JSON (default: the sandbox's own)")
    p.add_argument("--out", help="record file, one JSON line per question (default: eval-runs)")
    p.add_argument("--concurrency", type=int, default=3)
    return p.parse_args(argv)
