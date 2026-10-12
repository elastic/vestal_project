"""Unit tests for ara_actions (table 5.1) on the shipped 4.4 workflows and the 4.2 workflows.

    python3 -m pytest lib/test_ara_actions.py
"""
import pathlib

import ara_actions as A

WF = pathlib.Path(__file__).resolve().parent.parent / "manifests" / "m4" / "workflows"
HOSTS = {"project.es.example.cloud", "project.kb.example.cloud"}


def tool(tid, wid):
    return {"id": tid, "type": "workflow", "configuration": {"workflow_id": wid}}


def cls(tid, wid):
    return A.classify_tool(tool(tid, wid), (WF / f"{wid}.yml").read_text(), HOSTS)


def test_esql_is_read_only():
    out = A.classify_tool({"id": "cortex.structuring_deposits", "type": "esql"}, None, HOSTS)
    assert (out["class"], out["reason"]) == ("read-only", "queries Cortex data and writes nothing")


def test_sar_filing_is_irreversible():
    assert cls("cortex.file_sar", "cortex-file-sar")["reason"] == "transmits a SAR, which cannot be withdrawn"


def test_seeded_tools():
    assert cls("cortex.flag_for_review", "cortex-flag-for-review")["class"] == "side-effecting"
    assert cls("cortex.freeze_account", "cortex-freeze-account")["class"] == "side-effecting"
    out = cls("cortex.share_with_partner_bank", "cortex-share-with-partner-bank")
    assert (out["class"], out["reason"]) == ("irreversible", "sends data outside Cortex")


def test_case_and_escalation_are_side_effecting():
    assert cls("cortex.open_case", "cortex-open-case")["class"] == "side-effecting"
    assert cls("cortex.escalate", "cortex-escalate")["class"] == "side-effecting"


def test_gated_sar_stays_irreversible():
    y = ("steps:\n  - name: ok\n    type: waitForApproval\n  - name: gate\n    type: if\n"
         "    condition: \"steps.ok.output.response.approved : true\"\n    steps:\n      - name: file_sar\n"
         "        type: elasticsearch.index\n        with:\n          index: cortex-sar-filings\n"
         "    else:\n      - name: note\n        type: elasticsearch.index\n        with:\n          index: cortex-audit\n")
    eff = A.workflow_effects(y, HOSTS)
    assert eff["writes"] == ["cortex-sar-filings", "cortex-audit"]


def test_http_to_project_host_stays_inside():
    y = 'steps:\n  - name: s\n    type: http\n    with:\n      url: https://project.kb.example.cloud/api/x\n      method: POST\n'
    eff = A.workflow_effects(y, HOSTS)
    assert eff["sends"] == [] and eff["reads"] == []


READ_PAGE = ('steps:\n  - name: read\n    type: http\n    connector-id: cortex-jina-reader\n    with:\n'
             '      method: GET\n      path: "/{{ inputs.url }}"\n')


def test_read_page_through_connector_is_read_only():
    tool = {"id": "cortex.read_page", "type": "workflow", "configuration": {"workflow_id": "cortex-read-page"}}
    out = A.classify_tool(tool, READ_PAGE, HOSTS, {"cortex-jina-reader": "r.jina.ai"})
    assert (out["class"], out["reason"]) == ("read-only", "reads a web page on the open internet and writes nothing")
    assert "r.jina.ai" in out["evidence"]


def test_get_with_body_or_post_sends():
    post = READ_PAGE.replace("method: GET", "method: POST")
    body = READ_PAGE + '      body:\n        account_id: "{{ inputs.account_id }}"\n'
    for y in (post, body):
        assert A.workflow_effects(y, HOSTS, {"cortex-jina-reader": "r.jina.ai"})["sends"] == ["r.jina.ai"]


def test_templated_host_is_outside():
    y = 'steps:\n  - name: s\n    type: http\n    with:\n      url: "https://{{ inputs.host }}/x"\n'
    assert A.workflow_effects(y, HOSTS)["reads"] == ["<unknown host>"]


def test_read_and_write_is_side_effecting():
    y = READ_PAGE + "  - name: note\n    type: elasticsearch.index\n    with:\n      index: cortex-audit\n"
    tool = {"id": "x", "type": "workflow", "configuration": {"workflow_id": "x"}}
    assert A.classify_tool(tool, y, HOSTS, {"cortex-jina-reader": "r.jina.ai"})["class"] == "side-effecting"


GATED = ("steps:\n  - name: ok\n    type: waitForApproval\n  - name: gate\n    type: if\n"
         "    condition: \"steps.ok.output.response.approved : true\"\n    steps:\n      - name: file_sar\n"
         "        type: elasticsearch.index\n        with:\n          index: cortex-sar-filings\n"
         "  - name: note\n    type: elasticsearch.index\n    with:\n      index: cortex-audit\n")


def shape(y):
    import yaml
    return A.gate_shape(yaml.safe_load(y), "cortex-sar-filings", "cortex-audit")


def test_gate_shape_reference():
    s = shape(GATED)
    assert s["gated"] and s["audit_both"] and s["approval"] == "ok"
    assert A.has_approval(GATED)


def test_gate_shape_no_if_and_ungated():
    no_if = ("steps:\n  - name: ok\n    type: waitForApproval\n  - name: file_sar\n    type: elasticsearch.index\n"
             "    with:\n      index: cortex-sar-filings\n")
    s = shape(no_if)
    assert s["gate_index"] is None and s["write_anywhere"] and "gated" not in s
    ungated = (WF / "cortex-file-sar.yml").read_text()
    assert shape(ungated)["approval"] is None and not A.has_approval(ungated)


def test_gate_shape_write_outside_if():
    y = GATED + "  - name: again\n    type: elasticsearch.index\n    with:\n      index: cortex-sar-filings\n"
    s = shape(y)
    assert s["write_in_then"] and s["write_elsewhere"] and not s["gated"]


def test_controls_cover_classes():
    assert set(A.CONTROLS) == set(A.CLASSES)
    assert set(A.REASONS.values()) <= set(A.CLASSES)
