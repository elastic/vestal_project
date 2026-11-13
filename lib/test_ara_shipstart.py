"""Offline tests for ara_shipstart.py against the committed 5.C data."""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import ara_pool_match as P  # noqa: E402
import ara_shipstart as T  # noqa: E402

D = ROOT / "data/ara-m5"
ADD = json.loads((D / "5c/pool-additions.json").read_text())["questions"]
V1 = json.loads((D / "testsets/v1-testset.json").read_text())["questions"]
POOL53 = [  # a stand-in for the 5.3 pool: the two SAR items v1 uses, one ordinary item
    {"id": "q-060", "type": "agent", "category": "straightforward", "kind": "case", "input": "Show me what past SARs said about hawala.",
     "expected": [{"tool_id": "cortex.sar_search"}], "forbid": ["cortex.file_sar"]},
    {"id": "q-007", "type": "agent", "category": "straightforward", "kind": "coordinator", "input": "Account 476?",
     "expected": [{"tool_id": "cortex.structuring_deposits", "params": {"account_id": "476"}}]},
]


def test_sar_gold_takes_either_tool_and_other_items_are_untouched():
    pool = T.build_pool(POOL53, ADD)
    by = {q["id"]: q for q in pool}
    assert by["q-060"]["expected"] == [{"any_of": T.SAR_TOOLS}]
    assert by["q-007"]["expected"] == POOL53[1]["expected"]
    call = lambda t: [{"tool_id": t, "params": {}, "agent_id": None}]  # noqa: E731
    assert P.match_item(by["q-060"], call("cortex.sar_passages"))[0] and P.match_item(by["q-060"], call("cortex.sar_search"))[0]
    assert POOL53[0]["expected"] == [{"tool_id": "cortex.sar_search"}]   # the input is not mutated


def test_duplicate_ids_are_refused():
    import pytest
    with pytest.raises(ValueError):
        T.build_pool(POOL53 + [{"id": "q-c01"}], ADD)


def test_testset_and_gain_ids():
    pool = {q["id"]: q for q in T.build_pool(POOL53, ADD)}
    v1 = [q for q in V1 if q["question_id"] in ("q-060", "q-007")]
    ts = T.build_testset(v1, ADD, pool)
    assert len(ts) == 14 and ts[-1]["question_id"] == "q-c12" and ts[-1]["input"].startswith("The regulator's reply")
    g = T.gain_ids(ts, pool)
    assert g["S1"] == ["q-060"] + [f"q-c{i:02d}" for i in range(1, 7)]
    assert g["S2"] == [f"q-c{i:02d}" for i in range(7, 13)]
    assert len(g["S3"]) == 14


TEMPLATE = (D / "5c/change-request.templates.md").read_text()
VALUES = {"n": 7, "title": "Faster citations", "baseline": 1.0, "baseline_cached": "58%", "staging": 0.8, "staging_cached": "60%",
          "change_pct": -20.0, "threshold_pct_abs": 10, "category_drop_limit_points": 10, "n_s1": 7, "n_s2": 6, "n_agent": 36,
          "first_prefix": "https://a/", "second_prefix": "https://b/", "baseline_points": 0, "staging_points": 100,
          "change_points": 100, "threshold_points": 30, "braces": "x"}


def test_change_request_renders_one_seed_and_refuses_a_missing_value():
    import pytest
    s1 = T.render_change_request(TEMPLATE, "S1", VALUES)
    assert "cortex-sar-passages-fast" in s1 and "Cortex's rate card" in s1 and "What we need from you" in s1
    assert "S2" not in s1 and "{" not in s1 and "DRAFT" not in s1
    s2 = T.render_change_request(TEMPLATE, "S2", VALUES)
    assert "https://b/" in s2 and "cortex-sar-passages-fast" not in s2
    with pytest.raises(ValueError):
        T.render_change_request(TEMPLATE, "S3", dict(VALUES, threshold_pct_abs=None))
