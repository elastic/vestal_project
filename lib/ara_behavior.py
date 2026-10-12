"""ara_behavior.py - run a question set through an agent and grade each route (22 section 1).

Shared by the BEHAVIOR checks (held-out sets, root, tina-runtime key) and by ara-ab-behavior.py,
the learner's dev helper. A case is

    {"id": "b1-03", "input": "...", "expected": [{"tool_id": "cortex.x", "params": {"account_id": "476"}}],
     "forbid": ["cortex.y"]}

and is graded on its route and structured literals only (09 section 5a): never on answer text.

Principle 8. A case whose converse call gets no usable answer is retried while the budget allows. If
it still has none, or a delegated route's trace is not complete within 30 s, or the runner itself
fails, its result carries "error" and the caller must not grade the set: a failed remote call is
never credited and never dropped. The checks turn that into ara_grade.unreachable(). A converse that
Kibana refuses with a 4xx (the agent was deleted or will not load) is the learner's: the case fails
with that reason and is graded.

Held-out conversations (09 section 7 rule 1). tina-runtime is minted by the admin user, the user the
learner's Kibana tab signs in as, and conversations are listed per user. So every conversation a
check opens is deleted as soon as its route is recorded (cleanup), and a runner ends with
purge_conversations(), which deletes any conversation since its start whose first message is one
of its inputs (a converse that timed out on our side can still have created one).
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

from agent_builder import (AB, ABError, internal_calls, route_matches, route_record, splice_delegated,
                           trace_calls)

TRACE_BUDGET_S = 30  # 09 section 5a: sub-agent calls are read from traces, polling up to 30 s


class TraceNotReady(ABError):
    """A delegated round's trace was not complete within the budget: an environment failure (R-P8)."""

    def __init__(self, message: str):
        super().__init__(message, 503)


def poll_spans(fetch, trace_id: str, budget_s: float = TRACE_BUDGET_S, poll_s: float = 2.0) -> list[dict]:
    """All spans of one trace once they stop arriving: the root span is present and two reads in a
    row return the same count (probe-42: complete 5 to 10 s after converse returned). fetch(trace_id)
    returns the span documents; an outage in it raises. A trace still incomplete at the end of the
    budget raises TraceNotReady: a missing specialist call is never read as a learner miss."""
    end = time.monotonic() + budget_s
    last_n, spans = -1, []
    while True:
        spans = fetch(trace_id) or []
        rooted = any(not sp.get("parent_span_id") for sp in spans)
        if rooted and len(spans) == last_n:
            return spans
        last_n = len(spans)
        if time.monotonic() + poll_s > end:
            raise TraceNotReady(f"trace {trace_id} was not complete after {int(budget_s)} s "
                                f"({len(spans)} spans{'' if rooted else ', no root span'})")
        time.sleep(poll_s)


def service_of(error: str | None, default: str = "Kibana") -> str:
    """The service an outage record's error names, for ara_grade.unreachable(): Elasticsearch for an
    Elasticsearch or trace-store read, the Jina Reader for a page read, Kibana otherwise."""
    e = str(error or "")
    if "Jina" in e:
        return "The Jina Reader"
    if "ESError" in e or "TraceNotReady" in e or "trace" in e.lower() or "Elasticsearch" in e:
        return "Elasticsearch"
    return default


def _norm(text: str) -> str:
    return " ".join(str(text or "").lower().split())


def delete_conversation(ab: AB, conversation_id: str | None, attempts: int = 3) -> bool:
    """Best effort, retried: True when the conversation is gone."""
    if not conversation_id:
        return True
    for n in range(attempts):
        try:
            if ab.delete_conversation(conversation_id) in (200, 204, 404):
                return True
        except ABError:
            pass
        time.sleep(1 + n)
    return False


def run_case(ab: AB, agent_id: str, case: dict, deadline_at: float | None = None, attempts: int = 2,
             spans=None, cleanup: bool = True) -> dict:
    """One case. spans, when given, is fetch(trace_id) -> span documents: a route that delegates
    (run_subagent) then gets the specialist's own calls spliced in from the trace. cleanup deletes the
    conversation once its route is read (the checks); the dev helper keeps it for the learner."""
    t0 = time.monotonic()
    last = None
    for attempt in range(attempts):
        resp = None
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
            out = {"id": case["id"], "passed": ok, "reason": reason, "route": record,
                   "internal": internal_calls(resp), "conversation_id": resp.get("conversation_id"),
                   "trace_id": resp.get("trace_id"), "seconds": round(time.monotonic() - t0, 1)}
            if cleanup:
                out["conversation_deleted"] = delete_conversation(ab, resp.get("conversation_id"))
            return out
        except ValueError as e:
            # converse answered with a 4xx: Kibana refused the request (no such agent, an agent it cannot load)
            return {"id": case["id"], "passed": False, "route": [], "internal": [], "learner_error": str(e)[:300],
                    "reason": f"Kibana refused the question ({str(e)[:160]})", "seconds": round(time.monotonic() - t0, 1)}
        except ABError as e:
            last = e
            if cleanup and resp is not None:
                delete_conversation(ab, resp.get("conversation_id"))
            # another attempt needs at least one typical converse (about 20 s) before the deadline
            if deadline_at is not None and time.monotonic() + 22 > deadline_at:
                break
            time.sleep(1 + attempt)
        except Exception as e:  # noqa: BLE001 - a fault in the measurement is ours, never the learner's
            last = e
            break
    return {"id": case["id"], "passed": False, "reason": "no answer", "route": [], "internal": [],
            "error": f"{type(last).__name__}: {last}", "seconds": round(time.monotonic() - t0, 1)}


def run_cases(ab: AB, agent_id: str, cases: list[dict], concurrency: int = 3,
              deadline_at: float | None = None, spans=None, cleanup: bool = True) -> list[dict]:
    """Every case, at most `concurrency` in flight, results in the input order."""
    with ThreadPoolExecutor(max(1, concurrency)) as pool:
        return list(pool.map(lambda c: run_case(ab, agent_id, c, deadline_at, spans=spans, cleanup=cleanup), cases))


def purge_conversations(ab: AB, texts: list[str], since: float, agent_id: str | None = None) -> int:
    """Delete every conversation of this user, updated since `since` (epoch seconds), whose first
    message is one of `texts`. The sweep after a runner's own deletes. Returns how many it deleted;
    an outage while listing is swallowed (the per-case deletes already ran)."""
    import datetime as dt
    wanted = {_norm(t) for t in texts if t}
    gone = 0
    try:
        items = ab.conversations(agent_id)
    except ABError:
        return 0
    for item in items:
        stamp = str(item.get("updated_at") or item.get("created_at") or item.get("updatedAt") or item.get("createdAt") or "")
        try:
            when = dt.datetime.strptime(stamp[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc).timestamp()
        except ValueError:
            when = None
        if when is not None and when < since - 120:
            continue
        try:
            conv = ab.conversation(item.get("id")) or {}
        except ABError:
            continue
        rounds = [r for r in conv.get("rounds") or [] if isinstance(r, dict)]
        first = (rounds[0].get("input") if rounds else None) or {}
        text = first.get("message") if isinstance(first, dict) else first
        if _norm(text) in wanted and delete_conversation(ab, item.get("id")):
            gone += 1
    return gone


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
# Instruqt stops a check at about 60 s, and a held-out set takes 30 s to several minutes. A BEHAVIOR
# check therefore starts the run as a detached root process keyed by a fingerprint of what it grades,
# waits for it inside its own deadline, and grades the record when it is there. Otherwise the check
# ends with no grade and asks for another Check; the run carries on and the next Check grades it.
#
# The manager follows M3's _ara_bgjob (3.C), adapted to one record file per run:
#  - <record>.start names the current run: fingerprint, start time (also the runner's token, last on
#    its command line), pid. Starting a run kills the previous run's process group first.
#  - A run that died without a record, or runs past max_s, is killed and started again.
#  - The runner writes through publish(), which keeps its record only while it is still the current
#    run: a superseded run never overwrites a newer record.
#  - A record with an outage is returned once and consumed, so the next Check measures again (R-P8).
#  - consume(): a record whose graded criterion failed is graded once; the next Check measures again,
#    so a run-to-run miss is not frozen in.
#  - A file lock keeps two Checks from starting two runs.

import fcntl  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import pathlib  # noqa: E402
import signal  # noqa: E402
import subprocess  # noqa: E402

MAX_RUN_S = 900  # a run with no record after this long is killed and started again


def fingerprint(*objects) -> str:
    return hashlib.sha256(json.dumps(objects, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _read(path: pathlib.Path) -> dict | None:
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def write_json(path: pathlib.Path, data: dict) -> None:
    """Root-only, by rename, so a reader never sees half a record."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True, default=str)
    os.replace(tmp, path)


class _Lock:
    def __init__(self, record: pathlib.Path):
        record.parent.mkdir(parents=True, exist_ok=True)
        self.path = record.with_suffix(".lock")

    def __enter__(self):
        self.f = open(self.path, "a")
        fcntl.flock(self.f, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        self.f.close()


def _token(started: float) -> str:
    return repr(float(started))


def _alive(st: dict | None) -> bool:
    """The run named in the start file is still running: its pid's command line ends with its token."""
    if not st or not st.get("pid"):
        return False
    pid = int(st["pid"])
    proc = pathlib.Path(f"/proc/{pid}/cmdline")
    if proc.parent.parent.exists():
        try:
            return _token(st["started"]).encode() in proc.read_bytes()
        except OSError:
            return False
    try:  # no /proc (developer machines): the pid exists and is not a zombie
        out = subprocess.run(["ps", "-o", "stat=,command=", "-p", str(pid)], capture_output=True, text=True)
        line = out.stdout.strip()
        return bool(line) and not line.startswith("Z") and _token(st["started"]) in line
    except OSError:
        return False


def _kill(st: dict | None) -> None:
    if not _alive(st):
        return
    for sig, pause in ((signal.SIGTERM, 3.0), (signal.SIGKILL, 0.5)):
        try:
            os.killpg(int(st["pid"]), sig)
        except OSError:
            return
        t = time.time()
        while time.time() - t < pause and _alive(st):
            time.sleep(0.1)


def _current(rec: dict | None, st: dict | None, fp: str) -> bool:
    """The record belongs to the run the start file names, for this fingerprint."""
    return bool(rec and st and rec.get("fingerprint") == fp == st.get("fingerprint")
                and float(rec.get("started", -1)) == float(st.get("started", -2)))


def _start(record: pathlib.Path, fp: str, runner: list[str], old: dict | None) -> dict:
    _kill(old)
    now = time.time()
    with open(os.environ.get("ARA_BEHAVIOR_LOG", "/var/log/ara-behavior.log"), "a") as log:
        proc = subprocess.Popen(runner + [fp, _token(now)], stdin=subprocess.DEVNULL, stdout=log,
                                stderr=subprocess.STDOUT, start_new_session=True, close_fds=True, cwd="/")
    st = {"fingerprint": fp, "started": now, "pid": proc.pid}
    write_json(record.with_suffix(".start"), st)
    return st


def ensure_run(record: pathlib.Path, fp: str, runner: list[str], wait_s: float, poll_s: float = 1.0,
               max_s: float = MAX_RUN_S) -> tuple[dict | None, float]:
    """The finished record for fingerprint fp, or None if the run is still going after wait_s.
    Starts `runner + [fp, token]` (detached, root, its own process group) when no usable record and
    no live run for fp exists. The runner writes {"fingerprint": fp, "started": float(token), ...}
    with publish(). Returns (record, seconds since the run started)."""
    start_p = record.with_suffix(".start")
    end = time.monotonic() + wait_s
    started = time.time()
    for _ in range(2):  # a run that died with no record is started once more
        with _Lock(record):
            st, rec = _read(start_p), _read(record)
            if _current(rec, st, fp) and not st.get("consumed"):
                if rec.get("outage"):
                    st["consumed"] = True  # graded once as "no grade"; the next Check measures again
                    write_json(start_p, st)
                return rec, time.time() - float(st["started"])
            live = (st and st.get("fingerprint") == fp and not st.get("consumed") and _alive(st)
                    and time.time() - float(st.get("started", 0)) < max_s)
            if not live:
                st = _start(record, fp, runner, st)
        started = float(st["started"])
        died = False
        while True:
            rec = _read(record)
            if _current(rec, st, fp):
                if rec.get("outage"):
                    consume(record, fp)
                return rec, time.time() - started
            if not _alive(st):
                time.sleep(0.5)  # it may have just written its record
                rec = _read(record)
                if _current(rec, st, fp):
                    if rec.get("outage"):
                        consume(record, fp)
                    return rec, time.time() - started
                died = True
                break
            if time.monotonic() + poll_s > end:
                return None, time.time() - started
            time.sleep(poll_s)
        if time.monotonic() + 5 > end:
            break
    return None, time.time() - started  # died twice, or no time left to restart: the next Check starts it


def publish(record: pathlib.Path, rec: dict) -> bool:
    """The runner's write: kept only while this run is still the current one for its record."""
    with _Lock(record):
        st = _read(record.with_suffix(".start"))
        if not (st and st.get("fingerprint") == rec.get("fingerprint")
                and float(st.get("started", -2)) == float(rec.get("started", -1)) and not st.get("consumed")):
            print(f"run {rec.get('fingerprint')} superseded; record not written", flush=True)
            return False
        write_json(record, rec)
        return True


def still_current(record: pathlib.Path, fp: str, started: float) -> bool:
    """For a runner with more work after its first publish (4.C's dev pool)."""
    st = _read(record.with_suffix(".start"))
    return bool(st and st.get("fingerprint") == fp and float(st.get("started", -2)) == float(started)
                and not st.get("consumed"))


def consume(record: pathlib.Path, fp: str) -> None:
    """The record for fp was graded and must not be graded again: the next Check measures anew."""
    with _Lock(record):
        start_p = record.with_suffix(".start")
        st = _read(start_p)
        if st and st.get("fingerprint") == fp:
            st["consumed"] = True
            write_json(start_p, st)
