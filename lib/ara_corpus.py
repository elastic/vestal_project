"""ara_corpus.py - load M5's copy of the M3 corpus at provisioning (25 sections 8.2 and 8.3).

    from ara_security import ES, api_key_auth
    load_corpus(ES(es_url, api_key_auth(admin_key), timeout=300), "/opt/ara/src", identifiers=False)

ara-m4-end loads the fields M3 indexed (identifiers=False); the 5.1 start and later load the same
documents with subject_name, subject_account and subject_tin (identifiers=True). Mappings are the
committed ones in data/ara-m5/mappings/; body is semantic_text, as M3 indexed the corpus, with a
body_text copy for lexical search. Each index is recreated, so a re-run gives the same state.
"""
from __future__ import annotations

import json
import pathlib

from ara_embed_retry import post_docs

IDENTIFIERS = ("subject_name", "subject_account", "subject_tin")
INDICES = (("cortex-cases", "case_id", 20), ("cortex-sar-narratives", "sar_id", 4))  # (index, id field, bulk batch)


def documents(src: pathlib.Path, index: str, identifiers: bool) -> list[dict]:
    rows = [json.loads(line) for line in (src / "data/ara-m5" / f"{index}.ndjson").read_text().splitlines() if line.strip()]
    out = []
    for r in rows:
        doc = {k: v for k, v in r.items() if identifiers or k not in IDENTIFIERS}
        doc["body_text"] = r["body"]
        out.append(doc)
    return out


def load_index(es, src: pathlib.Path, index: str, id_field: str, batch: int, identifiers: bool, log=print) -> int:
    mapping = json.loads((src / "data/ara-m5/mappings" / f"{index}.json").read_text())
    code, body = es.request("DELETE", f"/{index}?ignore_unavailable=true")
    if code not in (200, 404):
        raise SystemExit(f"{index}: delete HTTP {code} {str(body)[:200]}")
    code, body = es.request("PUT", f"/{index}", mapping)
    if code != 200:
        raise SystemExit(f"{index}: create HTTP {code} {str(body)[:300]}")
    docs = documents(src, index, identifiers)
    # semantic_text runs inference inside the bulk request, so long SAR narratives go a few at a time; a document the embedding
    # endpoint refused (503, 429, timeout) is sent again a little later, only that one, under its fixed _id (ara_embed_retry)
    left = post_docs(es, index, docs, lambda d: d[id_field], batch=batch, log=log)
    if left:
        raise SystemExit(f"{index}: bulk {str(left[0][1])[:300]} ({len(left)} documents not accepted)")
    es.request("POST", f"/{index}/_refresh")
    code, body = es.request("GET", f"/{index}/_count")
    n = body.get("count") if code == 200 else None
    if n != len(docs):
        raise SystemExit(f"{index}: {n} documents after load, expected {len(docs)}")
    log(f"{index}: {n} documents{' with identifier fields' if identifiers else ''}")
    return n


def load_corpus(es, src: str | pathlib.Path, identifiers: bool, log=print) -> dict:
    src = pathlib.Path(src)
    return {ix: load_index(es, src, ix, idf, b, identifiers, log) for ix, idf, b in INDICES}
