"""Unit tests for ara_desk (the 4.C fraud desk).

    python3 -m pytest lib/test_ara_desk.py
"""
import ara_desk as D


def agent(aid, tools, subs=()):
    return {"id": aid, "configuration": {"tools": [{"tool_ids": list(tools)}], "subagent_ids": list(subs)}}


TINA = agent(D.COORDINATOR, ["cortex.structuring_deposits", "cortex.open_case"], [D.SECURITIES, "aml-desk"])
SEC = agent(D.SECURITIES, D.BROKERAGE_TOOLS + ["cortex.open_case"])


def test_find_aml_prefers_tinas_subagent():
    agents = [TINA, SEC, agent("aaa-stray", D.AML_TOOLS), agent("aml-desk", ["cortex.layering_chain"])]
    assert D.find_aml(TINA, agents) == ("aml-desk", True)


def test_find_aml_outside_subagents_and_none():
    tina = agent(D.COORDINATOR, [], [D.SECURITIES])
    assert D.find_aml(tina, [tina, SEC, agent("lone", D.AML_TOOLS)]) == ("lone", False)
    assert D.find_aml(tina, [tina, SEC]) == (None, False)


def test_tools_on_tina_do_not_make_her_the_specialist():
    tina = agent(D.COORDINATOR, D.AML_TOOLS, [D.SECURITIES])
    assert D.find_aml(tina, [tina, SEC]) == (None, False)


def test_resolve_and_roles():
    cases = [{"id": "c2", "expected": [{"tool_id": "run_subagent", "params": {"agent_id": D.AML}},
                                       {"tool_id": "cortex.layering_chain", "agent_id": D.AML, "params": {"account_id": "32687"}}]}]
    out = D.resolve(cases, "aml-desk")
    assert out[0]["expected"][0]["params"]["agent_id"] == "aml-desk"
    assert out[0]["expected"][1]["agent_id"] == "aml-desk"
    assert cases[0]["expected"][1]["agent_id"] == D.AML  # the input is not changed
    assert D.resolve(cases, None)[0]["expected"][1]["agent_id"] == D.NO_SPECIALIST
    assert [D.role_of(a, "aml-desk") for a in (D.COORDINATOR, D.SECURITIES, "aml-desk", "x")] == \
        ["coordinator", "securities_specialist", "aml_specialist", "other"]


def test_holders():
    assert D.holders([TINA, SEC], "cortex.open_case") == sorted([D.COORDINATOR, D.SECURITIES])
