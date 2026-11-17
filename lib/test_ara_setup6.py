"""The M6 setup plan: order contracts for every track and variant, the runner, and the HTTP-only handlers over fakes."""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ara_setup6 as S  # noqa: E402
import ara_workflows_m6 as WM  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent


def names(p): return [s["name"] for s in p]


def test_every_plan_respects_its_own_needs_and_ends_with_the_schedule_check():
    for track in S.TRACKS:
        for seed in range(30):
            p = S.plan(track, seed)
            seen = []
            for st in p:
                assert all(n in seen for n in st["needs"]), (track, seed, st["name"])
                seen.append(st["name"])
            assert names(p)[-1] == "verify_no_schedule" and p[0]["name"] == "settings"
            assert len(names(p)) == len(set(names(p)))


def test_baseline_precedes_the_seed_and_degraded_follows_it_in_6_4_and_c():
    for track in ("6-4", "6-c"):
        n = names(S.plan(track, 4))
        assert n.index("baseline") < n.index("seed") < n.index("degraded")
        assert n.index("history_load") < n.index("change_log") < n.index("seed")


def test_6_2_installs_patterns_before_the_baseline_and_6_1_loads_the_pack_before_the_defect():
    n = names(S.plan("6-2", 0))
    assert n.index("patterns") < n.index("baseline") and n.index("pack_load") < n.index("patterns")
    n = names(S.plan("6-1", 0))
    assert n.index("pack_load") < n.index("defect") < n.index("heldout")


def test_variants_follow_the_seed_and_cover_all_of_them():
    assert {S.variants(i)["pack"] for i in range(30)} == {"A", "B", "C"} and {S.variants(i)["policy"] for i in range(30)} == {0, 1, 2}
    by = lambda tr, s, n: next(x for x in S.plan(tr, s) if x["name"] == n)
    assert by("6-1", 1, "pack_load")["args"]["pack"] == "T-B" and by("6-2", 2, "pack_load")["args"]["pack"] == "W3"
    assert {S.variants(i)["ops"] for i in range(30)} == {"O1", "O2", "O3"}


def test_runner_orders_and_stops():
    log, ran = [], []
    handlers = {s["name"]: (lambda n=s["name"], **a: ran.append(n)) for s in S.plan("6-3", 0)}
    done = S.run(S.plan("6-3", 0), handlers, log.append)
    assert done == ran == names(S.plan("6-3", 0)) and any("baseline (detached)" in l for l in log)
    try:
        S.run(S.plan("6-3", 0)[3:], handlers, log.append)
        raise AssertionError("expected RuntimeError")
    except RuntimeError as e:
        assert "needs" in str(e)
    handlers["testset"] = lambda **a: (_ for _ in ()).throw(RuntimeError("boom"))
    try:
        S.run(S.plan("6-3", 0), handlers, log.append)
        raise AssertionError
    except RuntimeError as e:
        assert "boom" in str(e)
    try:
        S.run(S.plan("6-3", 0), {}, log.append); raise AssertionError
    except RuntimeError as e:
        assert "no handler" in str(e)


class FakeAB:
    def __init__(self, wfs=None, valid=True): self.wfs, self.valid = wfs or {}, valid
    def put_workflow(self, wid, text): self.wfs[wid] = text; return 200, {"valid": self.valid}
    def get_workflow(self, wid): return {"yaml": self.wfs.get(wid, "")}


def make(tmp_path, ab=None, calls=None, sources=None):
    calls = calls if calls is not None else []
    def kb(m, p, b):
        calls.append((m, p, b))
        if p == "/api/workflows/search":
            return 200, {"results": [{"id": w} for w in (ab.wfs if ab else {})]}
        return 200, {}
    def es(m, p, b): calls.append((m, p, b)); return 200, {}
    return S.Setup6(ab or FakeAB(), kb, es, tmp_path, ROOT, sources or {"cortex-canary-run": WM.canary_run_yaml, "cortex-answer-audit": WM.answer_audit_yaml}), calls


def test_settings_turn_system_prompt_and_user_data_off_and_the_rest_on(tmp_path):
    st, calls = make(tmp_path)
    st.settings(True, False, False)
    sent = {list(b["changes"])[0]: list(b["changes"].values())[0] for m, _, b in calls if m == "POST"}
    assert sent["agentBuilder:tracing:includeSystemPrompt"] is False and sent["agentBuilder:tracing:includeUserData"] is False
    assert sent["agentBuilder:tracing:includeToolDetails"] is True and len(sent) == 8


def test_indices_roles_workflows_and_files(tmp_path):
    st, calls = make(tmp_path)
    st.indices(["cortex-eval-ledger"]); st.roles(["cortex-evaluator-reader"]); st.workflows(["cortex-canary-run"])
    assert ("PUT", "/cortex-eval-ledger") in [(m, p) for m, p, _ in calls] and ("PUT", "/_security/role/cortex-evaluator-reader") in [(m, p) for m, p, _ in calls]
    st.write_file("/home/elastic/cortex-ops/scenarios.md", "x", 0o644)
    assert (tmp_path / "home/elastic/cortex-ops/scenarios.md").read_text() == "x"


def test_a_scheduled_workflow_is_refused_at_load_and_found_by_the_final_check(tmp_path):
    sched = WM.canary_run_yaml().replace("  - type: manual\n", "  - type: manual\n  - type: scheduled\n    with:\n      every: 1m\n", 1)
    st, _ = make(tmp_path, sources={"w": lambda: sched})
    try:
        st.workflows(["w"]); raise AssertionError("expected RuntimeError")
    except RuntimeError as e:
        assert "scheduled trigger" in str(e)
    ab = FakeAB({"ok": WM.canary_run_yaml(), "bad": sched})
    st, _ = make(tmp_path, ab)
    try:
        st.verify_no_schedule(); raise AssertionError
    except RuntimeError as e:
        assert "bad" in str(e) and "ok" not in str(e).split(":")[1]
    ab.wfs.pop("bad"); make(tmp_path, ab)[0].verify_no_schedule()


def test_cli_plan_prints_json_steps_and_run_refuses_unwired(capsys, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("ara_setup6_cli", ROOT / "lib" / "ara-setup6.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    assert m.main(["plan", "6-4", "3"]) == 0
    rows = [json.loads(l) for l in capsys.readouterr().out.splitlines()]
    assert rows[0]["name"] == "settings" and rows[-1]["name"] == "verify_no_schedule"
    assert m.main(["plan", "9-9", "3"]) == 2 and m.main(["plan", "6-4"]) == 2
    st, _ = make(pathlib.Path("/tmp"))
    import ara_setup6_steps as SS
    steps = SS.Steps6(None, None, None, None, "p", pathlib.Path("/tmp"), pathlib.Path("/tmp"), pathlib.Path("/tmp"), "6-4")
    h = m.handlers(st, steps)
    for track in S.TRACKS:
        assert all(x["name"] in h for x in S.plan(track, 0)), track
    assert set(steps.handlers()).isdisjoint(m.NEEDS_LIVE)
    for t in S.TRACKS:
        for sd in (0, 5, 17):
            assert {x["name"] for x in S.plan(t, sd)} <= set(h)


def test_schedule_check_falls_back_to_known_ids_when_no_list_route_answers(tmp_path):
    sched = WM.canary_run_yaml().replace("  - type: manual\n", "  - type: manual\n  - type: scheduled\n    with:\n      every: 1m\n", 1)
    ab = FakeAB({"cortex-canary-run": sched})
    st = S.Setup6(ab, lambda m, p, b: (404, {}), lambda m, p, b: (200, {}), tmp_path, ROOT, {"cortex-canary-run": WM.canary_run_yaml})
    try:
        st.verify_no_schedule(); raise AssertionError("expected RuntimeError")
    except RuntimeError as e:
        assert "cortex-canary-run" in str(e)


def test_the_inherited_4_2_sweep_loses_its_schedule_at_the_final_check(tmp_path):
    text = (ROOT / "manifests/m4/workflows/cortex-structuring-sweep.yml").read_text()
    assert "type: scheduled" in text and "type: manual" in WM.strip_scheduled(text) and not WM.scheduled_triggers(WM.strip_scheduled(text))
    ab = FakeAB({"cortex-structuring-sweep": text})
    ab.put_workflow = lambda wid, y: (ab.wfs.__setitem__(wid, y) or (200, {}))
    st, _ = make(tmp_path, ab)
    st.verify_no_schedule()
    assert not WM.scheduled_triggers(ab.wfs["cortex-structuring-sweep"])


def test_the_evaluator_skeleton_may_be_stored_invalid_with_its_placeholders(tmp_path, capsys):
    ab = FakeAB(valid=False)
    st = S.Setup6(ab, lambda m, p, b: (200, {}), lambda m, p, b: (200, {}), tmp_path, ROOT, {"cortex-evaluator-run": lambda: WM.evaluator_run_yaml("inf")})
    st.workflows(["cortex-evaluator-run"])
    assert "stored with its placeholders" in capsys.readouterr().out
    st2 = S.Setup6(ab, lambda m, p, b: (200, {}), lambda m, p, b: (200, {}), tmp_path, ROOT, {"cortex-canary-run": WM.canary_run_yaml})
    try:
        st2.workflows(["cortex-canary-run"]); raise AssertionError("expected RuntimeError")
    except RuntimeError as e:
        assert "refused" in str(e)
