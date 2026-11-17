"""Offline tests for ara_monitor.py over fixture alerting and _query responses (shape from probe P8)."""
import pathlib
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ara_monitor as M  # noqa: E402

RULE = {"id": "r1", "name": "canary drop", "enabled": True, "rule_type_id": ".es-query",
        "schedule": {"interval": "5m"}, "alert_delay": {"active": 2},
        "params": {"searchType": "esqlQuery", "timeField": "@timestamp", "threshold": [0], "thresholdComparator": ">",
                   "esqlQuery": {"esql": "FROM cortex-eval-runs | WHERE testset_version == \"canary-v1\" | STATS acc = AVG(score) | WHERE acc < 0.7"}}}
T0 = datetime(2026, 11, 10, 3, 0, tzinfo=timezone.utc)


def test_read_rule():
    r = M.read_rule(RULE)
    assert r["esql"].startswith("FROM cortex-eval-runs") and r["time_field"] == "@timestamp"
    assert r["schedule_seconds"] == 300 and r["alert_delay_active"] == 2 and r["enabled"]
    assert M.read_rule({**RULE, "alert_delay": None})["alert_delay_active"] == 1
    assert M.read_rule({**RULE, "params": {**RULE["params"], "esqlQuery": "FROM x"}})["esql"] == "FROM x"


def test_read_rule_rejects_non_esql_and_empty():
    for bad in ({**RULE, "rule_type_id": ".index-threshold"},
                {**RULE, "params": {**RULE["params"], "searchType": "esQuery"}},
                {**RULE, "params": {**RULE["params"], "esqlQuery": {"esql": " "}}}):
        try:
            M.read_rule(bad)
        except ValueError:
            continue
        raise AssertionError(bad)
    try:
        M.read_rule({**RULE, "schedule": {"interval": "5 fortnights"}})
    except ValueError:
        pass
    else:
        raise AssertionError


def test_query_body_range_filter_on_time_field():
    b = M.query_body(M.read_rule(RULE), T0, T0 + timedelta(hours=3))
    assert b["query"].startswith("FROM") and b["filter"]["range"]["@timestamp"] == {
        "gte": "2026-11-10T03:00:00.000Z", "lt": "2026-11-10T06:00:00.000Z", "format": "strict_date_optional_time"}
    r = M.read_rule(RULE)
    r["time_field"] = None
    try:
        M.query_body(r, T0, T0)
    except ValueError:
        pass
    else:
        raise AssertionError


def test_rows():
    assert M.rows({"columns": [{"name": "a"}, {"name": "b"}], "values": [[1, 2], [3, 4]]}) == [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
    assert M.rows({}) == []


def test_would_alert_needs_consecutive_runs():
    r = M.read_rule(RULE)
    assert M.would_alert(r, [True, False, True, False]) is None
    assert M.would_alert(r, [False, True, True]) == 2
    assert M.would_alert({**r, "alert_delay_active": 1}, [False, True]) == 1


def test_simulate_fires_before_the_deadline_only_on_the_bad_night():
    r = M.read_rule(RULE)
    bad_from = T0 + timedelta(minutes=20)

    def runner(body):
        lo = datetime.fromisoformat(body["filter"]["range"]["@timestamp"]["gte"].replace("Z", "+00:00"))
        return {"columns": [{"name": "acc"}], "values": [[0.5]] if lo >= bad_from else []}

    at, runs = M.simulate(r, runner, T0, T0 + timedelta(hours=1))
    assert len(runs) == 12 and at == T0 + timedelta(minutes=30)  # first match at the 25 min tick, second at 30
    at, _ = M.simulate(r, lambda b: {"columns": [], "values": []}, T0, T0 + timedelta(hours=1))
    assert at is None
