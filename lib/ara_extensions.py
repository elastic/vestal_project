"""ara_extensions.py - connectors, the two grants, plugins, and connector calls in a route (22 section 1).

Used by the 4.4 Build 1 check and solve, the 4.4 Defend Q1, and the end-state manifest checks.

    conns = connectors_of_type(ab, ".jina")
    grants(agent, connector_id) -> {"tool": bool, "connector": bool}
    plugin_by_source(ab, url) -> plugin dict or None (source_url compared after normalising)
    connector_calls(resp, connector_ids) -> [{"connector_id", "sub_action", "url", "ok", "code", "status"}]

A connector call's step result carries the connector's own answer: a bad key returns
data.ok false with code 401 while the step type stays "other" and the trace span stays Ok
(research 19, B3). So a call is judged by its result, never by the step type or the span.
"""
from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

SUB_ACTION_TOOL = "platform.core.execute_connector_sub_action"


def norm_url(url: Any) -> str:
    """Scheme dropped, host lowercased, trailing slash dropped (22 section 8.3)."""
    p = urlparse(str(url or "").strip())
    return f"{(p.hostname or '').lower()}{p.path.rstrip('/')}" + (f"?{p.query}" if p.query else "")


def connectors_of_type(ab, type_id: str) -> list[dict]:
    code, body = ab.get("/api/actions/connectors")
    return [c for c in (body if code == 200 and isinstance(body, list) else []) if c.get("connector_type_id") == type_id]


def agent_config(agent: dict | None) -> dict:
    return (agent or {}).get("configuration") or {}


def tool_ids(agent: dict | None) -> list[str]:
    out: list[str] = []
    for entry in agent_config(agent).get("tools") or []:
        out.extend(entry.get("tool_ids") or [])
    return out


def grants(agent: dict | None, connector_id: str) -> dict:
    """Both grants an agent needs to call a connector (research 19, 21a section 6 ruling 1)."""
    return {"tool": SUB_ACTION_TOOL in tool_ids(agent),
            "connector": connector_id in (agent_config(agent).get("connector_ids") or [])}


def plugins(ab) -> list[dict]:
    code, body = ab.get("/api/agent_builder/plugins")
    return list((body or {}).get("results") or []) if code == 200 and isinstance(body, dict) else []


def plugin_by_name(ab, name: str) -> dict | None:
    return next((p for p in plugins(ab) if p.get("name") == name), None)


def plugin_by_source(ab, url: str) -> dict | None:
    want = norm_url(url)
    return next((p for p in plugins(ab) if norm_url(p.get("source_url")) == want), None)


def _result_data(results: Any) -> dict:
    for r in results or []:
        if isinstance(r, dict) and isinstance(r.get("data"), dict):
            return r["data"]
    return {}


def _params(step: dict) -> dict:
    p = step.get("params") or {}
    if isinstance(p, str):
        try:
            p = json.loads(p)
        except ValueError:
            p = {}
    return p if isinstance(p, dict) else {}


def connector_calls(resp: dict, connector_ids: list[str] | None = None) -> list[dict]:
    """Every execute_connector_sub_action call in one converse response, in order."""
    out = []
    for s in (resp or {}).get("steps") or []:
        if not isinstance(s, dict) or s.get("type") != "tool_call" or s.get("tool_id") != SUB_ACTION_TOOL:
            continue
        p = _params(s)
        cid = p.get("connectorId") or p.get("connector_id")
        if connector_ids is not None and cid not in connector_ids:
            continue
        inner = p.get("params") if isinstance(p.get("params"), dict) else {}
        data = _result_data(s.get("results"))
        err = next((r for r in s.get("results") or [] if isinstance(r, dict) and r.get("type") == "error"), None)
        out.append({"connector_id": cid, "sub_action": p.get("subAction"), "url": inner.get("url"),
                    "ok": data.get("ok") is True and err is None, "code": data.get("code"),
                    "status": data.get("status") or data.get("httpStatus"),
                    "error": (err or {}).get("data", {}).get("message") if err else None})
    return out


def skill_loads(resp: dict) -> list[str]:
    """Skill paths loaded with load_skill in one response (recorded, never gated: 22 section 5)."""
    return [str(_params(s).get("skill") or "") for s in (resp or {}).get("steps") or []
            if isinstance(s, dict) and s.get("type") == "tool_call" and s.get("tool_id") == "load_skill"]
