"""Pack writing, verification and loading (28 section 8.5), over a fake bulk endpoint."""
import importlib.util
import json
import pathlib
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ara_history as H  # noqa: E402
import ara_pack_cli as C  # noqa: E402
import ara_tracepack as T  # noqa: E402

spec = importlib.util.spec_from_file_location("ara_packs_main", pathlib.Path(__file__).resolve().parent / "ara-packs.py")
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)
NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)


def spans(n_traces=3):
    out = []
    for t in range(n_traces):
        tid = f"{t + 1:032x}"
        base = f"2026-10-{10 + t:02d}T09:00:00.000Z"
        out.append({"trace_id": tid, "span_id": f"{t * 10 + 1:016x}", "name": "invoke_agent Tina", "@timestamp": base, "duration": 5_000_000_000,
                    "attributes": {"gen_ai.conversation.id": f"conv-{t}"}})
        out.append({"trace_id": tid, "span_id": f"{t * 10 + 2:016x}", "parent_span_id": f"{t * 10 + 1:016x}", "name": "execute_tool cortex.policy_search",
                    "@timestamp": base, "duration": 1_000_000_000, "attributes": {"gen_ai.conversation.id": f"conv-{t}"}})
    return out


class FakeES:
    def __init__(self, fail=False):
        self.docs, self.fail = {}, fail

    def request_ndjson(self, method, path, text):
        lines = text.strip().split("\n")
        items = []
        for a, d in zip(lines[::2], lines[1::2]):
            act = json.loads(a)["create"]
            if self.fail:
                items.append({"create": {"status": 400, "error": {"reason": "mapping"}}})
            elif act["_id"] in self.docs:
                items.append({"create": {"status": 409}})
            else:
                self.docs[act["_id"]] = json.loads(d); items.append({"create": {"status": 201}})
        return 200, {"errors": self.fail, "items": items}


def test_write_is_deterministic_and_verifies(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    m1, m2 = C.write_pack(spans(), a, "T-A", part_size=4), C.write_pack(spans(), b, "T-A", part_size=4)
    assert m1 == m2 and m1["spans"] == 6 and sorted(m1["files"]) == ["part-000.ndjson.gz", "part-001.ndjson.gz"]
    assert C.verify(a, m1) == [] and json.loads((a / "manifest.json").read_text()) == m1
    (a / "part-001.ndjson.gz").write_bytes(b"tampered")
    assert any("hash mismatch" in p for p in C.verify(a, m1))


def test_load_retimes_remaps_the_key_and_is_idempotent(tmp_path):
    m = C.write_pack(spans(), tmp_path, "T-A")
    key = {"failing_span_id": f"{2:016x}", "costly_span_id": f"{12:016x}", "costly_input_tokens": 1234}
    es = FakeES()
    out = C.load(tmp_path, m, es, NOW, key, salt="sbx1")
    assert out["created"] == 6 and out["already_loaded"] == 0 and len(es.docs) == 6
    assert out["key"]["failing_span_id"] != key["failing_span_id"] and out["key"]["costly_input_tokens"] == 1234
    new_ids = {d["span_id"] for d in es.docs.values()}
    assert out["key"]["failing_span_id"] in new_ids and out["key"]["costly_span_id"] in new_ids
    end = max(H.span_end(d) for d in es.docs.values())
    assert abs((NOW - end).total_seconds() - 3600) < 1
    again = C.load(tmp_path, m, es, NOW, key, salt="sbx1")
    assert again["created"] == 0 and again["already_loaded"] == 6 and again["key"] == out["key"]
    other = C.load(tmp_path, m, FakeES(), NOW, key, salt="sbx2")
    assert other["key"]["failing_span_id"] != out["key"]["failing_span_id"]


def test_load_refuses_a_bad_pack_and_a_rejected_bulk(tmp_path):
    m = C.write_pack(spans(), tmp_path, "T-A")
    es = FakeES()
    try:
        C.load(tmp_path, dict(m, spans=7), es, NOW)
        raise AssertionError("expected PackError")
    except C.PackError as e:
        assert "span count" in str(e)
    assert es.docs == {}
    try:
        C.load(tmp_path, m, FakeES(fail=True), NOW, salt="s")
        raise AssertionError("expected PackError")
    except C.PackError as e:
        assert "rejected" in str(e)
    bad = spans(); bad[1]["parent_span_id"] = "f" * 16
    m2 = C.write_pack(bad, tmp_path / "bad", "T-X")
    assert any("parent" in p for p in C.verify(tmp_path / "bad", m2))


def test_cli_write_verify_load(tmp_path, capsys):
    f = tmp_path / "spans.ndjson"
    f.write_text("\n".join(json.dumps(s) for s in spans()) + "\n")
    assert M.main(["write", str(f), str(tmp_path / "p"), "--pack", "T-A"]) == 0
    assert M.main(["verify", str(tmp_path / "p"), str(tmp_path / "p" / "manifest.json")]) == 0
    (tmp_path / "key.json").write_text(json.dumps({"failing_span_id": f"{2:016x}"}))
    assert M.main(["load", str(tmp_path / "p"), str(tmp_path / "p" / "manifest.json"), "--salt", "s", "--key", str(tmp_path / "key.json"),
                   "--out-key", str(tmp_path / "out.json")], es=FakeES(), now=NOW) == 0
    assert json.loads((tmp_path / "out.json").read_text())["failing_span_id"] != f"{2:016x}"
    assert "loaded 6 spans" in capsys.readouterr().out
    (tmp_path / "p" / "part-000.ndjson.gz").write_bytes(b"x")
    assert M.main(["verify", str(tmp_path / "p"), str(tmp_path / "p" / "manifest.json")]) == 1
    assert M.main(["verify", str(tmp_path / "none"), str(tmp_path / "nope.json")]) == 1
