"""Offline tests for ara_corpus.py and the committed M5 corpus (25 section 8.2)."""
from __future__ import annotations

import importlib.util
import json
import pathlib
import re
import sys

LIB = pathlib.Path(__file__).resolve().parent
ROOT = LIB.parent
sys.path.insert(0, str(LIB))

import ara_corpus as C  # noqa: E402

spec = importlib.util.spec_from_file_location("gen_m5_corpus", ROOT / "scripts/gen_m5_corpus.py")
GEN = importlib.util.module_from_spec(spec)
spec.loader.exec_module(GEN)


class FakeES:
    def __init__(self):
        self.docs, self.calls = {}, []

    def request(self, method, path, body=None):
        self.calls.append((method, path))
        ix = path.strip("/").split("/")[0].split("?")[0]
        if method == "DELETE":
            self.docs.pop(ix, None)
            return 200, {}
        if method == "PUT":
            self.docs[ix] = {}
            return 200, {"acknowledged": True}
        if path.endswith("/_count"):
            return 200, {"count": len(self.docs[ix])}
        return 200, {}

    def request_ndjson(self, method, path, ndjson):
        lines = ndjson.splitlines()
        for a, d in zip(lines[::2], lines[1::2]):
            meta = json.loads(a)["index"]
            self.docs[meta["_index"]][meta["_id"]] = json.loads(d)
        return 200, {"errors": False, "items": []}


def test_committed_corpus_is_current_and_planted_as_the_spec_says():
    built = GEN.build()
    for name, text in built.items():
        assert (ROOT / "data/ara-m5" / name).read_text() == text, f"rebuild {name}"
    cases = [json.loads(x) for x in built["cortex-cases.ndjson"].splitlines()]
    sars = [json.loads(x) for x in built["cortex-sar-narratives.ndjson"].splitlines()]
    assert len(cases) == 120 and len(sars) == 40
    tins = [d["subject_tin"] for d in cases + sars]
    assert len(set(tins)) == 160 and all(re.fullmatch(r"9\d\d-\d\d-\d{4}", t) for t in tins)
    assert not any(k.startswith("gold") or k == "questions" for d in cases + sars for k in d)
    # 25 section 2, B2: structuring cases are 16 for first-line (low, medium) and 24 for the investigator
    st = [d for d in cases if d["case_type"] == "structuring"]
    assert len(st) == 24 and sum(d["risk_tier"] in ("low", "medium") for d in st) == 16


def test_load_with_and_without_identifier_fields():
    es = FakeES()
    n = C.load_corpus(es, ROOT, identifiers=False, log=lambda *_: None)
    assert n == {"cortex-cases": 120, "cortex-sar-narratives": 40}
    case = es.docs["cortex-cases"]["case-structuring-001"]
    assert "subject_tin" not in case and case["body_text"] == case["body"]
    C.load_corpus(es, ROOT, identifiers=True, log=lambda *_: None)
    assert es.docs["cortex-sar-narratives"]["sar-001"]["subject_tin"].startswith("9")
    mapping = json.loads((ROOT / "data/ara-m5/mappings/cortex-cases.json").read_text())["mappings"]["properties"]
    assert all(mapping[f]["type"] == "keyword" for f in ("case_type", "risk_tier", *C.IDENTIFIERS))


if __name__ == "__main__":
    for k, fn in sorted(globals().items()):
        if k.startswith("test_"):
            fn()
            print(f"  ok    {k}")
