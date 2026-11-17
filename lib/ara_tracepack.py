"""ara_tracepack.py - the trace pack reader and validator, and the 6.1 key (28 sections 2, 8.5).

Pure functions over files and span documents; no HTTP. A pack is gzipped NDJSON under data/ara-m6/traces/<pack>/ with a
per-file hash in a root-held manifest. The manifest's shape is this module's choice (28 leaves it to the builder):

    {"pack": "T-A", "spans": 1234, "files": {"part-000.ndjson.gz": "<sha256 of the file's bytes>", ...}}

    verify_manifest(pack_dir, manifest)      problems: missing or extra file, hash mismatch, span count mismatch
    read_pack(pack_dir)                      every span, in file order
    validate_spans(spans, strict_ids)        structural problems: fields, id shapes, parents, one root per trace
    field_set(spans)                         {flattened field name: type name} (Phase 0 item 0-e)
    compare_field_sets(pack, live)           {"missing": [...], "extra": [...], "type_changed": [...]}
    validate_key_6_1(key, spans, variant)    problems in a 6.1 key against its pack's spans and the variant table
    remap_key(key, id_map)                   the key under the loader's id map (28 section 8.5 item 3)
    compare_record(record, key, fields)      field names that differ; a record never reveals the expected value
    keys_distinct(keys, fields)              True when every two variants differ on every field (6.1 acceptance 2)

Harness numbers never come from traces (28 section 1): nothing here feeds a gate or an aggregate.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import pathlib
import re
from typing import Any

import ara_trace as T

FAILURE_CLASSES = ("tool_error_in_ok_result", "validation_error", "empty_result", "model_error")
COSTLY_CAUSES = ("oversized_tool_result", "repeated_tool_call", "long_system_prompt", "slow_tool")
DEFECTIVE_CLAUSES = ("threshold_stricter_than_policy", "literal_does_not_match_data", "amount_unit_mismatch",
                     "window_too_short", "no_defect")
CAPABILITIES = ("account_history_window", "counterparty_lookup", "policy_exception_by_date", "sanctions_screening",
                "out_of_scope_correctly_escalated")
KEY_FIELDS = ("failing_span_id", "failure_class", "costly_span_id", "costly_cause", "costly_input_tokens")

# 28 section 2's fault table, one row per variant: what each Build's key must say.
VARIANTS = {
    "A": {"failure_class": "tool_error_in_ok_result", "failing_tool": "cortex.read_page", "costly_cause": "oversized_tool_result",
          "defective_clause": "threshold_stricter_than_policy", "missing_capability": "account_history_window"},
    "B": {"failure_class": "validation_error", "failing_tool": "cortex.case_lookup", "costly_cause": "repeated_tool_call",
          "defective_clause": "literal_does_not_match_data", "missing_capability": "counterparty_lookup"},
    "C": {"failure_class": "empty_result", "failing_tool": "cortex.sar_search", "costly_cause": "oversized_tool_result",
          "defective_clause": "amount_unit_mismatch", "missing_capability": "policy_exception_by_date"},
}

_TRACE_ID = re.compile(r"[0-9a-f]{32}")
_SPAN_ID = re.compile(r"[0-9a-f]{16}")


def sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _pack_files(pack_dir: pathlib.Path) -> list[pathlib.Path]:
    return sorted(p for p in pathlib.Path(pack_dir).iterdir() if p.name.endswith(".ndjson.gz"))


def read_file(path: pathlib.Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def read_pack(pack_dir: str | pathlib.Path) -> list[dict]:
    spans: list[dict] = []
    for p in _pack_files(pathlib.Path(pack_dir)):
        spans.extend(read_file(p))
    return spans


def verify_manifest(pack_dir: str | pathlib.Path, manifest: dict) -> list[str]:
    """Counts and per-file hashes against the root-held manifest; any problem fails the Brief's environment gate."""
    pack_dir = pathlib.Path(pack_dir)
    problems = []
    want = manifest.get("files") or {}
    have = {p.name: p for p in _pack_files(pack_dir)}
    for name in sorted(set(want) - set(have)):
        problems.append(f"missing file {name}")
    for name in sorted(set(have) - set(want)):
        problems.append(f"file {name} is not in the manifest")
    for name in sorted(set(want) & set(have)):
        if sha256_file(have[name]) != want[name]:
            problems.append(f"hash mismatch for {name}")
    if not problems and "spans" in manifest:
        n = sum(len(read_file(p)) for p in have.values())
        if n != manifest["spans"]:
            problems.append(f"span count {n}, manifest says {manifest['spans']}")
    return problems


def validate_spans(spans: list[dict], strict_ids: bool = True) -> list[str]:
    """Structure only: every span has trace_id, span_id, name, @timestamp and a numeric duration; ids are unique per
    trace; every parent exists in its own trace; each trace has exactly one root; one conversation id per trace.
    strict_ids also requires 32-hex trace ids and 16-hex span ids (the OpenTelemetry shapes)."""
    problems = []
    seen: set[tuple] = set()
    by_trace: dict[Any, list[dict]] = {}
    for i, s in enumerate(spans):
        miss = [k for k in ("trace_id", "span_id", "name", "@timestamp") if not s.get(k)]
        if miss:
            problems.append(f"span {i}: missing {', '.join(miss)}")
            continue
        if not isinstance(s.get("duration"), (int, float)):
            problems.append(f"span {s['span_id']}: duration is not a number")
        if strict_ids and not (_TRACE_ID.fullmatch(str(s["trace_id"])) and _SPAN_ID.fullmatch(str(s["span_id"]))):
            problems.append(f"span {s['span_id']}: trace or span id has the wrong shape")
        k = (s["trace_id"], s["span_id"])
        if k in seen:
            problems.append(f"span {s['span_id']}: duplicate in trace {s['trace_id']}")
        seen.add(k)
        by_trace.setdefault(s["trace_id"], []).append(s)
    for tid, group in by_trace.items():
        ids = {s["span_id"] for s in group}
        roots = [s for s in group if not s.get("parent_span_id")]
        if len(roots) != 1:
            problems.append(f"trace {tid}: {len(roots)} roots")
        for s in group:
            if s.get("parent_span_id") and s["parent_span_id"] not in ids:
                problems.append(f"span {s['span_id']}: parent {s['parent_span_id']} is not in trace {tid}")
        convs = {T.get(s, "attributes.gen_ai.conversation.id") for s in group} - {None}
        if len(convs) > 1:
            problems.append(f"trace {tid}: {len(convs)} conversation ids")
    return problems


def _flatten(d: dict, prefix: str = "") -> dict[str, str]:
    out = {}
    for k, v in d.items():
        name = f"{prefix}{k}"
        if isinstance(v, dict) and v:
            out.update(_flatten(v, name + "."))
        else:
            out[name] = type(v).__name__
    return out


def field_set(spans: list[dict]) -> dict[str, str]:
    """Every field the spans carry, nested or flat, as a dotted name with a type name. A field seen with two types
    reports the first non-null type."""
    out: dict[str, str] = {}
    for s in spans:
        for k, t in _flatten(s).items():
            if k not in out or out[k] == "NoneType":
                out[k] = t
    return out


def compare_field_sets(pack: dict[str, str], live: dict[str, str]) -> dict[str, list]:
    """Phase 0 item 0-e. `missing` are in the pack and not in the live round, `extra` the reverse."""
    shared = set(pack) & set(live)
    return {"missing": sorted(set(pack) - set(live)), "extra": sorted(set(live) - set(pack)),
            "type_changed": sorted(k for k in shared if "NoneType" not in (pack[k], live[k]) and pack[k] != live[k])}


def validate_key_6_1(key: dict, spans: list[dict], variant: str) -> list[str]:
    """A 6.1 key: ids exist, the failing and costly spans sit in one trace, the classes are in the closed lists and
    match the variant's row, the failing span is a tool span of the variant's tool, and the token count is the costly
    model span's input tokens exactly."""
    problems = []
    row = VARIANTS.get(variant)
    if row is None:
        return [f"unknown variant {variant!r}"]
    by_id = {s.get("span_id"): s for s in spans}
    for f in KEY_FIELDS:
        if f not in key:
            problems.append(f"key lacks {f}")
    if problems:
        return problems
    if key["failure_class"] not in FAILURE_CLASSES:
        problems.append("failure_class is not in the closed list")
    if key["costly_cause"] not in COSTLY_CAUSES:
        problems.append("costly_cause is not in the closed list")
    if key["failure_class"] != row["failure_class"]:
        problems.append(f"failure_class does not match variant {variant}")
    if key["costly_cause"] != row["costly_cause"]:
        problems.append(f"costly_cause does not match variant {variant}")
    if not isinstance(key["costly_input_tokens"], int) or isinstance(key["costly_input_tokens"], bool):
        problems.append("costly_input_tokens is not an integer")
    fail, cost = by_id.get(key["failing_span_id"]), by_id.get(key["costly_span_id"])
    if fail is None:
        problems.append("failing_span_id is not in the pack")
    elif not T.is_tool(fail):
        problems.append("failing_span_id is not a tool span")
    elif T.get(fail, "attributes.gen_ai.tool.name") != row["failing_tool"]:
        problems.append(f"the failing span is not a {row['failing_tool']} call")
    elif T.tool_call(fail)["outcome"] != row["failure_class"]:
        problems.append("the failing span's outcome does not read as the key's failure_class")
    if cost is None:
        problems.append("costly_span_id is not in the pack")
    elif not T.is_model(cost):
        problems.append("costly_span_id is not a model span")
    elif T.model_call(cost)["input_tokens"] != key["costly_input_tokens"]:
        problems.append("costly_input_tokens is not the costly span's input tokens")
    if fail is not None and cost is not None and fail.get("trace_id") != cost.get("trace_id"):
        problems.append("the failing and costly spans are in different traces")
    return problems


def remap_key(key: dict, id_map: dict[str, str]) -> dict:
    """Apply the loader's id map to every string value that is a mapped id, at any depth (a week key nests lists of ids); other values pass through."""
    def walk(v):
        if isinstance(v, str):
            return id_map.get(v, v)
        if isinstance(v, list):
            return [walk(x) for x in v]
        if isinstance(v, dict):
            return {k: walk(x) for k, x in v.items()}
        return v
    return walk(key)


def compare_record(record: dict, key: dict, fields: tuple[str, ...] = KEY_FIELDS) -> list[str]:
    """The fields of a learner's record that differ from the key, by name only. An integer field equals exactly;
    a missing field differs. The caller words the message (09 section 7): it names the field, never the answer."""
    bad = []
    for f in fields:
        if f not in record or record[f] != key.get(f) or type(record[f]) is not type(key.get(f)):
            bad.append(f)
    return bad


def keys_distinct(keys: dict[str, dict], fields: tuple[str, ...] = KEY_FIELDS) -> bool:
    names = sorted(keys)
    return all(keys[a].get(f) != keys[b].get(f) for i, a in enumerate(names) for b in names[i + 1:] for f in fields)
