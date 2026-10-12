"""ara_actions.py - action class and required control, derived from tool definitions (22 section 5.1,
refined by D-28).

The ground truth for 4.4 Build 2, the 4.4 Defend Q2 and the 4.C Defend. Nothing here reads a
learner's answer: it reads Tina's live configuration, each tool's definition, and for a Workflow
tool the workflow's YAML, and applies table 5.1 (first row that applies):

    Workflow writing to cortex-sar-filings, or sending data outside Cortex
      (an http step to a non-Cortex host with a method other than GET or HEAD, or a body)
                                                       -> irreversible,   control approval gate plus audit entry
    Workflow writing only to Cortex records that can be
      corrected or removed                             -> side-effecting, control audit entry
    ES|QL or index search tool; a workflow whose only outside call is a GET of a web
      page with no body (D-28: cortex.read_page)       -> read-only,      control none

    items = classify_agent(ab, "tina-compliance", cortex_hosts={...})
    -> [{"id", "class", "reason", "control", "evidence"}]

An http step's host is its `url` host; a step that names a saved connector (`connector-id`, by id
or name) and gives only a `path` takes the connector's configured URL host.
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
IRREVERSIBLE_INDICES = {"cortex-sar-filings"}
WRITE_STEPS = {"elasticsearch.index", "elasticsearch.bulk", "elasticsearch.update", "elasticsearch.delete",
               "elasticsearch.create", "elasticsearch.delete_by_query", "elasticsearch.update_by_query"}
READ_METHODS = {"GET", "HEAD"}


def _steps(steps: Any):
    """Every step in a workflow definition, nested branches and loops included, in order."""
    for s in steps or []:
        if not isinstance(s, dict):
            continue
        yield s
        for key in ("steps", "else"):
            yield from _steps(s.get(key))


def _host(url: Any) -> str:
    text = str(url or "")
    if "{{" in text.split("//", 1)[-1].split("/", 1)[0]:
        return ""  # a templated host is unknown, never a Cortex host
    return (urlparse(text).hostname or "").lower()


def workflow_effects(yaml_text: str, cortex_hosts: set[str], connector_hosts: dict[str, str] | None = None) -> dict:
    """{"writes": [index...], "sends": [host...], "reads": [host...]} for one workflow's YAML.
    sends: http calls outside Cortex that can carry data out (any method but GET or HEAD, or a body);
    reads: GET or HEAD calls outside Cortex with no body."""
    import yaml  # the check venv has pyyaml; learner helpers never call this
    try:
        doc = yaml.safe_load(yaml_text) or {}
    except yaml.YAMLError:
        doc = {}
    writes, sends, reads = [], [], []
    for s in _steps(doc.get("steps") if isinstance(doc, dict) else None):
        typ = str(s.get("type") or "")
        w = s.get("with") if isinstance(s.get("with"), dict) else {}
        if typ in WRITE_STEPS:
            writes.append(str(w.get("index") or ""))
        elif typ == "elasticsearch.request" and str(w.get("method") or "GET").upper() != "GET":
            writes.append(str(w.get("path") or "").lstrip("/").split("/")[0])
        elif typ == "http":
            if w.get("url"):
                host = _host(w.get("url"))
            else:
                host = (connector_hosts or {}).get(str(s.get("connector-id") or ""), "")
            if host and host in cortex_hosts:
                continue
            host = host or "<unknown host>"
            if str(w.get("method") or "GET").upper() in READ_METHODS and w.get("body") in (None, "", {}):
                reads.append(host)
            else:
                sends.append(host)
    return {"writes": writes, "sends": sends, "reads": reads}


def classify_tool(tool: dict, workflow_yaml: str | None, cortex_hosts: set[str],
                  connector_hosts: dict[str, str] | None = None) -> dict:
    tid, typ = tool.get("id"), tool.get("type")
    if typ in ("esql", "index_search"):
        return {"id": tid, "class": "read-only", "reason": "queries Cortex data and writes nothing",
                "evidence": f"{typ} tool"}
    if typ == "workflow":
        eff = workflow_effects(workflow_yaml or "", cortex_hosts, connector_hosts)
        wf = ((tool.get("configuration") or {}).get("workflow_id"))
        if set(eff["writes"]) & IRREVERSIBLE_INDICES:
            return {"id": tid, "class": "irreversible", "reason": "transmits a SAR, which cannot be withdrawn",
                    "evidence": f"workflow {wf} writes to cortex-sar-filings"}
        if eff["sends"]:
            return {"id": tid, "class": "irreversible", "reason": "sends data outside Cortex",
                    "evidence": f"workflow {wf} sends an http request with data to {eff['sends'][0]}"}
        if eff["writes"]:
            return {"id": tid, "class": "side-effecting", "reason": "writes a Cortex record that can be corrected or removed",
                    "evidence": f"workflow {wf} writes to {', '.join(sorted(set(eff['writes'])))}"}
        if eff["reads"]:
            return {"id": tid, "class": "read-only", "reason": "reads a web page on the open internet and writes nothing",
                    "evidence": f"workflow {wf} only GETs a page from {eff['reads'][0]} and writes nothing"}
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


def connector_hosts(ab) -> dict[str, str]:
    """{connector id or name: host} for every saved .http connector, so a workflow's http step that
    names one by connector-id resolves to the host it calls."""
    code, conns = ab.get("/api/actions/connectors")
    out: dict[str, str] = {}
    for c in (conns if code == 200 and isinstance(conns, list) else []):
        if c.get("connector_type_id") != ".http":
            continue
        host = _host((c.get("config") or {}).get("url"))
        for key in (c.get("id"), c.get("name")):
            if key:
                out[str(key)] = host
    return out


def classify_agent(ab, agent_id: str, cortex_hosts: set[str]) -> list[dict]:
    """Every custom tool on the agent, sorted by id, each with its class, reason, control and evidence."""
    agent = ab.get_agent(agent_id)
    conns = None
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
            if conns is None and "connector-id" in str(wf_yaml or ""):
                conns = connector_hosts(ab)
        out.append(classify_tool(tool, wf_yaml, cortex_hosts, conns))
    for item in out:
        item["control"] = CONTROLS[item["class"]]
    return out


def hosts_from_env(env: dict) -> set[str]:
    """The project's own hosts: an http step to one of them stays inside Cortex."""
    return {(urlparse(env.get(k, "")).hostname or "").lower() for k in ("ES_URL", "ES_ENDPOINT", "KIBANA_URL")} - {""}
