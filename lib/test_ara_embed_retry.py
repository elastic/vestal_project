"""Offline tests for ara_embed_retry.py: a managed embedding endpoint that answers 503 for a while, against fakes."""
from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ara_embed_retry as R  # noqa: E402

BUSY = {"type": "inference_exception", "reason": "Exception when running inference id [.jina-embeddings-v5-text-small] on field [body]",
        "caused_by": {"type": "status_exception", "reason": "Received a server error status code for request from inference entity id "
                      "[.jina-embeddings-v5-text-small] status [503]. Error message: [Service temporarily unavailable]"}}
BAD_INPUT = {"type": "inference_exception", "reason": "x", "caused_by": {"type": "status_exception", "reason": "inference entity id [.j] status [400]. Error message: [too long]"}}
MAPPING = {"type": "mapper_parsing_exception", "reason": "failed to parse field [effective_date]"}


class Index:
    """The index as the fake cluster keeps it, by _id; `script` says what each send meets: a set of ids refused with an error."""
    def __init__(self, script):
        self.docs, self.sent, self.script = {}, [], list(script)

    def refuse(self, ids):
        refused = self.script.pop(0) if self.script else {}
        if isinstance(refused, Exception):
            return refused
        return {i: refused[i] for i in ids if i in refused}


class FakeHelpersBulk(Index):
    def __call__(self, es, actions, chunk_size, raise_on_error, request_timeout):
        assert raise_on_error is False and request_timeout == 300
        self.sent.append([a["_id"] for a in actions])
        refused = self.refuse(self.sent[-1])
        if isinstance(refused, Exception):
            raise refused
        errs = []
        for a in actions:
            if a["_id"] in refused:
                errs.append({"index": {"_id": a["_id"], "status": 400, "error": refused[a["_id"]], "data": a["_source"]}})
            else:
                self.docs[a["_id"]] = a["_source"]
        return len(actions) - len(errs), errs


class FakeES(Index):
    def __init__(self, script, whole=None):
        super().__init__(script)
        self.whole, self.queries = list(whole or []), []

    def request_ndjson(self, method, path, ops):
        self.queries.append(path)
        lines = [l for l in ops.splitlines() if l]
        ids = [__import__("json").loads(lines[i])["index"]["_id"] for i in range(0, len(lines), 2)]
        self.sent.append(ids)
        if self.whole:
            code = self.whole.pop(0)
            if code != 200:
                return code, {"error": "Service temporarily unavailable"}
        refused = self.refuse(ids)
        items = []
        for i, doc in zip(ids, [__import__("json").loads(lines[k]) for k in range(1, len(lines), 2)]):
            if i in refused:
                items.append({"index": {"_id": i, "status": 400, "error": refused[i]}})
            else:
                self.docs[i] = doc
                items.append({"index": {"_id": i, "status": 201}})
        return 200, {"errors": bool(refused), "items": items}


def actions(n):
    return [{"_index": "ix", "_id": f"d{i}", "_source": {"n": i}} for i in range(n)]


def run_bulk(index, n=6, **kw):
    sleeps = []
    out = R.bulk_resilient(None, actions(n), bulk=index, sleep=sleeps.append, log=lambda *_: None, **kw)
    return out, sleeps


def test_the_wait_is_the_seeder_ladder_then_sixty_seconds_for_450():
    assert R.LADDER[:3] == (15, 30, 45) and set(R.LADDER[3:]) == {60} and len(R.LADDER) == 9 and sum(R.LADDER) == 450


@pytest.mark.parametrize("err,expected", [
    (BUSY, True), ({"index": {"_id": "a", "status": 400, "error": BUSY}}, True), ({"status": 429, "error": {"type": "es_rejected_execution_exception"}}, True),
    ("bulk HTTP 503 Service temporarily unavailable", True), ("bulk HTTP 429 slow down", True), ("bulk HTTP 0 connection reset", True),
    (TimeoutError("read timed out"), True), (BAD_INPUT, False), (MAPPING, False), ("bulk HTTP 400 bad request", False),
    ({"index": {"_id": "a", "status": 400, "error": MAPPING, "data": {"body": "timeout unavailable status [503]"}}}, False)])
def test_what_counts_as_transient(err, expected):
    assert R.transient_error(err) is expected


def test_503_then_success_sends_the_refused_documents_again_with_the_same_ids_and_no_duplicates():
    ix = FakeHelpersBulk([{f"d{i}": BUSY for i in range(6)}])
    out, sleeps = run_bulk(ix)
    assert out == [] and sleeps == [15]
    assert ix.sent == [[f"d{i}" for i in range(6)]] * 2
    assert sorted(ix.docs) == [f"d{i}" for i in range(6)] and len(ix.docs) == 6


def test_only_the_refused_documents_are_sent_again():
    ix = FakeHelpersBulk([{"d1": BUSY, "d4": BUSY, "d5": BUSY}, {"d4": BUSY}])
    out, sleeps = run_bulk(ix)
    assert out == [] and sleeps == [15, 30]
    assert ix.sent == [["d0", "d1", "d2", "d3", "d4", "d5"], ["d1", "d4", "d5"], ["d4"]]
    assert sorted(ix.docs) == [f"d{i}" for i in range(6)]


def test_a_persistent_503_ends_after_the_ladder_with_the_errors_and_nothing_loaded():
    ix = FakeHelpersBulk([{f"d{i}": BUSY for i in range(3)}] * 20)
    out, sleeps = run_bulk(ix, n=3)
    assert len(out) == 3 and tuple(sleeps) == R.LADDER and len(ix.sent) == 10 and ix.docs == {}
    assert "503" in str(out[0])


def test_a_non_transient_error_ends_at_once_without_waiting():
    ix = FakeHelpersBulk([{"d2": MAPPING}])
    out, sleeps = run_bulk(ix)
    assert len(out) == 1 and sleeps == [] and len(ix.sent) == 1
    assert out[0]["index"]["_id"] == "d2"


def test_a_bad_input_inference_error_is_not_retried():
    out, sleeps = run_bulk(FakeHelpersBulk([{"d0": BAD_INPUT}]), n=2)
    assert len(out) == 1 and sleeps == []


def test_a_mix_of_transient_and_non_transient_ends_at_once():
    ix = FakeHelpersBulk([{"d0": BUSY, "d1": MAPPING}])
    out, sleeps = run_bulk(ix, n=3)
    assert len(out) == 2 and sleeps == [] and len(ix.sent) == 1


def test_a_transient_client_exception_is_retried_and_a_real_fault_is_raised():
    out, sleeps = run_bulk(FakeHelpersBulk([TimeoutError("read timed out"), {}]))
    assert out == [] and sleeps == [15]
    with pytest.raises(ValueError):
        run_bulk(FakeHelpersBulk([ValueError("not our problem")]))


def test_the_log_names_the_wait_and_the_count(capsys):
    ix = FakeHelpersBulk([{"d0": BUSY}])
    R.bulk_resilient(None, actions(2), bulk=ix, sleep=lambda s: None)
    out = capsys.readouterr().out
    assert "embedding service is busy (1 of 2 documents" in out and "15 s" in out and "retry 1 of 9" in out


def docs(n):
    return [{"id": f"p{i}", "body": "x"} for i in range(n)]


def post(es, n=5, batch=2, **kw):
    sleeps = []
    left = R.post_docs(es, "ix", docs(n), lambda d: d["id"], batch=batch, sleep=sleeps.append, log=lambda *_: None, **kw)
    return left, sleeps


def test_post_docs_a_whole_bulk_503_is_sent_again_and_lands_once():
    es = FakeES([], whole=[503, 502, 200])
    left, sleeps = post(es, n=2, batch=2)
    assert left == [] and sleeps == [15, 30] and sorted(es.docs) == ["p0", "p1"] and len(es.sent) == 3


def test_post_docs_item_errors_are_sent_again_alone_and_the_query_string_is_kept():
    es = FakeES([{"p1": BUSY}, {}, {"p3": BUSY}, {}, {}], whole=[])
    left, sleeps = post(es, query="?refresh=wait_for")
    assert left == [] and sleeps == [15, 15] and sorted(es.docs) == [f"p{i}" for i in range(5)]
    assert es.sent == [["p0", "p1"], ["p1"], ["p2", "p3"], ["p3"], ["p4"]]
    assert set(es.queries) == {"/_bulk?refresh=wait_for"}


def test_post_docs_a_persistent_503_stops_at_the_first_batch_and_returns_what_is_left():
    es = FakeES([{"p0": BUSY, "p1": BUSY}] * 20)
    left, sleeps = post(es)
    assert [d["id"] for d, _ in left] == ["p0", "p1"] and tuple(sleeps) == R.LADDER and es.docs == {}
    assert len(es.sent) == 10


def test_post_docs_a_mapping_error_ends_at_once():
    left, sleeps = post(FakeES([{"p0": MAPPING}]))
    assert [d["id"] for d, _ in left] == ["p0"] and sleeps == []
