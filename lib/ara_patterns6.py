"""ara_patterns6.py - Lab 6.2's five week patterns: what each is, which three a week variant has live, how setup installs it in the live objects, and the
week's two named review proposals (28 section 3).

    PATTERNS[name]        target and accepted proposal types (the week key's vocabulary; ara_m6_checks.grounding reads it)
    LIVE[week]            the three patterns live in W1..W3 (unattached_tool is live in all three: the 6.1 end builds cortex.account_history and does not attach it)
    install(name, ab, assets)   put the pattern in the live objects (idempotent); the state the gate measures is the state the week recorded
    review_proposals(week, policy, key)   [prop-review-1, prop-review-2]: one grounded, one trap; which is which differs by week variant. The trap's
                                    effect on the gate set is a calibration matter [PENDING: calibration]; this file only fixes which proposal is which.

Standard library only; `ab` is agent_builder.AB. Evidence in a proposal is taken from the week key's own conversation and trace ids.
"""
from __future__ import annotations

import copy
import json
import pathlib

import ara_gap6 as GP
import ara_loop as L

PATTERNS = {
    "unattached_tool": {"target": "tina-compliance", "types": ["attach_tool"]},
    "double_search": {"target": "cortex.policy_search", "types": ["tool_description_change"]},
    "short_default_window": {"target": "cortex.layering_chain", "types": ["tool_query_change", "tool_description_change"]},
    "oversized_result": {"target": "cortex.case_correspondence", "types": ["tool_query_change"]},
    "needless_question": {"target": "tina-compliance", "types": ["instruction_change"]},
}
LIVE = {1: ["unattached_tool", "double_search", "oversized_result"],
        2: ["unattached_tool", "short_default_window", "needless_question"],
        3: ["unattached_tool", "oversized_result", "needless_question"]}
OBSERVATIONS = {
    "unattached_tool": "The analyst asked for an account's history and Tina escalated; cortex.account_history exists and is not attached.",
    "double_search": "Tina ran cortex.policy_search twice for one policy question.",
    "short_default_window": "The analyst asked about the last quarter and the answer covers only 30 days.",
    "oversized_result": "cortex.case_correspondence returned whole letter bodies and the next model call carried them.",
    "needless_question": "Tina asked which window to use before answering a question Cortex policy says to default.",
}
DOUBLE = "For every policy question, search twice: once with the analyst's wording and once with the policy's formal name, then use both result sets."
NEEDLESS = "When an analyst asks about activity on an account (deposits, wires or trades) and names no date window, ask which window they want before you look anything up, even when your skill or tool names a default."
WHOLE_BODY = "FROM cortex-case-correspondence\n| WHERE case_id == ?case_id\n| KEEP corr_id, from_party, received_at, body\n| SORT received_at ASC"
# A correspondent's reply quotes the whole earlier thread under a standing confidentiality notice; the letters Tina fetches carry it (a build choice:
# the stock letters are ~230 characters, too short for "whole bodies inflate the call" to cost anything). Text is fixed so every sandbox measures the same.
# 80 quoted lines, not 35: with 35 the reference fix (headers only) saved 9.3% of cost (range 7.5 to 11.2 over repeats), below the largest min_gain (12), so a correct answer failed about half the time.
THREAD_MARK = "[quoted thread]"
THREAD = (THREAD_MARK + "\n" + "\n".join(
    f"> On {d} the sender wrote: please treat this message and every attachment as confidential and intended only for the named recipient at the receiving institution. "
    f"If you are not the intended recipient, notify the sender at once and delete all copies. Reference {r}: the request for information, our prior reply and the "
    "acknowledgement of receipt are repeated below for the file, in the order sent, so that the receiving institution holds the full thread without further requests."
    for d, r in [("the first business day of the review", "RFI-A"), ("the third business day", "RFI-B"), ("the fifth business day", "RFI-C"),
                 ("the eighth business day", "RFI-D"), ("the tenth business day", "RFI-E"), ("the twelfth business day", "RFI-F"),
                 ("the fifteenth business day", "RFI-G"), ("the eighteenth business day", "RFI-H"), ("the twentieth business day", "RFI-I")]
    + [(f"business day {n}", f"RFI-{n}") for n in range(22, 22 + 2 * 80, 2)]))
INFLATE_SCRIPT = ("if (!ctx._source.body.contains(params.mark)) { ctx._source.body = ctx._source.body + params.sep + params.thread }")
TOOL_KEYS = ("id", "type", "description", "tags", "configuration")


def _tool_body(t: dict) -> dict:
    return {k: copy.deepcopy(t[k]) for k in TOOL_KEYS if k in t}


def _manifest_tool(assets: pathlib.Path, rel: str, tool_id: str) -> dict:
    m = json.loads((assets / rel).read_text())
    return next(t for t in m["tools"] if t["id"] == tool_id)


def _put_tool(ab, tool: dict) -> None:
    code, body = ab.put_tool(_tool_body(tool))
    if code not in (200, 201):
        raise RuntimeError(f"could not write {tool['id']} (HTTP {code}): {str(body)[:200]}")


def agent_write_body(a: dict) -> dict:
    """An agent as a write accepts it: the read's server fields are left out (6.2 live round; the 6.3 check's no-op deploy puts Tina back through this)."""
    body_in = {k: a[k] for k in ("id", "name", "description", "configuration", "labels", "avatar_color", "avatar_symbol") if k in a}
    if isinstance(a.get("access_control"), dict) and "access_mode" in a["access_control"]:  # the read adds `entries`, which a write refuses
        body_in["access_control"] = {"access_mode": a["access_control"]["access_mode"]}
    return body_in


def _edit_agent(ab, agent_id: str, fn) -> None:
    a = ab.get_agent(agent_id)
    if a is None:
        raise RuntimeError(f"{agent_id} is missing")
    a = fn(a)
    code, body = ab.put_agent(agent_write_body(a))
    if code not in (200, 201):
        raise RuntimeError(f"could not write {agent_id} (HTTP {code}): {str(body)[:200]}")


def install(name: str, ab, assets: pathlib.Path, agent: str = "tina-compliance", held: pathlib.Path | None = None) -> None:
    """`held` is the root-only held-out directory: the account-history tool's definition is private (the reference queries stay out of the public bundle)."""
    if name == "unattached_tool":
        if held is None or not (held / "unattached-tool.json").exists():
            raise RuntimeError("unattached-tool.json is not installed (the track's private files)")
        _put_tool(ab, json.loads((held / "unattached-tool.json").read_text()))
    elif name == "double_search":
        t = ab.get_tool("cortex.policy_search")
        if DOUBLE not in (t.get("description") or ""):
            t["description"] = (t.get("description") or "").rstrip() + " " + DOUBLE
            _put_tool(ab, t)
    elif name == "oversized_result":
        t = ab.get_tool("cortex.case_correspondence")
        if t["configuration"].get("query") != WHOLE_BODY:
            t["configuration"]["query"] = WHOLE_BODY
            _put_tool(ab, t)
    elif name == "short_default_window":
        _put_tool(ab, _manifest_tool(assets, "manifests/m4/ara-m4-capstone-start.json", "cortex.layering_chain"))

        def attach(a):
            ids = L.tool_id_list(a)
            if "cortex.layering_chain" not in ids:
                ids.append("cortex.layering_chain")
            return a
        _edit_agent(ab, agent, attach)
    elif name == "needless_question":
        def add(a):
            c = a["configuration"]
            if NEEDLESS not in c.get("instructions", ""):
                c["instructions"] = c["instructions"].rstrip("\n") + "\n" + NEEDLESS
            return a
        _edit_agent(ab, agent, add)
    else:
        raise ValueError(name)


def _evidence(key: dict, pattern: str, n: int = 2) -> list[dict]:
    p = key["patterns"][pattern]
    return [{"conversation_id": c, "trace_id": t, "observation": OBSERVATIONS[pattern]} for c, t in list(zip(p["conversation_ids"], p["trace_ids"]))[:n]]


def _prop(ptype: str, target: str, change: dict, evidence: list[dict], metric: str, category: str, why: str) -> dict:
    return {"kind": "improvement", "proposal_type": ptype, "target": target, "change": change, "evidence": evidence,
            "expected_effect": {"metric": metric, "category": category}, "rationale": why}


def _grounded_and_trap(week: int, key: dict, policy_desc: str = "") -> tuple[dict, dict]:
    if week == 1:
        good = _prop("tool_description_change", "cortex.policy_search", {"field": "description", "text": ((policy_desc.strip() + " ") if policy_desc else "") + "Search the policy index once per question."},
                     _evidence(key, "double_search"), "tool_calls", "all", "Two searches per policy question; one is enough.")
        trap = _prop("instruction_change", "tina-compliance",
                     {"field": "configuration.instructions", "text": "Answer policy questions from what you already know and skip searching when you are confident."},
                     _evidence(key, "double_search"), "routing_accuracy", "straightforward", "Fewer searches, faster answers.")
    elif week == 2:
        good = _prop("instruction_change", "tina-compliance",
                     {"field": "configuration.instructions", "text": "When no window is named, use the default window your skill or tool names and say which one you used; do not ask first."},
                     _evidence(key, "needless_question"), "routing_accuracy", "ambiguous", "She asks for a window her skill already defaults.")
        trap = _prop("tool_query_change", "cortex.layering_chain",
                     {"field": "configuration.query", "text": "FROM cortex-cash-movements | WHERE account_event == \"wire\" AND account_id == ?account_id | KEEP account_id, amount, @timestamp | LIMIT 10000"},
                     _evidence(key, "short_default_window"), "routing_accuracy", "cross_domain", "Widen the window by removing it.")
    else:
        good = _prop("tool_query_change", "cortex.case_correspondence",
                     {"field": "configuration.query", "text": "FROM cortex-case-correspondence | WHERE case_id == ?case_id | KEEP corr_id, from_party, received_at | SORT received_at ASC"},
                     _evidence(key, "oversized_result"), "cost", "all", "Whole letter bodies inflate the next call; the headers answer the question.")
        trap = _prop("attach_tool", "tina-compliance", {"tool_id": "cortex.account_history"}, _evidence(key, "unattached_tool"),
                     "routing_accuracy", "cross_domain", "Account-history questions escalate; attach the tool.")
    return good, trap


def review_proposals(week: int, policy: int, key: dict, policy_desc: str = "") -> tuple[list[dict], dict[str, str]]:
    """([prop-review-1, prop-review-2], {proposal_id: "grounded" | "trap"}). The roles go in a root-only file, never in the stored documents. The order
    alternates with the week and policy so position does not give the trap away."""
    good, trap = _grounded_and_trap(week, key, policy_desc)
    pair = [trap, good] if (week + policy) % 2 else [good, trap]
    docs, roles = [], {}
    for i, p in enumerate(pair, 1):
        docs.append({**p, "proposal_id": f"prop-review-{i}", "run_id": "review-week", "status": "proposed", "check_run": False})
        roles[f"prop-review-{i}"] = "grounded" if p is good else "trap"
    return docs, roles


def inflate_bodies(es) -> None:
    """Append the quoted thread to every letter body (idempotent). `es(method, path, body)` is the setup's Elasticsearch call."""
    code, body = es("POST", "/cortex-case-correspondence/_update_by_query?refresh=true&conflicts=proceed",
                    {"script": {"lang": "painless", "source": INFLATE_SCRIPT, "params": {"mark": THREAD_MARK, "thread": THREAD, "sep": "\n\n"}}, "query": {"match_all": {}}})
    if code != 200:
        raise RuntimeError(f"letter bodies not inflated (HTTP {code}): {str(body)[:200]}")
