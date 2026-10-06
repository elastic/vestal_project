"""
test_defend.py — unit tests for defend.py's partial-choices notice and closing line.

Run with: python -m pytest lib/test_defend.py -v
or:        python lib/test_defend.py
"""

from __future__ import annotations

import builtins
import contextlib
import io
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import defend  # noqa: E402

NOTICE = "Some choices come from a Build you skipped, so they can't be shown. Check names that Build."


def _q(qid, choices):
    return {"questions": [{"id": qid, "text": "T", "choices": choices,
                           "reasons": [{"key": "r1", "label": "R1"}]}]}


# 3.3 q2 shape: two choices computed from one Build 3 result, two fixed choices.
Q33 = _q("q2", [
    {"key": "summarize_first", "label": "summarize_first retained more, by {result}",
     "computed": {"formula": "setB_small_retention_gap"}},
    {"key": "rerank_top_n", "label": "rerank_top_n retained more, by {result}",
     "computed": {"formula": "setB_small_retention_gap"}},
    {"key": "tie", "label": "Tie"},
    {"key": "neither", "label": "Neither"},
])

# 2.1 q2 shape: four computed choices whose labels can collide and dedupe.
Q21 = _q("q2", [
    {"key": "a", "label": "{result} chunks", "computed": {"formula": "floor(4000 / p95_tokens)"}},
    {"key": "b", "label": "{result} chunks", "computed": {"formula": "floor(4000 / p95_tokens) + 1"}},
    {"key": "c", "label": "{result} chunks", "computed": {"formula": "max(0, floor(4000 / p95_tokens) - 1)"}},
    {"key": "d", "label": "{result} chunks", "computed": {"formula": "floor(4000 / p95_tokens) * 2"}},
])

# 2.1 q3 shape: a fallback formula and an env: choice.
Q21_Q3 = _q("q3", [
    {"key": "pinned", "label": "{result}", "computed": {"formula": "pinned_model_id"}},
    {"key": "platform", "label": "{result}",
     "computed": {"formula": "platform_endpoint_id",
                  "fallback_formula": "'.' + pinned_model_id + '-completion'"}},
    {"key": "embed", "label": "{result}", "computed": {"formula": "env:ARA_EMBED_ID"}},
])


def _load(raw, results, env=None):
    return defend.load_questions_new(raw, results, env or {}, 0)[0]


def test_notice_fires_when_choice_and_fallback_missing():
    q = _load(Q33, {})
    assert q["partial"] is True
    assert sorted(c["key"] for c in q["choices"]) == ["neither", "tie"]


def test_notice_silent_with_results():
    q = _load(Q33, {"setB_small_retention_gap": 0.12})
    assert q["partial"] is False and len(q["choices"]) == 4


def test_notice_silent_on_withheld_tie_gap():
    # 3.3 Build 3 records the gap as None inside the tie band: the Build is finished.
    q = _load(Q33, {"setB_small_retention_gap": None})
    assert q["partial"] is False
    assert sorted(c["key"] for c in q["choices"]) == ["neither", "tie"]


def test_notice_silent_on_dedupe():
    # floor(4000 / 8000) = 0: a, c and d all read "0 chunks"; two are dropped as collisions.
    q = _load(Q21, {"p95_tokens": 8000})
    assert len(q["choices"]) == 2
    assert q["partial"] is False


def test_notice_silent_when_fallback_supplies_value():
    q = _load(Q21_Q3, {"pinned_model_id": "m"}, {"ARA_EMBED_ID": "e"})
    assert q["partial"] is False and len(q["choices"]) == 3


def test_notice_silent_on_missing_env_choice():
    q = _load(Q21_Q3, {"pinned_model_id": "m", "platform_endpoint_id": "p"})
    assert len(q["choices"]) == 2 and q["partial"] is False


def test_fully_missing_question_is_skipped_not_partial():
    q = _load(Q21, {})
    assert q["choices"] == [] and q["partial"] is False and q["missing"] == ["p95_tokens"]


def _ask(q):
    answers = iter(["1", "1"])
    real_input = builtins.input
    builtins.input = lambda *_: next(answers)
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            defend.ask_question(q, 2, 3)
    finally:
        builtins.input = real_input
    return buf.getvalue().splitlines()


def test_ask_prints_notice_before_header():
    lines = _ask(_load(Q33, {}))
    assert lines.count(NOTICE) == 1
    assert lines[lines.index(NOTICE) + 1] == "Question 2 of 3"


def test_ask_no_notice_on_dedupe():
    assert NOTICE not in _ask(_load(Q21, {"p95_tokens": 8000}))


def test_strings():
    assert defend.PARTIAL_NOTICE == NOTICE
    assert defend.CLOSING_NOT_PASSED == (
        "Fix what this names, then select Check. "
        "To change an answer, run python3 /opt/ara/lib/defend.py again.")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  ok    {fn.__name__}")
        except Exception as exc:
            print(f"  FAIL  {fn.__name__}: {exc!r}")
            failed += 1
    print(f"\n{len(fns) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
