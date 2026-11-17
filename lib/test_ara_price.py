"""Offline tests for ara_price.py (the 6.3 price check)."""
import pathlib
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ara_price as R  # noqa: E402
from agent_builder import token_cost  # noqa: E402

CARD = {"price_fresh_input": 2.0, "price_cached_input": 0.5, "price_output": 10.0}
START = datetime(2026, 11, 9, tzinfo=timezone.utc)


def recs(n=8):
    return [{"input_tokens": 10000, "cached_input_tokens": 6000, "output_tokens": 500} for _ in range(n)]


def test_run_cost_is_the_sum_of_token_cost_on_the_card():
    one = token_cost({"fresh_input_tokens": 4000, "cached_input_tokens": 6000, "output_tokens": 500}, CARD)
    assert one == pytest.approx((4000 * 2 + 6000 * 0.5 + 500 * 10) / 1e6)
    assert R.run_cost(recs(), CARD) == pytest.approx(8 * one)


def test_cached_as_fresh_prices_all_input_at_the_fresh_rate():
    assert R.run_cost(recs(1), CARD, cached_as_fresh=True) == pytest.approx((10000 * 2 + 500 * 10) / 1e6)


def test_runs_per_day_from_a_shift_rule():
    defn = {"triggers": [{"type": "manual"}, {"type": "scheduled", "with": {"rrule": {
        "freq": "DAILY", "interval": 1, "byhour": [6, 14, 22], "byminute": [0], "tzid": "America/New_York"}}}]}
    assert R.runs_per_day(defn, START) == 3.0
    assert R.runs_per_day({"triggers": [{"type": "manual"}]}, START) == 0.0


def test_options_are_four_different_values_with_the_stated_relations():
    o = R.options(recs(), CARD, 3)
    one = R.run_cost(recs(), CARD)
    assert o["per_run"] == round(one, 4) and o["true"] == round(3 * one, 4) and o["hourly"] == round(24 * one, 4)
    assert o["cached_as_fresh"] > o["true"] and R.distinct(o)
    assert R.options(recs(), CARD, 1)["true"] == R.options(recs(), CARD, 1)["per_run"] and not R.distinct(R.options(recs(), CARD, 1))


def test_card_is_checked():
    assert R.check_card(CARD) == []
    assert R.check_card({"price_fresh_input": 1}) == ["rate card lacks a number for price_cached_input", "rate card lacks a number for price_output"]
    with pytest.raises(ValueError):
        R.run_cost(recs(), {"price_fresh_input": 1})
