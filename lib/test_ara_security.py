"""Offline tests for ara_security.py. The _execute shapes are the ones Phase 0 r2 recorded
(mc8tzideei1c): an ES|QL error result naming an FLS-hidden column, an index search resource_list,
a workflow run that completes or fails at its write step, and a key without workflow_execute."""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import ara_security as S  # noqa: E402


class FakeAB:
    def __init__(self, code, body, executions=None):
        self.code, self.body, self.executions = code, body, executions or {}
        self.calls = []

    def request(self, method, path, body=None, ok_codes=()):
        self.calls.append((method, path, body, ok_codes))
        return self.code, self.body

    def wait_execution(self, execution_id, budget_s=30):
        return self.executions.get(execution_id)


def ex(results, code=200, executions=None, **kw):
    return S.execute_outcome(FakeAB(code, {"results": results}, executions), "cortex.t", {}, **kw)


def test_esql_rows_no_rows_and_hidden_field():
    rows = [{"type": "query", "data": {}}, {"type": "esql_results", "data": {
        "columns": [{"name": "case_id"}, {"name": "risk_tier"}], "values": [["C1", "low"], ["C2", "medium"]]}}]
    o = ex(rows, id_field="case_id")
    assert o["class"] == "rows" and o["ids"] == ["C1", "C2"] and o["fields"] == ["case_id", "risk_tier"]
    assert ex([{"type": "esql_results", "data": {"columns": [{"name": "case_id"}], "values": []}}])["class"] == "no_rows"
    err = ("verification_exception\n\tRoot causes:\n\t\tverification_exception: Found 2 problems\n"
           "line 1:95: Unknown column [subject_name]\nline 1:109: Unknown column [subject_tin]")
    o = ex([{"type": "error", "data": {"message": err}}])
    assert o["class"] == "error_hidden_field" and "subject_tin" in o["error"]


def test_index_search_reads_reference_ids():
    res = [{"type": "resource_list", "data": {"resources": [
        {"reference": {"id": "C003", "index": "cortex-cases"}, "partial": True,
         "content": {"snippets": ["Case 3: structuring review"]}},
        {"reference": {"id": "C002", "index": "cortex-cases"}, "content": {"title": "x", "subject_tin": "900-55-0002"}}]}}]
    o = ex(res)
    assert o["class"] == "rows" and o["ids"] == ["C002", "C003"] and "subject_tin" in o["fields"]
    assert ex([{"type": "resource_list", "data": {"resources": []}}])["class"] == "no_rows"


def test_workflow_outcomes_and_the_403_is_an_observation():
    run = lambda st: [{"type": "other", "data": {"execution": {"execution_id": "e1", "status": st}}}]
    assert ex(run("completed"))["class"] == "rows"
    assert ex(run("failed"))["class"] == "error_at_write"
    # read through the admin client: a failure the environment explains has no class
    admin = FakeAB(200, {}, {"e1": {"id": "e1", "status": "failed", "error": "HTTP 503 Service Unavailable"}})
    assert S.execute_outcome(FakeAB(200, {"results": run("running")}), "t", {}, admin_ab=admin)["class"] is None
    admin.executions["e1"] = {"id": "e1", "status": "failed", "stepExecutions": [
        {"stepId": "write_case", "status": "failed", "error": "security_exception: action [indices:data/write/index] is unauthorized"}]}
    assert S.execute_outcome(FakeAB(200, {"results": run("running")}), "t", {}, admin_ab=admin)["class"] == "error_at_write"
    msg = "Unauthorized to execute workflow 'cortex-open-case'. The 'workflowsManagement' execute privilege is required."
    assert ex([{"type": "error", "data": {"message": msg}}])["class"] == "error_not_authorized"
    fab = FakeAB(403, {"error": "Forbidden"})
    assert S.execute_outcome(fab, "t", {})["class"] == "error_not_authorized"
    assert fab.calls[0][3] == (403,)


def test_unknown_shapes_have_no_class():
    assert ex([{"type": "error", "data": {"message": "something else"}}])["class"] is None
    assert ex([], code=400)["class"] is None


def test_descriptors_compare_whatever_the_order_and_defaults():
    a = {"cortex-analyst-l1": {"cluster": ["monitor_inference"], "indices": [
        {"names": ["cortex-sar-narratives", "cortex-cases"], "privileges": ["view_index_metadata", "read"],
         "query": '{"terms": {"risk_tier": ["low", "medium"]}}',
         "field_security": {"grant": ["*"], "except": ["subject_tin", "subject_name", "subject_account"]}}],
        "applications": [{"application": "kibana-.kibana", "resources": ["*"],
                          "privileges": ["feature_agentBuilder.read", "feature_actions.read"]}]}}
    b = {"other-name": {"cluster": ["monitor_inference"], "run_as": [], "metadata": {}, "indices": [
        {"names": ["cortex-cases", "cortex-sar-narratives"], "privileges": ["read", "view_index_metadata"],
         "query": {"terms": {"risk_tier": ["low", "medium"]}}, "allow_restricted_indices": False,
         "field_security": {"grant": ["*"], "except": ["subject_account", "subject_name", "subject_tin"]}}],
        "applications": [{"application": "kibana-.kibana", "resources": ["*"],
                          "privileges": ["feature_actions.read", "feature_agentBuilder.read"]}]}}
    assert S.same_descriptors(a, b)
    b["other-name"]["indices"][0]["field_security"]["except"].pop()
    assert not S.same_descriptors(a, b)


def test_mint_refuses_an_api_key_admin():
    try:
        S.mint_key(S.ES("http://x", S.api_key_auth("k")), "n", {})
    except ValueError as e:
        assert "basic auth" in str(e)
    else:
        raise AssertionError("minted with an API key")


def test_diff_prediction_and_contains_any():
    obs = {"documents": {"C1": "retrievable", "C9": "blocked"}, "fields": {"subject_tin": "hidden"},
           "calls": {"case_lookup": "error_hidden_field"}}
    pred = {"documents": {"C1": "retrievable", "C9": "retrievable"}, "fields": {"subject_tin": "hidden"},
            "calls": {"case_lookup": "rows"}}
    d = S.diff_prediction(pred, obs)
    assert [(x["section"], x["item"]) for x in d] == [("documents", "C9"), ("calls", "case_lookup")]
    assert S.diff_prediction(obs, obs) == []
    assert S.contains_any({"a": ["900-55-0003"]}, ["900-55-0003", "C9"]) == ["900-55-0003"]


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  ok    {fn.__name__}")
