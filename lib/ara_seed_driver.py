"""ara_seed_driver.py - the degradation seeder's driver (28 section 5, 07 section 3.2): order and bookkeeping around a plan.

    seed(plan, client, es, measure, change_log_index="cortex-change-log") -> dict
    unseed(plan, client)                                             run the plan's revert (calibration and test sandboxes)

The order is the contract: `m6-baseline` exists (measured on the healthy state) BEFORE anything is applied; the plan's operations
run; the truthful change-log entry and its same-hour decoy are written; then `m6-degraded` is measured on the degraded state.
`measure(label)` runs the harness as root and writes the label's records (setup's job); `es.has_label(label)` and
`es.index_docs(index, docs)` are the two Elasticsearch calls the driver needs. A plan that fails part-way is reverted and the
error re-raised, so a sandbox is never left half-degraded; nothing is measured as `m6-degraded` then. Standard library only.
"""
from __future__ import annotations

import ara_degrade_live as DL


class SeedError(Exception):
    pass


def seed(plan: dict, client, es, measure, change_log_index: str = "cortex-change-log",
         baseline_label: str = "m6-baseline", degraded_label: str = "m6-degraded") -> dict:
    if not es.has_label(baseline_label):
        raise SeedError(f"{baseline_label} has not been measured: the baseline is taken on the healthy state, before the seed")
    if es.has_label(degraded_label):
        raise SeedError(f"{degraded_label} already exists: this sandbox has been seeded")
    try:
        DL.execute(client, plan["apply"])
    except DL.PlanFailed as e:
        try:
            DL.execute(client, plan["revert"])
        except DL.PlanFailed as e2:
            raise SeedError(f"the seed failed ({e}) and could not be reverted ({e2}): rebuild the sandbox") from None
        raise SeedError(f"the seed failed and was reverted: {e}") from None
    es.index_docs(change_log_index, plan["change_log"])
    measure(degraded_label)
    return {"layer": plan["layer"], "key": plan["key"], "change_ids": [e["change_id"] for e in plan["change_log"]],
            "cause_change_id": next(e["change_id"] for e in plan["change_log"] if e["cause"])}


def unseed(plan: dict, client) -> None:
    DL.execute(client, plan["revert"])
