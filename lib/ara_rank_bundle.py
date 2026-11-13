"""ara_rank_bundle.py - the 5.3 _rank_eval bundle and its cross-check (25 section 4, B1).

Elasticsearch scores one metric per _rank_eval call, so the bundle is three request bodies over the same
requests: precision@5, recall@5 and DCG@5 normalised, all with ignore_unlabeled false (an unlabeled hit counts
as not relevant). The queries run against the stored template; the cross-check recomputes the three metrics
from the hits each response reports, with ara_metrics.rank_eval_at_k, and compares within a tolerance.

    validate_labels(labelled)                     problems, empty when the labelled set can be sent
    build_bundle(labelled, template_id, ...)      {"index", "bodies": {metric: body}}
    retrieved_from(response)                      request id -> hit ids in rank order
    cross_check(responses, labelled, tol=0.005)   per-metric (reported, computed, ok) and an overall flag

labelled: [{"question_id", "query_text", "relevant_ids": [...]}] (the learner's labels). Standard library only.
"""
from __future__ import annotations

from typing import Any

from ara_metrics import rank_eval_at_k

K = 5
INDEX = "cortex-policies"
TEMPLATE_ID = "cortex-policy-retrieval"
TOLERANCE = 0.005
# stored template, hybrid form (25 section 4); kept here for the setup and for the tests that pin it
TEMPLATE_SOURCE = {"retriever": {"rrf": {"retrievers": [
    {"standard": {"query": {"match": {"body_text": "{{query_string}}"}}}},
    {"standard": {"query": {"semantic": {"field": "body", "query": "{{query_string}}"}}}}],
    "rank_window_size": 20}}, "size": 5, "_source": False}
METRICS = {  # bundle key -> (metric name in the body, parameters, key in ara_metrics.rank_eval_at_k)
    "precision_at_5": ("precision", {"k": K, "relevant_rating_threshold": 1, "ignore_unlabeled": False}, "precision_at_k"),
    "recall_at_5": ("recall", {"k": K, "relevant_rating_threshold": 1}, "recall_at_k"),
    "dcg_at_5": ("dcg", {"k": K, "normalize": True}, "ndcg_at_k"),
}


def validate_labels(labelled: list[dict]) -> list[str]:
    out = []
    if not labelled:
        return ["No labelled questions."]
    seen = set()
    for q in labelled:
        qid = q.get("question_id")
        if not qid or qid in seen:
            out.append(f"Question id {qid!r} is missing or repeated.")
        seen.add(qid)
        if not str(q.get("query_text") or "").strip():
            out.append(f"{qid}: no query text.")
        rel = q.get("relevant_ids")
        if not isinstance(rel, list) or not rel or not all(isinstance(r, str) and r for r in rel):
            out.append(f"{qid}: needs at least one relevant document id.")
    return out


def build_bundle(labelled: list[dict], template_id: str = TEMPLATE_ID, index: str = INDEX) -> dict:
    """The three _rank_eval bodies for POST {index}/_rank_eval. The template is the stored one, referenced
    by id; each question is one request whose ratings give rating 1 to every labelled id. Raises ValueError
    naming the problems when the labelled set is not sendable."""
    problems = validate_labels(labelled)
    if problems:
        raise ValueError(" ".join(problems))
    requests = [{"id": q["question_id"], "template_id": template_id, "params": {"query_string": q["query_text"]},
                 "ratings": [{"_index": index, "_id": d, "rating": 1} for d in dict.fromkeys(q["relevant_ids"])]}
                for q in labelled]
    templates = [{"id": template_id, "template": {"id": template_id}}]
    bodies = {key: {"templates": templates, "requests": requests, "metric": {name: dict(params)}}
              for key, (name, params, _) in METRICS.items()}
    return {"index": index, "bodies": bodies}


def retrieved_from(response: dict) -> dict:
    """request id -> hit ids in rank order, from a _rank_eval response's details."""
    out = {}
    for rid, d in ((response or {}).get("details") or {}).items():
        out[rid] = [h["hit"]["_id"] for h in d.get("hits") or [] if isinstance(h, dict) and (h.get("hit") or {}).get("_id")]
    return out


def cross_check(responses: dict, labelled: list[dict], tol: float = TOLERANCE) -> dict:
    """responses: bundle key -> the _rank_eval response to that body. For each metric, compare the reported
    metric_score with the one rank_eval_at_k computes from that response's own hits and the same labels.
    Returns {"ok", "metrics": {key: {"reported", "computed", "diff", "ok"}}, "missing": [keys]}; a missing or
    malformed response is not ok."""
    relevant = {q["question_id"]: set(q["relevant_ids"]) for q in labelled}
    metrics, missing = {}, []
    for key, (_, _, field) in METRICS.items():
        resp = responses.get(key)
        score = (resp or {}).get("metric_score") if isinstance(resp, dict) else None
        if not isinstance(score, (int, float)) or not (resp or {}).get("details"):
            missing.append(key)
            continue
        computed = rank_eval_at_k(retrieved_from(resp), relevant, K)[field]
        metrics[key] = {"reported": float(score), "computed": computed, "diff": abs(score - computed),
                        "ok": abs(score - computed) <= tol + 1e-12}
    return {"ok": not missing and all(m["ok"] for m in metrics.values()), "metrics": metrics, "missing": missing}
