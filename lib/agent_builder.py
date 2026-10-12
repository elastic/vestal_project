"""agent_builder.py - one place for every Agent Builder and Workflows call M4 makes (22 section 1).

Every check, solve and learner helper in M4 talks to Kibana through this module, so a Technical
Preview API change is fixed here once. Standard library only: checks run it on /opt/ara/venv and
learner helpers on the system python3.

Errors. A call that gets no usable answer (no connection, a timeout, 401, 403, 408, 429, 5xx)
raises ABError with status_code set, which ara_grade.is_outage() treats as an outage, so
ara_grade.remote() retries it and then exits with no grade (R-P8). Any other 4xx is returned to
the caller as (code, body): it is the learner's request or object, not the platform.

Determinism (09 section 5a). converse() refuses to run without a connector id, and route_record()
reads only the tool-call steps, never response.message. Internal platform tools are filtered.

    ab = AB(kibana_url, api_key, connector_id)
    resp = ab.converse("tina-compliance", "Did account 1981 ...?")
    route_record(resp) -> [{"tool_id", "params", "ok", "execution_id", "execution_status"}]
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

KBN_HEADERS = {"kbn-xsrf": "true", "elastic-api-version": "2023-10-31"}

# Tools the platform calls on its own (planning, skills, API discovery). They are never part of a
# graded route (22 section 1).
INTERNAL_TOOLS = {"write_todos", "load_skill", "describe_api", "execute_api", "search_relevant_skills"}
INTERNAL_PREFIXES = ("platform.",)

_OUTAGE = (401, 403, 408, 429)


class ABError(Exception):
    """No usable answer from Kibana. status_code is the HTTP status, or None for no answer."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class RemoteCallFailed(ABError):
    """No HTTP answer at all (refused, reset, timeout). The name is in ara_grade's outage list."""


def is_internal(tool_id: Any) -> bool:
    t = str(tool_id or "")
    return t in INTERNAL_TOOLS or t.startswith(INTERNAL_PREFIXES)


class AB:
    """A Kibana client bound to one API key. connector_id pins the model for converse()."""

    def __init__(self, kibana: str, api_key: str, connector_id: str | None = None, timeout: float = 45):
        self.kibana = kibana.rstrip("/")
        self.api_key = api_key
        self.connector_id = connector_id
        self.timeout = timeout

    @classmethod
    def from_env(cls, key_var: str = "ARA_TINA_RUNTIME_KEY", timeout: float = 45) -> "AB":
        return cls(os.environ["KIBANA_URL"], os.environ[key_var], os.environ.get("ARA_AB_CONNECTOR_ID"), timeout)

    # ── transport ────────────────────────────────────────────────────────────
    def request(self, method: str, path: str, body: Any = None, timeout: float | None = None,
                ok_codes: tuple = ()) -> tuple[int, Any]:
        """One call. Returns (status, parsed body) for 2xx and for a 4xx the caller owns; raises
        ABError for an outage status and RemoteCallFailed for no answer. ok_codes lists statuses in
        _OUTAGE that the caller wants returned instead (a 403 a check expects, for example)."""
        headers = {"Content-Type": "application/json", "Authorization": f"ApiKey {self.api_key}", **KBN_HEADERS}
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f"{self.kibana}{path}", data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                code, txt = resp.status, resp.read().decode()
        except urllib.error.HTTPError as e:
            code, txt = e.code, e.read().decode(errors="replace")
        except Exception as e:  # refused, reset, DNS, timeout
            raise RemoteCallFailed(f"{method} {path}: {type(e).__name__}: {e}") from None
        try:
            parsed = json.loads(txt) if txt else {}
        except ValueError:
            parsed = {"raw": txt[:500]}
        if (code in _OUTAGE or code >= 500) and code not in ok_codes:
            raise ABError(f"{method} {path}: HTTP {code} {str(parsed)[:300]}", code)
        return code, parsed

    def get(self, path: str, **kw):
        return self.request("GET", path, **kw)

    # ── tools ────────────────────────────────────────────────────────────────
    def get_tool(self, tool_id: str) -> dict | None:
        code, body = self.get(f"/api/agent_builder/tools/{tool_id}")
        return body if code == 200 else None

    def put_tool(self, tool: dict) -> tuple[int, Any]:
        """Create the tool, or replace it when it exists. The id goes in the path on update."""
        tid = tool["id"]
        if self.get_tool(tid) is None:
            return self.request("POST", "/api/agent_builder/tools", tool)
        return self.request("PUT", f"/api/agent_builder/tools/{tid}", {k: v for k, v in tool.items() if k not in ("id", "type")})

    def delete_tool(self, tool_id: str) -> int:
        return self.request("DELETE", f"/api/agent_builder/tools/{tool_id}")[0]

    def execute_tool(self, tool_id: str, params: dict) -> tuple[int, Any]:
        return self.request("POST", "/api/agent_builder/tools/_execute", {"tool_id": tool_id, "tool_params": params})

    # ── agents ───────────────────────────────────────────────────────────────
    def get_agent(self, agent_id: str) -> dict | None:
        code, body = self.get(f"/api/agent_builder/agents/{agent_id}")
        return body if code == 200 else None

    def put_agent(self, agent: dict) -> tuple[int, Any]:
        aid = agent["id"]
        if self.get_agent(aid) is None:
            return self.request("POST", "/api/agent_builder/agents", agent)
        return self.request("PUT", f"/api/agent_builder/agents/{aid}", {k: v for k, v in agent.items() if k != "id"})

    def delete_agent(self, agent_id: str) -> int:
        return self.request("DELETE", f"/api/agent_builder/agents/{agent_id}")[0]

    # ── conversations ────────────────────────────────────────────────────────
    def converse(self, agent_id: str, text: str, conversation_id: str | None = None,
                 timeout: float | None = None) -> dict:
        """One round with the pinned connector. Raises ABError on an outage; a 4xx (unknown agent,
        bad body) is raised too, because a check never sends one by design."""
        if not self.connector_id:
            raise ValueError("converse() needs a connector id (09 section 5a): set ARA_AB_CONNECTOR_ID")
        body = {"agent_id": agent_id, "input": text, "connector_id": self.connector_id}
        if conversation_id:
            body["conversation_id"] = conversation_id
        code, resp = self.request("POST", "/api/agent_builder/converse", body, timeout=timeout or self.timeout)
        if code != 200:  # an outage status already raised ABError in request()
            raise ValueError(f"converse {agent_id}: HTTP {code} {str(resp)[:300]}")
        return resp

    def conversation(self, conversation_id: str) -> dict | None:
        code, body = self.get(f"/api/agent_builder/conversations/{conversation_id}")
        return body if code == 200 else None

    # ── workflows ────────────────────────────────────────────────────────────
    def get_workflow(self, workflow_id: str) -> dict | None:
        code, body = self.get(f"/api/workflows/workflow/{workflow_id}")
        return body if code == 200 else None

    def put_workflow(self, workflow_id: str, yaml_text: str) -> tuple[int, Any]:
        if self.get_workflow(workflow_id) is not None:
            return self.request("PUT", f"/api/workflows/workflow/{workflow_id}", {"yaml": yaml_text})
        return self.request("POST", "/api/workflows/workflow", {"id": workflow_id, "yaml": yaml_text})

    def delete_workflow(self, workflow_id: str) -> int:
        return self.request("DELETE", f"/api/workflows/workflow/{workflow_id}")[0]

    def run_workflow(self, workflow_id: str, inputs: dict) -> str | None:
        code, body = self.request("POST", f"/api/workflows/workflow/{workflow_id}/run", {"inputs": inputs})
        return body.get("workflowExecutionId") if code == 200 and isinstance(body, dict) else None

    def execution(self, execution_id: str) -> dict | None:
        code, body = self.get(f"/api/workflows/executions/{execution_id}")
        return body if code == 200 else None

    def step_io(self, execution_id: str, step_execution_id: str) -> dict | None:
        code, body = self.get(f"/api/workflows/executions/{execution_id}/step/{step_execution_id}")
        return body if code == 200 else None

    def wait_execution(self, execution_id: str, budget_s: float = 30, poll_s: float = 1.5) -> dict | None:
        """Poll until the execution ends or the budget runs out; returns the last read."""
        end = time.monotonic() + budget_s
        last = None
        while True:
            last = self.execution(execution_id)
            if last and last.get("status") in ("completed", "failed", "cancelled", "timed_out", "skipped"):
                return last
            if time.monotonic() + poll_s > end:
                return last
            time.sleep(poll_s)

    # ── settings ─────────────────────────────────────────────────────────────
    def set_settings(self, changes: dict) -> tuple[int, Any]:
        return self.request("POST", "/internal/kibana/settings", {"changes": changes})


# ── route records (09 section 5a) ─────────────────────────────────────────────

def _execution(results: Any) -> tuple[str | None, str | None]:
    for r in results or []:
        d = r.get("data") if isinstance(r, dict) else None
        ex = d.get("execution") if isinstance(d, dict) else None
        if isinstance(ex, dict):
            return ex.get("execution_id"), ex.get("status")
    return None, None


def _result_ok(results: Any) -> bool:
    """A tool call worked when it returned at least one result and none is of type error."""
    rs = [r for r in (results or []) if isinstance(r, dict)]
    return bool(rs) and not any(r.get("type") == "error" for r in rs)


def route_record(resp: dict) -> list[dict]:
    """The ordered custom tool calls in one converse response, internal tools filtered."""
    out = []
    for s in (resp or {}).get("steps") or []:
        if not isinstance(s, dict) or s.get("type") != "tool_call" or is_internal(s.get("tool_id")):
            continue
        ex_id, ex_status = _execution(s.get("results"))
        out.append({"tool_id": s.get("tool_id"), "params": s.get("params") or {},
                    "ok": _result_ok(s.get("results")), "execution_id": ex_id, "execution_status": ex_status})
    return out


def internal_calls(resp: dict) -> list[str]:
    return [s.get("tool_id") for s in (resp or {}).get("steps") or []
            if isinstance(s, dict) and s.get("type") == "tool_call" and is_internal(s.get("tool_id"))]


def esql_rows(execute_resp: dict) -> tuple[list[str], list[list]] | None:
    """Columns and rows from a tools/_execute response for an ES|QL tool, or None if it has no
    esql_results block (an error result, or not an ES|QL tool)."""
    for r in (execute_resp or {}).get("results") or []:
        if isinstance(r, dict) and r.get("type") == "esql_results":
            data = r.get("data") or {}
            return [c.get("name") for c in data.get("columns") or []], list(data.get("values") or [])
    return None


def error_text(execute_resp: dict) -> str | None:
    for r in (execute_resp or {}).get("results") or []:
        if isinstance(r, dict) and r.get("type") == "error":
            d = r.get("data") or {}
            return str(d.get("message") or d)[:300]
    return None


def literal_equal(expected: Any, got: Any) -> bool:
    """Compare a structured literal the way 21a section 7 ruling 4 asks: ids as strings, numbers
    by value, never free text. "1981" equals 1981; 7 equals "7" and 7.0."""
    if isinstance(expected, bool) or isinstance(got, bool):
        return expected == got
    if isinstance(expected, (int, float)) or isinstance(got, (int, float)):
        try:
            return float(expected) == float(got)
        except (TypeError, ValueError):
            return False
    return str(expected).strip() == str(got).strip()


def route_matches(expected: list[dict], record: list[dict], forbid: list[str] = ()) -> tuple[bool, str]:
    """Grade one case. expected is an ordered list of {"tool_id", "params": {name: literal}}; every
    expected call must appear in the record in that order with its literals (other calls may sit
    between them). forbid lists tool ids that must not appear at all. Returns (passed, reason)."""
    for bad in forbid:
        if any(c["tool_id"] == bad for c in record):
            return False, f"called {bad}"
    i = 0
    for want in expected:
        while i < len(record):
            c = record[i]
            i += 1
            if c["tool_id"] == want["tool_id"] and all(
                    literal_equal(v, c["params"].get(k)) for k, v in (want.get("params") or {}).items()):
                break
        else:
            called = [c["tool_id"] for c in record] or ["no tool"]
            return False, f"expected {want['tool_id']}, got {', '.join(called)}"
    return True, "route matches"
