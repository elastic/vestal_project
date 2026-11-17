"""Offline tests for ara_degrade.py."""
import pathlib
import statistics
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ara_degrade as D  # noqa: E402

NOW = datetime(2026, 11, 10, 9, 30, tzinfo=timezone.utc)


def test_deterministic_per_participant_and_different_across():
    assert D.history("abc123", NOW) == D.history("abc123", NOW)
    keys = {tuple((k["type"], k["change_point_date"]) for k in D.history(p, NOW)["key"]) for p in ("a1", "b2", "c3", "d4", "e5", "f6")}
    assert len(keys) >= 4


def test_shape_30_days_3_runs_and_key():
    h = D.history("abc123", NOW)
    r = h["records"]
    assert len(r) == 90 and r[0]["@timestamp"] == "2026-10-11T06:00:00.000Z" and r[-1]["@timestamp"] == "2026-11-09T22:00:00.000Z"
    assert [k["type"] for k in h["key"]] != [] and sorted(k["type"] for k in h["key"]) == ["behavior_shift", "embedding_staleness", "retrieval_drift"]
    assert all(r[i]["@timestamp"] < r[i + 1]["@timestamp"] for i in range(89))
    assert len(D.history("abc123", NOW, days=30, runs_per_day=1)["records"]) == 30
    for bad in (0, 4):
        try:
            D.history("x", NOW, runs_per_day=bad)
        except ValueError:
            continue
        raise AssertionError


def test_windows_do_not_overlap_and_are_3_to_5_days():
    for p in ("a", "b", "c", "d", "e", "f", "g", "h"):
        ws = sorted(D._windows(p, 30), key=lambda w: w["start_day"])
        assert all(3 <= w["days"] <= 5 for w in ws)
        assert all(a["start_day"] + a["days"] < b["start_day"] for a, b in zip(ws, ws[1:])) and ws[-1]["start_day"] + ws[-1]["days"] <= 30


def _inside(records, key):
    lo, hi = key["change_point_date"], key["end_date"]
    ins = [r for r in records if lo <= r["@timestamp"][:10] < hi]
    out = [r for r in records if not any(k["change_point_date"] <= r["@timestamp"][:10] < k["end_date"] for k in H["key"])]
    return ins, out


H = D.history("abc123", NOW)


def test_signatures_match_the_type():
    for k in H["key"]:
        ins, out = _inside(H["records"], k)
        m = lambda rs, f: statistics.mean(D.series(rs, f)[i][1] for i in range(len(rs)))
        d = lambda f: m(ins, f) - m(out, f)
        if k["type"] == "retrieval_drift":
            assert d("retrieval.recall_at_5") < -0.1 and d("retrieval.lexical_recall_at_5") < -0.08 and abs(d("tool_calls_per_question")) < 0.3
        elif k["type"] == "embedding_staleness":
            assert d("retrieval.recall_at_5") < -0.1 and abs(d("retrieval.lexical_recall_at_5")) < 0.03
        else:
            assert d("escalation_share") > 0.1 and d("tool_calls_per_question") > 0.5 and abs(d("retrieval.recall_at_5")) < 0.03


def test_a_step_finder_lands_on_the_key_date():
    for k in H["key"]:
        lo = k["change_point_date"]
        # from three days before the window to its end: only this incident's start is in view
        d0 = datetime.fromisoformat(lo) - timedelta(days=3)
        idx = [i for i, r in enumerate(H["records"]) if d0 <= datetime.fromisoformat(r["@timestamp"][:10]) < datetime.fromisoformat(k["end_date"])]
        sub = [H["records"][i] for i in idx]
        field = {"retrieval_drift": "retrieval.ndcg_at_5", "embedding_staleness": "retrieval.recall_at_5", "behavior_shift": "escalation_share"}[k["type"]]
        vals = [v for _, v in D.series(sub, field)]
        at = sub[D.find_step(vals)]["@timestamp"][:10]
        assert abs((datetime.fromisoformat(at) - datetime.fromisoformat(lo)).days) <= 1, (k["type"], at, lo)


def test_change_log_has_cause_decoys_and_the_model_pin_in_the_staleness_window():
    log = H["change_log"]
    causes = [e for e in log if e["cause"]]
    assert len(causes) == 3 and len(log) >= 7 and log == sorted(log, key=lambda e: e["at"])
    stale = next(k for k in H["key"] if k["type"] == "embedding_staleness")
    pins = [e for e in log if e["kind"] == "model_pin"]
    assert len(pins) == 1 and stale["change_point_date"] <= pins[0]["at"][:10] < stale["end_date"] and not pins[0]["cause"]
    assert {e["change_id"] for e in causes} == {k["cause_change_id"] for k in H["key"]}
    assert all(set(e) >= {"at", "kind", "object", "before", "after", "change_id"} for e in log)


def test_series_reads_nested_paths():
    s = D.series(H["records"][:2], "retrieval.ndcg_at_5")
    assert len(s) == 2 and isinstance(s[0][1], float)


def test_history_night_record_is_last_nights_canary_run_with_the_types_effect():
    from datetime import datetime, timezone
    import ara_degrade as D
    now = datetime(2026, 11, 13, 11, 45, tzinfo=timezone.utc)
    h = D.history("p", now, healthy=True, night_type="embedding_staleness")
    night, last_healthy = h["records"][-1], h["records"][-2]
    assert len(h["records"]) == 91 and night["run_label"] == "canary-night" and not h["key"] and not h["change_log"]
    assert night["@timestamp"] == "2026-11-13T06:00:00.000Z" and night["@timestamp"] > last_healthy["@timestamp"]
    assert night["retrieval"]["recall_at_5"] < 0.70 < 0.80 < last_healthy["retrieval"]["recall_at_5"] + 0.06   # the staleness effect, well past the noise
    early = D.history("p", datetime(2026, 11, 13, 2, 0, tzinfo=timezone.utc), healthy=True, night_type="behavior_shift")
    assert early["records"][-1]["@timestamp"] == "2026-11-13T01:55:00.000Z"   # 06:00 has not come yet
    assert len(D.history("p", now, healthy=True)["records"]) == 90
