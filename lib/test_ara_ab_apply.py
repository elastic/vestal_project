"""Offline tests for ara-ab-apply.py: the committed ara-m4-end chain applied to an in-memory Kibana,
then --check finds nothing to change (22 section 8.4: a second apply is a no-op)."""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import sys

LIB = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(LIB))
spec = importlib.util.spec_from_file_location("ara_ab_apply", LIB / "ara-ab-apply.py")
APPLY = importlib.util.module_from_spec(spec)
spec.loader.exec_module(APPLY)
END = LIB.parent / "manifests/m5/ara-m4-end.json"


class FakeKibana:
    def __init__(self):
        self.settings, self.connectors_, self.workflows, self.tools, self.skills, self.agents = {}, [], {}, {}, {}, {}
        self.plugins_ = []

    def set_settings(self, changes):
        self.settings.update(changes)
        return 200, {}

    def connector_by_name(self, name):
        return next((c for c in self.connectors_ if c["name"] == name), None)

    def put_connector(self, name, type_id, config, secrets=None):
        # The server fills the .http config's unset fields (probe r6's GET after create and after update)
        config = {"headers": None, "hasAuth": False, "authType": None, "proxyUrl": None, "hasProxyAuth": False, **config}
        cur = self.connector_by_name(name)
        if cur:
            cur["config"] = config
        else:
            self.connectors_.append({"id": f"c{len(self.connectors_)}", "name": name,
                                     "connector_type_id": type_id, "config": config})
        return 200, {}

    def delete_connector(self, cid):
        self.connectors_ = [c for c in self.connectors_ if c["id"] != cid]
        return 204

    def get_workflow(self, wid):
        return {"yaml": self.workflows[wid]} if wid in self.workflows else None

    def put_workflow(self, wid, text):
        self.workflows[wid] = text
        return 200, {"valid": True}

    def get_tool(self, tid):
        return self.tools.get(tid)

    def put_tool(self, tool):
        self.tools[tool["id"]] = json.loads(json.dumps(tool))
        return 200, {}

    def get_skill(self, sid):
        return self.skills.get(sid)

    def put_skill(self, skill):
        self.skills[skill["id"]] = json.loads(json.dumps(skill))
        return 200, {}

    def get_agent(self, aid):
        return self.agents.get(aid)

    def put_agent(self, agent):
        self.agents[agent["id"]] = json.loads(json.dumps(agent))
        return 200, {}

    def install_plugin(self, url, timeout=120):
        self.plugins_.append({"id": "p-server-1", "name": "cortex-compliance", "source_url": url})
        return 200, {}

    def get(self, path, **kw):
        assert path == "/api/agent_builder/plugins", path
        return 200, {"results": self.plugins_}


def test_ara_m4_end_applies_and_a_second_apply_is_a_no_op():
    os.environ.setdefault("ARA_AB_CONNECTOR_ID", ".anthropic-claude-5.5-sonnet-chat_completion")
    kb = FakeKibana()
    assert APPLY.apply(END, kb, log=lambda *_: None) > 0
    tina = kb.agents["tina-compliance"]["configuration"]
    assert "cortex.read_page" in tina["tools"][0]["tool_ids"] and "cortex.file_sar" in tina["tools"][0]["tool_ids"]
    assert tina["plugin_ids"] == ["p-server-1"]
    assert tina["subagent_ids"] == ["cortex-securities-irregularities"]
    assert "waitForApproval" in kb.workflows["cortex-file-sar"] and "connector-id: cortex-jina-reader" in kb.workflows["cortex-read-page"]
    assert [c["name"] for c in kb.connectors_] == ["cortex-jina-reader"]
    assert not any(t.startswith(("cortex.flag_for_review", "cortex.freeze_account", "cortex.share_with")) for t in kb.tools)
    assert APPLY.apply(END, kb, check=True, log=lambda *_: None) == 0
    # one plugin install, however often the chain is applied
    APPLY.apply(END, kb, log=lambda *_: None)
    assert len(kb.plugins_) == 1


def test_check_reports_a_plugin_not_installed_and_a_changed_connector():
    os.environ.setdefault("ARA_AB_CONNECTOR_ID", ".anthropic-claude-5.5-sonnet-chat_completion")
    kb = FakeKibana()
    APPLY.apply(END, kb, log=lambda *_: None)
    kb.connectors_[0]["config"] = {"url": "https://example.com"}
    kb.plugins_.clear()
    lines = []
    assert APPLY.apply(END, kb, check=True, log=lines.append) >= 3  # connector, plugin, agent
    assert any("connector cortex-jina-reader differs" in x for x in lines)
    assert any("plugin cortex-compliance not installed" in x for x in lines)


def test_check_reports_a_header_the_manifest_does_not_state():
    os.environ.setdefault("ARA_AB_CONNECTOR_ID", ".anthropic-claude-5.5-sonnet-chat_completion")
    kb = FakeKibana()
    APPLY.apply(END, kb, log=lambda *_: None)
    assert APPLY.apply(END, kb, check=True, log=lambda *_: None) == 0
    kb.connectors_[0]["config"]["headers"] = {"x-probe": "1"}
    lines = []
    assert APPLY.apply(END, kb, check=True, log=lines.append) == 1
    assert any("connector cortex-jina-reader differs" in x for x in lines)


def test_every_committed_chain_reapplies_as_a_no_op():
    os.environ.setdefault("ARA_AB_CONNECTOR_ID", ".anthropic-claude-5.5-sonnet-chat_completion")
    for p in sorted((LIB.parent / "manifests").glob("m[45]/*.json")):
        kb = FakeKibana()
        APPLY.apply(p, kb, log=lambda *_: None)
        assert APPLY.apply(p, kb, check=True, log=lambda *_: None) == 0, p.name


def test_5_1_start_adds_the_two_tools_and_the_house_rule():
    os.environ.setdefault("ARA_AB_CONNECTOR_ID", ".anthropic-claude-5.5-sonnet-chat_completion")
    kb = FakeKibana()
    APPLY.apply(LIB.parent / "manifests/m5/ara-m5-5-1-start.json", kb, log=lambda *_: None)
    tina = kb.agents["tina-compliance"]
    assert {"cortex.case_lookup", "cortex.sar_search", "cortex.read_page"} <= set(tina["configuration"]["tools"][0]["tool_ids"])
    assert "never repeat a customer identifier" in tina["configuration"]["instructions"]
    assert tina["access_control"]["access_mode"] == "public"
    assert "subject_tin" in kb.tools["cortex.case_lookup"]["configuration"]["query"]


if __name__ == "__main__":
    for k, fn in sorted(globals().items()):
        if k.startswith("test_"):
            fn()
            print(f"  ok    {k}")
