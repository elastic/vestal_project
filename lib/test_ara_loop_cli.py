"""ara_loop_cli verbs over fakes (28 section 3, B2): copies only for a candidate, ledger entries, the unguarded apply."""
import copy
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ara_ledger as G  # noqa: E402
import ara_loop_cli as C  # noqa: E402
from ara_eval import CATEGORIES  # noqa: E402


class FakeAB:
    def __init__(self):
        self.agents = {"tina-compliance": {"id": "tina-compliance", "name": "Tina", "updated_at": "x", "configuration": {"instructions": "H\nBe brief.", "skill_ids": ["cortex-fraud-triage"], "tools": [{"tool_ids": ["a", "cortex.policy_search"]}]}}}
        self.tools = {"cortex.policy_search": {"id": "cortex.policy_search", "description": "Search twice.", "readonly": True},
                      "a": {"id": "a", "description": "A."}, "cortex.account_history": {"id": "cortex.account_history", "description": "H."}}
        self.skills = {"cortex-fraud-triage": {"id": "cortex-fraud-triage", "name": "Triage", "content": "x", "tool_ids": ["cortex.policy_search"]}}
        self.writes = []

    def get_skill(self, i): return copy.deepcopy(self.skills.get(i))

    def put_skill(self, s):
        self.writes.append(("skill", s["id"])); self.skills[s["id"]] = copy.deepcopy(s); return 200, {}

    def get_agent(self, i): return copy.deepcopy(self.agents.get(i))
    def get_tool(self, i): return copy.deepcopy(self.tools.get(i))

    def put_agent(self, a):
        self.writes.append(("agent", a["id"])); self.agents[a["id"]] = copy.deepcopy(a); return 200, {}

    def put_tool(self, t):
        if {"readonly", "created_at", "updated_at", "permissions"} & set(t):   # the platform refuses the read's server fields
            return 400, {"message": "Additional properties are not allowed"}
        self.writes.append(("tool", t["id"])); self.tools[t["id"]] = copy.deepcopy(t); return 200, {}


class FakeLedger:
    def __init__(self): self.rows = []
    def append(self, e): self.rows.append(e)
    def entries(self): return list(self.rows)


def agg(acc=80.0, tools=3.0, cost=0.01):
    ra = {c: acc for c in CATEGORIES}
    return {"routing_accuracy": ra, "routing_accuracy_overall": acc, "tool_calls_per_question": tools, "cost_per_question": cost, "ndcg_at_5": 0.7}


class FakeES:
    """The few calls a data change makes: counts, alias reads and moves, a reindex and a delete-by-query."""
    def __init__(self):
        self.indices = {"cortex-policies-v1": 5, "cortex-policies-fixed": 3}
        self.aliases = {"cortex-policies": ["cortex-policies-v1"]}
        self.calls = []

    def request(self, m, path, body=None):
        self.calls.append((m, path, body))
        if m == "GET" and path.endswith("/_count"):
            name = path.split("/")[1]
            return (200, {"count": self.indices[name]}) if name in self.indices or name in self.aliases else (404, {})
        if m == "GET" and path.startswith("/_alias/"):
            a = path.split("/")[2]
            return (200, {i: {"aliases": {a: {}}} for i in self.aliases[a]}) if a in self.aliases else (404, {})
        if path == "/_aliases":
            for act in body["actions"]:
                (kind, v), = act.items()
                cur = self.aliases.setdefault(v["alias"], [])
                if kind == "remove":
                    cur.remove(v["index"])
                else:
                    cur.append(v["index"])
            return 200, {"acknowledged": True}
        if path.startswith("/_reindex"):
            self.indices[body["dest"]["index"]] = 2
            return 200, {"total": 2, "failures": []}
        if path.endswith("/_delete_by_query") or "/_delete_by_query?" in path:
            self.indices["cortex-policies-v1"] -= 2
            return 200, {"deleted": 2}
        return 404, {}


class FakeProposals(dict):
    def add(self, doc):
        self[doc["proposal_id"]] = doc


class Deps:
    def __init__(self, props):
        self.ab, self.ledger, self.proposals, self.es = FakeAB(), FakeLedger(), FakeProposals(props), FakeES()
        self.agent_id = "tina-compliance"
        self.gate = {"testset_version": "v1", "target_scope": "proposal_category", "min_gain_points": 5.0, "min_gain_pct": 10.0,
                     "category_drop_limit_points": 5.0, "tool_call_limit_pct": 15.0, "cost_limit_pct": 20.0}
        self.thresholds = {"remeasure_tolerance_points": 3.0, "remeasure_tolerance_pct": 5.0}
        self.runs = {"m6-baseline": agg(70.0)}
        self.next = {}
        self.t = 0

    def now(self):
        self.t += 1
        return f"2026-11-11T10:{self.t:02d}:00Z"

    def measure(self, label, agent_id, index=None):
        self.indexes = getattr(self, "indexes", {})
        self.indexes[label] = index
        self.runs[label] = self.next.get(label) or agg(85.0)
        return self.runs[label]

    def measure_existing(self, label): return self.runs[label]


EV = [{"conversation_id": "c1", "trace_id": "t1", "observation": "escalated"}]
ATTACH = {"kind": "improvement", "proposal_type": "attach_tool", "target": "tina-compliance", "change": {"tool_id": "cortex.account_history"},
          "evidence": EV, "expected_effect": {"metric": "routing_accuracy", "category": "cross_domain"}}
TOOLDESC = {"kind": "improvement", "proposal_type": "tool_description_change", "target": "cortex.policy_search",
            "change": {"field": "description", "text": "Search once."}, "evidence": EV, "expected_effect": {"metric": "tool_calls", "category": "all"}}


def test_candidate_writes_copies_only():
    d = Deps({"p1": ATTACH, "p2": TOOLDESC})
    e1 = C.candidate(d, "p1")
    assert e1["candidate_agent_id"] == "tina-compliance--cand-p1" and e1["comparison_label"] == "m6-baseline"
    ca = d.ab.agents["tina-compliance--cand-p1"]
    assert "cortex.account_history--cand-p1" in ca["configuration"]["tools"][0]["tool_ids"] and "updated_at" not in ca
    assert ca["configuration"]["tools"][0]["tool_ids"][:2] == ["a--cand-p1", "cortex.policy_search--cand-p1"]
    assert ca["configuration"]["skill_ids"] == ["cortex-fraud-triage--cand-p1"]
    assert d.ab.skills["cortex-fraud-triage--cand-p1"]["tool_ids"] == ["cortex.policy_search--cand-p1"]
    assert e1["skill_copies"] == {"cortex-fraud-triage--cand-p1": "cortex-fraud-triage"} and e1["tool_copies"]["a--cand-p1"] == "a"
    assert "cortex.account_history" not in d.ab.agents["tina-compliance"]["configuration"]["tools"][0]["tool_ids"]
    e2 = C.candidate(d, "p2")
    assert e2["tool_copies"]["cortex.policy_search--cand-p2"] == "cortex.policy_search"
    assert d.ab.tools["cortex.policy_search--cand-p2"]["description"] == "Search once."
    assert d.ab.tools["cortex.policy_search"]["description"] == "Search twice."
    assert "cortex.policy_search--cand-p2" in d.ab.agents["tina-compliance--cand-p2"]["configuration"]["tools"][0]["tool_ids"]
    assert all(w[1].count("--cand-") for w in d.ab.writes)


def test_full_loop_gate_apply_remeasure_and_rollback():
    d = Deps({"p1": ATTACH})
    C.candidate(d, "p1")
    g = C.gate(d, "p1")
    assert g["gate"]["decision"] == "pass" and g["run_label"] == "gate-p1"
    a = C.apply(d, "p1")
    assert a["snapshot"]["tina-compliance"]["configuration"]["tools"][0]["tool_ids"] == ["a", "cortex.policy_search"] and "warning" not in a
    assert "cortex.account_history" in d.ab.agents["tina-compliance"]["configuration"]["tools"][0]["tool_ids"]
    d.next["remeasure-p1"] = agg(70.0)
    r = C.remeasure(d, "p1")
    assert r["outcome"] == "not_confirmed"
    C.rollback(d, "p1")
    assert d.ab.agents["tina-compliance"]["configuration"]["tools"][0]["tool_ids"] == ["a", "cortex.policy_search"]
    start = {"tina-compliance": {"id": "tina-compliance", "name": "Tina", "updated_at": "x", "configuration": {"instructions": "H\nBe brief.", "skill_ids": ["cortex-fraud-triage"], "tools": [{"tool_ids": ["a", "cortex.policy_search"]}]}}}
    assert G.check_ledger(start, d.ledger.entries(), {"p1": dict(ATTACH, proposal_id="p1")}) == []


def test_apply_is_not_stopped_but_warns():
    d = Deps({"p1": ATTACH})
    assert "has not been gated" in C.apply(d, "p1")["warning"]
    d2 = Deps({"p1": ATTACH})
    d2.next["gate-p1"] = agg(70.0)
    C.candidate(d2, "p1"); C.gate(d2, "p1")
    assert "failed its gate (no_gain)" in C.apply(d2, "p1")["warning"]
    try:
        C.apply(d2, "p1")
        raise AssertionError("second apply should be refused")
    except C.LoopError as e:
        assert "already applied" in str(e)


def test_second_proposal_is_compared_with_the_first_confirmed_remeasure():
    d = Deps({"p1": ATTACH, "p2": TOOLDESC})
    C.candidate(d, "p1"); C.gate(d, "p1"); C.apply(d, "p1"); C.remeasure(d, "p1")
    e = C.candidate(d, "p2")
    assert e["comparison_label"] == "remeasure-p1"


def test_bad_inputs_are_told_plainly():
    d = Deps({"bad": dict(ATTACH, change={})})
    for verb, pid, msg in (("candidate", "nope", "no proposal"), ("candidate", "bad", "does not meet the proposal spec"),
                           ("gate", "bad", "does not meet"), ):
        try:
            C.VERBS[verb](d, pid); raise AssertionError(verb)
        except C.LoopError as e:
            assert msg in str(e)
    d = Deps({"p1": ATTACH})
    for verb in ("gate", "remeasure", "rollback"):
        try:
            C.VERBS[verb](d, "p1"); raise AssertionError(verb)
        except C.LoopError:
            pass
    assert "does not exist" in str(_raises(lambda: C.candidate(Deps({"dc": dict(DATA, change=dict(DATA["change"], candidate_source="nope"))}), "dc")))


def _raises(fn):
    try:
        fn()
    except C.LoopError as e:
        return e
    raise AssertionError("expected LoopError")


def test_instruction_change_and_detach_touch_the_candidate_only():
    ins = dict(ATTACH, proposal_type="instruction_change", change={"field": "configuration.instructions", "text": "Default to 7 days."})
    det = dict(ATTACH, proposal_type="detach_tool", change={"tool_id": "a"})
    d = Deps({"i": ins, "x": det})
    C.candidate(d, "i"); C.candidate(d, "x")
    assert d.ab.agents["tina-compliance--cand-i"]["configuration"]["instructions"] == "Default to 7 days."
    assert d.ab.agents["tina-compliance"]["configuration"]["instructions"] == "H\nBe brief."
    assert "a--cand-x" not in d.ab.agents["tina-compliance--cand-x"]["configuration"]["tools"][0]["tool_ids"]
    assert "a" in d.ab.agents["tina-compliance"]["configuration"]["tools"][0]["tool_ids"]


def test_propose_validates_ids_and_refuses_a_repeat(tmp_path):
    import json
    d = Deps({})
    f = tmp_path / "fix.json"
    f.write_text(json.dumps({"proposals": [dict(ATTACH, rationale="because")]}))
    e = C.propose(d, str(f))
    pid = e["proposal_id"]
    assert pid.startswith("prop-") and len(pid) == 13 and d.proposals[pid]["run_id"] == "manual" and d.proposals[pid]["status"] == "proposed"
    assert "next: candidate" in C.summary(e)
    f.write_text(json.dumps(dict(ATTACH, rationale="a different story")))
    assert "already stored" in str(_raises(lambda: C.propose(d, str(f))))
    f.write_text(json.dumps(dict(ATTACH, change={})))
    assert "does not meet the spec" in str(_raises(lambda: C.propose(d, str(f))))
    assert "not a readable JSON file" in str(_raises(lambda: C.propose(d, str(tmp_path / "nope.json"))))
    C.candidate(d, pid)  # a stored proposal goes straight into the loop


def test_candidate_skill_name_is_a_valid_skill_name():
    out = C._clean({"id": "s1", "name": "Fraud triage", "content": "x"}, "s1--cand-prop-1", "skill")
    assert out["id"] == "s1--cand-prop-1" and out["name"] == "s1--cand-prop-1"
    assert "(" not in out["name"]
    assert C._clean({"id": "a", "name": "Tina"}, "a--c", "agent")["name"] == "Tina (candidate)"


def test_apply_and_rollback_of_a_tool_change_leave_the_servers_fields_out():
    d = Deps({"pd": TOOLDESC})
    C.apply(d, "pd")
    assert d.ab.tools["cortex.policy_search"]["description"] == "Search once."
    C.rollback(d, "pd")
    assert d.ab.tools["cortex.policy_search"]["description"] == "Search twice."


DATA = {"kind": "incident_fix", "proposal_type": "data_change", "target": "cortex.policy_search",
        "change": {"tool_id": "cortex.policy_search", "production_source": "cortex-policies", "candidate_source": "cortex-policies-fixed", "operation": "repoint_alias"},
        "evidence": EV, "expected_effect": {"metric": "ndcg_at_5", "category": "policy_retrieval"}}


def _data_deps(change=None):
    d = Deps({"dc": dict(DATA, change=dict(DATA["change"], **(change or {})))})
    d.ab.tools["cortex.policy_search"].update({"type": "index_search", "configuration": {"pattern": "cortex-policies", "other": ["cortex-policies-v1"]}})
    return d


def test_data_candidate_is_a_tool_copy_reading_the_candidate_index_and_production_is_untouched():
    d = _data_deps()
    e = C.candidate(d, "dc")
    cp = d.ab.tools["cortex.policy_search--cand-dc"]
    assert cp["configuration"]["pattern"] == "cortex-policies-fixed" and cp["configuration"]["other"] == ["cortex-policies-v1"]   # a whole-name match only
    assert d.ab.tools["cortex.policy_search"]["configuration"]["pattern"] == "cortex-policies"
    assert e["candidate_source"] == "cortex-policies-fixed" and all(w[1].count("--cand-") for w in d.ab.writes)


def test_data_candidate_refuses_a_tool_that_does_not_read_the_source():
    d = _data_deps({"production_source": "cortex-nothing"})
    d.es.indices["cortex-nothing"] = 1
    assert "does not read" in str(_raises(lambda: C.candidate(d, "dc")))
    d = _data_deps({"tool_id": "a"})
    assert "does not read" in str(_raises(lambda: C.candidate(d, "dc")))


def test_data_gate_measures_against_the_candidate_source():
    d = _data_deps()
    C.candidate(d, "dc")
    C.gate(d, "dc")
    assert d.indexes["gate-dc"] == "cortex-policies-fixed"


def test_repoint_alias_apply_and_rollback():
    d = _data_deps()
    C.candidate(d, "dc"); C.gate(d, "dc")
    a = C.apply(d, "dc")
    assert a["snapshot"] == {"alias": "cortex-policies", "indices": ["cortex-policies-v1"], "moved_to": "cortex-policies-fixed"}
    assert d.es.aliases["cortex-policies"] == ["cortex-policies-fixed"]
    assert d.ab.tools["cortex.policy_search"]["configuration"]["pattern"] == "cortex-policies"   # the production tool is never repointed
    C.rollback(d, "dc")
    assert d.es.aliases["cortex-policies"] == ["cortex-policies-v1"]


def test_repoint_alias_needs_an_alias():
    d = _data_deps({"production_source": "cortex-policies-v1"})
    d.ab.tools["cortex.policy_search"]["configuration"]["pattern"] = "cortex-policies-v1"
    C.candidate(d, "dc"); C.gate(d, "dc")
    assert "not an alias" in str(_raises(lambda: C.apply(d, "dc")))


def test_delete_matching_keeps_a_copy_and_rollback_restores_it():
    d = _data_deps({"operation": "delete_matching", "query": {"term": {"doc_type": "draft"}}, "production_source": "cortex-policies-v1"})
    d.ab.tools["cortex.policy_search"]["configuration"]["pattern"] = "cortex-policies-v1"
    C.candidate(d, "dc"); C.gate(d, "dc")
    a = C.apply(d, "dc")
    assert a["snapshot"] == {"copy": "cortex-policies-v1-deleted-dc", "source": "cortex-policies-v1", "deleted": 2}
    assert d.es.indices["cortex-policies-v1"] == 3 and "cortex-policies-v1-deleted-dc" in d.es.indices
    C.rollback(d, "dc")
    assert d.es.calls[-1][1].startswith("/_reindex") and d.es.calls[-1][2] == {"source": {"index": "cortex-policies-v1-deleted-dc"}, "dest": {"index": "cortex-policies-v1"}}
