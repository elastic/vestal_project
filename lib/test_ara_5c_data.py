"""Offline tests for the 5.C data: regulator pages, question additions, regulator replies, S1 passages."""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
D = ROOT / "data" / "ara-m5" / "5c"
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import ara_pool_match as P  # noqa: E402


def items():
    return json.loads((D / "pool-additions.json").read_text())["questions"]


def test_ids_are_unique_and_clear_of_v1():
    ids = [q["id"] for q in items()]
    v1 = {q["question_id"] for q in json.loads((ROOT / "data/ara-m5/testsets/v1-testset.json").read_text())["questions"]}
    assert len(ids) == len(set(ids)) == 12 and not set(ids) & v1


def test_every_regulation_item_names_a_committed_page_whose_title_line_is_its_first_heading():
    regs = [q for q in items() if q["source"] == "5c S2"]
    assert len(regs) >= 4
    for q in regs:
        name = q["page"]["url"].rsplit("/", 1)[1]
        text = (ROOT / "ara-m5-pages" / name).read_text()
        assert text.splitlines()[0] == "# " + q["page"]["title_line"]
        assert q["page"]["url"] in q["input"]            # the question pastes the URL (plan section 3)
        assert "Public-domain US government text" in text  # provenance paragraph


def test_gold_is_met_by_the_right_call_and_by_the_staged_tool():
    for q in items():
        if q["source"] == "5c S1":
            assert len([q]) and len(q["input"]) > 20
            for tool in ("cortex.sar_search", "cortex.sar_passages"):
                assert P.match_item(q, [{"tool_id": tool, "params": {"query": "x"}, "agent_id": None}])[0], (q["id"], tool)
            assert not P.match_item(q, [{"tool_id": "cortex.case_search", "params": {}, "agent_id": None}])[0]
        else:
            call = {"tool_id": "cortex.read_page", "params": {"url": q["page"]["url"]}, "agent_id": None}
            assert P.match_item(q, [call])[0] and not P.match_item(q, [dict(call, params={"url": "https://x/y"})])[0]


def test_replies_cite_the_same_url_and_are_correspondence_rows():
    urls = {q["page"]["url"] for q in items() if q["source"] == "5c S2"}
    rows = [json.loads(l) for l in (D / "regulator-replies.ndjson").read_text().splitlines()]
    assert len(rows) == len(urls) or len(rows) == 6
    for r in rows:
        assert set(r) == {"corr_id", "case_id", "case_type", "risk_tier", "from_party", "received_at", "body"}
        assert any(u in r["body"] for u in urls)
    assert len({r["corr_id"] for r in rows}) == len(rows)


def test_replies_are_on_known_cases():
    cases = {json.loads(l)["case_id"] for l in (ROOT / "data/ara-m5/cortex-cases.ndjson").read_text().splitlines()}
    for l in (D / "regulator-replies.ndjson").read_text().splitlines():
        r = json.loads(l)
        assert r["case_id"] in cases
