"""Offline tests for ara_pool_match.py."""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import agent_builder as A  # noqa: E402
import ara_pool_match as P  # noqa: E402


def call(tid, **params):
    return {"tool_id": tid, "params": params, "agent_id": None}


DEP = call("cortex.structuring_deposits", account_id="476", lookback_days=7)
DEP2 = call("cortex.structuring_deposits", account_id="1981", lookback_days=7)
POL = call("cortex.policy_search")
EXP = [{"tool_id": "cortex.structuring_deposits", "params": {"account_id": "1981", "lookback_days": 7}},
       {"tool_id": "cortex.structuring_deposits", "params": {"account_id": "476", "lookback_days": 7}}]


def test_ordinary_item_delegates_to_route_matches():
    item = {"expected": EXP, "forbid": ["cortex.open_case"]}
    for rec in ([DEP2, DEP], [DEP, DEP2], [], [DEP2, call("cortex.open_case")]):
        assert P.match_item(item, rec) == A.route_matches(item["expected"], rec, item["forbid"])
    assert P.match_item(item, [DEP, DEP2])[0] is False  # order still counts without ordering "any"


def test_ordering_any_accepts_either_order_and_distinct_calls():
    item = {"expected": EXP, "ordering": "any"}
    assert P.match_item(item, [DEP, DEP2])[0] and P.match_item(item, [DEP2, DEP])[0]
    assert not P.match_item(item, [DEP2])[0]  # one call cannot satisfy two expectations
    assert not P.match_item(item, [DEP2, DEP2])[0]
    two = {"expected": [{"tool_id": "cortex.structuring_deposits"}, EXP[0]], "ordering": "any"}
    assert P.match_item(two, [DEP2, DEP])[0]  # backtracking: the loose expectation must not take the specific call
    assert P.match_item(two, [DEP, DEP2])[0]


def test_ordering_any_params_forbid_and_delegation():
    item = {"expected": [{"tool_id": "run_subagent", "params": {"agent_id": "sec"}}, {"tool_id": "cortex.policy_search"}],
            "ordering": "any", "forbid": ["cortex.open_case"]}
    sub = {"tool_id": "run_subagent", "params": {"agent_id": "sec"}, "agent_id": None}
    assert P.match_item(item, [POL, sub])[0]
    assert not P.match_item(item, [POL, {**sub, "params": {"agent_id": "other"}}])[0]
    ok, why = P.match_item(item, [POL, sub, call("cortex.open_case")])
    assert not ok and why == "called cortex.open_case"


ASK_ITEM = {"expect_ask": True, "expected": [], "forbid": ["cortex.open_case"]}
ASK_STEP = {"steps": [{"type": "ask_user_question"}], "response": {"message": "Which account?"}}


def test_expect_ask_passes_on_a_question_and_no_call():
    assert P.match_item(ASK_ITEM, [], ASK_STEP) == (True, "asked")
    assert P.match_item(ASK_ITEM, [], {"steps": [], "response": {"message": "Which account do you mean?  "}})[0]


def test_expect_ask_fails_on_action_or_no_question():
    ok, why = P.match_item(ASK_ITEM, [call("cortex.open_case", account_id="1981")], ASK_STEP)
    assert not ok and "open_case" in why
    # the default is acting-only: a read-only lookup before the question is allowed (q-067 case_lookup), a forbidden one is not
    assert P.match_item(ASK_ITEM, [POL], ASK_STEP)[0]
    assert not P.match_item(dict(ASK_ITEM, forbid=["cortex.policy_search"]), [POL], ASK_STEP)[0]
    assert not P.match_item(ASK_ITEM, [call("cortex.escalate", account_id="1981")], ASK_STEP)[0]
    assert not P.match_item(ASK_ITEM, [call("cortex.file_sar", account_id="1981")], ASK_STEP)[0]
    # the route is what is graded: no acting call passes even when the reply is not phrased as a question (reported)
    ok, why = P.match_item(ASK_ITEM, [], {"steps": [], "response": {"message": "Done."}})
    assert ok and "not phrased as a question" in why
    assert P.match_item(ASK_ITEM, [], None)[0]
    # a caller may name its own acting set
    assert not P.match_item(ASK_ITEM, [POL], ASK_STEP, acting={"cortex.policy_search"})[0]


def test_is_ask():
    assert P.is_ask(ASK_STEP) and not P.is_ask({}) and not P.is_ask({"response": {"message": 5}})
