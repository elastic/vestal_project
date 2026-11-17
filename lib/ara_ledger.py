"""ara_ledger.py - the 6.2 ledger as the version history (28 section 3, B2; section 8.7 items 3; section 8.8).

Pure functions over ledger entries (rows of cortex-eval-ledger) and definitions; no HTTP.

    replay(start, entries, proposals)           (state, steps, problems): production's definitions derived from the ledger
    comparison_label(entries, proposal_id)      the label a candidate is compared with, when it was built
    remeasure_outcome(proposal, cand, re, thr)  "confirmed" or "not_confirmed"
    check_ledger(...)                           problems with a ledger's order, snapshots and outcomes (the B2 ARTIFACT rules)

`start` is {object_id: definition} for every object a proposal may change (the start state's definitions, with
the 6.2 patterns installed). An `apply` entry's `snapshot` is {object_id: the definition it replaced}; a `rollback`
restores its apply's snapshot, so it removes only that proposal's change (earlier confirmed changes stay) unless a
later apply changed the same object, which is reported (`rollback_clobbers`). A change that targets an object is
applied with ara_loop.apply_change to the definition of `proposal["target"]`. Entries are taken in `at` order, ties
in list order. Standard library only.
"""
from __future__ import annotations

import copy
from typing import Any

import ara_loop as L
from ara_eval import r1

ACTIONS = ("candidate", "gate", "apply", "remeasure", "rollback")


def _ordered(entries: list[dict]) -> list[dict]:
    return [e for _, e in sorted(enumerate(entries), key=lambda ie: (str(ie[1].get("at") or ""), ie[0]))]


def _applied_change(state: dict, proposal: dict) -> tuple[str, dict]:
    target = proposal["target"]
    if target not in state:
        raise KeyError(target)
    return target, L.apply_change(state[target], proposal)


SERVER_FIELDS = ("created_at", "updated_at", "permissions", "readonly")   # set by the server per caller and time: never part of a definition's identity


def norm(x):
    """A copy without the server-managed fields, at any depth: two definitions are the same when they differ only there."""
    if isinstance(x, dict):
        return {k: norm(v) for k, v in x.items() if k not in SERVER_FIELDS}
    if isinstance(x, list):
        return [norm(v) for v in x]
    return x


def replay(start: dict, entries: list[dict], proposals: dict) -> tuple[dict, list[dict], list[str]]:
    """Walk the ledger in order. Returns (final state, steps, problems). `steps` has one item per apply or rollback:
    {"proposal_id", "action", "before": {obj: def}, "after": {obj: def}} so a check can compare a snapshot with the
    state immediately before an apply. A rollback of a proposal with no live apply, or an apply of an unknown
    proposal, is a problem and changes nothing."""
    state = norm(copy.deepcopy(start))
    steps: list[dict] = []
    problems: list[str] = []
    live: dict[str, dict] = {}  # proposal_id -> the apply's snapshot, while the apply stands
    changed_after: dict[str, list[str]] = {}  # object -> proposal ids applied, in order
    for e in _ordered(entries):
        act, pid = e.get("action"), e.get("proposal_id")
        if act == "apply":
            prop = proposals.get(pid)
            if prop is None:
                problems.append(f"apply of {pid}: no such proposal")
                continue
            if pid in live:
                problems.append(f"apply of {pid}: already applied")
                continue
            try:
                obj, new = _applied_change(state, prop)
            except KeyError as k:
                problems.append(f"apply of {pid}: {k.args[0]} is not in the start state")
                continue
            before = {obj: copy.deepcopy(state[obj])}
            state[obj] = new
            live[pid] = before
            changed_after.setdefault(obj, []).append(pid)
            steps.append({"proposal_id": pid, "action": "apply", "before": before, "after": {obj: copy.deepcopy(new)}})
        elif act == "rollback":
            snap = live.pop(pid, None)
            if snap is None:
                problems.append(f"rollback of {pid}: it has no apply standing")
                continue
            before = {o: copy.deepcopy(state[o]) for o in snap}
            for o, d in snap.items():
                later = [p for p in changed_after.get(o, []) if p != pid and p in live and changed_after[o].index(p) > changed_after[o].index(pid)]
                if later:
                    problems.append(f"rollback_clobbers: rolling back {pid} also removes the change of {later[0]} on {o}")
                state[o] = copy.deepcopy(d)
                changed_after[o] = [p for p in changed_after[o] if p != pid]
            steps.append({"proposal_id": pid, "action": "rollback", "before": before, "after": copy.deepcopy(snap)})
    return state, steps, problems


def comparison_label(entries: list[dict], proposal_id: str) -> str:
    """Production's latest trusted measurement when the candidate was built: `m6-baseline`, or the last
    `remeasure-<id>` whose outcome is confirmed and whose apply has not been rolled back."""
    ordered = _ordered(entries)
    cut = next((i for i, e in enumerate(ordered) if e.get("action") == "candidate" and e.get("proposal_id") == proposal_id), len(ordered))
    stack: list[tuple[str, str]] = []  # (proposal_id, label) of each confirmed re-measure still standing
    for e in ordered[:cut]:
        pid = e.get("proposal_id")
        if e.get("action") == "rollback":
            stack = [(p, lab) for p, lab in stack if p != pid]
        elif e.get("action") == "remeasure" and e.get("outcome") == "confirmed":
            stack.append((pid, e.get("run_label") or f"remeasure-{pid}"))
    label = stack[-1][1] if stack else "m6-baseline"
    return label


def _metric(proposal: dict, agg: dict) -> float | None:
    m, cat = proposal["expected_effect"]["metric"], proposal["expected_effect"]["category"]
    if m == "routing_accuracy":
        return agg["routing_accuracy_overall"] if cat == "all" else agg["routing_accuracy"].get(cat)
    if m == "ndcg_at_5":
        v = agg.get("ndcg_at_5")
        return None if v is None else 100.0 * v
    return agg["tool_calls_per_question" if m == "tool_calls" else "cost_per_question"]


SMALL_CATEGORY = 15   # same bound as ara_loop.SMALL_CATEGORY


def remeasure_outcome(proposal: dict, candidate: dict, remeasure: dict, thresholds: dict) -> str:
    """`confirmed` when the re-measure's target metric is within the re-measure tolerance of the candidate's.
    Routing accuracy and nDCG (in points of 0.01) use `remeasure_tolerance_points`; tool calls and cost compare
    the re-measure with the candidate in percent of the candidate's value, tolerance `remeasure_tolerance_pct`.
    A routing-accuracy target in a category of under 15 questions is compared in questions: at most one question apart is confirmed."""
    a, b = _metric(proposal, candidate), _metric(proposal, remeasure)
    if a is None or b is None:
        return "not_confirmed"
    if proposal["expected_effect"]["metric"] in L.EFFICIENCY:
        tol = thresholds.get("remeasure_tolerance_pct")
        gap = abs(L._rise_pct(a, b)) if a else (0.0 if a == b else float("inf"))
    else:
        tol, gap = thresholds.get("remeasure_tolerance_points"), r1(abs(a - b))
        cat = proposal["expected_effect"]["category"]
        nc, nr = (candidate.get("category_counts") or {}).get(cat), (remeasure.get("category_counts") or {}).get(cat)
        if proposal["expected_effect"]["metric"] == "routing_accuracy" and cat != "all" and tol is not None and nc and nc == nr and nc < SMALL_CATEGORY:
            # a category of under 15 questions moves one question at a time: the re-measure may differ by at most one question
            return "confirmed" if round(gap * nc / 100.0) <= 1 else "not_confirmed"
    return "confirmed" if tol is not None and gap <= float(tol) else "not_confirmed"


def check_ledger(start: dict, entries: list[dict], proposals: dict, production: dict | None = None,
                 gate_runs: dict | None = None, thresholds: dict | None = None) -> list[str]:
    """The B2 ARTIFACT rules, as problems (empty when the ledger is consistent):
    every apply follows that proposal's gate entry; each apply's snapshot equals the replayed definition just
    before it; a `not_confirmed` remeasure has a later rollback; no rollback is left clobbering a later change;
    when `production` is given it equals the replayed state. `gate_runs` ({proposal_id: {"candidate": agg,
    "remeasure": agg}}) and `thresholds` additionally recompute each remeasure outcome."""
    state, steps, problems = replay(start, entries, proposals)
    ordered = _ordered(entries)
    seen_gate: set[str] = set()
    for e in ordered:
        pid = e.get("proposal_id")
        if e.get("action") == "gate":
            seen_gate.add(pid)
        if e.get("action") == "apply" and pid not in seen_gate:
            problems.append(f"apply of {pid} has no gate entry before it")
    applies = [e for e in ordered if e.get("action") == "apply"]
    ap_steps = [s for s in steps if s["action"] == "apply"]
    by_pid = {s["proposal_id"]: s for s in ap_steps}
    for e in applies:
        s = by_pid.get(e.get("proposal_id"))
        if s is not None and norm(e.get("snapshot")) != norm(s["before"]):
            problems.append(f"apply of {e['proposal_id']}: its snapshot is not the definition it replaced")
    for i, e in enumerate(ordered):
        pid = e.get("proposal_id")
        if e.get("action") != "remeasure":
            continue
        out = e.get("outcome")
        if gate_runs and thresholds and pid in gate_runs and proposals.get(pid):
            want = remeasure_outcome(proposals[pid], gate_runs[pid]["candidate"], gate_runs[pid]["remeasure"], thresholds)
            if out != want:
                problems.append(f"remeasure of {pid}: the ledger says {out}, the numbers say {want}")
        rolled = any(x.get("action") == "rollback" and x.get("proposal_id") == pid for x in ordered[i + 1:])
        if out == "not_confirmed" and not rolled:
            problems.append(f"remeasure of {pid} was not confirmed and the change was not rolled back")
        if out == "confirmed" and rolled:
            problems.append(f"{pid} was rolled back although its remeasure was confirmed")
    if production is not None:
        for obj, d in state.items():
            if norm(production.get(obj)) != norm(d):
                problems.append(f"production's {obj} is not the replayed state")
    return problems
