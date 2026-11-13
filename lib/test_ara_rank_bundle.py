"""Offline tests for ara_rank_bundle.py."""
from __future__ import annotations

import copy
import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import ara_rank_bundle as R  # noqa: E402
import pytest  # noqa: E402

LAB = [{"question_id": "q-002", "query_text": "How long to work an alert?", "relevant_ids": ["d1", "d2"]},
       {"question_id": "q-003", "query_text": "SAR clock?", "relevant_ids": ["d9"]}]
HITS = {"q-002": ["d1", "x", "d2", "y", "z"], "q-003": ["a", "b", "d9", "c", "e"]}


def _resp(score, hits=HITS):
    return {"metric_score": score, "details": {rid: {"hits": [{"hit": {"_id": h}, "rating": None} for h in ids]}
                                              for rid, ids in hits.items()}}


def _true():
    p = (2 / 5 + 1 / 5) / 2
    r = (1.0 + 1.0) / 2
    d1 = (1 + 1 / math.log2(4)) / (1 + 1 / math.log2(3))
    d2 = (1 / math.log2(4)) / 1
    return {"precision_at_5": p, "recall_at_5": r, "dcg_at_5": (d1 + d2) / 2}


def test_bundle_shape_matches_the_spec():
    b = R.build_bundle(LAB, "cortex-policy-retrieval")
    assert b["index"] == "cortex-policies" and set(b["bodies"]) == {"precision_at_5", "recall_at_5", "dcg_at_5"}
    m = {k: v["metric"] for k, v in b["bodies"].items()}
    assert m["precision_at_5"] == {"precision": {"k": 5, "relevant_rating_threshold": 1, "ignore_unlabeled": False}}
    assert m["recall_at_5"]["recall"]["k"] == 5
    assert m["dcg_at_5"] == {"dcg": {"k": 5, "normalize": True}}
    body = b["bodies"]["dcg_at_5"]
    assert body["templates"][0]["template"] == {"id": "cortex-policy-retrieval"}
    req = body["requests"][0]
    assert req["id"] == "q-002" and req["template_id"] == "cortex-policy-retrieval"
    assert req["params"] == {"query_string": "How long to work an alert?"}
    assert req["ratings"] == [{"_index": "cortex-policies", "_id": "d1", "rating": 1}, {"_index": "cortex-policies", "_id": "d2", "rating": 1}]


def test_bundle_rejects_unsendable_labels():
    for bad in ([], [{"question_id": "a", "query_text": "", "relevant_ids": ["d"]}],
                [{"question_id": "a", "query_text": "q", "relevant_ids": []}],
                [LAB[0], LAB[0]]):
        with pytest.raises(ValueError):
            R.build_bundle(bad)


def test_template_source_is_the_hybrid_form():
    s = R.TEMPLATE_SOURCE
    assert s["size"] == 5 and s["_source"] is False and s["retriever"]["rrf"]["rank_window_size"] == 20
    assert "{{query_string}}" in str(s)


def test_cross_check_agrees_with_correct_scores():
    t = _true()
    out = R.cross_check({k: _resp(v) for k, v in t.items()}, LAB)
    assert out["ok"] and not out["missing"]
    assert all(m["diff"] < 1e-9 for m in out["metrics"].values())


def test_cross_check_tolerance_edges_and_missing():
    t = _true()
    near = {k: _resp(v + (0.004 if k == "recall_at_5" else 0)) for k, v in t.items()}
    assert R.cross_check(near, LAB)["ok"]
    far = {k: _resp(v + (0.006 if k == "dcg_at_5" else 0)) for k, v in t.items()}
    out = R.cross_check(far, LAB)
    assert not out["ok"] and not out["metrics"]["dcg_at_5"]["ok"]
    partial = {k: _resp(v) for k, v in t.items() if k != "recall_at_5"}
    assert R.cross_check(partial, LAB)["missing"] == ["recall_at_5"]
    assert not R.cross_check({}, LAB)["ok"]


def test_cross_check_uses_the_reported_hits_not_the_labels_alone():
    t = _true()
    other = copy.deepcopy(HITS)
    other["q-003"] = ["d9", "a", "b", "c", "e"]
    out = R.cross_check({k: _resp(v, other) for k, v in t.items()}, LAB)
    assert not out["ok"]  # scores reported for different hits do not match what those hits compute to
