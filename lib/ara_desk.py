"""ara_desk.py - the 4.C fraud desk (07 section 1): which tools belong to which desk, and how the
learner's AML specialist is found.

Shared by the 4.C check, its solve, the provisioning baseline and ara-ab-behavior.py. The AML
specialist's id is the learner's own, so case files name it with the placeholder AML ("@aml") and
resolve() puts the real id in before a run. The specialist is found the way 07 section 1.4 says:
from Tina's subagent_ids, by its tools.
"""
from __future__ import annotations

import copy

COORDINATOR = "tina-compliance"
SECURITIES = "cortex-securities-irregularities"
AML = "@aml"
AML_TOOLS = ["cortex.layering_chain", "cortex.atm_smurfing"]
BROKERAGE_TOOLS = ["cortex.securities_layering", "cortex.wash_trading", "cortex.unexplained_wealth"]
SHARED_TOOL = "cortex.open_case"
SAR_TOOL = "cortex.file_sar"
NO_SPECIALIST = "<no AML specialist>"

# The five request types of the spec (07 section 1.3) and the tools that serve each.
REQUEST_TOOLS = {
    "structuring": ["cortex.structuring_deposits"],
    "cash_layering": ["cortex.layering_chain"],
    "atm_smurfing": ["cortex.atm_smurfing"],
    "securities": BROKERAGE_TOOLS,
    "sar_filing": [SAR_TOOL],
}
ROLES = ["coordinator", "securities_specialist", "aml_specialist"]


def tool_ids(agent: dict | None) -> list[str]:
    ids: list[str] = []
    for entry in ((agent or {}).get("configuration") or {}).get("tools") or []:
        ids.extend(entry.get("tool_ids") or [])
    return ids


def subagent_ids(agent: dict | None) -> list[str]:
    return list(((agent or {}).get("configuration") or {}).get("subagent_ids") or [])


def find_aml(coordinator: dict | None, agents: list[dict]) -> tuple[str | None, bool]:
    """(the AML specialist's id or None, whether it is one of Tina's sub-agents). Among agents other
    than Tina and the securities specialist that hold an AML tool, a sub-agent of Tina comes first,
    then the one holding more AML tools, then the lowest id."""
    subs = set(subagent_ids(coordinator))
    cands = []
    for a in agents:
        aid = a.get("id")
        if aid in (COORDINATOR, SECURITIES):
            continue
        n = sum(1 for t in tool_ids(a) if t in AML_TOOLS)
        if n:
            cands.append((aid not in subs, -n, str(aid)))
    if not cands:
        return None, False
    best = sorted(cands)[0]
    return best[2], not best[0]


def role_of(agent_id: str | None, aml_id: str | None) -> str:
    if agent_id == COORDINATOR:
        return "coordinator"
    if agent_id == SECURITIES:
        return "securities_specialist"
    if aml_id and agent_id == aml_id:
        return "aml_specialist"
    return "other"


def resolve(cases: list[dict], aml_id: str | None) -> list[dict]:
    """The cases with the AML placeholder replaced by the specialist's id (or a name no agent has)."""
    real = aml_id or NO_SPECIALIST
    out = copy.deepcopy(cases)
    for c in out:
        for want in c.get("expected") or []:
            if want.get("agent_id") == AML:
                want["agent_id"] = real
            params = want.get("params") or {}
            if params.get("agent_id") == AML:
                params["agent_id"] = real
    return out


def holders(agents: list[dict], tool_id: str) -> list[str]:
    """The ids of every agent that holds tool_id, sorted."""
    return sorted(str(a.get("id")) for a in agents if tool_id in tool_ids(a))
