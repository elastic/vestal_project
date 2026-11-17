import pytest

import ara_setcat as SC

ITEMS = [{"question_id": "q1", "input": "a"}, {"question_id": "q2", "input": "b"}]
KEY = {"questions": {}, "categories": {"q1": "ambiguous", "q2": "straightforward"}}


def test_the_key_supplies_every_category():
    out = SC.with_categories(ITEMS, KEY, "s")
    assert [(q["question_id"], q["category"]) for q in out] == [("q1", "ambiguous"), ("q2", "straightforward")]
    assert ITEMS[0].get("category") is None   # the input is not changed


@pytest.mark.parametrize("items,key,why", [
    (ITEMS, {"questions": {}}, "no categories"),
    (ITEMS, {"categories": {"q1": "ambiguous"}}, "q2 has no category"),
    (ITEMS, {"categories": {"q1": "ambiguous", "q2": "other"}}, "outside the list"),
    (ITEMS, {"categories": {**KEY["categories"], "q3": "ambiguous"}}, "key names an unknown question"),
    ([dict(ITEMS[0], category="ambiguous"), ITEMS[1]], KEY, "public label, even a matching one"),
    (ITEMS + [ITEMS[0]], KEY, "duplicate id"),
])
def test_every_gap_is_an_error(items, key, why):
    with pytest.raises(SC.CategoryError):
        SC.with_categories(items, key, "s")


def test_the_finished_file_guard_reports_missing_and_invalid():
    good = [dict(q, category=KEY["categories"][q["question_id"]]) for q in ITEMS]
    assert SC.check_categorised(good) == []
    assert len(SC.check_categorised([good[0], {"question_id": "q2"}, dict(good[1], category="x")])) == 2


def test_the_learner_loop_runs_the_gate_only_over_a_fully_categorised_set(tmp_path):
    import importlib.util
    import json
    import pathlib
    import ara_loop_cli as C
    spec = importlib.util.spec_from_file_location("ara_loop_script", pathlib.Path(__file__).with_name("ara-loop.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    deps = object.__new__(mod.Deps)
    for content in (json.dumps([{"question_id": "q1", "category": "ambiguous"}, {"question_id": "q2"}]), "not json"):
        f = tmp_path / "testset.json"
        f.write_text(content)
        mod.TESTSET = f
        with pytest.raises(C.LoopError):
            mod.Deps.measure(deps, "x", "tina-compliance")
    mod.TESTSET = tmp_path / "absent.json"
    with pytest.raises(C.LoopError):
        mod.Deps.measure(deps, "x", "tina-compliance")
