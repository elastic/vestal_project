#!/usr/bin/env python3
"""
m4_lint.py - the M4 lint lines (22 section 1, standard seed), for one traqs track.

Usage:
  python3 lib/kit/m4_lint.py <traqs track dir> [--assets <vestal_project root>]

Authoring tool; nothing in a sandbox runs it. Runs beside ara-lint.sh and align_lint.py. Rules:
  tag        ARA_ASSETS_TAG in the 01 setup is an m4-* tag, never main (D-09)
  connector  every check or solve file that converses (converse( or run_cases() builds its client
             with the pinned connector: ARA_AB_CONNECTOR_ID or the track helper's tina()
  message    no grading check (NN-*.py) reads response.message or ["response"] (answer prose is
             never graded, 22 section 1)
  ids        custom tool ids are dotted cortex.<name>; agent and workflow ids are hyphenated
             (22 section 8.1), in thresholds.json and the start manifest
  manifest   every agent and tool id a check reads (thresholds.json, AGENT_ID) is in the start
             manifest or built by the Builds (thresholds tool_id / workflow_id)
  model      a model or vendor id appears only on a line marked "# ARA_MODEL" (22 section 1)
  identity   no grading check converses with ES_API_KEY (checks converse as tina-runtime)
Exit 1 on any FAIL.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

MODEL_RE = re.compile(r"(claude-[a-z0-9.-]+|Claude-Sonnet|sonnet-\d|gemini-\d|gpt-\d|Anthropic-)", re.I)
TOOL_ID_RE = re.compile(r"^cortex\.[a-z0-9_]+$")
HYPHEN_ID_RE = re.compile(r"^(tina|cortex)-[a-z0-9-]+$")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("track", type=pathlib.Path)
    ap.add_argument("--assets", type=pathlib.Path, default=pathlib.Path(__file__).resolve().parents[2])
    a = ap.parse_args(argv)
    track, fails = a.track.resolve(), 0

    def report(rule, ok, msg):
        nonlocal fails
        print(f"  {'ok  ' if ok else 'FAIL'} {rule} {msg}")
        fails += 0 if ok else 1

    print(track.name)
    setup = next(track.glob("01-*/setup-elastic-serverless")).read_text()
    m = re.search(r'^ARA_ASSETS_TAG="([^"]+)"', setup, re.M)
    report("tag", bool(m) and m.group(1).startswith("m4-"), f"ARA_ASSETS_TAG={m.group(1) if m else None}")

    checks_dir = next(track.glob("private/checks/*/"), None)
    files = sorted(checks_dir.glob("*.py")) if checks_dir else []
    for f in files:
        text = f.read_text()
        if re.search(r"\.converse\(|run_cases\(", text):
            ok = "ARA_AB_CONNECTOR_ID" in text or re.search(r"\btina\(\)", text)
            report("connector", bool(ok), f.name)
        if re.match(r"\d\d-", f.name):
            report("message", not re.search(r"response\.message|\[\"response\"\]|\.get\(\"response\"\)", text), f.name)
            report("identity", not re.search(r"AB\([^)]*ES_API_KEY[^)]*\)\.converse|admin\(\)\.converse", text), f.name)

    thresholds = json.loads((track / "private/thresholds.json").read_text())
    ids = [(k, v) for sec in thresholds.values() if isinstance(sec, dict) for k, v in sec.items()
           if k in ("tool_id", "workflow_id")]
    for k, v in ids:
        ok = TOOL_ID_RE.match(v) if k == "tool_id" else HYPHEN_ID_RE.match(v)
        report("ids", bool(ok), f"{k}={v}")
    mpath = re.search(r"manifests/m4/([\w.-]+\.json)", setup)
    manifest_ids: set[str] = set()
    if mpath:
        mf = a.assets / "manifests/m4" / mpath.group(1)
        chain = []
        while mf.exists():
            m4 = json.loads(mf.read_text())
            chain.append(m4)
            mf = mf.parent / f"{m4['extends']}.json" if m4.get("extends") else pathlib.Path("/nonexistent")
        for m4 in chain:
            for t in m4.get("tools") or []:
                manifest_ids.add(t["id"])
                report("ids", bool(TOOL_ID_RE.match(t["id"])), f"manifest tool {t['id']}")
            for ag in m4.get("agents") or []:
                manifest_ids.add(ag["id"])
                report("ids", bool(HYPHEN_ID_RE.match(ag["id"])), f"manifest agent {ag['id']}")
    built = {v for sec in thresholds.values() if isinstance(sec, dict) for k, v in sec.items() if k in ("tool_id", "workflow_id")}
    for f in files:
        for agent_id in re.findall(r'AGENT_ID\s*=\s*"([^"]+)"', f.read_text()):
            report("manifest", agent_id in manifest_ids | built, f"{f.name} reads agent {agent_id}")
    report("manifest", bool(mpath), f"start manifest {mpath.group(1) if mpath else 'not named in the 01 setup'}")

    for f in sorted(track.rglob("*")):
        if not f.is_file() or "__pycache__" in f.parts or f.suffix not in ("", ".md", ".py", ".json", ".yml", ".sh"):
            continue
        for n, line in enumerate(f.read_text(errors="replace").splitlines(), 1):
            if MODEL_RE.search(line) and "# ARA_MODEL" not in line:
                report("model", False, f"{f.relative_to(track)}:{n}: {line.strip()[:90]}")
    print(f"  {fails} FAIL")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
