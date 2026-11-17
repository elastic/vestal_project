"""Offline tests for ara_history.py."""
import json
import pathlib
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ara_history as H  # noqa: E402
import ara_trace as T  # noqa: E402
from test_ara_trace import round_a  # noqa: E402

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)


def test_retime_ends_n_days_before_now_and_keeps_offsets():
    src = round_a()
    out = H.retime(src, NOW, 35)
    assert H.set_end(out) == NOW - timedelta(days=35)
    off = lambda spans: [(T.start(s) - T.start(spans[0])) for s in spans]
    assert off(out) == off(src)
    assert [s["parent_span_id"] for s in out[1:]] == [s["parent_span_id"] for s in src[1:]]
    assert src[0]["@timestamp"].startswith("2026-11-01")  # the input is not mutated


def test_retime_is_deterministic_and_repeatable():
    assert H.retime(round_a(), NOW, 3) == H.retime(round_a(), NOW, 3)


def test_salt_remaps_every_id_consistently_including_the_key_map():
    src = round_a()
    out = H.retime(src, NOW, 2, salt="r1")
    by_id = {s["span_id"] for s in out}
    assert all(s.get("parent_span_id") in by_id for s in out if s.get("parent_span_id"))
    assert not ({s["span_id"] for s in src} & by_id) and {s["trace_id"] for s in out} != {"t1"}
    assert T.get(out[0], H.CONV) != "c-1" and len({T.get(s, H.CONV) for s in out if T.get(s, H.CONV)}) == 1
    m = H.id_map(src, "r1")
    assert out[0]["span_id"] == m["a0"] and H.retime(src, NOW, 2, salt="r2")[0]["span_id"] != out[0]["span_id"]
    assert len(m["t1"]) == 32 and len(m["a0"]) == 16 and len(m["c-1"]) == 36


def test_bulk_body_uses_create_with_stable_ids():
    docs = H.retime(round_a(), NOW, 1)
    body = H.bulk_body(docs, "traces-agent_builder.otel-default", "T-A")
    lines = body.strip().split("\n")
    assert len(lines) == 2 * len(docs) and body.endswith("\n")
    act = json.loads(lines[0])["create"]
    assert act["_index"] == "traces-agent_builder.otel-default" and len(act["_id"]) == 32
    assert body == H.bulk_body(H.retime(round_a(), NOW, 1), "traces-agent_builder.otel-default", "T-A")  # idempotent
    ids = [json.loads(lines[i])["create"]["_id"] for i in range(0, len(lines), 2)]
    assert len(set(ids)) == len(ids)
    assert H.doc_id("T-B", docs[0]) != H.doc_id("T-A", docs[0])
    assert json.loads(lines[1])["span_id"] == "a0"


def test_reload_is_a_no_op_not_an_error():
    resp = {"items": [{"create": {"status": 201}}, {"create": {"status": 409, "error": {"type": "version_conflict_engine_exception"}}},
                      {"create": {"status": 400, "error": {"type": "mapper_parsing_exception"}}}]}
    c, e, errs = H.bulk_result(resp)
    assert (c, e, len(errs)) == (1, 1, 1)


def test_place_rounds_and_schedule():
    ends = H.business_hour_ends(NOW, 21, 3, "T-A")
    assert ends == H.business_hour_ends(NOW, 21, 3, "T-A") and ends == sorted(ends)
    assert all(e.weekday() < 5 and 8 <= e.hour < 18 and e <= NOW for e in ends) and len(ends) >= 40
    out = H.place_rounds([round_a(), round_a()], ends[:2], salt="T-A")
    assert len({s["trace_id"] for s in out}) == 2 and len({s["span_id"] for s in out}) == 20
    assert H.set_end(out[:10]) == ends[0]
    try:
        H.place_rounds([round_a()], ends[:2])
    except ValueError:
        pass
    else:
        raise AssertionError


def test_verify_against_manifest():
    docs = round_a()
    import hashlib
    man = {"span_count": 10, "trace_count": 1,
           "sha256": hashlib.sha256("\n".join(sorted(s["span_id"] for s in docs)).encode()).hexdigest()}
    assert H.verify(docs, man) == []
    assert len(H.verify(docs[:-1], man)) == 2
