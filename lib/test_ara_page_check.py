"""Offline tests for the page_fetch_ok recompute hook (ara_integrity.apply_page_check, ara_shipgate.make_page_check)."""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import ara_eval as E  # noqa: E402
import ara_integrity as I  # noqa: E402
import ara_shipgate as G  # noqa: E402

URL = "https://raw.githubusercontent.com/elastic/vestal_project/m5-v1.0/ara-m5-pages/x.md"
ITEM = {"page": {"url": URL, "title_line": "Rule 17a-8 Recordkeeping"}}
GOOD = {"ran": True, "status_code": 200, "output": "# Rule 17a-8 Recordkeeping\nbody"}


def rec(qid, ex, url=URL, stored=True):
    return {"question_id": qid, "category": "straightforward",
            "observed_route": [{"tool_id": "cortex.read_page", "params": {"url": url}, "ok": True,
                                "execution_id": ex, "page_fetch_ok": stored}]}


def test_the_check_overwrites_what_a_record_claims():
    steps = {"e1": GOOD, "e2": {"ran": True, "status_code": 404, "output": ""}}
    pc = G.make_page_check(steps.get)
    recs = [rec("q1", "e1", stored=False), rec("q2", "e2", stored=True), rec("q3", None, stored=True)]
    I.apply_page_check(recs, {"q1": ITEM, "q2": ITEM, "q3": ITEM}, pc)
    assert [r["observed_route"][0]["page_fetch_ok"] for r in recs] == [True, False, False]


def test_wrong_page_unreadable_step_and_no_page_are_not_fetches():
    pc = G.make_page_check({"e1": GOOD}.get)
    other = "https://raw.githubusercontent.com/elastic/vestal_project/m5-v1.0/ara-m5-pages/y.md"
    recs = [rec("q1", "e1", url=other), rec("q2", "missing"), rec("q3", "e1")]
    I.apply_page_check(recs, {"q1": ITEM, "q2": ITEM, "q3": {}}, pc)
    assert [r["observed_route"][0]["page_fetch_ok"] for r in recs] == [False, False, False]
    boom = G.make_page_check(lambda ex: (_ for _ in ()).throw(RuntimeError("down")))
    assert boom(recs[0]["observed_route"][0], ITEM) is False


def test_other_tools_are_left_alone_and_the_share_reads_the_recomputed_value():
    r = rec("q1", "e1", stored=False)
    r["observed_route"].append({"tool_id": "cortex.policy_search", "params": {}, "ok": True})
    I.apply_page_check([r], {"q1": ITEM}, G.make_page_check({"e1": GOOD}.get))
    assert "page_fetch_ok" not in r["observed_route"][1]
    assert r["observed_route"][0]["page_fetch_ok"] is True
