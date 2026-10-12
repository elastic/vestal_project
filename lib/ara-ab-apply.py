#!/usr/bin/env python3
"""ara-ab-apply.py - apply an M4 start-state manifest to Kibana, idempotently (22 sections 1 and 8.4).

    ara-ab-apply.py <manifest.json> [--check]

Run by provision.sh as root with the admin key (KIBANA_URL, ES_API_KEY in the environment). Every
object in the manifest is created when missing and replaced when it differs; objects the manifest
does not name are left alone. --check changes nothing and exits 1 when any object differs, which
is how the manifest chain test proves a second apply is a no-op.

Manifest shape (manifests/m4/*.json):

    {"id": "ara-m4-4-1-start",
     "extends": "ara-m4-...-start" | null,         # applied first, recursively
     "settings": {"agentBuilder:tracing:enabled": true, ...},
     "workflows": [{"id": "...", "yaml_file": "workflows/x.yml"}],   # relative to the manifest
     "tools": [{"id": "cortex.x", "type": "esql", "description": "...", "configuration": {...}}],
     "agents": [{"id": "tina-compliance", "name": "...", "configuration": {...}}]}

Order: settings, workflows, tools, agents, so every reference exists before it is used.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from agent_builder import AB  # noqa: E402

# 21a section 2 ruling 2 and section 10: every tracing content setting set explicitly, plus the two
# feature flags M4 needs. The manifest may override any of them.
BASE_SETTINGS = {
    "agentBuilder:tracing:enabled": True,
    "agentBuilder:tracing:includeRealNames": True,
    "agentBuilder:tracing:includeRealIds": True,
    "agentBuilder:tracing:includeUserPrompts": True,
    "agentBuilder:tracing:includeToolDetails": True,
    "agentBuilder:tracing:includeLlmResponses": True,
    "agentBuilder:tracing:includeSystemPrompt": True,
    "agentBuilder:experimentalFeatures": True,
    "workflows:ui:enabled": True,
}

# Fields the server adds or that a PUT does not take; ignored when comparing.
_SERVER_FIELDS = {"readonly", "created_at", "updated_at", "createdAt", "updatedAt", "created_by", "updated_by",
                  "schema", "avatar_color", "avatar_symbol", "labels", "type"}


def load(path: pathlib.Path, seen: set | None = None) -> list[tuple[pathlib.Path, dict]]:
    """The manifest and everything it extends, base first."""
    seen = seen or set()
    m = json.loads(path.read_text())
    if m["id"] in seen:
        raise SystemExit(f"manifest cycle at {m['id']}")
    seen.add(m["id"])
    chain = []
    if m.get("extends"):
        chain = load(path.parent / f"{m['extends']}.json", seen)
    return chain + [(path, m)]


def _norm(obj, keep_type: bool = False):
    if isinstance(obj, dict):
        return {k: _norm(v) for k, v in sorted(obj.items())
                if (keep_type or k not in _SERVER_FIELDS) and v not in (None, [], {})}
    if isinstance(obj, list):
        return [_norm(v) for v in obj]
    return obj


def differs(want: dict, have: dict | None) -> bool:
    if have is None:
        return True
    have_sub = {k: have.get(k) for k in want}
    return _norm(want) != _norm(have_sub)


def apply(manifest: pathlib.Path, ab: AB, check: bool = False, log=print) -> int:
    changed = 0
    for path, m in load(manifest):
        settings = {**(BASE_SETTINGS if not m.get("extends") else {}), **(m.get("settings") or {})}
        if settings and not check:
            for key, value in settings.items():  # one at a time, so a refusal names its setting
                code, body = ab.set_settings({key: value})
                if code != 200:
                    raise SystemExit(f"{m['id']}: setting {key} HTTP {code} {str(body)[:200]}")
            log(f"{m['id']}: {len(settings)} settings set")
        for wf in m.get("workflows") or []:
            text = (path.parent / wf["yaml_file"]).read_text()
            have = ab.get_workflow(wf["id"])
            if have is not None and (have.get("yaml") or "").strip() == text.strip():
                continue
            changed += 1
            if check:
                log(f"{m['id']}: workflow {wf['id']} differs")
                continue
            code, body = ab.put_workflow(wf["id"], text)
            if code != 200 or (isinstance(body, dict) and body.get("valid") is False):
                raise SystemExit(f"{m['id']}: workflow {wf['id']} HTTP {code} {str(body)[:300]}")
            log(f"{m['id']}: workflow {wf['id']} applied")
        for tool in m.get("tools") or []:
            if not differs(tool, ab.get_tool(tool["id"])):
                continue
            changed += 1
            if check:
                log(f"{m['id']}: tool {tool['id']} differs")
                continue
            code, body = ab.put_tool(tool)
            if code != 200:
                raise SystemExit(f"{m['id']}: tool {tool['id']} HTTP {code} {str(body)[:300]}")
            log(f"{m['id']}: tool {tool['id']} applied")
        for agent in m.get("agents") or []:
            if not differs(agent, ab.get_agent(agent["id"])):
                continue
            changed += 1
            if check:
                log(f"{m['id']}: agent {agent['id']} differs")
                continue
            code, body = ab.put_agent(agent)
            if code != 200:
                raise SystemExit(f"{m['id']}: agent {agent['id']} HTTP {code} {str(body)[:300]}")
            log(f"{m['id']}: agent {agent['id']} applied")
    return changed


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1].startswith("-"):
        print(__doc__)
        return 2
    check = "--check" in argv[2:]
    ab = AB(os.environ["KIBANA_URL"], os.environ["ES_API_KEY"], timeout=60)
    n = apply(pathlib.Path(argv[1]), ab, check=check)
    print(f"{'differ' if check else 'applied'}: {n}")
    return 1 if check and n else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
