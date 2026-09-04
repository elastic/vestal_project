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
) -> list[dict]:
    """Like run_queries but uses a learner-supplied query template dict.

    The template may contain {query_text} as a placeholder which is substituted.
    """
    results = []
    for q in queries:
        body_str = json.dumps(query_template).replace("{query_text}", q["query_text"])
        body = json.loads(body_str)
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
