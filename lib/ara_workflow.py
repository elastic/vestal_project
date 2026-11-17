"""ara_workflow.py - the workflow reader (28 section 1): a workflow's triggers, its executions filtered by
trigger, status, time and inputs, and the occurrences of every scheduled trigger over a window in its effective
time zone. Pure parsing over fixture API responses; no HTTP, and nothing here saves, enables or disables a
workflow (a scheduled workflow runs as its last saver, 29 section 3).

    triggers(defn)                       [{type, every_seconds | rrule, tzid}] from a workflow definition
    scheduled(defn)                      the scheduled triggers only
    has_interval(defn)                   True when an `every` trigger is present
    occurrences(trigger, start, end)     UTC datetimes a scheduled trigger fires in [start, end)
    expand(defn, start, end)             sorted, de-duplicated occurrences of all scheduled triggers
    executions(resp)                     normalised execution list
    filter_executions(execs, ...)        by workflow, triggered_by, started after, status, change_id

Trigger shapes (28 section 4 teaching points): `type: scheduled`, `with: {every: "1m"}` or
`with: {rrule: {freq: DAILY|WEEKLY|MONTHLY, interval, byhour, byminute, byweekday, tzid}}`; tzid defaults to UTC;
there is no cron syntax; the shortest interval is one minute. The platform's response field names are not yet
probed (P2): execution fields are read under the names in _EXEC_KEYS, and the choice is in the module's tests.
Calendar rules anchor at the window's start (interval 1 is anchor-free); `byhour` or `byminute` missing means the
anchor's hour or minute is not used, so the rule fires at hour 0 and minute 0 (a documented simplification).
Standard library only (zoneinfo for time zones).
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

_WEEKDAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6,
             "MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6}
_UNIT = {"s": 1, "m": 60, "h": 3600, "d": 86400}
_EXEC_KEYS = {"id": ("id", "executionId"), "workflow_id": ("workflowId", "workflow_id"),
              "triggered_by": ("triggeredBy", "triggered_by"), "started_at": ("startedAt", "startedTime", "started_at"),
              "status": ("status",), "inputs": ("inputs", "input"), "error": ("error",)}


def _every_seconds(text: Any) -> int:
    m = re.fullmatch(r"\s*(\d+)\s*([smhd])\s*", str(text))
    if not m:
        raise ValueError(f"unreadable interval {text!r}")
    return int(m.group(1)) * _UNIT[m.group(2)]


def _weekday(v: Any) -> int:
    if isinstance(v, int):
        return v
    key = str(v).strip().upper()
    if key not in _WEEKDAYS:
        raise ValueError(f"unknown weekday {v!r}")
    return _WEEKDAYS[key]


def _ints(v: Any) -> list[int]:
    return sorted({int(x) for x in (v if isinstance(v, list) else [v])}) if v is not None else []


def triggers(defn: dict) -> list[dict]:
    out = []
    for t in defn.get("triggers") or []:
        kind = t.get("type")
        w = t.get("with") or {}
        if kind != "scheduled":
            out.append({"type": kind})
            continue
        if "every" in w:
            out.append({"type": "scheduled", "every_seconds": _every_seconds(w["every"]), "tzid": "UTC"})
        elif isinstance(w.get("rrule"), dict):
            r = w["rrule"]
            freq = str(r.get("freq", "")).upper()
            if freq not in ("DAILY", "WEEKLY", "MONTHLY"):
                raise ValueError(f"rrule freq must be DAILY, WEEKLY or MONTHLY, not {r.get('freq')!r}")
            out.append({"type": "scheduled", "tzid": r.get("tzid") or "UTC", "rrule": {
                "freq": freq, "interval": int(r.get("interval", 1)), "byhour": _ints(r.get("byhour")),
                "byminute": _ints(r.get("byminute")), "byweekday": [_weekday(x) for x in (r.get("byweekday") or [])],
                "bymonthday": _ints(r.get("bymonthday"))}})
        else:
            out.append({"type": "scheduled", "unreadable": True})
    return out


def scheduled(defn: dict) -> list[dict]:
    return [t for t in triggers(defn) if t["type"] == "scheduled"]


def has_interval(defn: dict) -> bool:
    return any("every_seconds" in t for t in scheduled(defn))


def occurrences(trigger: dict, start: datetime, end: datetime) -> list[datetime]:
    """UTC datetimes in [start, end). `every` fires every interval from start; a calendar rule is expanded on
    local calendar days in its tzid, so a DST change moves the UTC time, not the local one."""
    if trigger.get("type") != "scheduled" or trigger.get("unreadable"):
        return []
    if "every_seconds" in trigger:
        step, out, t = timedelta(seconds=trigger["every_seconds"]), [], start + timedelta(seconds=trigger["every_seconds"])
        while t < end:
            out.append(t)
            t += step
        return out
    r, tz = trigger["rrule"], ZoneInfo(trigger["tzid"])
    anchor: date = start.astimezone(tz).date()
    hours, minutes = r["byhour"] or [0], r["byminute"] or [0]
    out = []
    day = anchor - timedelta(days=1)
    last = end.astimezone(tz).date() + timedelta(days=1)
    while day <= last:
        n = (day - anchor).days
        if r["freq"] == "DAILY":
            ok = n % r["interval"] == 0
        elif r["freq"] == "WEEKLY":
            wd = r["byweekday"] or [anchor.weekday()]
            ok = day.weekday() in wd and ((day - timedelta(days=day.weekday())) - (anchor - timedelta(days=anchor.weekday()))).days // 7 % r["interval"] == 0
        else:
            months = (day.year - anchor.year) * 12 + day.month - anchor.month
            ok = day.day in (r["bymonthday"] or [anchor.day]) and months % r["interval"] == 0
        if ok:
            for h in hours:
                for m in minutes:
                    t = datetime(day.year, day.month, day.day, h, m, tzinfo=tz).astimezone(timezone.utc)
                    if start <= t < end:
                        out.append(t)
        day += timedelta(days=1)
    return sorted(out)


def expand(defn: dict, start: datetime, end: datetime) -> list[datetime]:
    """Every scheduled trigger's occurrences in the window, merged; one rule with three byhour values and three
    rules with one each give the same list."""
    return sorted({t for trig in scheduled(defn) for t in occurrences(trig, start, end)})


def _pick(d: dict, names: tuple) -> Any:
    return next((d[n] for n in names if n in d), None)


def executions(resp: dict | list) -> list[dict]:
    """Normalised executions from a list response (a list, or an object holding `results`, `executions` or `items`)."""
    items = resp if isinstance(resp, list) else next((resp[k] for k in ("results", "executions", "items") if k in resp), [])
    out = []
    for e in items:
        n = {k: _pick(e, v) for k, v in _EXEC_KEYS.items()}
        if n["started_at"] is not None:
            n["started_at"] = datetime.fromisoformat(str(n["started_at"]).replace("Z", "+00:00"))
        n["inputs"] = n["inputs"] or {}
        out.append(n)
    return out


def filter_executions(execs: list[dict], workflow_id: str | None = None, triggered_by: str | None = None,
                      after: datetime | None = None, status: str | None = None, change_id: str | None = None) -> list[dict]:
    """Executions matching every filter given; `after` is exclusive; change_id reads the execution's inputs."""
    out = []
    for e in execs:
        if workflow_id and e["workflow_id"] != workflow_id:
            continue
        if triggered_by and e["triggered_by"] != triggered_by:
            continue
        if status and e["status"] != status:
            continue
        if after and not (e["started_at"] and e["started_at"] > after):
            continue
        if change_id is not None and e["inputs"].get("change_id") != change_id:
            continue
        out.append(e)
    return out


# ── ai.agent steps and the post-execution hook (28 sections 3, 4; gaps G3, P6, P7) ──

def _walk_steps(steps: Any):
    for s in steps or []:
        if not isinstance(s, dict):
            continue
        yield s
        for key in ("steps", "else", "on-failure"):
            nested = s.get(key)
            if isinstance(nested, list):
                yield from _walk_steps(nested)
            elif isinstance(nested, dict):
                yield from _walk_steps(nested.get("steps"))


def ai_agent_steps(defn: dict) -> list[dict]:
    """Every `ai.agent` step, nested steps included: name, agent_id, inference_id, message, schema, and
    create_conversation. agent-id, inference-id and create-conversation are read from the step, else from its
    `with` block (28 does not say which; P7 shows the platform's). Missing fields read as None."""
    out = []
    for s in _walk_steps(defn.get("steps")):
        if s.get("type") != "ai.agent":
            continue
        w = s.get("with") or {}
        pick = lambda *names: next((d[n] for d in (s, w) for n in names if n in d), None)
        out.append({"name": s.get("name"), "agent_id": pick("agent-id", "agent_id"),
                    "inference_id": pick("inference-id", "inference_id"), "message": w.get("message"),
                    "schema": w.get("schema"), "create_conversation": pick("create-conversation", "create_conversation")})
    return out


POST_EXEC_FIELD = "post_execution_workflow_ids"
POST_EXEC_LOCATIONS = (("configuration",),)  # P6 (probe r2, 2026-11-12): PUT at configuration 200 and reads back there; a top-level field is refused (400 unexpected property)


def post_execution_ids(agent: dict) -> tuple[list[str], tuple]:
    """Tina's post-execution workflow ids and where they were found. Both candidate locations (the agent's top
    level, and its `configuration`) sit behind this one function. Absent in both reads as ([], ()). When both are
    set and differ, the definition is ambiguous and ValueError says so."""
    found = []
    for path in POST_EXEC_LOCATIONS:
        node: Any = agent
        for k in path:
            node = node.get(k) if isinstance(node, dict) else None
        if isinstance(node, dict) and node.get(POST_EXEC_FIELD):
            found.append((list(node[POST_EXEC_FIELD]), path))
    if len(found) == 2 and sorted(found[0][0]) != sorted(found[1][0]):
        raise ValueError(f"{POST_EXEC_FIELD} is set in two places and they differ")
    return found[0] if found else ([], ())


def without_post_execution(agent: dict) -> dict:
    """A deep copy with the post-execution field removed from both candidate locations, for 'nothing else in the
    agent's definition changed' (6.3 B2, N3)."""
    import copy
    out = copy.deepcopy(agent)
    for path in POST_EXEC_LOCATIONS:
        node: Any = out
        for k in path:
            node = node.get(k) if isinstance(node, dict) else None
        if isinstance(node, dict):
            node.pop(POST_EXEC_FIELD, None)
    return out
