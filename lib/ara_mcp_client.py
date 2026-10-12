"""ara_mcp_client.py - Agent Builder MCP calls and the Claude Code transcript reader (22 section 1, 4.3).

MCP (probe-43 r1): the Kibana-hosted endpoint is `<kibana>/api/agent_builder/mcp`, streamable HTTP,
JSON-RPC over POST with `Accept: application/json, text/event-stream`; a reply may arrive as one SSE
`data:` line. `?namespace=cortex` limits tools/list to the Cortex tools, whose names show dots as
underscores (`cortex.open_case` -> `cortex_open_case`).

Transcripts (probe-43 r4, Claude Code 2.1.296): one JSONL file per session under
`~/.claude/projects/<cwd with / as ->/<session>.jsonl`. Assistant entries carry `message.content`
parts of type `tool_use` (`name`, `input`, `id`); MCP tools are named `mcp__<server>__<tool>`, shell
commands are `Bash` with `input.command`. The reader is pinned to the version in thresholds.json
(22 section 4 acceptance 5): a version change is a re-check, not a silent update.
"""
from __future__ import annotations

import base64
import json
import os
import pathlib
import re
import urllib.error
import urllib.request

MCP_PATH = "/api/agent_builder/mcp"
MCP_TOOL_RE = re.compile(r"^mcp__(?P<server>.+?)__(?P<tool>[A-Za-z0-9_.-]+)$")


class MCPError(Exception):
    """No answer from the MCP endpoint (network, 5xx, 408, 429): never graded (R-P8). It carries a
    status_code so ara_grade.is_outage() treats it as an outage (503 when there was no answer)."""

    def __init__(self, message: str, status_code: int = 503):
        super().__init__(message)
        self.status_code = status_code


def mcp_call(url: str, auth: str, method: str, params: dict | None = None, timeout: float = 120) -> tuple[int, dict]:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json", "Accept": "application/json, text/event-stream",
        "kbn-xsrf": "true", "Authorization": auth})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw, code = r.read().decode(errors="replace"), r.status
    except urllib.error.HTTPError as e:
        raw, code = e.read().decode(errors="replace"), e.code
        if code in (408, 429) or code >= 500:
            raise MCPError(f"{method}: HTTP {code}", code) from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise MCPError(f"{method}: {type(e).__name__}") from None
    for line in raw.splitlines():
        if line.startswith("data:"):
            raw = line[5:].strip()
            break
    try:
        return code, json.loads(raw) if raw else {}
    except ValueError:
        return code, {"raw": raw[:300]}


def mcp_tools_list(url: str, auth: str) -> tuple[int, list[dict]]:
    mcp_call(url, auth, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                       "clientInfo": {"name": "ara-check", "version": "1"}})
    code, body = mcp_call(url, auth, "tools/list")
    return code, list(((body or {}).get("result") or {}).get("tools") or [])


def mcp_tools_call(url: str, auth: str, name: str, args: dict) -> tuple[int, dict]:
    code, body = mcp_call(url, auth, "tools/call", {"name": name, "arguments": args})
    return code, (body or {}).get("result") or (body or {})


def result_failed(result: dict) -> str | None:
    """Why a tools/call result is a failure, or None. A workflow tool's failure is in the payload
    (execution status), not in isError (probe-43 M5)."""
    if not isinstance(result, dict) or result.get("isError"):
        return "the call returned an error"
    text = " ".join(str(c.get("text", "")) for c in result.get("content") or [] if isinstance(c, dict))
    if re.search(r'"type"\s*:\s*"error"', text):
        return "the tool returned an error result"
    if re.search(r'"status"\s*:\s*"failed"', text):
        return "the workflow run failed"
    return None


def underscore(tool_id: str) -> str:
    return tool_id.replace(".", "_")


def api_key_id(header_value: str) -> str | None:
    """The key id from an `ApiKey <encoded>` header (encoded = base64 of id:secret)."""
    m = re.match(r"^\s*ApiKey\s+(\S+)\s*$", header_value or "")
    if not m:
        return None
    try:
        raw = base64.b64decode(m.group(1) + "=" * (-len(m.group(1)) % 4)).decode()
    except (ValueError, UnicodeDecodeError):
        return None
    return raw.split(":", 1)[0] if ":" in raw else None


def read_learner_json(path: pathlib.Path) -> dict | None:
    """A learner-writable JSON file, read as data: symlinks and non-regular files refused (09 T20)."""
    try:
        st = os.lstat(path)
    except OSError:
        return None
    if not path.is_file() or path.is_symlink() or st.st_size > 1_000_000:
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def transcripts(home: str = "/home/elastic", since: float = 0) -> list[pathlib.Path]:
    """Claude Code session files modified after `since`, oldest first; symlinks refused."""
    root = pathlib.Path(home) / ".claude" / "projects"
    out = []
    for p in root.glob("*/*.jsonl"):
        try:
            if p.is_symlink() or not p.is_file() or os.lstat(p).st_mtime < since:
                continue
        except OSError:
            continue
        out.append(p)
    return sorted(out, key=lambda p: os.lstat(p).st_mtime)


def transcript_calls(path: pathlib.Path, max_bytes: int = 50_000_000) -> dict:
    """Read one transcript as data. Returns {"version", "cwd", "user_turns", "calls": [...]} where each
    call is {"kind": "mcp"|"shell"|"other", "server", "tool", "input", "id", "ok"}."""
    # Tool-use ids are not unique through the gateway (probe-43 r4: every call was toolu_bdrk_0), so a
    # result pairs with the earliest call of its id that has no result yet.
    calls, version, cwd, user_turns = [], None, None, 0
    if path.is_symlink() or os.lstat(path).st_size > max_bytes:
        return {"version": None, "cwd": None, "user_turns": 0, "calls": []}
    for line in path.read_text(errors="replace").splitlines():
        try:
            o = json.loads(line)
        except ValueError:
            continue
        if not isinstance(o, dict):
            continue
        version = o.get("version") or version
        cwd = o.get("cwd") or cwd
        msg = o.get("message") if isinstance(o.get("message"), dict) else {}
        content = msg.get("content")
        if o.get("type") == "user" and isinstance(content, str):
            user_turns += 1
        if not isinstance(content, list):
            continue
        if o.get("type") == "user" and any(isinstance(c, dict) and c.get("type") == "text" for c in content):
            user_turns += 1
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "tool_use":
                name = str(part.get("name", ""))
                m = MCP_TOOL_RE.match(name)
                inp = part.get("input") if isinstance(part.get("input"), dict) else {}
                if m:
                    calls.append({"kind": "mcp", "server": m.group("server"), "tool": m.group("tool"), "input": inp,
                                  "id": part.get("id"), "ok": None})
                elif name == "Bash":
                    calls.append({"kind": "shell", "server": None, "tool": "Bash", "input": inp, "id": part.get("id"), "ok": None})
                else:
                    calls.append({"kind": "other", "server": None, "tool": name, "input": inp, "id": part.get("id"), "ok": None})
            elif part.get("type") == "tool_result":
                for c in calls:
                    if c["id"] == part.get("tool_use_id") and c["ok"] is None:
                        c["ok"] = not part.get("is_error")
                        break
    return {"version": version, "cwd": cwd, "user_turns": user_turns, "calls": calls}
