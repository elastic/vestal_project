"""ara_degrade.py - the degradation seeder's history half (28 section 5, 6.4 B1): a deterministic 30-day canary
history with three incident windows, one per degradation type, for the CHANGE_POINT lab.

    variant(participant_id)                          0, 1 or 2: which order of the three types
    history(participant_id, now, days=30, ...)       {"records", "change_log", "key"}
    series(records, field)                           [(timestamp, value)] for one field, in run order
    find_step(values)                                where the earliest large step begins (a test helper)

Everything is seeded by the participant id (sha256), so one participant always gets the same history, two
participants usually get different days and magnitudes, and the key says where each window starts. Each record
is one canary run (three a day at the shift starts) in the cortex-eval-runs summary fields a run's aggregates
give. The numbers are synthetic: the spec's real-run history (28 section 14 item 31) replaces them where a real
canary history exists; this module is the generator for labs and tests that need a history with a known key.

Signatures (28 section 5 teaching points):
  retrieval_drift      recall and nDCG at 5 step down and the lexical control steps down too; routes unchanged
  embedding_staleness  recall at 5 steps down, the lexical control holds; nDCG falls a little; routes unchanged
  behavior_shift       escalation share and tool calls step up, accuracy falls; retrieval flat
Every incident ends (the window closes) so the lab has both a step and a recovery. Standard library only.
"""
from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta, timezone

from ara_eval import CATEGORIES

SHIFT_HOURS = (6, 14, 22)
ORDERS = (("retrieval_drift", "embedding_staleness", "behavior_shift"),
          ("embedding_staleness", "behavior_shift", "retrieval_drift"),
          ("behavior_shift", "retrieval_drift", "embedding_staleness"))
SIGNAL = {"retrieval_drift": "ranking_down_semantic_and_lexical_after_ingest",
          "embedding_staleness": "semantic_recall_down_lexical_flat",
          "behavior_shift": "tool_mix_shifted_retrieval_flat"}
CHANGE_KIND = {"retrieval_drift": "ingest", "embedding_staleness": "endpoint_change", "behavior_shift": "deploy"}
DECOY_KIND = {"retrieval_drift": "connector_rotation", "embedding_staleness": "deploy", "behavior_shift": "ingest"}
# healthy mean, noise sd
HEALTHY = {"acc": (84.0, 1.2), "tools": (2.6, 0.08), "escalation_share": (0.12, 0.015),
           "recall_at_5": (0.82, 0.015), "ndcg_at_5": (0.74, 0.015), "lexical_recall_at_5": (0.70, 0.015)}
# incident shift per field
EFFECT = {"retrieval_drift": {"recall_at_5": -0.20, "ndcg_at_5": -0.20, "lexical_recall_at_5": -0.14},
          "embedding_staleness": {"recall_at_5": -0.22, "ndcg_at_5": -0.12},
          "behavior_shift": {"escalation_share": 0.20, "tools": 0.9, "acc": -9.0}}


def _rng(participant_id: str, *salt: str) -> random.Random:
    return random.Random(int(hashlib.sha256("|".join((participant_id,) + salt).encode()).hexdigest()[:16], 16))


def variant(participant_id: str) -> int:
    return int(hashlib.sha256(participant_id.encode()).hexdigest(), 16) % 3


def _windows(participant_id: str, days: int) -> list[dict]:
    """Three non-overlapping windows, one per type, each 3 to 5 days, one per third of the history."""
    rng, seg = _rng(participant_id, "windows"), days // 3
    out = []
    for i, typ in enumerate(ORDERS[variant(participant_id)]):
        length = rng.randint(3, 5)
        first = rng.randint(2, max(2, seg - length - 1))
        out.append({"type": typ, "signal": SIGNAL[typ], "start_day": i * seg + first, "days": length})
    return out


def history(participant_id: str, now: datetime, days: int = 30, runs_per_day: int = 3, healthy: bool = False, night_type: str | None = None) -> dict:
    """Records (oldest first), a change log and the key. Day 0 is `days` days before the midnight before `now`;
    the last run is on the day before that midnight. runs_per_day is 1 to 3 (shift hours 06, 14, 22 UTC).
    healthy=True gives the same series with no degradation windows, change log or key (the capstone: only last night is bad).
    night_type (a degradation type) adds one more record, label `canary-night`: last night's 06:00 canary run, with that type's effect on every
    series (`now` minus five minutes when 06:00 UTC has not come yet). The capstone's monitor reads this stream."""
    if not 1 <= runs_per_day <= len(SHIFT_HOURS):
        raise ValueError("runs_per_day is 1 to 3")
    midnight = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    day0 = midnight - timedelta(days=days)
    wins = [] if healthy else _windows(participant_id, days)
    rng = _rng(participant_id, "values")
    records = []
    for d in range(days):
        w = next((w for w in wins if w["start_day"] <= d < w["start_day"] + w["days"]), None)
        for k in range(runs_per_day):
            vals = {}
            for f, (mean, sd) in HEALTHY.items():
                shift = EFFECT[w["type"]].get(f, 0.0) if w else 0.0
                vals[f] = mean + shift + rng.gauss(0, sd)
            cats = {c: round(min(100.0, max(0.0, vals["acc"] + rng.gauss(0, 2.5))), 1) for c in CATEGORIES}
            at = day0 + timedelta(days=d, hours=SHIFT_HOURS[k])
            records.append({
                "@timestamp": at.strftime("%Y-%m-%dT%H:%M:%S.000Z"), "run_label": f"canary-seed-{d:02d}-{k}",
                "testset_version": "canary-v1", "provided": True, "questions": 8,
                "routing_accuracy_overall": round(min(100.0, max(0.0, vals["acc"])), 1), "routing_accuracy": cats,
                "tool_calls_per_question": round(max(0.5, vals["tools"]), 2),
                "escalation_share": round(min(1.0, max(0.0, vals["escalation_share"])), 3),
                "retrieval": {"recall_at_5": round(min(1.0, max(0.0, vals["recall_at_5"])), 3),
                              "ndcg_at_5": round(min(1.0, max(0.0, vals["ndcg_at_5"])), 3),
                              "lexical_recall_at_5": round(min(1.0, max(0.0, vals["lexical_recall_at_5"])), 3)}})
    if night_type:
        nrng = _rng(participant_id, "night")
        vals = {f: mean + EFFECT[night_type].get(f, 0.0) + nrng.gauss(0, sd) for f, (mean, sd) in HEALTHY.items()}
        cats = {c: round(min(100.0, max(0.0, vals["acc"] + nrng.gauss(0, 2.5))), 1) for c in CATEGORIES}
        at = min(midnight + timedelta(hours=SHIFT_HOURS[0]), now.astimezone(timezone.utc) - timedelta(minutes=5))
        records.append({
            "@timestamp": at.strftime("%Y-%m-%dT%H:%M:%S.000Z"), "run_label": "canary-night",
            "testset_version": "canary-v1", "provided": True, "questions": 8,
            "routing_accuracy_overall": round(min(100.0, max(0.0, vals["acc"])), 1), "routing_accuracy": cats,
            "tool_calls_per_question": round(max(0.5, vals["tools"]), 2),
            "escalation_share": round(min(1.0, max(0.0, vals["escalation_share"])), 3),
            "retrieval": {"recall_at_5": round(min(1.0, max(0.0, vals["recall_at_5"])), 3),
                          "ndcg_at_5": round(min(1.0, max(0.0, vals["ndcg_at_5"])), 3),
                          "lexical_recall_at_5": round(min(1.0, max(0.0, vals["lexical_recall_at_5"])), 3)}})
    log, key = [], []
    crng = _rng(participant_id, "log")
    for w in wins:
        at = day0 + timedelta(days=w["start_day"], hours=SHIFT_HOURS[0] - crng.randint(1, 3))  # just before the first affected run
        cid = f"chg-{hashlib.sha256((participant_id + w['type']).encode()).hexdigest()[:8]}"
        log.append({"at": _iso(at), "kind": CHANGE_KIND[w["type"]], "object": _OBJECT[w["type"]],
                    "before": "previous", "after": "current", "change_id": cid, "actor": "cortex-ops", "cause": True})
        dat = at + timedelta(hours=crng.choice((-9, -5, 3)))  # a decoy closer to some incident than a quiet gap
        log.append({"at": _iso(dat), "kind": DECOY_KIND[w["type"]], "object": "cortex-misc", "before": "a", "after": "b",
                    "change_id": f"chg-{hashlib.sha256((participant_id + 'd' + w['type']).encode()).hexdigest()[:8]}",
                    "actor": "cortex-ops", "cause": False})
        if w["type"] == "embedding_staleness":  # the failure-first story: a model pin inside the staleness window
            pin = day0 + timedelta(days=w["start_day"] + 1, hours=SHIFT_HOURS[1])
            log.append({"at": _iso(pin), "kind": "model_pin", "object": "tina-compliance", "before": "m-old", "after": "m-new",
                        "change_id": f"chg-{hashlib.sha256((participant_id + 'pin').encode()).hexdigest()[:8]}",
                        "actor": "cortex-ops", "cause": False})
        key.append({"type": w["type"], "signal": w["signal"], "change_point_date": (day0 + timedelta(days=w["start_day"])).date().isoformat(),
                    "end_date": (day0 + timedelta(days=w["start_day"] + w["days"])).date().isoformat(), "cause_change_id": cid})
    log.sort(key=lambda e: e["at"])
    return {"records": records, "change_log": log, "key": key}


_OBJECT = {"retrieval_drift": "cortex-policies", "embedding_staleness": "cortex-policies-v2", "behavior_shift": "cortex.escalate"}


def _iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def series(records: list[dict], field: str) -> list[tuple[str, float]]:
    """(timestamp, value) per run for a field; `retrieval.recall_at_5` style paths read the nested block."""
    out = []
    for r in records:
        v: object = r
        for p in field.split("."):
            v = v[p]
        out.append((r["@timestamp"], v))
    return out


def find_step(values: list[float], width: int = 3) -> int:
    """The index where the earliest large step begins: the gap between the means of `width` values after and
    before each split, the first split run whose gap is at least 60 percent of the largest, at its peak."""
    gaps = {i: abs(sum(values[i:i + width]) / width - sum(values[i - width:i]) / width)
            for i in range(width, len(values) - width + 1)}
    if not gaps:
        return 0
    cut = 0.6 * max(gaps.values())
    first = min(i for i, g in gaps.items() if g >= cut)
    run = [first]
    while run[-1] + 1 in gaps and gaps[run[-1] + 1] >= cut:
        run.append(run[-1] + 1)
    return max(run, key=lambda i: gaps[i])
