#!/usr/bin/env python3
"""
ara-intake.py - (re)load Cortex's intake set into cortex-intake (25 section 3, Lab 5.2 Build 3).

Usage:
  python3 /opt/ara/lib/ara-intake.py load            # as the learner (credentials from ~/env)
  python3 /opt/ara/lib/ara-intake.py init <mapping>  # provisioning only: create the index, no pipeline

load indexes every raw record in /opt/ara/data/intake/*.ndjson into cortex-intake, through whatever
default pipeline the index has (index.default_pipeline), and removes any document that is not a raw
record. Each record keeps its intake_id as _id, so a reload replaces the same documents and is
idempotent: run it after every pipeline change. The check runs the same reload before it measures.

Why load overwrites in place instead of recreating the index: the learner's configuration lives on the
index (the default pipeline setting, any mapping a pipeline's new fields added) and in the roles that
name it. A reload's job is the data. Recreating would have to copy every setting back, would drop
anything it did not know to copy, and would leave the index missing for a moment while a tool or a
check reads it. Overwriting by _id and deleting strays keeps every setting and needs no copy.

Standard library only; imported by the 5.2 check (load()).
"""
from __future__ import annotations

import glob
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import ara_security as S  # noqa: E402

INDEX = "cortex-intake"
DATA = pathlib.Path(os.environ.get("ARA_INTAKE_DATA", "/opt/ara/data/intake"))
BATCH = 100


def records(data: pathlib.Path = DATA) -> list[dict]:
    out = []
    for f in sorted(glob.glob(str(data / "*.ndjson"))):
        out += [json.loads(line) for line in pathlib.Path(f).read_text().splitlines() if line.strip()]
    if not out:
        raise SystemExit(f"No intake records under {data}.")
    return out


def default_pipeline(es: S.ES) -> str | None:
    """The index's default pipeline, or None (unset, or "_none")."""
    code, body = es.request("GET", f"/{INDEX}/_settings/index.default_pipeline?flat_settings=true")
    if code != 200:
        raise SystemExit(f"{INDEX}: settings HTTP {code} {str(body)[:200]}")
    p = ((body.get(INDEX) or {}).get("settings") or {}).get("index.default_pipeline")
    return None if p in (None, "", "_none") else p


def create(es: S.ES, mapping: dict) -> None:
    """Provisioning: the index with the committed mapping and no pipeline (25 section 3 start state)."""
    code, body = es.request("DELETE", f"/{INDEX}?ignore_unavailable=true")
    if code not in (200, 404):
        raise SystemExit(f"{INDEX}: delete HTTP {code} {str(body)[:200]}")
    code, body = es.request("PUT", f"/{INDEX}", mapping)
    if code != 200:
        raise SystemExit(f"{INDEX}: create HTTP {code} {str(body)[:300]}")


def load(es: S.ES, rows: list[dict] | None = None) -> dict:
    """Reload the raw records through the index's default pipeline. Returns {"pipeline", "indexed",
    "failed": [{"intake_id", "error"}], "removed", "count"}. A record the pipeline fails or drops is
    reported, never retried: the pipeline is the thing under test."""
    rows = records() if rows is None else rows
    pipeline = default_pipeline(es)
    failed, indexed = [], 0
    for i in range(0, len(rows), BATCH):
        part = rows[i:i + BATCH]
        ops = "".join(json.dumps({"index": {"_index": INDEX, "_id": r["intake_id"]}}) + "\n" + json.dumps(r) + "\n"
                      for r in part)
        code, body = es.request_ndjson("POST", "/_bulk", ops)
        if code != 200:
            raise SystemExit(f"{INDEX}: bulk HTTP {code} {str(body)[:300]}")
        for r, item in zip(part, body.get("items") or []):
            res = next(iter(item.values()))
            if res.get("error"):
                err = res["error"]
                failed.append({"intake_id": r["intake_id"],
                               "error": f"{err.get('type')}: {err.get('reason')}"[:300] if isinstance(err, dict) else str(err)[:300]})
            elif res.get("result") == "noop":  # a drop processor
                failed.append({"intake_id": r["intake_id"], "error": "dropped by the pipeline"})
            else:
                indexed += 1
    ids = [r["intake_id"] for r in rows]
    code, body = es.request("POST", f"/{INDEX}/_delete_by_query?refresh=true",
                            {"query": {"bool": {"must_not": {"ids": {"values": ids}}}}})
    removed = body.get("deleted", 0) if code == 200 else 0
    es.request("POST", f"/{INDEX}/_refresh")
    code, body = es.request("GET", f"/{INDEX}/_count")
    return {"pipeline": pipeline, "indexed": indexed, "failed": failed, "removed": removed,
            "count": body.get("count") if code == 200 else None}


def _env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        sys.exit(f"{name} is not set. Open a new terminal (it loads ~/env) and run this again.")
    return v


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in ("load", "init"):
        print(__doc__.strip().split("\n\n")[1])
        return 2
    es = S.ES(_env("ES_ENDPOINT").rstrip("/"), S.api_key_auth(_env("ES_API_KEY")), timeout=60)
    if argv[0] == "init":
        create(es, json.loads(pathlib.Path(argv[1]).read_text()))
        out = load(es)
        print(f"{INDEX}: {out['count']} records, no pipeline")
        return 0 if out["count"] == len(records()) and not out["failed"] else 1
    out = load(es)
    via = f"through the default pipeline {out['pipeline']}" if out["pipeline"] else "with no default pipeline (stored as typed)"
    print(f"Loaded {out['indexed']} of {out['indexed'] + len(out['failed'])} intake records into {INDEX} {via}.")
    if out["removed"]:
        print(f"Removed {out['removed']} document(s) that are not intake records.")
    for f in out["failed"][:3]:
        print(f"  {f['intake_id']}: {f['error']}")
    if out["failed"]:
        print(f"{len(out['failed'])} record(s) did not load. Test the pipeline on one record with "
              f"POST _ingest/pipeline/<name>/_simulate, fix it, and run this again.")
        return 1
    print(f"{INDEX} now holds {out['count']} documents.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
