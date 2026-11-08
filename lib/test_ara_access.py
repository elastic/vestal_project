"""Offline tests for ara-access.py: predict records once on the server clock, explain asks only about
mismatches and records closed-list mechanisms."""
from __future__ import annotations

import builtins
import importlib.util
import json
import pathlib
import sys
import tempfile

LIB = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(LIB))
spec = importlib.util.spec_from_file_location("ara_access", LIB / "ara-access.py")
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)
PROBES = LIB.parent / "modules/m5/5-1-access-control/access/probes.json"


class Clock:
    def request(self, method, path, body=None):
        assert path == "/_query"
        return 200, {"values": [[1_762_550_000_000]]}


def _answers(seq):
    it = iter(seq)
    return lambda *_: next(it)


def test_predict_once_then_explain_mismatches():
    probes = json.loads(PROBES.read_text())
    n = len(A.items(probes))
    assert n == 13  # six documents, four fields, three calls
    with tempfile.TemporaryDirectory() as tmp:
        A.HOME, A.PROBES = pathlib.Path(tmp), PROBES
        A.admin = lambda: Clock()
        orig = builtins.input
        try:
            builtins.input = _answers(["1"] * n)  # everything retrievable / visible / rows
            A.predict()
            pred = json.loads((A.HOME / "prediction.json").read_text())
            assert pred["recorded_at_ms"] == 1_762_550_000_000 and pred["calls"]["case_lookup"] == "rows"
            try:
                A.predict()
            except SystemExit as e:
                assert "already holds your first prediction" in str(e)
            else:
                raise AssertionError("predict overwrote the first prediction")
            obs = {s: dict(v) for s, v in pred.items() if s in ("documents", "fields", "calls")}
            obs["fields"]["subject_tin"] = "hidden"
            obs["calls"]["case_lookup"] = "error_hidden_field"
            (A.HOME / "observations.json").write_text(json.dumps(obs))
            builtins.input = _answers(["2", "3"])  # fls_hidden, query_names_hidden_field
            A.explain()
        finally:
            builtins.input = orig
        pred = json.loads((A.HOME / "prediction.json").read_text())
        assert pred["mechanisms"] == {"fields/subject_tin": "fls_hidden", "calls/case_lookup": "query_names_hidden_field"}
