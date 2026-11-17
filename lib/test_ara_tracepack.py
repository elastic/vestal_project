"""Offline tests for ara_tracepack.py."""
import gzip
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ara_history as H  # noqa: E402
import ara_trace as T  # noqa: E402
import ara_tracepack as P  # noqa: E402
from test_ara_trace import round_a  # noqa: E402


def write_pack(d, spans, parts=2):
    files = {}
    for i in range(parts):
        p = d / f"part-{i:03d}.ndjson.gz"
        with gzip.open(p, "wt") as f:
            for s in spans[i::parts]:
                f.write(json.dumps(s) + "\n")
        files[p.name] = P.sha256_file(p)
    return {"pack": "T-A", "spans": len(spans), "files": files}


def key_a():
    return {"failing_span_id": "a6", "failure_class": "tool_error_in_ok_result", "costly_span_id": "a5",
            "costly_cause": "oversized_tool_result", "costly_input_tokens": 9000}


def test_manifest_verifies_and_read_returns_every_span(tmp_path):
    m = write_pack(tmp_path, round_a())
    assert P.verify_manifest(tmp_path, m) == []
    assert sorted(s["span_id"] for s in P.read_pack(tmp_path)) == sorted(s["span_id"] for s in round_a())


def test_manifest_mismatches_are_named(tmp_path):
    m = write_pack(tmp_path, round_a())
    (tmp_path / "part-000.ndjson.gz").write_bytes(gzip.compress(b'{"a":1}\n'))
    assert P.verify_manifest(tmp_path, m) == ["hash mismatch for part-000.ndjson.gz"]
    (tmp_path / "part-001.ndjson.gz").unlink()
    (tmp_path / "extra.ndjson.gz").write_bytes(b"")
    out = P.verify_manifest(tmp_path, m)
    assert "missing file part-001.ndjson.gz" in out and "file extra.ndjson.gz is not in the manifest" in out


def test_span_count_mismatch(tmp_path):
    m = write_pack(tmp_path, round_a())
    m["spans"] += 1
    assert P.verify_manifest(tmp_path, m) == [f"span count {len(round_a())}, manifest says {len(round_a()) + 1}"]


def test_validate_spans_clean_and_broken():
    assert P.validate_spans(round_a(), strict_ids=False) == []
    s = round_a()
    s[3]["parent_span_id"] = "ghost"
    s.append(dict(s[1]))
    out = P.validate_spans(s, strict_ids=False)
    assert any("parent ghost" in p for p in out) and any("duplicate" in p for p in out)
    assert any(p.startswith("span a0: trace or span id") for p in P.validate_spans(round_a()))
    del s[0]["name"]
    assert any("missing name" in p for p in P.validate_spans(s, strict_ids=False))


def test_validate_spans_requires_one_root_and_one_conversation():
    s = round_a()
    s[1]["parent_span_id"] = None
    assert any("2 roots" in p for p in P.validate_spans(s, strict_ids=False))
    s = round_a()
    s[2].setdefault("attributes", {})["gen_ai.conversation.id"] = "c-2"
    assert any("2 conversation ids" in p for p in P.validate_spans(s, strict_ids=False))


def test_strict_ids_accept_hex_after_a_salted_remap():
    out = H.retime(round_a(), T.parse_ts("2026-11-10T00:00:00Z"), 3, salt="s")
    assert P.validate_spans(out) == []


def test_field_set_and_compare():
    a = P.field_set(round_a())
    assert a["attributes.gen_ai.tool.name"] == "str" and a["duration"] == "int"
    live = dict(a)
    live["new.field"] = "str"
    del live["attributes.gen_ai.tool.name"]
    live["duration"] = "float"
    assert P.compare_field_sets(a, live) == {"missing": ["attributes.gen_ai.tool.name"], "extra": ["new.field"], "type_changed": ["duration"]}
    assert P.compare_field_sets(a, a) == {"missing": [], "extra": [], "type_changed": []}


def test_key_validates_against_spans_and_variant():
    assert P.validate_key_6_1(key_a(), round_a(), "A") == []
    k = key_a() | {"costly_input_tokens": 1234}
    assert P.validate_key_6_1(k, round_a(), "A") == ["costly_input_tokens is not the costly span's input tokens"]
    # a key copied from variant A fails variant B's table
    out = P.validate_key_6_1(key_a(), round_a(), "B")
    assert "failure_class does not match variant B" in out and "costly_cause does not match variant B" in out
    assert P.validate_key_6_1(key_a() | {"failing_span_id": "a4"}, round_a(), "A")[0] == "the failing span is not a cortex.read_page call"
    assert P.validate_key_6_1(key_a() | {"costly_span_id": "zz"}, round_a(), "A") == ["costly_span_id is not in the pack"]
    assert P.validate_key_6_1({}, round_a(), "A")[0] == "key lacks failing_span_id"
    assert P.validate_key_6_1(key_a(), round_a(), "Z") == ["unknown variant 'Z'"]


def test_remap_key_follows_the_loader_map():
    spans = round_a()
    m = H.id_map(spans, "s")
    k = P.remap_key(key_a(), m)
    assert k["failing_span_id"] == m["a6"] and k["costly_span_id"] == m["a5"]
    assert k["costly_input_tokens"] == 9000 and k["failure_class"] == "tool_error_in_ok_result"


def test_compare_record_names_fields_not_answers():
    rec = key_a() | {"costly_input_tokens": 9001, "failure_class": "empty_result"}
    assert P.compare_record(rec, key_a()) == ["failure_class", "costly_input_tokens"]
    assert P.compare_record({k: v for k, v in key_a().items() if k != "costly_cause"}, key_a()) == ["costly_cause"]
    assert P.compare_record(key_a() | {"costly_input_tokens": "9000"}, key_a()) == ["costly_input_tokens"]
    assert P.compare_record(key_a(), key_a()) == []


def test_variants_have_distinct_keys():
    keys = {"A": key_a(), "B": key_a() | {"failing_span_id": "b1"}, "C": key_a() | {"failing_span_id": "c1"}}
    assert not P.keys_distinct(keys)  # failure_class etc. still equal
    for v in "ABC":
        keys[v] = {f: f"{v}-{f}" for f in P.KEY_FIELDS}
    assert P.keys_distinct(keys)
    # the variant table itself never repeats a fault between two variants
    for f in ("failure_class", "defective_clause", "missing_capability", "failing_tool"):
        assert len({r[f] for r in P.VARIANTS.values()}) == 3
