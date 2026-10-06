#!/usr/bin/env python3
"""
qa_record.py - check or migrate a track's ara-qa-record.yml to the one schema (alignment N5).

Usage:
  python3 lib/kit/qa_record.py check   <track dir>            # exit 1 on any failure
  python3 lib/kit/qa_record.py migrate <track dir> [--write]  # print (or write) the migrated record

The schema is lib/kit/ara-qa-record.template.yml. migrate keeps the old record byte for byte
under history.pre_alignment_2026_10_06 (re-indented, so it still parses to the same data), fills
what it can read from the track (slug, module, title, assets tag and prefix), and leaves "<...>"
placeholders for the owner; check fails until none is left. Authoring tool; needs PyYAML.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

import yaml

SCHEMA = "ara-qa-record/1"
TEMPLATE = pathlib.Path(__file__).resolve().parent / "ara-qa-record.template.yml"
HISTORY_KEY = "pre_alignment_2026_10_06"
REQUIRED = {
    "schema": str, "track": str, "module": str, "title": str, "assets": dict, "traqs_head": str,
    "calibration": str, "validate_heldout": dict, "lint": dict, "track_test": dict,
    "integrity_review": str, "departures": list, "divergences_kept": list, "status": str,
    "last_updated": str, "history": dict,
}
NESTED = {
    "assets": ("repo", "prefix", "tag", "tag_status", "branch", "head"),
    "validate_heldout": ("command", "result", "date"),
    "lint": ("ara_lint", "align_lint", "instruqt_validate", "date"),
    "track_test": ("result", "participant_id", "slug", "assets_ref", "date"),
}
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
BRANCH = {"M1": "m1-assets", "M2": "m2-v13", "M3": "m3-assets"}


def check(track_dir: pathlib.Path) -> list[str]:
    path = track_dir / "ara-qa-record.yml"
    if not path.exists():
        return [f"{path} missing"]
    try:
        rec = yaml.safe_load(path.read_text())
    except yaml.YAMLError as e:
        return [f"not valid YAML: {e}"]
    if not isinstance(rec, dict):
        return ["not a mapping"]
    fails = []
    for k, t in REQUIRED.items():
        if k not in rec:
            fails.append(f"missing key: {k}")
        elif not isinstance(rec[k], t):
            fails.append(f"{k} must be a {t.__name__}")
    for k, subs in NESTED.items():
        for s in subs:
            if isinstance(rec.get(k), dict) and s not in rec[k]:
                fails.append(f"missing key: {k}.{s}")
    extra = sorted(set(rec) - set(REQUIRED))
    if extra:
        fails.append(f"keys outside the schema (dated notes go under history): {extra}")
    if rec.get("schema") != SCHEMA:
        fails.append(f"schema must be {SCHEMA}")
    if rec.get("track") != track_dir.name:
        fails.append(f"track {rec.get('track')!r} differs from the dir name {track_dir.name!r}")
    if rec.get("module") not in ("M1", "M2", "M3", "M4", "M5", "M6"):
        fails.append("module must be M1 to M6")
    for k in ("last_updated",):
        if isinstance(rec.get(k), str) and not DATE.match(rec[k]):
            fails.append(f"{k} must be YYYY-MM-DD")
    for k in ("validate_heldout", "lint", "track_test"):
        d = rec.get(k)
        if isinstance(d, dict) and isinstance(d.get("date"), str) and not DATE.match(d["date"]):
            fails.append(f"{k}.date must be YYYY-MM-DD")
    left = sorted(set(re.findall(r"<[^<>\n]{1,60}>", yaml.safe_dump({k: v for k, v in rec.items() if k != "history"}))))
    if left:
        fails.append(f"placeholders left: {left[:5]}")
    return fails


def _read(pattern: str, text: str) -> str | None:
    m = re.search(pattern, text, re.M)
    return m.group(1) if m else None


def migrate(track_dir: pathlib.Path) -> str:
    path = track_dir / "ara-qa-record.yml"
    old = path.read_text() if path.exists() else ""
    old_data = yaml.safe_load(old) if old.strip() else None
    if isinstance(old_data, dict) and old_data.get("schema") == SCHEMA:
        raise SystemExit(f"{path} is already {SCHEMA}")
    slug = track_dir.name
    m = re.match(r"cert-sk-ara-(\d)-", slug)
    module = f"M{m.group(1)}" if m else "<M1|M2|M3>"
    title = "<track.yml title>"
    ty = track_dir / "track.yml"
    if ty.exists():
        title = (yaml.safe_load(ty.read_text()) or {}).get("title", title)
    setup = next(iter(sorted(track_dir.glob("01-*/setup-elastic-serverless"))), None)
    stext = setup.read_text() if setup else ""
    tag = _read(r'^ARA_ASSETS_TAG="([^"]+)"', stext) or "<ARA_ASSETS_TAG>"
    prefix = _read(r'^ARA_ASSETS_PREFIX="([^"]+)"', stext) or "agentic-retrieval-architect/<m>"

    new = TEMPLATE.read_text()
    new = re.sub(r"^#.*\n", "", new, flags=re.M)   # the template's own header comment
    subs = {"track: <slug>": f"track: {slug}", "module: <M1|M2|M3>": f"module: {module}",
            'title: "<track.yml title>"': f"title: {yaml.safe_dump(title, width=1000).strip().removesuffix('...').strip()}",
            'tag: "<ARA_ASSETS_TAG in the ch01 setup>"': f'tag: "{tag}"',
            "prefix: agentic-retrieval-architect/<m1|m2|m3>": f"prefix: {prefix}",
            "branch: <m1-assets|m2-v13|m3-assets>": f"branch: {BRANCH.get(module, '<branch>')}"}
    for a, b in subs.items():
        new = new.replace(a, b)
    new = re.sub(r"\s+#.*$", "", new, flags=re.M)  # field comments
    new = new.replace("history: {}", "history:")
    body = re.sub(r"\A---\s*\n", "", old).rstrip("\n")
    if body.strip():
        indented = "\n".join(("    " + line) if line.strip() else "" for line in body.split("\n"))
        new = new.rstrip("\n") + f"\n  {HISTORY_KEY}:\n{indented}\n"
    else:
        new = new.replace("history:", "history: {}").rstrip("\n") + "\n"
    parsed = yaml.safe_load(new)
    if old_data is not None and parsed["history"][HISTORY_KEY] != old_data:
        raise SystemExit("migration changed the old record's data; not writing")
    return new


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="ARA qa-record schema tool")
    ap.add_argument("cmd", choices=("check", "migrate"))
    ap.add_argument("track_dir", type=pathlib.Path)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "check":
        fails = check(a.track_dir)
        for f in fails:
            print(f"  FAIL: {f}")
        print("  OK" if not fails else f"  {len(fails)} failure(s)")
        return 1 if fails else 0
    text = migrate(a.track_dir)
    if a.write:
        (a.track_dir / "ara-qa-record.yml").write_text(text)
        print(f"Written: {a.track_dir / 'ara-qa-record.yml'}; fill the <...> fields, then run check.")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
