#!/usr/bin/env python3
"""
ara-packs.py - trace packs for Lab 6.1 and the M6 histories (builder and setup use; never the learner).

  python3 ara-packs.py write  <spans.ndjson> <pack-dir> --pack T-A [--part-size 5000]
  python3 ara-packs.py verify <pack-dir> <manifest.json>
  python3 ara-packs.py load   <pack-dir> <manifest.json> --salt <sandbox salt> [--key key.json --out-key remapped.json] [--end-hours-before 1]

`load` reads ES_URL and ES_API_KEY from the environment (setup runs it as root with the project's admin key), verifies the
manifest and the spans first, re-times the pack to end an hour before now, bulk-creates the spans with explicit ids, and writes the
key remapped to the loaded ids. Exit 0 done, 1 the pack does not verify or the load was refused, 2 bad input.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import ara_pack_cli as C  # noqa: E402


def main(argv: list[str], es=None, now=None) -> int:
    ap = argparse.ArgumentParser(prog="ara-packs.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("write"); w.add_argument("spans"); w.add_argument("pack_dir"); w.add_argument("--pack", required=True); w.add_argument("--part-size", type=int, default=5000)
    v = sub.add_parser("verify"); v.add_argument("pack_dir"); v.add_argument("manifest")
    l = sub.add_parser("load"); l.add_argument("pack_dir"); l.add_argument("manifest"); l.add_argument("--salt", required=True)
    l.add_argument("--key"); l.add_argument("--out-key"); l.add_argument("--end-hours-before", type=float, default=1.0)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "write":
            spans = [json.loads(x) for x in pathlib.Path(a.spans).read_text().splitlines() if x.strip()]
            m = C.write_pack(spans, a.pack_dir, a.pack, a.part_size)
            print(f"wrote {len(m['files'])} part(s), {m['spans']} spans, manifest.json")
            return 0
        manifest = json.loads(pathlib.Path(a.manifest).read_text())
        if a.cmd == "verify":
            bad = C.verify(a.pack_dir, manifest)
            print("\n".join(bad) if bad else f"{manifest['pack']}: verified, {manifest['spans']} spans")
            return 1 if bad else 0
        if es is None:
            from ara_security import ES
            es = ES(os.environ["ES_URL"].rstrip("/"), f"ApiKey {os.environ['ES_API_KEY']}", timeout=300)
        key = json.loads(pathlib.Path(a.key).read_text()) if a.key else None
        out = C.load(a.pack_dir, manifest, es, now or datetime.datetime.now(datetime.timezone.utc), key, a.salt, a.end_hours_before)
        if a.out_key and out["key"] is not None:
            pathlib.Path(a.out_key).write_text(json.dumps(out["key"], indent=2, sort_keys=True) + "\n")
        print(f"loaded {out['spans']} spans ({out['created']} created, {out['already_loaded']} already there)")
        return 0
    except (C.PackError, OSError, ValueError, KeyError) as e:
        print(f"{type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
