"""ara_pool_match.py - route grading for the 5.3 question pool (25 section 4).

A wrapper over agent_builder.route_matches for the two pool-schema extensions it does not know. Ordinary
items go straight to route_matches, so M4's grading is untouched.

    is_ask(resp)                         did Tina ask the analyst a question in this converse response
    match_any_order(expected, record, forbid)   every expected call matched to a distinct recorded call
    match_item(item, record, resp)       (passed, reason) for one pool item
    expand_any_of(expected)              the alternative gold lists an `any_of` entry stands for

Pool schema: `expect_ask: true` means the right answer is a clarifying question and no tool call; `ordering:
"any"` means the expected calls are independent and may come in any order. An expected entry may carry
`any_of: [tool_id, ...]` in place of `tool_id` (same params): the entry is met by a call to any of those tools. 5.C
uses it for SAR-citation questions, where Tina's call goes to `cortex.sar_search` before the staged change and to
`cortex.sar_passages` after it. Standard library only.
"""
from __future__ import annotations

from typing import Any

from agent_builder import literal_equal, route_matches


def is_ask(resp: dict | None) -> bool:
    """Tina asked instead of acting: an ask_user_question step (t4c-probe1), or, with no such step, an
    answer message whose text ends in a question mark."""
    resp = resp or {}
    if any(isinstance(s, dict) and s.get("type") == "ask_user_question" for s in resp.get("steps") or []):
        return True
    msg = (resp.get("response") or {}).get("message") if isinstance(resp.get("response"), dict) else None
    return isinstance(msg, str) and msg.rstrip().endswith("?")


def _fits(want: dict, call: dict) -> bool:
    return (call["tool_id"] == want["tool_id"] and ("agent_id" not in want or call.get("agent_id") == want["agent_id"])
            and all(literal_equal(v, (call.get("params") or {}).get(k)) for k, v in (want.get("params") or {}).items()))


def match_any_order(expected: list[dict], record: list[dict], forbid: list[str] = ()) -> tuple[bool, str]:
    """route_matches without the order: each expected call needs its own recorded call (a recorded call
    satisfies at most one expectation), found by backtracking so two expectations on the same tool with
    different params cannot starve each other. Other calls may be present; forbid works as in route_matches."""
    for bad in forbid:
        if any(c["tool_id"] == bad for c in record):
            return False, f"called {bad}"
    taken: dict[int, int] = {}  # record index -> expected index

    def place(i: int, seen: set) -> bool:
        for j, call in enumerate(record):
            if j in seen or not _fits(expected[i], call):
                continue
            seen.add(j)
            if j not in taken or place(taken[j], seen):
                taken[j] = i
                return True
        return False

    for i, want in enumerate(expected):
        if not place(i, set()):
            called = [c["tool_id"] for c in record] or ["no tool"]
            return False, f"expected {want['tool_id']}, got {', '.join(called)}"
    return True, "route matches"


def expand_any_of(expected: list[dict]) -> list[list[dict]]:
    """The gold lists an expected list stands for: one per combination of the `any_of` alternatives. A list with no
    `any_of` entry gives itself, so ordinary items are untouched."""
    lists: list[list[dict]] = [[]]
    for want in expected:
        alts = want.get("any_of")
        if not alts:
            lists = [l + [want] for l in lists]
            continue
        base = {k: v for k, v in want.items() if k != "any_of"}
        lists = [l + [dict(base, tool_id=t)] for l in lists for t in alts]
    return lists


def _first_pass(lists: list[list[dict]], grade) -> tuple[bool, str]:
    first = (False, "route does not match")
    for i, exp in enumerate(lists):
        ok, why = grade(exp)
        if ok:
            return True, why
        if i == 0:
            first = (ok, why)
    return first


# Tools that change something or report outward: an ask must come before any of them. A read-only lookup used to
# decide whether to ask is not acting (ruled 2026-11-11); an item's own `forbid` still fails on any listed tool.
ACTING_TOOLS = frozenset({"cortex.open_case", "cortex.escalate", "cortex.file_sar"})


def match_item(item: dict, record: list[dict], resp: dict | None = None, acting: set | None = None) -> tuple[bool, str]:
    """Grade one pool item. expect_ask: passes when Tina called none of the acting tools
    (ACTING_TOOLS, or `acting` when given); read-only calls before the ask are allowed. A call to a tool the item
    forbids always fails.
    Otherwise ordering "any" uses match_any_order, and everything else is route_matches unchanged."""
    forbid = item.get("forbid") or []
    if item.get("expect_ask"):
        for bad in forbid:
            if any(c["tool_id"] == bad for c in record):
                return False, f"called {bad}"
        made = [c["tool_id"] for c in record if c["tool_id"] in (ACTING_TOOLS if acting is None else acting)]
        if made:
            return False, f"expected a question, got {', '.join(made)}"
        # Whether the reply reads as a question is wording, and it varies run to run (q-067: the same reply asks, or
        # offers, in different words); the route is what code can grade. No acting call is a pass; `asked` is reported.
        return True, "asked" if is_ask(resp) else "no acting call (the reply is not phrased as a question)"
    lists = expand_any_of(item.get("expected") or [])
    if item.get("ordering") == "any":
        return _first_pass(lists, lambda exp: match_any_order(exp, record, forbid))
    return _first_pass(lists, lambda exp: route_matches(exp, record, forbid))
