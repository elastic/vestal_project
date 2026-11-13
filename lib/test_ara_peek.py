"""Offline tests for ara_behavior.peek: the Defend feedback reads the stored run and never starts, kills or consumes one."""
from __future__ import annotations

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import ara_behavior as B  # noqa: E402


def _put(tmp, fp, started, **extra):
    rec = tmp / "run.json"
    B.write_json(rec.with_suffix(".start"), {"fingerprint": fp, "started": started, "pid": 0, **{k: v for k, v in extra.items() if k == "consumed"}})
    B.write_json(rec, {"fingerprint": fp, "started": started, "outage": extra.get("outage"), "result": {"status": "pass"}})
    return rec


def test_peek_returns_a_finished_record_for_its_fingerprint(tmp_path):
    rec = _put(tmp_path, "abc", 1.0)
    assert B.peek(rec, "abc")["result"]["status"] == "pass"


def test_peek_is_silent_for_another_fingerprint_or_no_record(tmp_path):
    rec = _put(tmp_path, "abc", 1.0)
    assert B.peek(rec, "other") is None
    assert B.peek(tmp_path / "none.json", "abc") is None


def test_peek_skips_a_consumed_or_outage_record(tmp_path):
    assert B.peek(_put(tmp_path, "abc", 1.0, consumed=True), "abc") is None
    assert B.peek(_put(tmp_path, "abd", 2.0, outage="Kibana did not respond"), "abd") is None


def test_peek_does_not_start_or_consume(tmp_path):
    rec = _put(tmp_path, "abc", 1.0)
    before = rec.with_suffix(".start").read_text()
    B.peek(rec, "abc"); B.peek(rec, "zzz")
    assert rec.with_suffix(".start").read_text() == before
