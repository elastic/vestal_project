"""ara_integrity.py - the evaluation integrity procedure (25 section 8.7), as pure functions with injected clients.

    strip(obj, fields)                  copy of obj without the server-managed fields, at every depth
    snapshot(objects, strip_fields)     {"objects": key -> stripped object, "fingerprints": key -> hash}
    collect_reach(reader, agent_ids)    every object in Tina's reach, key -> raw object (agent/<id>, tool/<id>, ...)
    diff(a, b)                          [{"object", "field", "change"}] between two snapshots, objects and JSON paths named
    recompute(records, reader, ...)     step 2, 3 and 5: failures naming the question id and the field
    check_run(...)                      check-run binding (step 4): fingerprint, run, fingerprint, recompute, freeze
    update_binding(objects, convs, ...) update-time binding: every conversation post-dates every object's update
    reset(snapshot, current)            PUT bodies that restore the root-held snapshot; the caller applies them
    write_start_state(path, reader, ...) the 5.4 start-state copy `ara-eval.py reset` restores from (setup writes it)

Clients are injected: `reader` has get_agent/get_tool/get_skill/get_workflow(id), connectors(), plugins() and
conversation(id) (agent_builder.AB does); `client` has converse_timed(agent_id, text) (ara_eval_run). No live
call is made here. A failed remote call is never graded (principle 8): ara_eval_run retries twice, then the
record is `unreachable` and check_run returns status `unreachable` with no grade and nothing frozen.
Standard library only.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import pathlib
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Iterable

import ara_behavior
import ara_eval
import ara_eval_run
from agent_builder import ABError, round_usage, route_record
from ara_pool_match import match_item

# Server-managed fields: moved by the server, not by an edit. Probe: an identical re-PUT of the agent changes
# only /agent/updated_at, and idle drift is zero. Extend through the parameter, never by editing this tuple.
DEFAULT_STRIP = ("created_at", "updated_at", "permissions")
# Round statuses that end a conversation (P2 records). awaiting_prompt is a round that ended on an ask or a
# confirmation nobody answered: the eval never answers one, so it is the final state of that question (phase0-r5).
TERMINAL = ("completed", "declined", "unanswered", "awaiting_prompt")
USAGE_FIELDS = ("input_tokens", "output_tokens", "cached_input_tokens", "llm_calls", "fresh_input_tokens")

# ── 1. fingerprints ───────────────────────────────────────────────────────────

def strip(obj: Any, fields: Iterable[str] = DEFAULT_STRIP) -> Any:
    """Deep copy of obj without any dict key in fields, at every depth."""
    drop = set(fields)
    if isinstance(obj, dict):
        return {k: strip(v, drop) for k, v in obj.items() if k not in drop}
    if isinstance(obj, list):
        return [strip(v, drop) for v in obj]
    return copy.deepcopy(obj)


def snapshot(objects: dict[str, Any], strip_fields: Iterable[str] = DEFAULT_STRIP) -> dict:
    """objects: key ("agent/tina-compliance") -> raw object. The stripped copies are kept so diff() can name a
    field; ara_behavior.fingerprint hashes each one."""
    clean = {k: strip(v, strip_fields) for k, v in sorted(objects.items())}
    return {"objects": clean, "fingerprints": {k: ara_behavior.fingerprint(v) for k, v in clean.items()}}


def _walk(a: Any, b: Any, path: str, out: list) -> None:
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            p = f"{path}/{k}"
            if k not in a:
                out.append((p, "added"))
            elif k not in b:
                out.append((p, "removed"))
            else:
                _walk(a[k], b[k], p, out)
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            _walk(x, y, f"{path}/{i}", out)
    elif a != b:
        out.append((path, "changed"))


def diff(fp_a: dict, fp_b: dict) -> list[dict]:
    """Differences between two snapshots, one entry per changed field: {"object", "field", "change"}.
    An object in one snapshot only is {"object", "field": "", "change": "added"|"removed"}."""
    a, b = fp_a.get("objects", {}), fp_b.get("objects", {})
    out: list[dict] = []
    for key in sorted(set(a) | set(b)):
        if key not in a:
            out.append({"object": key, "field": "", "change": "added"})
        elif key not in b:
            out.append({"object": key, "field": "", "change": "removed"})
        elif fp_a["fingerprints"][key] != fp_b["fingerprints"][key]:
            found: list = []
            _walk(a[key], b[key], "", found)
            out.extend({"object": key, "field": p or "/", "change": c} for p, c in found)
    return out


def _find(obj: Any, keys: tuple[str, ...]) -> list[str]:
    """Every string in a list or scalar under any dict key in keys, at any depth, in order, without repeats."""
    seen: list[str] = []

    def go(o: Any) -> None:
        if isinstance(o, dict):
            for k, v in o.items():
                if k in keys:
                    for s in (v if isinstance(v, list) else [v]):
                        if isinstance(s, str) and s not in seen:
                            seen.append(s)
                go(v)
        elif isinstance(o, list):
            for v in o:
                go(v)
    go(obj)
    return seen


def collect_reach(reader: Any, agent_ids: list[str], connector_ids: Iterable[str] = ()) -> dict[str, Any]:
    """Tina's reach (8.7 step 4): her agent and the sub-agent's; every tool either holds; every skill attached
    to either, with the tools it references; every installed plugin; every workflow behind any of those
    tools; every connector those workflows name (`connector-id`/`connector_id`) or the caller lists.
    Keys are "<kind>/<id>". An object the reader cannot find is recorded as None, so a deletion shows in diff()."""
    out: dict[str, Any] = {}

    def put(kind: str, oid: str, getter: Callable) -> Any:
        key = f"{kind}/{oid}"
        if key not in out:
            out[key] = getter(oid)
        return out[key]

    tool_ids: list[str] = []
    skill_ids: list[str] = []
    for aid in agent_ids:
        ag = put("agent", aid, reader.get_agent)
        tool_ids += [t for t in _find(ag, ("tool_ids",)) if t not in tool_ids]
        skill_ids += [s for s in _find(ag, ("skill_ids",)) if s not in skill_ids]
    for sid in skill_ids:
        sk = put("skill", sid, reader.get_skill)
        tool_ids += [t for t in _find(sk, ("tool_ids",)) if t not in tool_ids]
    for p in reader.plugins() or []:
        out[f"plugin/{p.get('id') or p.get('name')}"] = p
    wf_ids: list[str] = []
    for tid in tool_ids:
        tl = put("tool", tid, reader.get_tool)
        wf_ids += [w for w in _find(tl, ("workflow_id",)) if w not in wf_ids]
    conns = list(connector_ids)
    for wid in wf_ids:
        wf = put("workflow", wid, reader.get_workflow)
        text = json.dumps(wf, default=str)
        conns += [c for c in re.findall(r'connector[-_]id["\']?\s*[:=]\s*\\?["\']?([\w.:-]+)', text) if c not in conns]
    if conns:
        listed = {c.get("id"): c for c in reader.connectors() or [] if isinstance(c, dict)}
        for cid in conns:
            out.setdefault(f"connector/{cid}", listed.get(cid))
    return out

# ── 2, 3, 5. recompute from conversations ────────────────────────────────────

def _t(x: Any) -> float | None:
    if isinstance(x, (int, float)):
        return float(x) / 1000 if x > 1e11 else float(x)
    if isinstance(x, str):
        try:
            return dt.datetime.fromisoformat(x.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def _fail(qid: Any, field: str, reason: str, stored: Any = None, recomputed: Any = None) -> dict:
    return {"question_id": qid, "field": field, "reason": reason, "stored": stored, "recomputed": recomputed}


def _own(route: list[dict]) -> list[tuple]:
    """The coordinator's own calls (the route record without the trace join), comparable."""
    return [(c.get("tool_id"), json.dumps(c.get("params") or {}, sort_keys=True), bool(c.get("ok")))
            for c in route if not c.get("agent_id")]


def recompute(records: list[dict], reader: Any, testset: list[dict], pool: dict, agent_id: str,
              pinned_model: str | None = None, window: tuple[float, float] | None = None,
              terminal: Iterable[str] = TERMINAL, latency_tolerance_ms: int | None = None) -> list[dict]:
    """Failures (empty = verified). Every failure names the question id. Canonical inputs (testset, pool) come
    from root-held files, never from the records. A test-set question with no record fails; so does a record
    for a question outside the test set, and two records sharing a conversation."""
    fails: list[dict] = []
    by_q: dict[Any, dict] = {}
    for r in records:
        if r.get("question_id") in by_q:
            fails.append(_fail(r.get("question_id"), "record", "more than one record for the question"))
        by_q[r.get("question_id")] = r
    wanted = [e["question_id"] for e in testset]
    for qid in wanted:
        if qid not in by_q:
            fails.append(_fail(qid, "record", "no record for the question"))
    for qid in by_q:
        if qid not in wanted:
            fails.append(_fail(qid, "record", "record for a question outside the test set"))
    used: dict[str, Any] = {}
    for qid in wanted:
        rec, q = by_q.get(qid), pool.get(qid)
        if rec is None:
            continue
        if q is None:
            fails.append(_fail(qid, "question", "question id not in the pool"))
            continue
        cid = rec.get("conversation_id")
        if not cid:
            fails.append(_fail(qid, "conversation_id", "record names no conversation"))
            continue
        if cid in used:
            fails.append(_fail(qid, "conversation_id", f"conversation shared with {used[cid]}", cid))
            continue
        used[cid] = qid
        try:
            conv = reader.conversation(cid)
        except ABError as e:
            fails.append(_fail(qid, "conversation_id", f"conversation unreadable ({str(e)[:80]})", cid))
            continue
        if not conv:
            fails.append(_fail(qid, "conversation_id", "conversation missing", cid))
            continue
        if conv.get("agent_id") != agent_id:
            fails.append(_fail(qid, "agent_id", "conversation is not Tina's", agent_id, conv.get("agent_id")))
            continue
        rounds = conv.get("rounds") or []
        if len(rounds) != 1:
            fails.append(_fail(qid, "rounds", "conversation does not have exactly one round", 1, len(rounds)))
            continue
        rnd = rounds[0]
        if rnd.get("status") not in tuple(terminal):
            fails.append(_fail(qid, "status", "round is not terminal", list(terminal), rnd.get("status")))
            continue
        said = rnd.get("input")
        said = said.get("message") if isinstance(said, dict) else said
        if said != q.get("input"):
            fails.append(_fail(qid, "input", "round input differs from the canonical question", q.get("input"), said))
            continue
        usage = round_usage(rnd, None, cid)
        if pinned_model and usage["models"] != [pinned_model]:
            fails.append(_fail(qid, "model", "round did not run on the pinned model", pinned_model, usage["models"]))
            continue
        if window:
            ts = _t(rnd.get("started_at") or conv.get("created_at"))
            if ts is None or not window[0] <= ts <= window[1]:
                fails.append(_fail(qid, "started_at", "round is outside the run window", list(window), ts))
                continue
        route = route_record(rnd)
        ok, _why = match_item(q, route, rnd)
        want: dict[str, Any] = {"observed_route": _own(route), "route_correct": ok,
                                "tool_call_count": usage["tool_call_count"],
                                **{k: usage[k] for k in USAGE_FIELDS}}
        have = dict(rec, observed_route=_own(rec.get("observed_route") or rec.get("route") or []))
        for field, v in want.items():
            if field in have and have[field] != v:
                fails.append(_fail(qid, field, "stored value differs from the conversation", have[field], v))
        if "route_correct" not in rec:
            fails.append(_fail(qid, "route_correct", "stored record has no route_correct"))
        if latency_tolerance_ms is not None and rnd.get("time_to_last_token") is not None:
            api = rnd["time_to_last_token"]
            if abs((rec.get("latency_ms") or 0) - api) > latency_tolerance_ms:
                fails.append(_fail(qid, "latency_ms", "stored latency differs from the API's", rec.get("latency_ms"), api))
    return fails

def apply_page_check(records: list[dict], pool: dict, page_check: Callable[[dict, dict], bool]) -> None:
    """Set `page_fetch_ok` on every cortex.read_page entry of every record's observed_route, from the check's own
    reading of the call's workflow execution: page_check(call, pool_item) -> bool. The stored value (a learner's
    record) is never trusted: it is overwritten. ara_eval.aggregates reads this field for page_fetch_share."""
    for rec in records:
        item = pool.get(rec.get("question_id")) or {}
        for call in rec.get("observed_route") or []:
            if call.get("tool_id") == "cortex.read_page":
                call["page_fetch_ok"] = bool(page_check(call, item))


# ── 3. check-run binding ──────────────────────────────────────────────────────

def check_run(client: Any, reader: Any, agent_id: str, testset: list[dict], pool: dict, label: str,
              take_snapshot: Callable[[], dict], freeze_path: str, expected: dict | None = None,
              key: dict | None = None, card: dict | None = None, concurrency: int = 3,
              pinned_model: str | None = None, earlier_frozen: Iterable[str] = (),
              record_writer: Callable[[dict], None] | None = None, clock: Callable[[], float] = time.time,
              page_check: Callable[[dict, dict], bool] | None = None, **run_kw: Any) -> dict:
    """The check makes the graded run itself (8.7 step 4, check-run binding).

    take_snapshot() -> snapshot() of Tina's reach, read root-side. expected is the label's expected state (a
    snapshot); None means the start-of-run state. The reach is fingerprinted at the start, each time one of the
    run's conversations ends, and once after the last; any difference from expected discards the run and
    fails, naming the object. Records are written (record_writer) under run label `<label>-check` with no judge
    scores. The records are then verified against their conversations (recompute) and, only if everything holds,
    the conversation ids, trusted aggregates and freeze time are written to freeze_path (a root-held JSON path
    the caller chooses). No conversation of an earlier frozen label (earlier_frozen: their freeze files) may
    be reused. Returns {"status": "pass"|"fail"|"unreachable", "failures": [...], "aggregates": ...}; status
    `unreachable` means a remote call failed after its retries: nothing is graded and nothing is frozen.
    page_check (5.C) is page_fetch_ok's recompute: see apply_page_check."""
    start = take_snapshot()
    want = expected if expected is not None else start
    changes = [dict(d, at="start") for d in diff(want, start)]
    if changes:
        return {"status": "fail", "label": label, "failures": changes, "aggregates": None}
    t0 = clock()
    drift: list[dict] = []
    lock = threading.Lock()

    def after_conversation(rec: dict) -> None:
        run_label = dict(rec, run_label=f"{label}-check", judge={"faithfulness": None, "answer_relevance": None,
                                                                 "context_precision": None})
        if record_writer:
            record_writer(run_label)
        with lock:  # one fingerprint at a time; a read after each ended conversation
            found = diff(want, take_snapshot())
            drift.extend(dict(d, at=f"after {rec.get('question_id')}") for d in found)

    records = ara_eval_run.run_testset(client, agent_id, testset, pool, key=key, concurrency=concurrency,
                                       writer=after_conversation, **run_kw)
    final = diff(want, take_snapshot())
    drift.extend(dict(d, at="end") for d in final)
    if drift:
        return {"status": "fail", "label": label, "failures": drift, "aggregates": None, "discarded": True}
    if any(r.get("status") == "unreachable" for r in records):
        return {"status": "unreachable", "label": label, "failures": [
            _fail(r["question_id"], "status", r.get("reason") or "unreachable") for r in records
            if r.get("status") == "unreachable"], "aggregates": None}
    if ara_eval_run.exit_code(records):  # refused or error records are not a grade either
        return {"status": "fail", "label": label, "aggregates": None, "failures": [
            _fail(r["question_id"], "status", f"{r.get('status')}: {r.get('reason')}") for r in records
            if r.get("status") != "graded"]}
    end = clock()
    fails = recompute(records, reader, testset, pool, agent_id, pinned_model=pinned_model, window=(t0 - 1, end + 1))
    seen: dict[str, str] = {}
    for path in earlier_frozen:
        try:
            with open(path, encoding="utf-8") as f:
                for cid in json.load(f).get("conversation_ids", []):
                    seen[cid] = path
        except (OSError, ValueError):
            fails.append(_fail(None, "earlier_frozen", f"frozen label unreadable: {path}"))
    fails += [_fail(r["question_id"], "conversation_id", f"conversation already frozen in {seen[r['conversation_id']]}")
              for r in records if r.get("conversation_id") in seen]
    if fails:
        return {"status": "fail", "label": label, "failures": fails, "aggregates": None}
    if page_check is not None:  # 5.C: the page fetch is recomputed from the executions, never taken from a record
        apply_page_check(records, pool, page_check)
    agg = ara_eval.aggregates(records, card)
    frozen = {"label": label, "run_label": f"{label}-check", "conversation_ids": [r["conversation_id"] for r in records],
              "aggregates": agg, "frozen_at": clock(), "testset": [e["question_id"] for e in testset],
              "fingerprints": start["fingerprints"]}
    ara_behavior.write_json(pathlib.Path(freeze_path), frozen)
    return {"status": "pass", "label": label, "failures": [], "aggregates": agg, "records": records, "frozen": frozen}

# ── 4. update-time binding ────────────────────────────────────────────────────

def update_binding(objects: dict[str, Any], conversations: list[dict], freezes: Iterable[float] = (),
                   fields: tuple[str, ...] = ("updated_at",)) -> list[dict]:
    """Every conversation post-dates the last update of every fingerprinted object that carries an update time
    (agents, workflows, plugins per Phase 0 item 0-g) and the freeze time of any earlier label. Objects
    without one are skipped (they need check-run binding). conversations: [{"id", "created_at"}]. Failures
    name the object and the conversation."""
    stamps: dict[str, float] = {}
    for key, obj in objects.items():
        for f in fields:
            t = _t((obj or {}).get(f)) if isinstance(obj, dict) else None
            if t is not None:
                stamps[key] = max(stamps.get(key, 0.0), t)
    out = []
    for c in conversations:
        ts = _t(c.get("created_at"))
        if ts is None:
            out.append({"object": None, "conversation_id": c.get("id"), "reason": "conversation has no usable time"})
            continue
        out += [{"object": k, "conversation_id": c.get("id"), "reason": "object updated after the conversation"}
                for k, t in sorted(stamps.items()) if ts <= t]
        out += [{"object": None, "conversation_id": c.get("id"), "reason": "conversation predates an earlier freeze"}
                for f in freezes if ts <= f]
    return out

# ── 5. reset ──────────────────────────────────────────────────────────────────

def reset(snap: dict, current: dict | None = None) -> list[dict]:
    """PUT bodies that restore the 5.3-start snapshot (root-held). With `current` (a snapshot of now), only the
    objects that differ or are missing; without, every object. Each entry {"kind", "id", "body"} carries the
    stripped object, so the server-managed fields are not sent. The caller applies them."""
    keys = snap.get("objects", {})
    cur = (current or {}).get("fingerprints")
    out = []
    for key, body in keys.items():
        if body is None or (cur is not None and cur.get(key) == snap["fingerprints"][key]):
            continue
        kind, _, oid = key.partition("/")
        out.append({"kind": kind, "id": oid, "body": copy.deepcopy(body)})
    return out


# ── 6. the start-state copy ───────────────────────────────────────────────────

START_STATE_VERSION = 1
START_STRIP = DEFAULT_STRIP + ("secrets",)  # a copy installed with the track never holds a secret


def build_start_state(reader: Any, agent_ids: list[str], connector_ids: Iterable[str] = (),
                      strip_fields: Iterable[str] = START_STRIP) -> dict:
    """The start-state document from live objects: {"version", "agent_ids", "connector_ids", "strip_fields",
    "objects": key -> stripped object, "fingerprints": key -> hash}. An object the reader cannot find is
    left out (it would be unrestorable), so setup fails loudly through the missing agent check instead."""
    strip_fields = list(strip_fields)
    reach = {k: v for k, v in collect_reach(reader, agent_ids, connector_ids).items() if v is not None}
    snap = snapshot(reach, strip_fields)
    return {"version": START_STATE_VERSION, "agent_ids": list(agent_ids), "connector_ids": sorted(set(connector_ids)),
            "strip_fields": strip_fields, **snap}


def write_start_state(path: str | pathlib.Path, reader: Any, agent_ids: list[str],
                      connector_ids: Iterable[str] = (), strip_fields: Iterable[str] = START_STRIP) -> dict:
    """Write the start-state copy (setup, once, from the live 5.4 start objects). Returns the document."""
    doc = build_start_state(reader, agent_ids, connector_ids, strip_fields)
    for aid in agent_ids:
        if f"agent/{aid}" not in doc["objects"]:
            raise ValueError(f"agent {aid} was not found; the start-state copy was not written")
    ara_behavior.write_json(pathlib.Path(path), doc)
    return doc
