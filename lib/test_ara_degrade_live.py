"""ara_degrade_live: plans as data, a fake client, and the fixed-state rules."""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ara_degrade_live as D  # noqa: E402

MANUAL = [{"chunk_id": f"policy-{i // 8:03d}-s{i}", "body": f"Section {i}: the bank must file within {i} days.", "body_text": f"Section {i}", "title": "t"} for i in range(89)]
MAPPING = {"mappings": {"properties": {"body": {"type": "semantic_text", "inference_id": "old"}, "body_text": {"type": "text"}}}}
AT = "2026-11-11T05:00:00.000Z"
D._sleep = lambda s: None   # no real waiting in tests


class Fake:
    def __init__(self, fail_at=None):
        self.calls, self.fail_at = [], fail_at

    def _do(self, m, p, text=None):
        self.calls.append((m, p))
        if text:   # what a bulk loaded, per index, so a COUNT after it reads what was really sent
            if not hasattr(self, "loaded"):
                self.loaded = {}
            for line in text.strip().split("\n")[::2]:
                act = json.loads(line)
                idx = next(iter(act.values())).get("_index") or p.split("/")[1]
                self.loaded[idx] = self.loaded.get(idx, 0) + 1
        if self.fail_at and self.fail_at in p:
            return 500, {"error": "boom"}
        if p.endswith("/_count"):
            return 200, {"count": getattr(self, "loaded", {}).get(p.split("/")[1], 0)}
        return 200, {}

    def request(self, m, p, body=None): return self._do(m, p)
    def request_ndjson(self, m, p, text): return self._do(m, p, text)


def test_l1_adds_forty_faq_chunks_and_reverts_by_doc_type():
    plan = D.plan_l1(MANUAL, AT, "s1")
    assert len(plan["docs"]) == 40 and all(d["doc_type"] == "faq" for d in plan["docs"])
    assert plan["docs"] == D.plan_l1(MANUAL, AT, "s1")["docs"] != D.plan_l1(MANUAL, AT, "s2")["docs"]
    lines = plan["apply"][0]["ndjson"].strip().split("\n")
    assert len(lines) == 80 and json.loads(lines[0])["create"]["_id"] == "faq-001"
    assert plan["revert"][0]["body"] == {"query": {"term": {"doc_type": "faq"}}}
    assert len(plan["change_log"]) == 2 and plan["change_log"][0]["cause"] and not plan["change_log"][1]["cause"]
    assert plan["change_log"][0]["at"] == plan["change_log"][1]["at"]


def test_l2_splits_89_chunks_once_each_and_uses_two_endpoints():
    plan = D.plan_l2(MANUAL, MAPPING, "old", "new", AT, "s1")
    assert sorted(plan["v1"] + plan["v2"]) == sorted(m["chunk_id"] for m in MANUAL) and not set(plan["v1"]) & set(plan["v2"])
    puts = [o for o in plan["apply"] if o["method"] == "PUT"]
    assert puts[0]["body"]["mappings"]["properties"]["body"]["inference_id"] == "old"
    assert puts[1]["body"]["mappings"]["properties"]["body"]["inference_id"] == "new"
    assert MAPPING["mappings"]["properties"]["body"]["inference_id"] == "old"
    order = [(o["method"], o["path"]) for o in plan["apply"]]
    assert order.index(("DELETE", "/cortex-policies")) < order.index(("POST", "/_aliases"))
    more, _ = D.split_ids([m["chunk_id"] for m in MANUAL], 0.7, "s1")
    assert set(plan["v2"]) <= set(more)


def test_l3_keeps_before_and_after_and_reverts_to_the_original():
    tool = {"id": "cortex.escalate", "type": "workflow", "description": "Escalate out-of-scope requests.", "tags": [], "configuration": {"workflow_id": "w"}, "created_at": "x"}
    plan = D.plan_l3(tool, AT, "s1")
    assert plan["before"] == tool["description"] and plan["after"].startswith(tool["description"]) and plan["after"] != plan["before"]
    assert plan["apply"][0]["body"]["description"] == plan["after"] and "created_at" not in plan["apply"][0]["body"]
    assert plan["revert"][0]["body"]["description"] == plan["before"]
    assert plan["change_log"][0]["before"] == plan["before"] and plan["change_log"][0]["after"] == plan["after"]


def test_execute_stops_at_the_first_refusal_and_tolerates_a_missing_delete():
    plan = D.plan_l2(MANUAL, MAPPING, "old", "new", AT)
    c = Fake(fail_at="-v2/_bulk")
    try:
        D.execute(c, plan["apply"])
        raise AssertionError("expected PlanFailed")
    except D.PlanFailed as e:
        assert "HTTP 500" in str(e) and "-v2/_bulk" in str(e) and "after 4 attempts" in str(e)
    assert ("DELETE", "/cortex-policies") not in c.calls
    class Missing(Fake):
        def _do(self, m, p, text=None): return (404, {}) if m == "DELETE" else (200, {})
    assert len(D.execute(Missing(), plan["revert"])) == 4


def test_bulk_errors_in_a_200_are_failures():
    class Err(Fake):
        def request_ndjson(self, m, p, text): return 200, {"errors": True, "items": [{"create": {"error": {"reason": "mapping"}}}]}
    try:
        D.execute(Err(), D.plan_l1(MANUAL, AT)["apply"])
        raise AssertionError("expected PlanFailed")
    except D.PlanFailed as e:
        assert "bulk had errors" in str(e)


def test_fixed_state_rules():
    ids = [m["chunk_id"] for m in MANUAL]
    assert D.endpoint_uniform({"a": "new", "b": "new"}, ids, ids) == []
    assert "different inference endpoints" in D.endpoint_uniform({"a": "old", "b": "new"}, ids, ids)[0]
    assert "missing" in D.endpoint_uniform({"a": "new"}, ids[:-1], ids)[0]
    assert "more than once" in D.endpoint_uniform({"a": "new"}, ids + ids[:2], ids)[0]
    assert D.faq_reachable({"q1": [{"chunk_id": "faq-004"}], "q2": [{"chunk_id": "policy-001-s3"}], "q3": [{"doc_type": "faq"}]}) == ["q1", "q3"]
    assert D.l3_restored("Escalate  out-of-scope\nrequests. ", "Escalate out-of-scope requests.") and not D.l3_restored("x", "y")


def test_c1_loads_thirty_draft_chunks_and_reverts_by_draft_type():
    plan = D.plan_c1(MANUAL, AT, "s1")
    assert plan["layer"] == "C1" and len(plan["docs"]) == 30 and all(d["doc_type"] == "draft" and d["body"].startswith("DRAFT") for d in plan["docs"])
    assert plan["revert"][0]["body"] == {"query": {"term": {"doc_type": "draft"}}} and plan["key"]["doc_type"] == "draft"
    assert D.plan_l1(MANUAL, AT, "s1")["docs"][0]["doc_type"] == "faq"


def test_c3_appends_one_instruction_and_reverts_exactly():
    agent = {"id": "tina-compliance", "name": "Tina", "created_at": "x", "configuration": {"instructions": "HARDENING\nBe brief.\n", "tools": [{"tool_ids": ["a"]}]}}
    plan = D.plan_c3(agent, AT, "s1")
    assert plan["after"] == "HARDENING\nBe brief.\n" + D.C3_SENTENCE and plan["before"] == agent["configuration"]["instructions"]
    body = plan["apply"][0]["body"]
    assert body["configuration"]["instructions"] == plan["after"] and body["configuration"]["tools"] == [{"tool_ids": ["a"]}] and "created_at" not in body and "id" not in body
    assert plan["revert"][0]["body"]["configuration"]["instructions"] == plan["before"]
    assert agent["configuration"]["instructions"] == "HARDENING\nBe brief.\n"


def test_revert_of_l2_survives_an_apply_that_failed_before_the_index_was_deleted():
    manual = [{"chunk_id": f"policy-{i}", "body": "b", "body_text": "b"} for i in range(4)]
    mapping = {"mappings": {"properties": {"body": {"type": "semantic_text", "inference_id": "old"}}}}
    plan = D.plan_l2(manual, mapping, "old", "new", AT, "s1")

    class C:   # cortex-policies still exists: creating it again is refused, as on the live server
        def __init__(self):
            self.log = []

        def request(self, m, p, b=None):
            self.log.append((m, p))
            if m == "PUT" and p == "/cortex-policies":
                return 400, {"error": {"type": "resource_already_exists_exception"}}
            return 404 if m == "DELETE" else 200, {}

        def request_ndjson(self, m, p, t):
            self.log.append((m, p))
            return 200, {"errors": False}
    c = C()
    D.execute(c, plan["revert"])
    assert c.log[-1] == ("POST", "/cortex-policies/_bulk?refresh=wait_for")
    # an index creation that is not marked idempotent still fails
    import pytest
    with pytest.raises(D.PlanFailed):
        D.execute(C(), [D.op("PUT", "/cortex-policies", {})])


def test_a_copied_mapping_drops_the_old_models_settings():
    mapping = {"mappings": {"properties": {"body": {"type": "semantic_text", "inference_id": "old", "model_settings": {"dimensions": 1024, "similarity": "cosine"}}}}}
    out = D._with_endpoint(mapping, "new")
    f = out["mappings"]["properties"]["body"]
    assert f["inference_id"] == "new" and "model_settings" not in f
    assert "model_settings" in mapping["mappings"]["properties"]["body"]   # the input is left alone


def test_c1_leaves_the_index_mapping_as_it_found_it():
    c1, l1 = D.plan_c1(MANUAL, AT, "s1"), D.plan_l1(MANUAL, AT, "s1")
    # the draft chunks carry `status`: it stays in _source, but the load must not map it (the residue raised tool calls 1.40 -> 2.09)
    assert c1["apply"][0]["method"] == "PUT" and c1["apply"][0]["path"] == "/cortex-policies/_mapping" and c1["apply"][0]["body"] == {"dynamic": False}
    assert c1["apply"][1]["path"].startswith("/_bulk") and "superseded" in c1["apply"][1]["ndjson"] and c1["apply"][2]["method"] == "COUNT" and c1["apply"][2]["expect"] == 30
    assert c1["apply"][3]["path"] == "/cortex-policies/_mapping" and c1["apply"][3]["body"] == {"dynamic": True}   # lifted once the load is counted: the learner sees the index's own setting
    assert c1["revert"][0]["path"].endswith("_delete_by_query?refresh=true") and c1["revert"][-1]["body"] == {"dynamic": True}
    # plan_l1 itself keeps the old behaviour unless asked (6.4's setup asks: see test_ara_setup6_steps)
    assert [o["path"] for o in l1["apply"]] == ["/_bulk?refresh=wait_for", "/cortex-policies/_count"] and len(l1["revert"]) == 1
    l1c = D.plan_l1(MANUAL, AT, "s1", clean_mapping=True)
    assert l1c["apply"][0]["body"] == {"dynamic": False} and l1c["revert"][-1]["body"] == {"dynamic": True} and "audience" in l1c["apply"][1]["ndjson"]
    assert l1c["apply"][-1]["body"] == {"dynamic": True}


def test_l2_and_c2_warm_the_new_endpoint_before_loading_it_and_refresh_after():
    for plan in (D.plan_l2(MANUAL, MAPPING, "old", "new", AT, "s1"), D.plan_c2(MANUAL, MAPPING, "old", "new", AT, "s1")):
        paths = [(o["method"], o["path"]) for o in plan["apply"]]
        i_put, i_warm, i_b2 = paths.index(("PUT", "/cortex-policies-v2")), paths.index(("WARM", "/cortex-policies-v2/_search")), paths.index(("POST", "/cortex-policies-v2/_bulk"))
        i_ref, i_del = paths.index(("POST", "/cortex-policies-v2/_refresh")), paths.index(("DELETE", "/cortex-policies"))
        assert i_put < i_warm < i_b2 < i_ref < i_del
        bulks = [o for o in plan["apply"] if o["ndjson"] is not None]
        assert len(bulks) == 2 and all("refresh" not in o["path"] and o["retries"] == D.BULK_RETRIES for o in bulks)   # not tied to a refresh cycle, safe to send again
        assert all('"index"' in o["ndjson"].split("\n")[0] for o in bulks)                                           # fixed ids: a second send overwrites, never duplicates


def test_warm_waits_for_a_cold_endpoint_but_only_so_long():
    class Cold(Fake):
        def __init__(self, cold_calls): super().__init__(); self.n = 0; self.cold = cold_calls
        def request(self, m, p, body=None):
            if m == "POST" and p.endswith("/_search"):
                self.n += 1
                return (503, {"error": "starting"}) if self.n <= self.cold else (200, {})
            return self._do(m, p)
    warm = D.op("WARM", "/cortex-policies-v2/_search", D.WARM_QUERY, wait_s=5.0)
    c = Cold(3); D.execute(c, [warm]); assert c.n == 4
    slept = []; D._sleep = slept.append
    try:
        import time as _t
        real = _t.monotonic; ticks = iter(range(0, 10_000, 3)); D.time.monotonic = lambda: next(ticks)
        try:
            D.execute(Cold(10 ** 6), [warm]); raise AssertionError("expected PlanFailed")
        except D.PlanFailed as e:
            assert "no answer within 5 s" in str(e) and "HTTP 503" in str(e)
        finally:
            D.time.monotonic = real
    finally:
        D._sleep = lambda s: None
    assert slept and all(x == 10 for x in slept)


def test_a_bulk_that_timed_out_is_sent_again_and_the_seed_survives():
    class Slow(Fake):
        def __init__(self, bad): super().__init__(); self.bad = bad; self.sent = 0
        def request_ndjson(self, m, p, text):
            if "-v2/_bulk" in p:
                self.sent += 1
                if self.sent <= self.bad:
                    return 200, {"errors": True, "items": [{"index": {"error": {"type": "task_cancelled_exception", "reason": "request timed out after [4.3m]"}}}]}
            return self._do(m, p, text)
    plan = D.plan_c2(MANUAL, MAPPING, "old", "new", AT, "s1")
    c = Slow(2); D.execute(c, plan["apply"]); assert c.sent == 3 and ("DELETE", "/cortex-policies") in c.calls
    c = Slow(99)
    try:
        D.execute(c, plan["apply"]); raise AssertionError("expected PlanFailed")
    except D.PlanFailed as e:
        assert "task_cancelled" in str(e) and "after 4 attempts" in str(e)
    assert c.sent == 4 and ("DELETE", "/cortex-policies") not in c.calls    # bounded, and production was never touched
    # a mapping error is not retried
    class Bad(Fake):
        def __init__(self): super().__init__(); self.sent = 0
        def request_ndjson(self, m, p, text):
            self.sent += 1
            return 200, {"errors": True, "items": [{"index": {"error": {"type": "mapper_parsing_exception", "reason": "bad field"}}}]}
    b = Bad()
    try:
        D.execute(b, [D.op("POST", "/x/_bulk", ndjson="{}\n{}\n", retries=3)]); raise AssertionError("expected PlanFailed")
    except D.PlanFailed:
        assert b.sent == 1


def test_warm_replays_the_live_408_while_the_endpoint_starts():
    # the live client RAISES for 408 (ABError); the body is the one the platform sent while the trained model deployment was starting
    from agent_builder import ABError, RemoteCallFailed
    body408 = ("POST /cortex-policies-v2/_search: HTTP 408 {'error': {'root_cause': [{'type': 'model_deployment_timeout_exception', 'reason': 'Timed out after [10s] waiting for trained model "
               "deployment for inference endpoint [.multilingual-e5-small-elasticsearch] to start. The inference endpoint can not be used to perform inference until the deployment has started.'}]}}")

    class Starting(Fake):
        def __init__(self, polls): super().__init__(); self.polls = polls; self.n = 0
        def request(self, m, p, body=None):
            self.calls.append((m, p))
            if p.endswith("/_search"):
                self.n += 1
                if self.n <= self.polls:
                    raise (ABError(body408, 408) if self.n % 2 else RemoteCallFailed("POST /x: TimeoutError: timed out"))
                return 200, {}
            return self._do(m, p)
    warm = D.op("WARM", "/cortex-policies-v2/_search", D.WARM_QUERY, wait_s=420.0)
    c = Starting(7)
    D.execute(c, [warm])
    assert c.n == 8   # seven refusals tolerated, the eighth poll answered
    plan = D.plan_c2(MANUAL, MAPPING, "old", "new", AT, "s1")
    c = Starting(3)
    D.execute(c, plan["apply"])
    assert c.n == 4 and ("DELETE", "/cortex-policies") in c.calls


def test_a_bulk_that_raises_408_or_overload_is_sent_again():
    from agent_builder import ABError

    class Flaky(Fake):
        def __init__(self): super().__init__(); self.sent = 0
        def request_ndjson(self, m, p, text):
            self.sent += 1
            if self.sent <= 2:
                raise ABError("POST /x/_bulk: HTTP 408 {'error': 'timeout'}", 408)
            return 200, {"errors": False, "items": []}
    c = Flaky()
    D.execute(c, [D.op("POST", "/x/_bulk", ndjson="{}\n{}\n", retries=3)])
    assert c.sent == 3


def test_a_load_that_came_up_short_fails_the_seed_instead_of_passing_as_a_smaller_index():
    for plan, want in ((D.plan_l1(MANUAL, AT, "s1"), {"/cortex-policies/_count": 40}),
                       (D.plan_l2(MANUAL, MAPPING, "old", "new", AT, "s1"), {"/cortex-policies-v1/_count": len(D.plan_l2(MANUAL, MAPPING, "old", "new", AT, "s1")["v1"]),
                                                                         "/cortex-policies-v2/_count": len(D.plan_l2(MANUAL, MAPPING, "old", "new", AT, "s1")["v2"])})):
        counts = {o["path"]: o["expect"] for o in plan["apply"] if o["method"] == "COUNT"}
        assert counts == want

    class Counting(Fake):
        def __init__(self, n): super().__init__(); self.n = n
        def request(self, m, p, body=None):
            self.calls.append((m, p))
            return (200, {"count": self.n}) if p.endswith("/_count") else (200, {})
    ok = D.op("COUNT", "/cortex-policies-v2/_count", expect=5)
    import contextlib, io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        D.execute(Counting(5), [ok])
    assert "SEED-COUNT /cortex-policies-v2/_count expected 5 found 5 ok" in buf.getvalue()
    short = io.StringIO()
    try:
        with contextlib.redirect_stdout(short):
            D.execute(Counting(4), [ok])
        raise AssertionError("expected PlanFailed")
    except D.PlanFailed as e:
        assert "expected 5 found 4 short" in short.getvalue()
        assert "4 documents counted" in str(e) and "5 expected" in str(e)
    try:
        D.execute(Fake(fail_at="_count"), [ok]); raise AssertionError("expected PlanFailed")
    except D.PlanFailed as e:
        assert "HTTP 500" in str(e)
    # the count comes after the load and the refresh, before the alias moves
    order = [(o["method"], o["path"]) for o in D.plan_l2(MANUAL, MAPPING, "old", "new", AT, "s1")["apply"]]
    assert order.index(("POST", "/cortex-policies-v2/_refresh")) < order.index(("COUNT", "/cortex-policies-v2/_count")) < order.index(("DELETE", "/cortex-policies"))
