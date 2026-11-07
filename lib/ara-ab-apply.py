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
     "connectors": [{"name": "...", "connector_type_id": ".http", "config": {...}}],   # by name (ids are
                                                                     # server-assigned); no secrets
     "workflows": [{"id": "...", "yaml_file": "workflows/x.yml"}],   # relative to the manifest;
                                                                     # @@CONNECTOR@@ -> $ARA_AB_CONNECTOR_ID
     "tools": [{"id": "cortex.x", "type": "esql", "description": "...", "configuration": {...}}],
     "skills": [{"id": "cortex-x", "name": "...", "description": "...", "content": "...", "tool_ids": [...]}],
     "plugins": [{"name": "cortex-compliance", "source_url": "https://github.com/.../tree/<tag>/..."}],
     "agents": [{"id": "tina-compliance", "name": "...", "configuration": {...}}]}   # sub-agents first

Order: settings, connectors, workflows, tools, skills, plugins, agents, so every reference exists before it
is used. A plugin id is server-assigned: an agent names it as "@@PLUGIN:<name>@@" in plugin_ids, resolved
to the installed plugin with that source_url. Connectors and plugins are M5 additions (R-4): M4 made the
4.4 connector and plugin in its solve, and ara-m4-end needs them as manifest objects.
"""
from __future__ import annotations

import json
import os
import re
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from agent_builder import AB  # noqa: E402
from ara_extensions import plugin_by_source  # noqa: E402

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

CONNECTOR_PLACEHOLDER = "@@CONNECTOR@@"
PLUGIN_REF = re.compile(r"^@@PLUGIN:(.+)@@$")

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


def _config_same(want: dict, have: dict) -> bool:
    """A connector config matches when every key the manifest states matches and every key the server
    added is unset (None, False or empty: the server fills headers, proxyUrl, hasProxyAuth and the like,
    probe r6). A header added by hand is still a difference."""
    return all(_norm(want.get(k)) == _norm(have.get(k)) for k in want) \
        and not any(have[k] for k in have if k not in want)


def differs(want: dict, have: dict | None) -> bool:
    if have is None:
        return True
    have_sub = {k: have.get(k) for k in want}
    return _norm(want) != _norm(have_sub)


def resolve_plugins(agent: dict, ab: AB, urls: dict, check: bool) -> dict:
    """Replace "@@PLUGIN:<name>@@" in configuration.plugin_ids with the installed plugin's id. Under
    --check a plugin not yet installed keeps its placeholder, so the agent shows as differing."""
    cfg = agent.get("configuration") or {}
    ids = cfg.get("plugin_ids")
    if not ids:
        return agent
    out = []
    for pid in ids:
        m = PLUGIN_REF.match(pid)
        if not m:
            out.append(pid)
            continue
        if m.group(1) not in urls:
            raise SystemExit(f"agent {agent['id']}: plugin {m.group(1)} is not in this manifest chain")
        plug = plugin_by_source(ab, urls[m.group(1)])
        if plug is None and not check:
            raise SystemExit(f"agent {agent['id']}: plugin {m.group(1)} is not installed")
        out.append(plug["id"] if plug else pid)
    return {**agent, "configuration": {**cfg, "plugin_ids": out}}


KINDS = (("connectors", "name"), ("workflows", "id"), ("tools", "id"), ("skills", "id"), ("plugins", "name"),
         ("agents", "id"))


def effective(chain: list[tuple[pathlib.Path, dict]]) -> dict:
    """One manifest equal to applying the chain in order: settings merged over BASE_SETTINGS, and per kind
    each object's last definition, placed where it was last defined (so a sub-agent a later manifest lists
    before Tina still comes first). Applied once, a chain writes each object at most once, and --check
    compares the end state, not every intermediate definition."""
    out = {"id": chain[-1][1]["id"], "settings": dict(BASE_SETTINGS)}
    for kind, key in KINDS:
        last: dict = {}
        for n, (path, m) in enumerate(chain):
            for i, obj in enumerate(m.get(kind) or []):
                obj = dict(obj)
                if kind == "workflows":
                    obj["_file"] = path.parent / obj["yaml_file"]
                last[obj[key]] = ((n, i), obj)
        out[kind] = [o for _, o in sorted(last.values(), key=lambda x: x[0])]
    for _, m in chain:
        out["settings"].update(m.get("settings") or {})
    return out


def apply(manifest: pathlib.Path, ab: AB, check: bool = False, log=print) -> int:
    changed = 0
    plugin_urls: dict = {}
    for m in [effective(load(manifest))]:
        settings = m["settings"]
        if settings and not check:
            for key, value in settings.items():  # one at a time, so a refusal names its setting
                code, body = ab.set_settings({key: value})
                if code != 200:
                    raise SystemExit(f"{m['id']}: setting {key} HTTP {code} {str(body)[:200]}")
            log(f"{m['id']}: {len(settings)} settings set")
        for conn in m.get("connectors") or []:
            have = ab.connector_by_name(conn["name"])
            if have is not None and have.get("connector_type_id") == conn["connector_type_id"] \
                    and _config_same(conn.get("config") or {}, have.get("config") or {}):
                continue
            changed += 1
            if check:
                log(f"{m['id']}: connector {conn['name']} differs")
                continue
            if have is not None and have.get("connector_type_id") != conn["connector_type_id"]:
                ab.delete_connector(have["id"])  # a connector's type cannot change in place
            code, body = ab.put_connector(conn["name"], conn["connector_type_id"], conn.get("config") or {})
            if code != 200:
                raise SystemExit(f"{m['id']}: connector {conn['name']} HTTP {code} {str(body)[:300]}")
            log(f"{m['id']}: connector {conn['name']} applied")
        for wf in m.get("workflows") or []:
            text = wf["_file"].read_text()
            # Workflow AI steps name the pinned connector (D-18); the manifest holds a placeholder.
            if CONNECTOR_PLACEHOLDER in text:
                conn = os.environ.get("ARA_AB_CONNECTOR_ID")
                if not conn:
                    raise SystemExit(f"{m['id']}: workflow {wf['id']} needs ARA_AB_CONNECTOR_ID")
                text = text.replace(CONNECTOR_PLACEHOLDER, conn)
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
        for skill in m.get("skills") or []:
            if not differs(skill, ab.get_skill(skill["id"])):
                continue
            changed += 1
            if check:
                log(f"{m['id']}: skill {skill['id']} differs")
                continue
            code, body = ab.put_skill(skill)
            if code != 200:
                raise SystemExit(f"{m['id']}: skill {skill['id']} HTTP {code} {str(body)[:300]}")
            log(f"{m['id']}: skill {skill['id']} applied")
        for plug in m.get("plugins") or []:
            plugin_urls[plug["name"]] = plug["source_url"]
            if plugin_by_source(ab, plug["source_url"]) is not None:
                continue
            changed += 1
            if check:
                log(f"{m['id']}: plugin {plug['name']} not installed")
                continue
            code, body = ab.install_plugin(plug["source_url"])
            if code != 200 or plugin_by_source(ab, plug["source_url"]) is None:
                raise SystemExit(f"{m['id']}: plugin {plug['name']} HTTP {code} {str(body)[:300]}")
            log(f"{m['id']}: plugin {plug['name']} installed")
        for agent in m.get("agents") or []:
            agent = resolve_plugins(agent, ab, plugin_urls, check)
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
