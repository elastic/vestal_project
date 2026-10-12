"""ara_actions.py - action class and required control, derived from tool definitions (22 section 5.1).

The ground truth for 4.4 Build 2, the 4.4 Defend Q2 and the 4.C Defend. Nothing here reads a
learner's answer: it reads Tina's live configuration, each tool's definition, and for a Workflow
tool the workflow's YAML, and applies table 5.1:

    ES|QL or index search tool; connector sub-action browse   -> read-only,      control none
    Workflow writing only to Cortex records that can be
      corrected or removed                                    -> side-effecting, control audit entry
    Workflow writing to cortex-sar-filings, or sending data
      outside Cortex (an http step to a non-Cortex host)      -> irreversible,   control approval gate plus audit entry

    items = classify_agent(ab, "tina-compliance", cortex_hosts={...})
    -> [{"id", "label", "class", "reason", "control", "evidence"}]

The Jina browse is one item, id JINA_ITEM, present when Tina holds the sub-action tool and a .jina
connector in connector_ids (both grants, 22 section 5 Build 1).
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

CLASSES = ["read-only", "side-effecting", "irreversible"]
CONTROLS = {"read-only": "none", "side-effecting": "audit entry", "irreversible": "approval gate plus audit entry"}
# The closed reason list (22 section 5, Build 2). Keys are what the learner's record holds.
REASONS = {
    "queries Cortex data and writes nothing": "read-only",
    "reads a web page on the open internet and writes nothing": "read-only",
    "writes a Cortex record that can be corrected or removed": "side-effecting",
    "transmits a SAR, which cannot be withdrawn": "irreversible",
    "sends data outside Cortex": "irreversible",
}
JINA_ITEM = "jina-browse"
SUB_ACTION_TOOL = "platform.core.execute_connector_sub_action"
IRREVERSIBLE_INDICES = {"cortex-sar-filings"}
WRITE_STEPS = {"elasticsearch.index", "elasticsearch.bulk", "elasticsearch.update", "elasticsearch.delete",
               "elasticsearch.create", "elasticsearch.delete_by_query", "elasticsearch.update_by_query"}


def _steps(steps: Any):
    """Every step in a workflow definition, nested branches and loops included, in order."""
    for s in steps or []:
        if not isinstance(s, dict):
            continue
        yield s
        for key in ("steps", "else"):
            yield from _steps(s.get(key))


def workflow_effects(yaml_text: str, cortex_hosts: set[str]) -> dict:
    """{"writes": [index...], "outside": [host...]} for one workflow's YAML."""
    import yaml  # the check venv has pyyaml; learner helpers never call this
    try:
        doc = yaml.safe_load(yaml_text) or {}
    except yaml.YAMLError:
        doc = {}
    writes, outside = [], []
    for s in _steps(doc.get("steps") if isinstance(doc, dict) else None):
        typ = str(s.get("type") or "")
        w = s.get("with") if isinstance(s.get("with"), dict) else {}
        if typ in WRITE_STEPS:
            writes.append(str(w.get("index") or ""))
        elif typ == "elasticsearch.request" and str(w.get("method") or "GET").upper() != "GET":
            writes.append(str(w.get("path") or "").lstrip("/").split("/")[0])
        elif typ == "http":
            host = (urlparse(str(w.get("url") or "")).hostname or "").lower()
            if host not in cortex_hosts:
                outside.append(host or "<templated host>")
    return {"writes": writes, "outside": outside}


def classify_tool(tool: dict, workflow_yaml: str | None, cortex_hosts: set[str]) -> dict:
    tid, typ = tool.get("id"), tool.get("type")
    if typ in ("esql", "index_search"):
        return {"id": tid, "class": "read-only", "reason": "queries Cortex data and writes nothing",
                "evidence": f"{typ} tool"}
    if typ == "workflow":
        eff = workflow_effects(workflow_yaml or "", cortex_hosts)
        wf = ((tool.get("configuration") or {}).get("workflow_id"))
        if set(eff["writes"]) & IRREVERSIBLE_INDICES:
            return {"id": tid, "class": "irreversible", "reason": "transmits a SAR, which cannot be withdrawn",
                    "evidence": f"workflow {wf} writes to cortex-sar-filings"}
        if eff["outside"]:
            return {"id": tid, "class": "irreversible", "reason": "sends data outside Cortex",
                    "evidence": f"workflow {wf} has an http step to {eff['outside'][0]}"}
        if eff["writes"]:
            return {"id": tid, "class": "side-effecting", "reason": "writes a Cortex record that can be corrected or removed",
                    "evidence": f"workflow {wf} writes to {', '.join(sorted(set(eff['writes'])))}"}
        return {"id": tid, "class": "read-only", "reason": "queries Cortex data and writes nothing",
                "evidence": f"workflow {wf} writes nothing"}
    # Any other custom type (mcp, for example) is not in table 5.1: side-effecting until a person decides.
    return {"id": tid, "class": "side-effecting", "reason": "writes a Cortex record that can be corrected or removed",
            "evidence": f"{typ} tool, not in table 5.1"}


def agent_tool_ids(agent: dict | None) -> list[str]:
    ids: list[str] = []
    for entry in ((agent or {}).get("configuration") or {}).get("tools") or []:
        ids.extend(entry.get("tool_ids") or [])
    return ids


def jina_connectors(ab) -> list[dict]:
    code, conns = ab.get("/api/actions/connectors")
    return [c for c in (conns if code == 200 and isinstance(conns, list) else []) if c.get("connector_type_id") == ".jina"]


def classify_agent(ab, agent_id: str, cortex_hosts: set[str]) -> list[dict]:
    """Every custom tool on the agent, plus the Jina browse when both grants are present, sorted by id."""
    agent = ab.get_agent(agent_id)
    out = []
    for tid in sorted(set(agent_tool_ids(agent))):
        if tid.startswith("platform.") or tid.startswith("."):
            continue
        tool = ab.get_tool(tid)
        if tool is None:
            continue
        wf_yaml = None
        if tool.get("type") == "workflow":
            wf = ab.get_workflow(((tool.get("configuration") or {}).get("workflow_id")) or "")
            wf_yaml = (wf or {}).get("yaml")
        out.append(classify_tool(tool, wf_yaml, cortex_hosts))
    granted = set(((agent or {}).get("configuration") or {}).get("connector_ids") or [])
    if SUB_ACTION_TOOL in agent_tool_ids(agent) and any(c.get("id") in granted for c in jina_connectors(ab)):
        out.append({"id": JINA_ITEM, "class": "read-only",
                    "reason": "reads a web page on the open internet and writes nothing",
                    "evidence": "connector sub-action browse on a .jina connector"})
    for item in out:
        item["control"] = CONTROLS[item["class"]]
    return sorted(out, key=lambda i: i["id"])


def hosts_from_env(env: dict) -> set[str]:
    """The project's own hosts: an http step to one of them stays inside Cortex."""
    return {(urlparse(env.get(k, "")).hostname or "").lower() for k in ("ES_URL", "ES_ENDPOINT", "KIBANA_URL")} - {""}
