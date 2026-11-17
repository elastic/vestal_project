"""ara_monitor.py - the monitor reader (28 section 1, probe P8): read an alert rule's definition and run its
ES|QL query over a named window. Pure parsing over `GET /api/alerting/rule/<id>` responses and `_query` responses;
the HTTP calls are injected, never made here.

    read_rule(resp)                      rule type, ES|QL text, time field, schedule seconds, alert delay, enabled
    query_body(rule, start, end)         the `_query` body: the rule's query with a range filter on its time field
    rows(resp)                           a `_query` response -> list of row dicts
    run_window(rule, run_query, a, b)    rows the query returns over [a, b)
    would_alert(rule, windows)           alert times for a list of run results, honouring alert_delay.active
    simulate(rule, run_query, a, b, window_s)   runs at each schedule tick; returns (alert time or None, runs)

An ES|QL rule creates one alert per returned row; `alert_delay.active` is the number of consecutive runs that must
match before the alert fires (default 1). Standard library only.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

ESQL_TYPE = ".es-query"
_UNIT = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def interval_seconds(text: Any) -> int:
    m = re.fullmatch(r"\s*(\d+)\s*([smhd])\s*", str(text or ""))
    if not m:
        raise ValueError(f"unreadable interval {text!r}")
    return int(m.group(1)) * _UNIT[m.group(2)]


def read_rule(resp: dict) -> dict:
    """The fields the 6.C check grades. Raises ValueError, naming the field, when the rule is not an ES|QL rule."""
    params = resp.get("params") or {}
    if resp.get("rule_type_id") != ESQL_TYPE or params.get("searchType") != "esqlQuery":
        raise ValueError("the rule is not an ES|QL rule (rule type .es-query with searchType esqlQuery)")
    q = params.get("esqlQuery")
    esql = q.get("esql") if isinstance(q, dict) else q
    if not isinstance(esql, str) or not esql.strip():
        raise ValueError("the rule has no ES|QL query")
    delay = (resp.get("alert_delay") or {}).get("active")
    return {"id": resp.get("id"), "name": resp.get("name"), "enabled": bool(resp.get("enabled", True)),
            "esql": esql, "time_field": params.get("timeField"),
            "schedule_seconds": interval_seconds((resp.get("schedule") or {}).get("interval")),
            "alert_delay_active": int(delay) if delay else 1,
            "threshold": params.get("threshold"), "threshold_comparator": params.get("thresholdComparator")}


def _iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def query_body(rule: dict, start: datetime, end: datetime) -> dict:
    """The `_query` body for a window: the rule's query unchanged, with a range filter on the rule's time field
    (gte start, lt end). Raises ValueError when the rule has no time field to bound the window by."""
    if not rule.get("time_field"):
        raise ValueError("the rule has no time field, so its query cannot be bounded to a window")
    return {"query": rule["esql"],
            "filter": {"range": {rule["time_field"]: {"gte": _iso(start), "lt": _iso(end), "format": "strict_date_optional_time"}}}}


def rows(resp: dict) -> list[dict]:
    cols = [c["name"] for c in resp.get("columns", [])]
    return [dict(zip(cols, v)) for v in resp.get("values", [])]


def run_window(rule: dict, run_query: Callable[[dict], dict], start: datetime, end: datetime) -> list[dict]:
    return rows(run_query(query_body(rule, start, end)))


def would_alert(rule: dict, matches: list[bool]) -> int | None:
    """Index of the first run that fires, given whether each consecutive run matched, or None. The alert needs
    `alert_delay_active` consecutive matching runs."""
    need, streak = rule["alert_delay_active"], 0
    for i, m in enumerate(matches):
        streak = streak + 1 if m else 0
        if streak >= need:
            return i
    return None


def simulate(rule: dict, run_query: Callable[[dict], dict], start: datetime, end: datetime,
             window_s: int | None = None) -> tuple[datetime | None, list[tuple[datetime, int]]]:
    """Run the rule at every schedule tick from start (the first run is one interval after start) to end, each
    over the window_s seconds before the tick (default: the schedule interval). Returns the time of the first
    alert, or None, and (tick, matching rows) per run."""
    step = timedelta(seconds=rule["schedule_seconds"])
    span = timedelta(seconds=window_s or rule["schedule_seconds"])
    runs: list[tuple[datetime, int]] = []
    t = start + step
    while t <= end:
        runs.append((t, len(run_window(rule, run_query, t - span, t))))
        t += step
    i = would_alert(rule, [n > 0 for _, n in runs])
    return (runs[i][0] if i is not None else None), runs
