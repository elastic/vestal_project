"""Offline tests for ara_integrity.py (25 section 8.7) with fake clients."""
from __future__ import annotations

import copy
import json
import pathlib
import sys
import threading

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import ara_eval_run as H  # noqa: E402
import ara_integrity as I  # noqa: E402

POOL = H.load_pool({"questions": [
    {"id": "q1", "type": "agent", "input": "dep 476", "expected": [{"tool_id": "cortex.structuring_deposits", "params": {"account_id": "476"}}]},
    {"id": "q2", "type": "agent", "input": "who is 9?", "expected": [{"tool_id": "cortex.account_lookup", "params": {"account_id": "9"}}]},
]})
TS = [{"question_id": "q1"}, {"question_id": "q2"}]
KEY = {"q1": "straightforward", "q2": "ambiguous"}
ROUTES = {"dep 476": ("cortex.structuring_deposits", {"account_id": "476"}),
          "who is 9?": ("cortex.account_lookup", {"account_id": "9"})}
MODEL = "m-pin"


def make_round(text, tool=None, status="completed", started=1000.0, inp=1000, cached=400):
    steps = [{"type": "tool_call", "tool_id": tool[0], "params": tool[1], "results": []}] if tool else []
    return {"input": {"message": text}, "status": status, "started_at": started, "steps": steps,
            "model_usage": {"connectors": [{"model": MODEL, "input_tokens": inp, "cached_input_tokens": cached,
                                            "output_tokens": 50, "llm_calls": 2}]}}


class World:
    """Fake Kibana: converse creates a stored conversation; reach objects are mutable."""
    def __init__(self):
        self.convs, self.n, self.lock = {}, 0, threading.Lock()
        self.objects = {"agent": {"tina": {"id": "tina", "updated_at": "t0", "configuration": {"tools": [{"tool_ids": ["t1"]}], "skill_ids": ["s1"]}}},
                        "tool": {"t1": {"id": "t1", "configuration": {"workflow_id": "w1"}}},
                        "skill": {"s1": {"id": "s1", "content": "x", "tool_ids": ["t1"]}},
                        "workflow": {"w1": {"id": "w1", "updated_at": "t0", "yaml": "connector-id: c1"}}}
        self.plugin_list = [{"id": "p1", "updated_at": "t0"}]
        self.connector_list = [{"id": "c1", "name": "x"}]
        self.after_converse = None
        self.fail = {}

    def get_agent(self, i): return self.objects["agent"].get(i)
    def get_tool(self, i): return self.objects["tool"].get(i)
    def get_skill(self, i): return self.objects["skill"].get(i)
    def get_workflow(self, i): return self.objects["workflow"].get(i)
    def connectors(self): return self.connector_list
    def plugins(self): return self.plugin_list
    def conversation(self, cid): return copy.deepcopy(self.convs.get(cid))

    def converse_timed(self, agent_id, text):
        if text in self.fail:
            raise self.fail[text]
        with self.lock:
            self.n += 1
            cid = f"c{self.n}"
        rnd = make_round(text, ROUTES[text])
        self.convs[cid] = {"agent_id": agent_id, "rounds": [rnd]}
        resp = dict(rnd, conversation_id=cid, response={"message": "ok"})
        if self.after_converse:
            self.after_converse()
        return resp, 1200

    def delete_conversation(self, cid): pass


def snap(w):
    return I.snapshot(I.collect_reach(w, ["tina"]))


def run(w, tmp, **kw):
    out = []
    res = I.check_run(w, w, "tina", TS, POOL, "baseline", lambda: snap(w), str(tmp / "frozen.json"), key=KEY,
                      record_writer=out.append, clock=lambda: 1001.0, sleep=lambda s: None, **kw)
    return res, out


def test_strip_and_fingerprint_ignore_server_managed_fields_and_name_the_field():
    w = World()
    a = snap(w)
    w.objects["agent"]["tina"]["updated_at"] = "t9"
    assert I.diff(a, snap(w)) == []
    w.objects["agent"]["tina"]["configuration"]["instructions"] = "new"
    d = I.diff(a, snap(w))
    assert d == [{"object": "agent/tina", "field": "/configuration/instructions", "change": "added"}]
    w.objects["tool"]["t1"]["x"] = 1
    assert {x["object"] for x in I.diff(a, snap(w))} == {"agent/tina", "tool/t1"}


def test_strip_list_is_a_parameter():
    obj = {"revision": 3, "a": {"revision": 4, "b": 1}}
    s1 = I.snapshot({"agent/x": obj}, ("revision",))
    s2 = I.snapshot({"agent/x": {"revision": 9, "a": {"revision": 1, "b": 1}}}, ("revision",))
    assert I.diff(s1, s2) == []
    assert I.diff(I.snapshot({"agent/x": obj}), I.snapshot({"agent/x": {**obj, "revision": 9}}))


def test_reach_covers_agents_tools_skills_plugins_workflows_connectors():
    w = World()
    assert sorted(I.collect_reach(w, ["tina"])) == ["agent/tina", "connector/c1", "plugin/p1", "skill/s1", "tool/t1", "workflow/w1"]
    del w.objects["workflow"]["w1"]
    assert "workflow/w1" in {d["object"] for d in I.diff(snap(World()), snap(w))}


def good_records(w):
    recs = H.run_testset(w, "tina", TS, POOL, KEY, sleep=lambda s: None)
    return recs


def test_recompute_passes_on_honest_records_and_names_each_mismatch():
    w = World()
    recs = good_records(w)
    assert I.recompute(recs, w, TS, POOL, "tina", pinned_model=MODEL) == []
    recs[1]["route_correct"] = False
    recs[0]["cached_input_tokens"] = 0
    f = I.recompute(recs, w, TS, POOL, "tina")
    assert {(x["question_id"], x["field"]) for x in f} == {("q2", "route_correct"), ("q1", "cached_input_tokens")}


def test_recompute_fails_missing_foreign_two_round_and_unfinished_conversations():
    w = World()
    for broken in ("missing", "agent", "rounds", "status", "input", "model"):
        w = World()
        recs = good_records(w)
        c = w.convs[recs[0]["conversation_id"]]
        if broken == "missing":
            del w.convs[recs[0]["conversation_id"]]
        elif broken == "agent":
            c["agent_id"] = "other"
        elif broken == "rounds":
            c["rounds"].append(copy.deepcopy(c["rounds"][0]))
        elif broken == "status":
            c["rounds"][0]["status"] = "running"
        elif broken == "input":
            c["rounds"][0]["input"] = {"message": "different"}
        elif broken == "model":
            pass
        f = I.recompute(recs, w, TS, POOL, "tina", pinned_model="other-model" if broken == "model" else MODEL)
        assert f and all(x["question_id"] == "q1" for x in f if broken != "model"), broken
        assert any(x["question_id"] == "q1" for x in f), broken


def test_recompute_shared_conversation_missing_record_and_window():
    w = World()
    recs = good_records(w)
    recs[1]["conversation_id"] = recs[0]["conversation_id"]
    assert any(x["question_id"] == "q2" and x["field"] == "conversation_id" for x in I.recompute(recs, w, TS, POOL, "tina"))
    assert [x["question_id"] for x in I.recompute(recs[:1], World(), TS, POOL, "tina") if x["field"] == "record"] == ["q2"]
    recs = good_records(World())
    w2 = World(); recs = good_records(w2)
    assert I.recompute(recs, w2, TS, POOL, "tina", window=(2000, 3000))


def test_check_run_passes_records_check_label_and_freezes(tmp_path):
    w = World()
    res, out = run(w, tmp_path)
    assert res["status"] == "pass" and res["aggregates"]["questions"] == 2
    assert {r["run_label"] for r in out} == {"baseline-check"} and all(r["judge"]["faithfulness"] is None for r in out)
    frozen = json.loads((tmp_path / "frozen.json").read_text())
    assert sorted(frozen["conversation_ids"]) == ["c1", "c2"] and frozen["aggregates"] == res["aggregates"] and frozen["frozen_at"] == 1001.0


def test_edit_during_the_run_fails_naming_the_object_and_freezes_nothing(tmp_path):
    w = World()
    def edit():
        w.objects["tool"]["t1"]["description"] = "tweaked"
    w.after_converse = edit
    res, _ = run(w, tmp_path)
    assert res["status"] == "fail" and res["discarded"] and any(d["object"] == "tool/t1" for d in res["failures"])
    assert not (tmp_path / "frozen.json").exists()


def test_edit_made_and_restored_before_the_check_is_not_seen_but_start_mismatch_fails(tmp_path):
    w = World()
    expected = snap(w)
    w.objects["tool"]["t1"]["description"] = "tweaked"
    res, _ = run(w, tmp_path, expected=expected)
    assert res["status"] == "fail" and res["failures"][0]["at"] == "start" and res["failures"][0]["object"] == "tool/t1"
    del w.objects["tool"]["t1"]["description"]
    res, _ = run(w, tmp_path, expected=expected)
    assert res["status"] == "pass"


def test_unreachable_is_never_graded_nor_frozen(tmp_path):
    from agent_builder import ABError
    w = World()
    w.fail["who is 9?"] = ABError("503")
    res, _ = run(w, tmp_path)
    assert res["status"] == "unreachable" and res["aggregates"] is None
    assert [f["question_id"] for f in res["failures"]] == ["q2"]
    assert not (tmp_path / "frozen.json").exists()


def test_a_later_label_cannot_reuse_a_frozen_conversation(tmp_path):
    w = World()
    prior = tmp_path / "prior.json"
    prior.write_text(json.dumps({"conversation_ids": ["c1"]}))
    res, _ = run(w, tmp_path, earlier_frozen=[str(prior)])
    assert res["status"] == "fail" and any(f["question_id"] == "q1" for f in res["failures"])


def test_update_binding_names_the_object_updated_after_a_conversation():
    objs = {"agent/tina": {"updated_at": "2026-11-01T10:00:00Z"}, "tool/t1": {"x": 1}, "workflow/w": {"updated_at": 1_700_000_000}}
    ok = [{"id": "c1", "created_at": "2026-11-02T00:00:00Z"}]
    assert I.update_binding(objs, ok) == []
    bad = I.update_binding(objs, [{"id": "c2", "created_at": "2026-11-01T09:00:00Z"}])
    assert [b["object"] for b in bad] == ["agent/tina"] and bad[0]["conversation_id"] == "c2"
    froze = I.update_binding(objs, ok, freezes=[_ts("2026-11-03T00:00:00Z")])
    assert froze and froze[0]["object"] is None


def _ts(s):
    return I._t(s)


def test_reset_returns_put_bodies_for_changed_objects_without_server_fields():
    w = World()
    root = snap(w)
    w.objects["agent"]["tina"]["configuration"]["instructions"] = "edited"
    puts = I.reset(root, snap(w))
    assert [(p["kind"], p["id"]) for p in puts] == [("agent", "tina")]
    assert "updated_at" not in puts[0]["body"] and "instructions" not in puts[0]["body"]["configuration"]
    assert len(I.reset(root)) == len(root["objects"])
    assert I.reset(root, root) == []


def test_a_round_that_ended_on_an_unanswered_ask_is_terminal():
    w = World()
    recs = good_records(w)
    w.convs[recs[0]["conversation_id"]]["rounds"][0]["status"] = "awaiting_prompt"
    assert not I.recompute(recs, w, TS, POOL, "tina", pinned_model=MODEL)
