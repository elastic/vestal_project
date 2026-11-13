"""Offline tests for the public 5.3 data under data/ara-m5 (25 sections 4 and 8.5)."""
from __future__ import annotations

import json
import os
import pathlib
import re
import sys

import pytest

LIB = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(LIB))

import ara_eval as E  # noqa: E402
import ara_rank_bundle as RB  # noqa: E402

DATA = LIB.parent / "data" / "ara-m5"
EVAL_DIRS = ("templates", "samples", "tuning", "testsets")
EVAL_FILES = ("mappings/cortex-eval-samples.json", "mappings/cortex-eval-runs.json", "mappings/cortex-eval-testsets.json")
HELDOUT = pathlib.Path(os.environ.get("ARA_HELDOUT_RECORDS", pathlib.Path.home() / "ara-working/m5/calibration/judge/records"))
FIELDS = ("sample_id", "question", "passage_ids", "passages", "answer")


def load(rel):
    return json.loads((DATA / rel).read_text())


def all_files():
    """The 5.3 evaluation assets only: the other data/ara-m5 files are M3 corpus and 5.1/5.2 material."""
    out = [DATA / f for f in EVAL_FILES]
    for d in EVAL_DIRS:
        out += [p for p in (DATA / d).rglob("*") if p.is_file()] if (DATA / d).exists() else []
    return out


def test_mappings_hold_the_spec_fields():
    s = load("mappings/cortex-eval-samples.json")["mappings"]["properties"]
    assert set(s) == set(FIELDS)
    r = load("mappings/cortex-eval-runs.json")["mappings"]["properties"]
    for f in ("run_id", "run_label", "run_at", "provided", "connector_id", "judge_inference_id", "testset_version",
              "question_id", "sample_id", "category", "expected_route", "observed_route", "route_correct", "tool_call_count",
              "input_tokens", "output_tokens", "cached_input_tokens", "llm_calls", "latency_ms", "conversation_id"):
        assert f in r, f
    assert set(r["judge"]["properties"]) == {"faithfulness", "answer_relevance", "context_precision", "raw"}
    assert set(r["retrieval"]["properties"]) == {"precision_at_5", "recall_at_5", "ndcg_at_5"}
    assert "page_fetch_ok" in r["observed_route"]["properties"]
    t = load("mappings/cortex-eval-testsets.json")["mappings"]["properties"]
    assert set(t) == {"testset_version", "created_at", "questions"}


def test_template_is_the_hybrid_form_and_matches_the_bundle_constant():
    body = load("templates/cortex-policy-retrieval.json")
    assert body["script"]["lang"] == "mustache"
    assert body["script"]["source"] == RB.TEMPLATE_SOURCE
    assert body["script"]["source"]["size"] == 5 and "{{query_string}}" in json.dumps(body)


PRIVATE = pathlib.Path(os.environ.get("ARA_PRIVATE_53", pathlib.Path.home() / "ara-working/m5/build-5-3/private-assets"))


def test_seeded_sample_records_are_not_public():
    """The three defect records and their slot key are per-sandbox answers (Joe 2026-11-10): the track installs them root-held."""
    assert not (DATA / "samples").exists() or not any((DATA / "samples").glob("visible-*"))


@pytest.mark.skipif(not (PRIVATE / "visible-samples.json").exists(), reason="private 5.3 assets not on this machine")
def test_visible_samples_hide_the_defect_and_the_key_is_separate():
    vis = json.loads((PRIVATE / "visible-samples.json").read_text())
    assert len(vis["defects"]) == 3 and len(vis["controls"]) == 2
    for r in vis["defects"] + vis["controls"]:
        assert set(r) - {"slot"} == set(FIELDS)
    text = json.dumps(vis)
    for d in E.DEFECTS:
        assert d not in text
    assert "no_defect" not in text
    key = json.loads((PRIVATE / "visible-samples-key.json").read_text())["slots"]
    assert set(key.values()) == set(E.DEFECTS)
    assert {r["slot"] for r in vis["defects"]} == set(key)


def test_all_four_tuning_records_ship_with_labels():
    recs = load("tuning/public-tuning.json")["records"]
    assert [r["sample_id"] for r in recs] == ["t-01", "t-02", "t-03", "t-04"]
    assert sorted(r["defect"] for r in recs) == sorted([*E.DEFECTS, "no_defect"])
    assert all(set(r) == set(FIELDS) | {"defect"} for r in recs)


def test_example_testset_is_ten_dev_questions_with_fixed_categories():
    ts = load("testsets/example-testset.json")
    qs = ts["questions"]
    assert len(qs) == 10 and len({q["question_id"] for q in qs}) == 10
    assert all(q["category"] in E.CATEGORIES for q in qs)
    dev = {c["id"]: c for c in load_dev()}
    for q in qs:
        assert dev[q["question_id"]]["input"] == q["input"]
    text = " ".join(q["input"] for q in qs)
    assert "Who reviews a CX-7 alert" not in text and "passes through" not in text and "money only passes" not in text


def load_dev():
    return json.loads((LIB.parent / "data/dev-sets/m5/m4-reference.json").read_text())["cases"]


def test_no_category_key_files_in_eval_data():
    names = " ".join(str(p.relative_to(DATA)) for p in all_files())
    assert "pool" not in names and "category-key" not in names and "heldout" not in names


@pytest.mark.skipif(not (HELDOUT / "heldout-candidates.json").exists(), reason="held-out records not on this machine")
def test_no_heldout_record_text_is_in_public_data():
    blob = "\n".join(p.read_text() for p in all_files())
    recs = []
    for name in ("heldout.json", "heldout-candidates.json"):
        f = HELDOUT / name
        if f.exists():
            recs += json.loads(f.read_text())["records"]
    assert len(recs) >= 8
    for r in recs:
        assert r["answer"] not in blob, r["sample_id"]
        assert r["question"] not in blob, r["sample_id"]
        assert r["sample_id"] not in blob


def test_no_model_id_in_public_data():
    blob = "\n".join(p.read_text() for p in all_files()).lower()
    for pat in (r"gpt-\d", r"openai", r"claude", r"sonnet", r"opus", r"haiku", r"gemini", r"\.[a-z0-9-]+-completion"):
        assert not re.search(pat, blob), pat
    env_id = os.environ.get("ARA_JUDGE_INFERENCE_ID")
    if env_id:
        assert env_id.lower() not in blob
