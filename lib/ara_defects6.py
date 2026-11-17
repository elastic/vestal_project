"""ara_defects6.py - Lab 6.1 B2: the shared helpers for the structuring tool's definition (28 section 2). The variant defects and the held-out sets are private (m6/tools/private6.py).

    REFERENCE_QUERY                       the M4 query (manifests/m4/ara-m4-4-1-end.json), the fixed state
    returns_rows(docs, account, days, age_shift)   the reference semantics over cash-deposit documents (python twin of the query)

The definition the Build teaches (the assignment states it): a cash deposit of 8,000 to 9,999.99 dollars within the last N days
is a CX-7 event; any such deposit counts, there is no minimum count. A near-miss account is one whose sub-threshold deposits fall
outside the definition by amount (7,900 to 7,999.99) or by window (older than N days). Ages are fractional days at `now`; a set
is kept only when no decision flips if the sandbox has lived `margin` days longer (DATE_DIFF counts whole days at the time of the
call), so a learner who works for hours is graded on the same sets. Standard library only.
"""
from __future__ import annotations

import datetime as dt
import math

REFERENCE_QUERY = ('FROM cortex-wire-transfers\n| WHERE account_id == ?account_id\n    AND account_event == "deposit" AND deposit_type == "cash"\n'
                   '    AND amount >= 8000 AND amount < 10000\n    AND DATE_DIFF("day", @timestamp, NOW()) < ?lookback_days\n'
                   '| KEEP event_id, @timestamp, amount, branch_id\n| SORT @timestamp DESC')
LOOKBACKS = (3, 5, 7, 10, 14, 30)
BAND = (8000.0, 10000.0)
NEAR_BAND = (7900.0, 8000.0)
MARGIN = 0.25  # days a sandbox may outlive its load, without a decision flipping


def _t(ts: str) -> dt.datetime:
    return dt.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.000Z")


def age_days(ts: str, now: dt.datetime) -> float:
    return (now - _t(ts)).total_seconds() / 86400.0


def cash_deposits(docs: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for d in docs:
        if d.get("account_event") == "deposit" and d.get("deposit_type") == "cash":
            out.setdefault(d["account_id"], []).append(d)
    return out


def returns_rows(deps: list[dict], days: int, now: dt.datetime, shift: float = 0.0) -> bool:
    """The reference query over one account's cash deposits: a row when a deposit is in the band and floor(age + shift) < days."""
    return any(BAND[0] <= d["amount"] < BAND[1] and math.floor(age_days(d["@timestamp"], now) + shift) < days for d in deps)


def stable(deps: list[dict], days: int, now: dt.datetime, margin: float = MARGIN) -> bool:
    return returns_rows(deps, days, now) == returns_rows(deps, days, now, margin)
