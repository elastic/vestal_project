"""Offline tests for ara-intake.py: a reload overwrites by intake_id through the default pipeline, reports
records the pipeline fails or drops, and removes strays; _none counts as no pipeline."""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

LIB = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(LIB))
spec = importlib.util.spec_from_file_location("ara_intake", LIB / "ara-intake.py")
I = importlib.util.module_from_spec(spec)
spec.loader.exec_module(I)
DATA = LIB.parent / "data/ara-m5/intake"


class FakeES:
    def __init__(self, pipeline=None, fail_ids=(), drop_ids=()):
        self.pipeline, self.fail_ids, self.drop_ids = pipeline, set(fail_ids), set(drop_ids)
        self.docs, self.calls = {"stray-1": {}}, []

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        if "_settings" in path:
            s = {"index.default_pipeline": self.pipeline} if self.pipeline else {}
            return 200, {"cortex-intake": {"settings": s}}
        if "_delete_by_query" in path:
            keep = set(body["query"]["bool"]["must_not"]["ids"]["values"])
            gone = [k for k in self.docs if k not in keep]
            for k in gone:
                del self.docs[k]
            return 200, {"deleted": len(gone)}
        if path.endswith("_count"):
            return 200, {"count": len(self.docs)}
        return 200, {}

    def request_ndjson(self, method, path, ndjson):
        lines = ndjson.strip().split("\n")
        items = []
        for meta, doc in zip(lines[::2], lines[1::2]):
            _id = json.loads(meta)["index"]["_id"]
            if _id in self.fail_ids:
                items.append({"index": {"_id": _id, "error": {"type": "illegal_argument_exception", "reason": "boom"}}})
            elif _id in self.drop_ids:
                items.append({"index": {"_id": _id, "result": "noop"}})
            else:
                self.docs[_id] = json.loads(doc)
                items.append({"index": {"_id": _id, "result": "created"}})
        return 200, {"items": items, "errors": bool(self.fail_ids)}


def test_reload_is_idempotent_and_removes_strays():
    rows = I.records(DATA)
    es = FakeES(pipeline="cortex-intake-redact")
    a = I.load(es, rows)
    b = I.load(es, rows)
    assert a["pipeline"] == "cortex-intake-redact" and a["indexed"] == len(rows) == a["count"] == b["count"]
    assert a["removed"] == 1 and b["removed"] == 0 and not a["failed"]
    assert set(es.docs) == {r["intake_id"] for r in rows}


def test_failed_and_dropped_records_are_reported():
    rows = I.records(DATA)
    es = FakeES(fail_ids={"intake-003"}, drop_ids={"intake-004"})
    out = I.load(es, rows)
    assert [f["intake_id"] for f in out["failed"]] == ["intake-003", "intake-004"]
    assert "boom" in out["failed"][0]["error"] and out["failed"][1]["error"] == "dropped by the pipeline"
    assert out["count"] == len(rows) - 2


def test_none_pipeline():
    assert I.default_pipeline(FakeES(pipeline="_none")) is None
    assert I.default_pipeline(FakeES()) is None
