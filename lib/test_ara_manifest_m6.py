"""The M6 manifests: chain, no scheduled trigger, private overlays, committed copies in step with the generator."""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ara_manifest_m6 as M  # noqa: E402
import ara_workflows_m6 as W  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_the_generated_set_lints_clean_and_chains_to_m5():
    ms = M.build()
    assert M.lint(ms) == []
    assert M._chain(ms, "ara-m6-capstone-start") == ["ara-m6-capstone-start", "ara-m6-6-3-end", "ara-m6-6-3-start", "ara-m6-6-2-end", "ara-m6-6-2-start",
                                                    "ara-m6-6-1-end", "ara-m6-6-1-start", "ara-m5-end", "ara-m5-5-2-start"]
    assert {"ara-m6-6-1-start", "ara-m6-6-2-start", "ara-m6-6-3-start", "ara-m6-6-4-start", "ara-m6-capstone-start", "ara-m6-end"} <= set(ms)


def test_every_workflow_listed_is_manual_only_and_matches_its_generator():
    for m in M.build().values():
        for w in m.get("workflows", []):
            assert w["triggers"] == ["manual"] and w["enabled"] is True
            fn = getattr(W, w["source"].split(".")[1])
            text = fn("inf") if w["id"] == "cortex-evaluator-run" else fn()
            assert W.scheduled_triggers(text) == []


def test_lint_names_each_break():
    ms = M.build()
    ms["ara-m6-6-3-start"]["workflows"][0]["triggers"] = ["manual", "scheduled"]
    assert any("manual trigger only" in p for p in M.lint(ms))
    ms = M.build(); ms["ara-m6-6-4-start"]["extends"] = "nope"
    assert any("not defined" in p for p in M.lint(ms))
    ms = M.build(); ms["ara-m6-6-1-start"]["extends"] = "ara-m6-6-1-end"
    assert any("cycle" in p for p in M.lint(ms))
    ms = M.build(); ms["ara-m5-end"]["overlay"] = {}
    assert any("private overlay" in p for p in M.lint(ms))
    ms = M.build(); ms["ara-m6-6-4-start"]["run_labels"] = ["m6-baseline", "m6-baseline"]
    assert any("listed once" in p for p in M.lint(ms))
    ms = M.build(); ms["ara-m6-6-1-start"]["_doc"] += " SECRET HARDENING TEXT THAT IS LONG ENOUGH TO MATCH THE SIXTY CHARACTER PREFIX CHECK"
    assert any("hardening block" in p for p in M.lint(ms, "SECRET HARDENING TEXT THAT IS LONG ENOUGH TO MATCH THE SIXTY CHARACTER PREFIX CHECK"))


def test_committed_manifests_and_mappings_match():
    for mid, m in M.build().items():
        f = ROOT / "manifests" / "m6" / f"{mid}.json"
        assert json.loads(f.read_text()) == m, mid
    for name, path in M.INDICES.items():
        mapping = json.loads((ROOT / path).read_text())
        assert "properties" in mapping["mappings"], name
    assert json.loads((ROOT / "data/ara-m6/mappings/cortex-eval-runs.m6-extension.json").read_text())["version"] == 2
    roles = json.loads((ROOT / "data/ara-m6/roles/m6-roles.json").read_text())
    assert roles["cortex-evaluator-reader"]["cluster"] == ["monitor_inference"] and "P7_GUESS" in roles
