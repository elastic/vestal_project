"""
ara_metrics.py — shared evaluation metrics for ARA tracks.

Used by both learner-facing dev tooling (notebooks) and private check scripts.
Same code path; no drift between what the learner sees and what the check grades.

All functions accept the Elasticsearch client and query templates from env vars.
No credentials, no Instruqt-specific paths appear here.
"""

from __future__ import annotations

import json
import math
import os
import statistics
import time
from typing import Any

# ── Elasticsearch client factory ──────────────────────────────────────────────

def es_client():
    """Build an Elasticsearch client from environment variables."""
    from elasticsearch import Elasticsearch
    url = os.environ["ES_URL"]
    api_key = os.environ["ES_API_KEY"]
    return Elasticsearch(url, api_key=api_key, request_timeout=30)


# ── Query runner ──────────────────────────────────────────────────────────────

def run_queries(
    es,
    index: str,
    queries: list[dict],
    k: int = 10,
    inference_id: str | None = None,
) -> list[dict]:
    """
    Run a list of evaluation queries against an Elasticsearch index.

    Each item in `queries` is:
      {"query_id": str, "query_text": str, "relevant_ids": list[str]}

    Returns a list of result dicts:
      {"query_id": str, "retrieved_ids": list[str], "latency_ms": float}
    """
    results = []
    for q in queries:
        body = _build_query(q["query_text"], k, inference_id)
        t0 = time.perf_counter()
        resp = es.search(index=index, body=body, size=k)
        latency_ms = (time.perf_counter() - t0) * 1000
        retrieved = [hit["_id"] for hit in resp["hits"]["hits"]]
        results.append({
            "query_id": q["query_id"],
            "retrieved_ids": retrieved,
            "latency_ms": latency_ms,
        })
    return results


def run_queries_with_template(
    es,
    index: str,
    queries: list[dict],
    query_template: dict,
    k: int = 10,
    n_passes: int = 1,
) -> list[dict]:
    """Run queries using a learner-supplied retriever or query template.

    Substitutes {query_text} in the serialized template. When the template
    contains a "retriever" key the body is sent as-is (ES 9.x retriever API);
    otherwise it is wrapped as {"query": ...}. Results include doc_id field
    from _source when present, falling back to _id.

    n_passes: repeat the full query set n times and take the median latency per
    query, for stable p50/p95 measurement.
    """
    all_results: dict[str, list] = {}  # query_id -> list of result dicts per pass

    for _ in range(n_passes):
        for q in queries:
            body_str = json.dumps(query_template).replace("{query_text}", q["query_text"])
            body = json.loads(body_str)
            if "retriever" not in body and "query" not in body:
                body = {"query": body}
            t0 = time.perf_counter()
            resp = es.search(index=index, body=body, size=k)
            latency_ms = (time.perf_counter() - t0) * 1000
            retrieved = [
                hit.get("_source", {}).get("doc_id") or hit["_id"]
                for hit in resp["hits"]["hits"]
            ]
            qid = q["query_id"]
            if qid not in all_results:
                all_results[qid] = []
            all_results[qid].append({"retrieved_ids": retrieved, "latency_ms": latency_ms})

    # Collapse passes: union retrieved (first pass), median latency
    results = []
    for q in queries:
        passes = all_results.get(q["query_id"], [])
        if not passes:
            continue
        retrieved = passes[0]["retrieved_ids"]
        lats = sorted(p["latency_ms"] for p in passes)
        median_lat = lats[len(lats) // 2]
        results.append({"query_id": q["query_id"], "retrieved_ids": retrieved, "latency_ms": median_lat})
    return results


# ── Retriever template builders ───────────────────────────────────────────────

def retriever_bm25(field: str = "body_text") -> dict:
    """BM25 (lexical) retriever template. {query_text} is substituted at run time."""
    return {"query": {"match": {field: "{query_text}"}}}


def retriever_dense(field: str = "body") -> dict:
    """Dense semantic retriever template using semantic_text field."""
    return {"retriever": {"standard": {"query": {"semantic": {"field": field, "query": "{query_text}"}}}}}


def retriever_hybrid_rrf(
    text_field: str = "body_text",
    semantic_field: str = "body",
    rank_window_size: int = 50,
    rank_constant: int = 60,
) -> dict:
    """Hybrid RRF retriever template combining BM25 and dense."""
    return {
        "retriever": {
            "rrf": {
                "retrievers": [
                    {"standard": {"query": {"match": {text_field: "{query_text}"}}}},
                    {"standard": {"query": {"semantic": {"field": semantic_field, "query": "{query_text}"}}}},
                ],
                "rank_window_size": rank_window_size,
                "rank_constant": rank_constant,
            }
        }
    }


def retriever_hybrid_rerank(
    rerank_id: str,
    text_field: str = "body_text",
    semantic_field: str = "body",
    rank_window_size: int = 50,
    rank_constant: int = 60,
) -> dict:
    """Hybrid with reranking on top of RRF."""
    return {
        "retriever": {
            "text_similarity_reranker": {
                "retriever": {
                    "rrf": {
                        "retrievers": [
                            {"standard": {"query": {"match": {text_field: "{query_text}"}}}},
                            {"standard": {"query": {"semantic": {"field": semantic_field, "query": "{query_text}"}}}},
                        ],
                        "rank_window_size": rank_window_size,
                        "rank_constant": rank_constant,
                    }
                },
                "field": semantic_field,
                "inference_id": rerank_id,
                "inference_text": "{query_text}",
            }
        }
    }


# ── HNSW memory budget ────────────────────────────────────────────────────────

def hnsw_budget(n_vectors: int, dims: int, m: int, quantization: str = "float32") -> int:
    """Estimate RAM bytes for an HNSW index.

    quantization: "float32" (4 bytes/dim), "int8" (1 byte/dim), "bbq" (~0.125 byte/dim).
    Graph overhead: approximately 2 * m * 4 bytes per vector (HNSW bidirectional links).
    """
    bytes_per_dim = {"float32": 4.0, "int8": 1.0, "bbq": 0.125}.get(quantization, 4.0)
    vector_bytes = n_vectors * dims * bytes_per_dim
    graph_bytes = n_vectors * m * 2 * 4  # 2m edges, 4 bytes each (pointer size)
    return int(vector_bytes + graph_bytes)


# ── Alias probe ───────────────────────────────────────────────────────────────

def probe_alias(
    es,
    alias: str,
    log_path: str,
    interval_ms: int = 500,
    duration_secs: int = 60,
    query: dict | None = None,
) -> None:
    """Query the alias every interval_ms for duration_secs and log results.

    Designed to run from a setup script (as a background subprocess) to verify
    atomic alias swap in track 2.3. Log lines are JSON: timestamp, success, empty, error.
    """
    import threading

    probe_query = query or {"query": {"match_all": {}}, "size": 1}
    results = []
    deadline = time.time() + duration_secs

    def _probe():
        while time.time() < deadline:
            ts = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
            try:
                resp = es.search(index=alias, body=probe_query)
                hits = resp["hits"]["total"]["value"]
                results.append({"ts": ts, "success": True, "empty": hits == 0, "error": None})
            except Exception as exc:
                results.append({"ts": ts, "success": False, "empty": False, "error": str(exc)})
            time.sleep(interval_ms / 1000)

    t = threading.Thread(target=_probe, daemon=True)
    t.start()
    t.join(timeout=duration_secs + 2)

    with open(log_path, "w") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")


# ── ES|QL helper ──────────────────────────────────────────────────────────────

def esql(es, query: str, params: dict | None = None) -> list[dict]:
    """Run an ES|QL query and return rows as a list of dicts keyed by column name.

    params: named query parameters substituted by ES|QL (? notation or named params).
    """
    body: dict[str, Any] = {"query": query}
    if params:
        body["params"] = params
    resp = es.esql.query(**body)
    columns = [c["name"] for c in resp.get("columns", [])]
    return [dict(zip(columns, row)) for row in resp.get("values", [])]


def _build_query(text: str, k: int, inference_id: str | None) -> dict:
    if inference_id:
        return {
            "query": {
                "semantic": {
                    "field": "body_semantic",
                    "query": text,
                }
            }
        }
    return {"query": {"match": {"body": text}}}


# ── Relevance metrics ─────────────────────────────────────────────────────────

def precision_at_k(results: list[dict], queries: list[dict], k: int = 10) -> float:
    """Macro-averaged precision@k over all queries."""
    relevance = {q["query_id"]: set(q["relevant_ids"]) for q in queries}
    scores = []
    for r in results:
        rel = relevance.get(r["query_id"], set())
        retrieved = r["retrieved_ids"][:k]
        hits = sum(1 for doc_id in retrieved if doc_id in rel)
        scores.append(hits / k)
    return statistics.mean(scores) if scores else 0.0


def recall_at_k(results: list[dict], queries: list[dict], k: int = 10) -> float:
    """Macro-averaged recall@k over all queries."""
    relevance = {q["query_id"]: set(q["relevant_ids"]) for q in queries}
    scores = []
    for r in results:
        rel = relevance.get(r["query_id"], set())
        if not rel:
            continue
        retrieved = r["retrieved_ids"][:k]
        hits = sum(1 for doc_id in retrieved if doc_id in rel)
        scores.append(hits / len(rel))
    return statistics.mean(scores) if scores else 0.0


def ndcg_at_k(results: list[dict], queries: list[dict], k: int = 10) -> float:
    """Macro-averaged nDCG@k. Relevance is binary (1 if in relevant_ids, 0 otherwise)."""
    relevance = {q["query_id"]: set(q["relevant_ids"]) for q in queries}
    scores = []
    for r in results:
        rel = relevance.get(r["query_id"], set())
        retrieved = r["retrieved_ids"][:k]
        dcg = sum(
            (1 / math.log2(i + 2)) for i, doc_id in enumerate(retrieved) if doc_id in rel
        )
        ideal_hits = min(len(rel), k)
        idcg = sum(1 / math.log2(i + 2) for i in range(ideal_hits))
        scores.append(dcg / idcg if idcg > 0 else 0.0)
    return statistics.mean(scores) if scores else 0.0


def mrr(results: list[dict], queries: list[dict]) -> float:
    """Mean reciprocal rank."""
    relevance = {q["query_id"]: set(q["relevant_ids"]) for q in queries}
    scores = []
    for r in results:
        rel = relevance.get(r["query_id"], set())
        rr = 0.0
        for i, doc_id in enumerate(r["retrieved_ids"]):
            if doc_id in rel:
                rr = 1.0 / (i + 1)
                break
        scores.append(rr)
    return statistics.mean(scores) if scores else 0.0


# ── Latency metrics ───────────────────────────────────────────────────────────

def p50(results: list[dict]) -> float:
    """Median latency in ms."""
    lats = [r["latency_ms"] for r in results]
    return statistics.median(lats) if lats else 0.0


def p95(results: list[dict]) -> float:
    """95th-percentile latency in ms."""
    lats = sorted(r["latency_ms"] for r in results)
    if not lats:
        return 0.0
    idx = max(0, int(math.ceil(0.95 * len(lats))) - 1)
    return lats[idx]


# ── Token counting ────────────────────────────────────────────────────────────

def count_tokens_approx(text: str) -> int:
    """Very rough token count (words * 1.3) — use only for sanity checks."""
    return int(len(text.split()) * 1.3)


def count_tokens_messages(messages: list[dict]) -> int:
    """Approximate token count across a list of OpenAI-style message dicts."""
    return sum(count_tokens_approx(m.get("content", "")) for m in messages)


# ── Evaluation set helpers ────────────────────────────────────────────────────

def load_eval_set(path: str) -> list[dict]:
    """Load a JSONL or JSON evaluation set from disk."""
    p = __import__("pathlib").Path(path)
    if p.suffix == ".jsonl":
        return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]
    return json.loads(p.read_text())


def run_full_eval(
    es,
    index: str,
    eval_set: list[dict],
    k: int = 10,
    inference_id: str | None = None,
) -> dict:
    """Run precision@k, recall@k, nDCG@k, MRR, p50, p95 in one call."""
    results = run_queries(es, index, eval_set, k=k, inference_id=inference_id)
    return {
        f"precision_at_{k}": precision_at_k(results, eval_set, k),
        f"recall_at_{k}": recall_at_k(results, eval_set, k),
        f"ndcg_at_{k}": ndcg_at_k(results, eval_set, k),
        "mrr": mrr(results, eval_set),
        "latency_p50_ms": p50(results),
        "latency_p95_ms": p95(results),
        "query_count": len(results),
    }
