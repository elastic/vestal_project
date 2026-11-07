"""ara_eval.py - the evaluation harness's deterministic core (25 sections 4, 5, 8.5 and 8.7).

Pure functions the checks, ara-eval.py and M6 share, so a number is computed one way everywhere:

    parse_score(output, scale)          judge output -> scale value (first numeric token, clamp, snap)
    judge_gate(runs, key, ...)          5.3 B2 held-out gate over n judge runs
    coverage(testset, pool, key, ...)   5.3 B1 coverage rule: failures named, empty when it passes
    category_means(scores, cats, all)   per-category mean of per-query scores; a category with none is None
    aggregates(records, card)           trusted aggregates (8.7 step 6) from verified run records
    decide(before, after, budget)       5.4 decision rule table (5.2): (ship, primary_reason)

The live parts (harness runs, the judge runner, the integrity procedure's conversation reads) build on
these and on agent_builder.round_usage / token_cost. Standard library only.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

from agent_builder import token_cost

CATEGORIES = ("straightforward", "ambiguous", "time_window_edge", "cross_domain", "adversarial", "out_of_scope")
DEFECTS = {"unfaithful_to_context": "faithfulness", "faithful_but_off_question": "answer_relevance",
           "wrong_context_retrieved": "context_precision"}
METRICS = ("faithfulness", "answer_relevance", "context_precision")
DEFAULT_SCALE = (0.0, 0.5, 1.0)
_NUMBER = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)")


def r1(x: float | None) -> float | None:
    """One decimal, as the 5.4 rule's inputs are (5.2)."""
    return None if x is None else round(x + 0.0, 1)


# ── judge ─────────────────────────────────────────────────────────────────────

def parse_score(output: Any, scale: tuple = DEFAULT_SCALE) -> tuple[float | None, bool]:
    """(value, off_scale). The first numeric token of a COMPLETION output, clamped to 0 to 1 and snapped
    to the nearest scale value (a tie snaps down). off_scale is True when the token was not already a
    scale value (ara-eval.py judge reports the count). No numeric token: (None, True)."""
    m = _NUMBER.search(str(output or ""))
    if not m:
        return None, True
    raw = float(m.group(0))
    v = min(1.0, max(0.0, raw))
    snapped = min(scale, key=lambda s: (abs(s - v), s))
    return float(snapped), raw not in scale


def record_passes(scores: dict, defect: str, flag_margin: float, control_min: float) -> bool:
    """One held-out record in one run (5.3 B2). A defect record passes when its own metric is at least
    flag_margin below each of the other two; a control (no_defect) when all three are at least
    control_min. A missing score fails the record."""
    vals = {m: scores.get(m) for m in METRICS}
    if any(v is None for v in vals.values()):
        return False
    if defect == "no_defect":
        return all(v >= control_min for v in vals.values())
    own = DEFECTS[defect]
    return all(vals[own] <= vals[m] - flag_margin + 1e-9 for m in METRICS if m != own)


def judge_gate(runs: list[dict], key: dict, flag_margin: float, control_min: float, k: int) -> dict:
    """runs: one dict per judge run, sample_id -> {metric: score}. key: sample_id -> defect type or
    no_defect. Every record must pass in at least k runs. The message names the defect types missed and
    how many records, never the records (5.3 B2)."""
    passes = {sid: sum(record_passes(run.get(sid) or {}, d, flag_margin, control_min) for run in runs)
              for sid, d in key.items()}
    missed = [sid for sid, n in passes.items() if n < k]
    types = sorted({key[s] for s in missed})
    msg = ("" if not missed else f"Your judge missed {len(missed)} of {len(key)} held-out records "
           f"(in fewer than {k} of {len(runs)} runs): {', '.join(types)}.")
    return {"passed": not missed, "missed_types": types, "missed_count": len(missed), "message": msg}


# ── test sets ─────────────────────────────────────────────────────────────────

def coverage(testset: list[dict], pool: dict, key: dict, shares: dict, label_share_min: float = 0.8,
             size: tuple = (18, 30), min_policy: int = 6, min_agent: int = 10, min_per_category: int = 3,
             share_floor: float = 0.10) -> list[str]:
    """5.3 B1 coverage. testset: [{"question_id", "category"}]. pool: question_id -> {"kind": "policy" |
    "agent"}. key: question_id -> true category (private). shares: category -> share of the learner's
    log variant (0 to 1). Returns the failures, each a message; empty means it passes."""
    out = []
    ids = [q["question_id"] for q in testset]
    unknown = [i for i in ids if i not in pool]
    if unknown:
        out.append(f"{len(unknown)} question ids are not in the question pool: {', '.join(unknown[:5])}.")
    if len(set(ids)) != len(ids):
        out.append("A question appears more than once in the test set.")
    if not size[0] <= len(ids) <= size[1]:
        out.append(f"The test set holds {len(ids)} questions; it needs {size[0]} to {size[1]}.")
    known = [q for q in testset if q["question_id"] in pool]
    n_policy = sum(pool[q["question_id"]]["kind"] == "policy" for q in known)
    n_agent = sum(pool[q["question_id"]]["kind"] == "agent" for q in known)
    if n_policy < min_policy:
        out.append(f"{n_policy} policy-retrieval questions; at least {min_policy} are needed.")
    if n_agent < min_agent:
        out.append(f"{n_agent} agent-level questions; at least {min_agent} are needed.")
    true_counts = Counter(key[q["question_id"]] for q in known)
    short = [c for c in CATEGORIES if shares.get(c, 0) >= share_floor - 1e-9 and true_counts[c] < min_per_category]
    if short:
        out.append(f"Categories that are at least {int(share_floor * 100)} percent of the question log need at least "
                   f"{min_per_category} questions each: {', '.join(short)}.")
    if not any(c != "straightforward" and true_counts[c] for c in CATEGORIES):
        out.append("The test set covers only straightforward questions.")
    bad = [q for q in known if q.get("category") not in CATEGORIES]
    if bad:
        out.append(f"{len(bad)} questions carry no category from the fixed list.")
    agree = sum(q.get("category") == key[q["question_id"]] for q in known)
    if known and agree / len(known) < label_share_min - 1e-9:
        out.append(f"{agree} of {len(known)} category labels match the question log; at least "
                   f"{int(label_share_min * 100)} percent must.")
    return out


def category_means(scores: dict, categories: dict, wanted=CATEGORIES) -> dict:
    """Per-category mean of per-query scores (a _rank_eval metric_score per request, or a route_correct
    as 0/1). A category with no scored query reports None, never zero (5.3 B1)."""
    by = defaultdict(list)
    for qid, s in scores.items():
        if s is not None and qid in categories:
            by[categories[qid]].append(float(s))
    return {c: (sum(by[c]) / len(by[c]) if by[c] else None) for c in wanted}


# ── run records and aggregates ────────────────────────────────────────────────

def aggregates(records: list[dict], card: dict | None = None) -> dict:
    """Trusted aggregates (8.7 step 6) from verified run records (8.5 fields), agent-level questions only.
    Routing accuracy per category and overall in points, one decimal; per-question means of tool calls and
    fresh, cached, output and total tokens; cached share; cost per question on the rate card (5.4, 5.C);
    page-fetch share per category over questions that read a page."""
    recs = [r for r in records if r.get("expected_route") is not None]
    n = len(recs)
    if not n:
        return {"questions": 0}
    acc = category_means({r["question_id"]: 1.0 if r["route_correct"] else 0.0 for r in recs},
                         {r["question_id"]: r["category"] for r in recs})
    mean = lambda f: sum(f(r) for r in recs) / n
    total_in = sum(int(r.get("input_tokens") or 0) for r in recs)
    cached = sum(int(r.get("cached_input_tokens") or 0) for r in recs)
    out = {
        "questions": n,
        "routing_accuracy": {c: r1(v * 100) if v is not None else None for c, v in acc.items()},
        "routing_accuracy_overall": r1(100 * sum(bool(r["route_correct"]) for r in recs) / n),
        "tool_calls_per_question": mean(lambda r: int(r.get("tool_call_count") or 0)),
        "input_tokens_per_question": total_in / n,
        "cached_input_tokens_per_question": cached / n,
        "fresh_input_tokens_per_question": (total_in - cached) / n,
        "output_tokens_per_question": mean(lambda r: int(r.get("output_tokens") or 0)),
        "cached_share": (cached / total_in) if total_in else None,
    }
    out["total_tokens_per_question"] = out["input_tokens_per_question"] + out["output_tokens_per_question"]
    if card:
        out["cost_per_question"] = mean(lambda r: token_cost({
            "input_tokens": int(r.get("input_tokens") or 0), "cached_input_tokens": int(r.get("cached_input_tokens") or 0),
            "fresh_input_tokens": int(r.get("input_tokens") or 0) - int(r.get("cached_input_tokens") or 0),
            "output_tokens": int(r.get("output_tokens") or 0)}, card))
    reads = defaultdict(list)
    for r in recs:
        pages = [c for c in r.get("observed_route") or [] if c.get("tool_id") == "cortex.read_page"]
        if pages:
            reads[r["category"]].append(all(c.get("page_fetch_ok") for c in pages))
    out["page_fetch_share"] = {c: (sum(v) / len(v) if v else None) for c, v in ((c, reads.get(c, [])) for c in CATEGORIES)}
    return out


def _rise_pct(before: float, after: float) -> float:
    return r1(100.0 * (after - before) / before) if before else (0.0 if after == before else float("inf"))


def decide(before: dict, after: dict, budget: dict) -> tuple[bool, str, dict]:
    """5.4 decision rule table (25 section 5.2): the first row that applies wins. before and after are
    trusted aggregates with cost_per_question; budget holds min_gain_points, large_gain_points,
    category_drop_limit_points and the tool_call_limit_pct_ and cost_limit_pct_ small/large pairs.
    Returns (ship, primary_reason, the rule's inputs, rounded as the rule reads them)."""
    gain = r1(after["routing_accuracy_overall"] - before["routing_accuracy_overall"])
    drops = {c: r1(before["routing_accuracy"][c] - after["routing_accuracy"][c])
             for c in CATEGORIES if before["routing_accuracy"].get(c) is not None and after["routing_accuracy"].get(c) is not None}
    size = "small" if gain < budget["large_gain_points"] else "large"
    tool_rise = _rise_pct(before["tool_calls_per_question"], after["tool_calls_per_question"])
    cost_rise = _rise_pct(before["cost_per_question"], after["cost_per_question"])
    inputs = {"gain": gain, "category_drops": drops, "limits": size, "tool_call_rise_pct": tool_rise, "cost_rise_pct": cost_rise}
    if any(d > budget["category_drop_limit_points"] for d in drops.values()):
        return False, "category_regression_over_budget", inputs
    if gain < budget["min_gain_points"]:
        return False, "no_quality_gain", inputs
    if tool_rise > budget[f"tool_call_limit_pct_{size}"]:
        return False, "tool_call_regression_over_budget", inputs
    if cost_rise > budget[f"cost_limit_pct_{size}"]:
        return False, "token_cost_regression_over_budget", inputs
    return True, "quality_gain_within_budget", inputs
