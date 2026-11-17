"""ara_price.py - the 6.3 price check on M5's rate card (28 section 4, Defend Q2; B1's schedule).

A canary run is the eight records of one workflow execution. Its cost is the sum of token_cost over the records'
fresh, cached and output tokens on the rate card (price_fresh_input, price_cached_input, price_output, dollars per
million tokens, 25 section 5; every model priced on the same card, 25 section 1). What a schedule costs per day is
that run cost times the schedule's runs per day.

    run_cost(records, card)               dollars for one canary run
    runs_per_day(defn, start, days)       mean occurrences per day of the workflow's scheduled triggers (ara_workflow)
    day_cost(records, card, per_day)      run cost times runs per day
    options(records, card, per_day)       the four Defend Q2 values: true, per_run, hourly, cached_as_fresh
    distinct(opts)                        True when the four values differ at the displayed precision

Tokens are read from the run records (input_tokens, cached_input_tokens, output_tokens: the M5 record fields),
never from traces. Standard library only.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import ara_workflow as W
from agent_builder import token_cost

CARD_KEYS = ("price_fresh_input", "price_cached_input", "price_output")
PRECISION = 4  # decimal places of a dollar shown in options; 28 does not fix one (see lib-plan.md)


def check_card(card: Any) -> list[str]:
    if not isinstance(card, dict):
        return ["the rate card is not an object"]
    return [f"rate card lacks a number for {k}" for k in CARD_KEYS
            if not isinstance(card.get(k), (int, float)) or isinstance(card.get(k), bool)]


def _usage(r: dict, cached_as_fresh: bool = False) -> dict:
    total = int(r.get("input_tokens") or 0)
    cached = int(r.get("cached_input_tokens") or 0)
    if cached_as_fresh:
        return {"fresh_input_tokens": total, "cached_input_tokens": 0, "output_tokens": int(r.get("output_tokens") or 0)}
    return {"fresh_input_tokens": total - cached, "cached_input_tokens": cached, "output_tokens": int(r.get("output_tokens") or 0)}


def run_cost(records: list[dict], card: dict, cached_as_fresh: bool = False) -> float:
    bad = check_card(card)
    if bad:
        raise ValueError("; ".join(bad))
    return sum(token_cost(_usage(r, cached_as_fresh), card) for r in records)


def runs_per_day(defn: dict, start: datetime, days: int = 7) -> float:
    return len(W.expand(defn, start, start + timedelta(days=days))) / days


def day_cost(records: list[dict], card: dict, per_day: float, cached_as_fresh: bool = False) -> float:
    return run_cost(records, card, cached_as_fresh) * per_day


def options(records: list[dict], card: dict, per_day: float) -> dict[str, float]:
    """Defend Q2's four values: the true daily cost; one run's cost (forgets the multiplier); the cost at hourly runs
    (24 a day); the daily cost with cached input priced as fresh."""
    one = run_cost(records, card)
    vals = {"true": one * per_day, "per_run": one, "hourly": one * 24,
            "cached_as_fresh": day_cost(records, card, per_day, cached_as_fresh=True)}
    return {k: round(v, PRECISION) for k, v in vals.items()}


def distinct(opts: dict[str, float]) -> bool:
    return len(set(opts.values())) == len(opts)
