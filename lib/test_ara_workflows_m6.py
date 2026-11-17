"""The provided M6 workflow definitions: they parse, carry no scheduled trigger, and the reader sees what the checks read."""
import pathlib
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ara_workflow as AW  # noqa: E402
import ara_workflows_m6 as W  # noqa: E402

yaml = pytest.importorskip("yaml")
START = datetime(2026, 11, 11, tzinfo=timezone.utc)
ALL = {"evaluator": W.evaluator_run_yaml("inf-1"), "canary": W.canary_run_yaml(), "audit": W.answer_audit_yaml()}


def test_every_definition_parses_has_a_manual_trigger_and_no_schedule():
    for name, text in ALL.items():
        d = yaml.safe_load(text)
        assert d["version"] == "1" and d["enabled"] is True and d["triggers"] == [{"type": "manual"}], name
        assert W.scheduled_triggers(text) == [] and AW.scheduled(d) == [] and AW.expand(d, START, START.replace(day=18)) == [], name
        assert not AW.has_interval(d)


def test_evaluator_skeleton_has_the_two_placeholders_and_the_pinned_step():
    d = yaml.safe_load(ALL["evaluator"])
    assert W.input_names(ALL["evaluator"]) == ["window_start", "window_end"]
    [step] = AW.ai_agent_steps(d)
    assert step["agent_id"] == "cortex-evaluator" and step["inference_id"] == "inf-1"
    assert step["message"] == W.PLACEHOLDER_MESSAGE and step["schema"] == W.PLACEHOLDER_SCHEMA
    assert W.placeholders_left(ALL["evaluator"]) == [W.PLACEHOLDER_MESSAGE, W.PLACEHOLDER_SCHEMA]
    filled = ALL["evaluator"].replace(W.PLACEHOLDER_MESSAGE, "Review the week.").replace(W.PLACEHOLDER_SCHEMA, "{}")
    assert W.placeholders_left(filled) == []
    write = d["steps"][1]["steps"][0]
    assert write["type"] == "elasticsearch.index" and write["with"]["index"] == "cortex-eval-proposals"
    doc = write["with"]["document"]
    assert set(W.PROPOSAL_FIELDS) <= set(doc) and {"run_id", "proposal_id", "status"} <= set(doc)
    assert "execution.id" in doc["run_id"] and d["steps"][1]["foreach"].find(W.STRUCTURED_OUTPUT_PATH) > 0


def test_canary_asks_in_fresh_conversations_and_records_the_canary_fields():
    d = yaml.safe_load(ALL["canary"])
    assert W.input_names(ALL["canary"]) == ["change_id"] and d["inputs"][0]["required"] is False
    [step] = AW.ai_agent_steps(d)
    assert step["agent_id"] == "tina-compliance" and step["create_conversation"] is True
    doc = d["steps"][1]["steps"][1]["with"]["document"]
    assert {"question_id", "conversation_id", "workflow_execution_id", "triggered_by", "change_id", "run_label", "testset_version"} <= set(doc)
    assert doc["run_label"].startswith("canary-") and doc["testset_version"] == "canary-v1"


def test_audit_declares_the_post_execution_inputs_and_writes_only_for_sar_answers():
    d = yaml.safe_load(ALL["audit"])
    assert W.input_names(ALL["audit"]) == ["round_id", "conversation_id", "agent_id", "tool_calls"]
    loop = d["steps"][0]
    assert loop["type"] == "foreach" and loop["foreach"] == "{{ inputs.tool_calls }}"
    cond = loop["steps"][0]
    assert cond["type"] == "if" and cond["condition"] == "foreach.item.tool_id : cortex.sar_search"
    w = cond["steps"][0]["with"]
    assert set(w["document"]) == {"round_id", "conversation_id", "audited_at"} and w["index"] == "cortex-audit"
    assert w["id"] == "{{ inputs.round_id }}"  # one record per round whatever number of calls match
    assert W.step_names(ALL["audit"]) == ["each_call", "only_sar_answers", "write_audit"]
