"""ara_pack_cli.py - write, verify and load a trace pack (28 section 8.5): the logic behind ara-packs.py.

    write_pack(spans, pack_dir, pack, part_size)   gzipped NDJSON parts + the manifest {"pack", "spans", "files"} (deterministic bytes)
    verify(pack_dir, manifest)                     manifest problems and structural problems of the spans
    load(pack_dir, manifest, es, now, key, ...)    verify, re-time to end `end_hours_before` hours before now under a salt, bulk-create,
                                                   return the id map, the remapped key and counts; never loads a pack that fails verify

`es` is injected: request_ndjson(method, path, text) -> (status, body). The load is idempotent (a 409 on create is a span that is
already there) and stops on any other bulk error. Ids are replaced under one deterministic map (ara_history.id_map) so two
sandboxes loading the same pack see the same ids, and the root-held key is remapped with the same map (28 section 8.5 item 3), so
`failing_span_id` in the key names the span the learner reads. Standard library only.
"""
from __future__ import annotations

import gzip
import json
import pathlib
from datetime import datetime
from typing import Any

import ara_history as H
import ara_tracepack as T

SPAN_INDEX = "traces-agent_builder.otel-default"
PART_SUFFIX = ".ndjson.gz"


class PackError(Exception):
    pass


def _gz(lines: list[str]) -> bytes:
    import io
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as g:  # mtime 0: the same spans always give the same bytes
        g.write(("\n".join(lines) + "\n").encode())
    return buf.getvalue()


def write_pack(spans: list[dict], pack_dir: str | pathlib.Path, pack: str, part_size: int = 5000) -> dict:
    """Write spans in order as part-000.ndjson.gz, ...; returns (and writes as manifest.json beside the parts) the manifest.
    The manifest is root-held in a sandbox: setup copies it from /opt/ara/heldout, not from the pack directory."""
    d = pathlib.Path(pack_dir)
    d.mkdir(parents=True, exist_ok=True)
    for old in d.glob(f"part-*{PART_SUFFIX}"):
        old.unlink()
    files = {}
    for i in range(0, max(len(spans), 1), part_size):
        name = f"part-{i // part_size:03d}{PART_SUFFIX}"
        (d / name).write_bytes(_gz([json.dumps(s, sort_keys=True, separators=(",", ":")) for s in spans[i:i + part_size]]))
        files[name] = T.sha256_file(d / name)
    manifest = {"pack": pack, "spans": len(spans), "files": files}
    (d / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def verify(pack_dir: str | pathlib.Path, manifest: dict) -> list[str]:
    bad = T.verify_manifest(pack_dir, manifest)
    if bad:
        return bad
    return T.validate_spans(T.read_pack(pack_dir))


def load(pack_dir: str | pathlib.Path, manifest: dict, es: Any, now: datetime, key: dict | None = None, salt: str = "",
         end_hours_before: float = 1.0, index: str = SPAN_INDEX, chunk: int = 2000) -> dict:
    bad = verify(pack_dir, manifest)
    if bad:
        raise PackError("the pack does not verify: " + "; ".join(bad[:5]))
    spans = T.read_pack(pack_dir)
    moved = H.retime(spans, now, end_hours_before / 24.0, salt or None)
    created = existing = 0
    for part in H.chunks(moved, chunk):
        code, body = es.request_ndjson("POST", "/_bulk?refresh=wait_for", H.bulk_body(part, index, manifest.get("pack", "")))
        if code != 200 or not isinstance(body, dict):
            raise PackError(f"bulk load refused (HTTP {code})")
        c, e, errors = H.bulk_result(body)
        if errors:
            raise PackError(f"{len(errors)} spans were rejected; first: {str(errors[0])[:200]}")
        created, existing = created + c, existing + e
    ids = H.id_map(spans, salt) if salt else {}
    return {"spans": len(spans), "created": created, "already_loaded": existing, "id_map": ids,
            "key": T.remap_key(key, ids) if key is not None else None}
