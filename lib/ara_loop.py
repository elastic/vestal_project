"""ara_loop.py - the proposal gate's rule tables (28 section 3.2) and the proposal spec check, as pure functions.

The live parts of ara-loop.py (candidate, gate runs, apply, rollback) build on these; the check applies the same
functions to trusted aggregates, so a decision is computed one way everywhere.

    validate_proposal(p)                      messages, empty when the proposal meets the spec (28 section 3)
    gain(proposal, comparison, candidate, gate)   the gain on the proposal's expected_effect
    decide_improvement(comparison, candidate, proposal, gate)   (decision, reason, inputs, rows)
    decide_incident(baseline, candidate, proposal, gate)        (decision, reason, inputs, rows)
    decide(kind, ...)                         the rule table for the proposal's kind

Aggregates are the trusted-aggregates dicts of ara_eval.aggregates (routing_accuracy per category and
routing_accuracy_overall in points, tool_calls_per_question, cost_per_question) plus `ndcg_at_5` over the gate
set's policy questions. `rows` lists every rule in order with its inputs and whether it applied, for the ledger.
Inputs are computed from unrounded aggregates, then rounded: points and percents to one decimal, nDCG gain in
points of 0.01 (so 0.05 is 5.0). A gate value of None or "none" means no limit. Standard library only.
"""
from __future__ import annotations

from typing import Any

from ara_eval import CATEGORIES, r1

KINDS = ("improvement", "incident_fix")
TYPES = ("instruction_change", "tool_description_change", "tool_query_change", "attach_tool", "detach_tool", "data_change")
METRICS = {"routing_accuracy": CATEGORIES + ("all",), "ndcg_at_5": ("policy_retrieval",),
           "tool_calls": ("all",), "cost": ("all",)}
OPERATIONS = ("repoint_alias", "delete_matching")
EFFICIENCY = ("tool_calls", "cost")


def _nonempty(v: Any) -> bool:
    return isinstance(v, str) and bool(v.strip())


def validate_proposal(p: Any) -> list[str]:
    """Why a proposal does not meet the spec; empty when it does. Messages name the field, never a record. The
    rationale is not read (prose is never graded)."""
    if not isinstance(p, dict):
        return ["a proposal is a JSON object"]
    bad: list[str] = []
    for f in ("kind", "proposal_type", "target", "change", "evidence", "expected_effect"):
        if f not in p:
            bad.append(f"{f} is required")
    if bad:
        return bad
    if p["kind"] not in KINDS:
        bad.append(f"kind must be one of {', '.join(KINDS)}")
    if p["proposal_type"] not in TYPES:
        bad.append(f"proposal_type must be one of {', '.join(TYPES)}")
    if not _nonempty(p["target"]):
        bad.append("target must be an agent id or a tool id")
    ev = p["evidence"]
    if not isinstance(ev, list) or not ev:
        bad.append("evidence needs at least one item")
    else:
        for i, e in enumerate(ev):
            if not isinstance(e, dict) or not _nonempty(e.get("conversation_id")) or not _nonempty(e.get("trace_id")) \
                    or not _nonempty(e.get("observation")):
                bad.append(f"evidence[{i}] needs conversation_id, trace_id and observation")
    eff = p["expected_effect"]
    if not isinstance(eff, dict) or eff.get("metric") not in METRICS or eff.get("category") not in METRICS.get(eff.get("metric"), ()):
        bad.append("expected_effect needs a metric and a category that goes with it")
    ch, t = p["change"], p["proposal_type"]
    if not isinstance(ch, dict):
        bad.append("change must be an object")
    elif t in ("attach_tool", "detach_tool"):
        if not _nonempty(ch.get("tool_id")):
            bad.append(f"a {t} change needs tool_id")
    elif t == "data_change":
        for f in ("tool_id", "production_source", "candidate_source"):
            if not _nonempty(ch.get(f)):
                bad.append(f"a data_change needs {f}")
        if ch.get("operation") not in OPERATIONS:
            bad.append(f"a data_change operation must be one of {', '.join(OPERATIONS)}")
        elif ch["operation"] == "delete_matching" and not isinstance(ch.get("query"), dict):
            bad.append("a delete_matching operation needs its query")
    elif t in TYPES:
        if not _nonempty(ch.get("field")) or not _nonempty(ch.get("text")):
            bad.append(f"a {t} change needs field and text")
    if p["kind"] == "improvement" and t == "data_change":
        bad.append("an improvement proposal never changes data")
    return bad


def _limit(v: Any) -> float | None:
    return None if v is None or v == "none" else float(v)


def _rise_pct(base: float, new: float) -> float:
    if base:
        return r1(100.0 * (new - base) / base)
    return 0.0 if new == base else float("inf")


def _effect(proposal: dict) -> tuple[str, str]:
    e = proposal["expected_effect"]
    return e["metric"], e["category"]


def gain(proposal: dict, comparison: dict, candidate: dict, gate: dict | None = None) -> float | None:
    """The candidate minus the comparison on the proposal's expected_effect. Routing accuracy in points in the
    named category (every agent-level question for `all`, or when gate target_scope is `overall`); nDCG at 5 in
    points of 0.01; tool calls and cost as the fall in percent of the comparison's mean."""
    metric, cat = _effect(proposal)
    overall = (gate or {}).get("target_scope") == "overall"
    if metric == "routing_accuracy":
        if cat == "all" or overall:
            a, b = candidate["routing_accuracy_overall"], comparison["routing_accuracy_overall"]
        else:
            a, b = candidate["routing_accuracy"].get(cat), comparison["routing_accuracy"].get(cat)
        return None if a is None or b is None else r1(a - b)
    if metric == "ndcg_at_5":
        a, b = candidate.get("ndcg_at_5"), comparison.get("ndcg_at_5")
        return None if a is None or b is None else r1(100.0 * (a - b))
    key = "tool_calls_per_question" if metric == "tool_calls" else "cost_per_question"
    return r1(-_rise_pct(comparison[key], candidate[key]))


def _drops(base: dict, cand: dict) -> dict[str, float]:
    return {c: r1(base["routing_accuracy"][c] - cand["routing_accuracy"][c]) for c in CATEGORIES
            if base["routing_accuracy"].get(c) is not None and cand["routing_accuracy"].get(c) is not None}


SMALL_CATEGORY = 15   # a category with fewer agent questions than this moves in steps of 100/n points (one question is 7 to 25 points), so it is judged in questions


def _lost_questions(before: dict, after: dict, cat: str, drop: float) -> int | None:
    """Questions a category lost, when both measurements hold the same count under SMALL_CATEGORY; None when the points rule applies."""
    nb, na = (before.get("category_counts") or {}).get(cat), (after.get("category_counts") or {}).get(cat)
    if not nb or nb != na or nb >= SMALL_CATEGORY:
        return None
    return round(drop * nb / 100.0)


def category_regressed(before: dict, after: dict, drops: dict[str, float], limit: float | None) -> bool:
    """The category-drop row. A category of 15 or more questions regresses when it falls by more than `limit` points. A smaller category
    regresses only when it loses at least 2 questions (one question is more than the limit, and a single question is within the run-to-run
    spread of an agent question), and still beyond the limit in points."""
    if limit is None:
        return False
    for c, d in drops.items():
        lost = _lost_questions(before, after, c, d)
        if (d > limit) if lost is None else (lost >= 2 and d > limit):
            return True
    return False


def _first(rows: list[dict]) -> tuple[str, str]:
    for r in rows:
        if r["applies"]:
            return r["decision"], r["reason"]
    return "pass", ""


def decide_improvement(comparison: dict, candidate: dict, proposal: dict, gate: dict) -> tuple[str, str, dict, list[dict]]:
    """The improvement table (28 section 3.2); the first row that applies wins."""
    metric, _ = _effect(proposal)
    g = gain(proposal, comparison, candidate, gate)
    need = _limit(gate.get("min_gain_pct" if metric in EFFICIENCY else "min_gain_points"))
    drops = _drops(comparison, candidate)
    tool_rise = _rise_pct(comparison["tool_calls_per_question"], candidate["tool_calls_per_question"])
    cost_rise = _rise_pct(comparison["cost_per_question"], candidate["cost_per_question"])
    cd, tl, cl = _limit(gate.get("category_drop_limit_points")), _limit(gate.get("tool_call_limit_pct")), _limit(gate.get("cost_limit_pct"))
    inputs = {"gain": g, "min_gain": need, "category_drops": drops, "tool_call_rise_pct": tool_rise, "cost_rise_pct": cost_rise}
    rows = [
        {"rule": "category_drop", "applies": category_regressed(comparison, candidate, drops, cd),
         "decision": "fail", "reason": "category_regression"},
        {"rule": "min_gain", "applies": need is not None and (g is None or g < need), "decision": "fail", "reason": "no_gain"},
        {"rule": "tool_calls", "applies": tl is not None and tool_rise > tl, "decision": "fail", "reason": "tool_call_regression"},
        {"rule": "cost", "applies": cl is not None and cost_rise > cl, "decision": "fail", "reason": "cost_regression"},
        {"rule": "otherwise", "applies": True, "decision": "pass", "reason": "within_policy"},
    ]
    d, why = _first(rows)
    return d, why, inputs, rows


def decide_incident(baseline: dict, candidate: dict, proposal: dict, gate: dict) -> tuple[str, str, dict, list[dict]]:
    """The incident table: the candidate against the healthy m6-baseline; the target is recovery, not gain.
    `within tolerance` is the absolute difference, so a candidate far above the baseline is also not a recovery."""
    inc = gate.get("incident") or {}
    metric, cat = _effect(proposal)
    drops = _drops(baseline, candidate)
    if metric == "ndcg_at_5":
        a, b, tol = candidate.get("ndcg_at_5"), baseline.get("ndcg_at_5"), inc.get("recovery_tolerance_ndcg")
        gap = None if a is None or b is None else round(abs(round(a, 2) - round(b, 2)), 2)
    else:
        if cat == "all" or gate.get("target_scope") == "overall":
            a, b = candidate["routing_accuracy_overall"], baseline["routing_accuracy_overall"]
        else:
            a, b = candidate["routing_accuracy"].get(cat), baseline["routing_accuracy"].get(cat)
        tol = inc.get("recovery_tolerance_points")
        gap = None if a is None or b is None else r1(abs(a - b))
    tool_rise = _rise_pct(baseline["tool_calls_per_question"], candidate["tool_calls_per_question"])
    cost_rise = _rise_pct(baseline["cost_per_question"], candidate["cost_per_question"])
    cd, tl, cl = _limit(gate.get("category_drop_limit_points")), _limit(gate.get("tool_call_limit_pct")), _limit(gate.get("cost_limit_pct"))
    inputs = {"affected_gap": gap, "recovery_tolerance": tol, "category_drops": drops,
              "tool_call_rise_pct": tool_rise, "cost_rise_pct": cost_rise}
    rows = [
        {"rule": "category_drop", "applies": category_regressed(baseline, candidate, drops, cd),
         "decision": "fail", "reason": "category_regression"},
        {"rule": "recovery", "applies": gap is None or tol is None or gap > float(tol), "decision": "fail", "reason": "no_recovery"},
        {"rule": "tool_calls", "applies": tl is not None and tool_rise > tl, "decision": "fail", "reason": "tool_call_regression"},
        {"rule": "cost", "applies": cl is not None and cost_rise > cl, "decision": "fail", "reason": "cost_regression"},
        {"rule": "otherwise", "applies": True, "decision": "pass", "reason": "recovers_within_policy"},
    ]
    d, why = _first(rows)
    return d, why, inputs, rows


def decide(proposal: dict, comparison: dict, candidate: dict, gate: dict, baseline: dict | None = None) -> tuple[str, str, dict, list[dict]]:
    """The rule table for the proposal's kind. An incident fix is judged against `baseline` (m6-baseline), an
    improvement against `comparison` (production's latest trusted measurement)."""
    if proposal.get("kind") == "incident_fix":
        return decide_incident(baseline if baseline is not None else comparison, candidate, proposal, gate)
    return decide_improvement(comparison, candidate, proposal, gate)


# ── applying a change to a definition (28 section 3; gap G6) ──────────────────

NAMED_PREFIX = "prop-review-"  # the week's two named proposals: prop-review-1 and prop-review-2


def is_named(proposal_id: Any) -> bool:
    return isinstance(proposal_id, str) and proposal_id.startswith(NAMED_PREFIX)


def _path(defn: dict, field: str):
    parts = field.split(".")
    node = defn
    for k in parts[:-1]:
        node = node.get(k) if isinstance(node, dict) else None
    if not isinstance(node, dict) or parts[-1] not in node:
        raise KeyError(field)
    return node, parts[-1]


def tool_id_list(defn: dict) -> list:
    """The list an agent definition keeps its tool ids in, as the live list object (edit in place): the first
    group's `tool_ids` under `configuration.tools` (Agent Builder's shape), else a top-level `tool_ids`, which is
    created when neither exists."""
    groups = (defn.get("configuration") or {}).get("tools")
    if isinstance(groups, list) and groups and isinstance(groups[0], dict):
        return groups[0].setdefault("tool_ids", [])
    return defn.setdefault("tool_ids", [])


def apply_change(defn: dict, proposal: dict) -> dict:
    """The definition after a proposal's change, as a copy (the candidate's copy; production is not touched here).
    attach_tool and detach_tool edit the definition's tool id list (`tool_id_list`: `configuration.tools[0].tool_ids`, else `tool_ids`). A text change sets the dotted
    `field` to `text`; for a named proposal (`prop-review-*`) the text is appended on a new line and the
    existing field is kept, so M5's hardening block in the instructions survives (G6). A tool_query_change replaces the query: appended text would not be a query. A tool_description_change replaces the description (the proposal carries the whole corrected description: an appended line would sit beside the sentence it corrects). Raises KeyError when the
    field does not exist in the definition."""
    import copy
    out = copy.deepcopy(defn)
    ch, t = proposal["change"], proposal["proposal_type"]
    if t in ("attach_tool", "detach_tool"):
        ids = tool_id_list(out)
        if t == "attach_tool" and ch["tool_id"] not in ids:
            ids.append(ch["tool_id"])
        if t == "detach_tool":
            ids[:] = [i for i in ids if i != ch["tool_id"]]
        return out
    node, key = _path(out, ch["field"])
    old = node[key]
    if is_named(proposal.get("proposal_id")) and isinstance(old, str) and t not in ("tool_query_change", "tool_description_change"):
        node[key] = old.rstrip("\n") + "\n" + ch["text"]
    else:
        node[key] = ch["text"]
    return out
