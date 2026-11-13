"""Offline tests for the `any_of` gold entry in ara_pool_match (5.C SAR-citation questions)."""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import ara_pool_match as P  # noqa: E402


def call(tid, **params):
    return {"tool_id": tid, "params": params, "agent_id": None}


SAR = {"expected": [{"any_of": ["cortex.sar_search", "cortex.sar_passages"], "params": {"query": "layering"}}]}


def test_either_tool_meets_an_any_of_entry():
    assert P.match_item(SAR, [call("cortex.sar_search", query="layering")])[0]
    assert P.match_item(SAR, [call("cortex.sar_passages", query="layering")])[0]


def test_another_tool_or_other_params_still_fail():
    assert not P.match_item(SAR, [call("cortex.case_search", query="layering")])[0]
    assert not P.match_item(SAR, [call("cortex.sar_passages", query="other")])[0]
    assert not P.match_item(SAR, [])[0]


def test_any_of_keeps_forbid_and_order_rules():
    item = {"expected": [{"tool_id": "cortex.policy_search"}, {"any_of": ["cortex.sar_search", "cortex.sar_passages"]}],
            "forbid": ["cortex.file_sar"]}
    assert P.match_item(item, [call("cortex.policy_search"), call("cortex.sar_passages")])[0]
    assert not P.match_item(item, [call("cortex.sar_passages"), call("cortex.policy_search")])[0]
    assert not P.match_item(item, [call("cortex.policy_search"), call("cortex.sar_search"), call("cortex.file_sar")])[0]
    anyorder = dict(item, ordering="any")
    assert P.match_item(anyorder, [call("cortex.sar_passages"), call("cortex.policy_search")])[0]


def test_an_item_without_any_of_is_one_unchanged_list():
    exp = [{"tool_id": "cortex.policy_search"}]
    assert P.expand_any_of(exp) == [exp]
    assert P.expand_any_of([]) == [[]]
