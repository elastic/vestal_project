"""Offline tests for ara_workflow.py over fixture workflow definitions and execution lists."""
import pathlib
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ara_workflow as W  # noqa: E402

UTC = timezone.utc
START = datetime(2026, 11, 9, 0, 0, tzinfo=UTC)  # a Monday
END = START + timedelta(days=7)


def rule(**kw):
    return {"type": "scheduled", "with": {"rrule": {"freq": "DAILY", "interval": 1, **kw}}}


def hours_utc(defn):
    return [t.strftime("%a %H:%M") for t in W.expand(defn, START, END)]


def test_one_rule_with_three_hours_equals_three_rules():
    one = {"triggers": [{"type": "manual"}, rule(byhour=[6, 14, 22], byminute=[0], tzid="America/New_York")]}
    three = {"triggers": [rule(byhour=[h], byminute=[0], tzid="America/New_York") for h in (22, 6, 14)]}
    a = W.expand(one, START, END)
    assert a == W.expand(three, START, END) and len(a) == 21
    # November 9 is standard time in New York (UTC-5): 06:00 local is 11:00 UTC
    assert a[0] == datetime(2026, 11, 9, 3, 0, tzinfo=UTC)  # 22:00 on Nov 8 local
    assert a[1] == datetime(2026, 11, 9, 11, 0, tzinfo=UTC)


def test_tzid_matters_and_defaults_to_utc():
    ny = W.expand({"triggers": [rule(byhour=[6], byminute=[0], tzid="America/New_York")]}, START, END)
    utc = W.expand({"triggers": [rule(byhour=[6], byminute=[0])]}, START, END)
    assert ny != utc and utc[0] == datetime(2026, 11, 9, 6, 0, tzinfo=UTC)
    assert W.scheduled({"triggers": [rule(byhour=[6])]})[0]["tzid"] == "UTC"


def test_dst_moves_utc_not_local():
    # clocks in New York go back on 2026-11-01; across it the UTC hour of a 06:00 local rule changes
    s, e = datetime(2026, 10, 30, tzinfo=UTC), datetime(2026, 11, 4, tzinfo=UTC)
    got = [t.hour for t in W.expand({"triggers": [rule(byhour=[6], byminute=[0], tzid="America/New_York")]}, s, e)]
    assert got == [10, 10, 11, 11, 11]


def test_window_is_half_open_and_ordered():
    t = {"triggers": [rule(byhour=[0], byminute=[0])]}
    occ = W.expand(t, START, END)
    assert occ[0] == START and occ[-1] == END - timedelta(days=1) and len(occ) == 7


def test_interval_trigger():
    d = {"triggers": [{"type": "scheduled", "with": {"every": "1m"}}, {"type": "manual"}]}
    assert W.has_interval(d) and not W.has_interval({"triggers": [rule(byhour=[1])]})
    occ = W.expand(d, START, START + timedelta(minutes=5))
    assert len(occ) == 4 and occ[0] == START + timedelta(minutes=1)
    assert W.triggers(d)[1] == {"type": "manual"}


def test_weekly_and_monthly():
    wk = {"triggers": [{"type": "scheduled", "with": {"rrule": {"freq": "WEEKLY", "byweekday": ["MO", "FR"], "byhour": [9]}}}]}
    assert [t.strftime("%a") for t in W.expand(wk, START, END)] == ["Mon", "Fri"]
    mo = {"triggers": [{"type": "scheduled", "with": {"rrule": {"freq": "MONTHLY", "bymonthday": [15], "byhour": [9]}}}]}
    assert [t.day for t in W.expand(mo, START, datetime(2027, 2, 1, tzinfo=UTC))] == [15, 15, 15]
    biweekly = {"triggers": [{"type": "scheduled", "with": {"rrule": {"freq": "WEEKLY", "interval": 2, "byweekday": ["MO"], "byhour": [9]}}}]}
    assert len(W.expand(biweekly, START, START + timedelta(days=28))) == 2


def test_bad_rules_raise_or_expand_to_nothing():
    for bad in ({"freq": "HOURLY"}, {"freq": "DAILY", "byweekday": ["XX"]}):
        try:
            W.triggers({"triggers": [{"type": "scheduled", "with": {"rrule": bad}}]})
        except ValueError:
            continue
        raise AssertionError(bad)
    assert W.expand({"triggers": [{"type": "scheduled", "with": {"cron": "* * * * *"}}]}, START, END) == []
    assert W.expand({"triggers": []}, START, END) == []


EXECS = {"results": [
    {"id": "e1", "workflowId": "cortex-canary-run", "triggeredBy": "scheduled", "startedAt": "2026-11-10T06:00:01Z", "status": "completed", "inputs": {}},
    {"id": "e2", "workflowId": "cortex-canary-run", "triggeredBy": "manual", "startedAt": "2026-11-10T06:05:00Z", "status": "completed", "inputs": {"change_id": "chg-1"}},
    {"id": "e3", "workflowId": "cortex-answer-audit", "triggeredBy": "scheduled", "startedAt": "2026-11-09T06:00:00Z", "status": "failed"},
]}


def test_executions_and_filters():
    ex = W.executions(EXECS)
    assert len(ex) == 3 and ex[2]["inputs"] == {} and ex[0]["started_at"] == datetime(2026, 11, 10, 6, 0, 1, tzinfo=UTC)
    ids = lambda **kw: [e["id"] for e in W.filter_executions(ex, **kw)]
    assert ids(workflow_id="cortex-canary-run", triggered_by="scheduled") == ["e1"]
    assert ids(after=datetime(2026, 11, 10, 6, 0, 1, tzinfo=UTC)) == ["e2"]
    assert ids(change_id="chg-1") == ["e2"] and ids(status="failed") == ["e3"] and ids() == ["e1", "e2", "e3"]
    assert W.executions([]) == [] and W.executions({"items": EXECS["results"][:1]})[0]["id"] == "e1"


def test_ai_agent_steps_read_nested_and_both_field_homes():
    defn = {"steps": [
        {"name": "ask", "type": "ai.agent", "agent-id": "cortex-evaluator", "inference-id": "cortex-evaluator-model",
         "with": {"message": "m", "schema": {"type": "object"}}},
        {"name": "each", "type": "foreach", "steps": [{"name": "w", "type": "elasticsearch.index"},
                                                      {"name": "inner", "type": "ai.agent", "with": {"agent_id": "x", "create-conversation": True}}]}]}
    a, b = W.ai_agent_steps(defn)
    assert (a["agent_id"], a["inference_id"], a["message"], a["schema"]) == ("cortex-evaluator", "cortex-evaluator-model", "m", {"type": "object"})
    assert b["name"] == "inner" and b["agent_id"] == "x" and b["create_conversation"] is True and b["inference_id"] is None
    assert W.ai_agent_steps({}) == []


def test_post_execution_ids_live_at_configuration_only():
    """P6 (probe r2): the platform refuses the field at the top level, so only configuration.post_execution_workflow_ids counts."""
    nested = {"id": "tina", "configuration": {"post_execution_workflow_ids": ["cortex-answer-audit"]}}
    assert W.post_execution_ids(nested) == (["cortex-answer-audit"], ("configuration",))
    assert W.post_execution_ids({"id": "tina", "configuration": {}}) == ([], ())
    assert W.post_execution_ids({"id": "tina", "post_execution_workflow_ids": ["x"]}) == ([], ())


def test_without_post_execution_compares_the_rest_of_the_definition():
    before = {"id": "tina", "configuration": {"instructions": "i"}}
    after = {"id": "tina", "configuration": {"instructions": "i", "post_execution_workflow_ids": ["a"]}}
    assert W.without_post_execution(after) == before
    assert "post_execution_workflow_ids" in after["configuration"]  # not mutated
