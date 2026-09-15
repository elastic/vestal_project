"""
ara_pack.py — context packing utilities for ARA M3 tracks.

M3 pedagogical purpose:
  After retrieval, learners must fit retrieved passages into the LLM's context
  window without losing critical content.  This module provides the three
  strategies explored in track 3.3:

    rerank_top_n      — pick the best-N passages by semantic relevance
    summarize_first   — compress each passage before packing
    pack_context      — the pluggable entry point learners complete

The pluggable function is `pack_context`.  The reference implementation here
shows how strategies compose; learners swap it out with their own.

Route B only: all LLM calls go through the Elasticsearch _inference API.
No ARA_MODEL_FAST/STRONG. No hardcoded model names.
"""

from __future__ import annotations

import os
from typing import Any

from ara_metrics import token_count
from tina.client import es_client


# ── Strategy 1: Rerank ────────────────────────────────────────────────────────

def rerank_top_n(
    results: list[dict],
    query: str,
    n: int,
    rerank_id: str,
) -> list[dict]:
    """Rerank `results` against `query` using the EIS reranker `rerank_id`.

    M3 pedagogical purpose:
      Track 3.3 introduces the idea that retrieved order is not always the best
      order for the context window.  Learners see that a reranker can surface
      the most relevant passages regardless of BM25 or dense-vector rank.

    Each result dict must have a ``text`` field (or ``body`` field as fallback).
    Returns the top-n results in ranked order, each with an added
    ``rerank_score`` field.  Uses the Elasticsearch _inference API.

    Args:
        results:   Retrieved passage dicts (must contain ``text`` or ``body``).
        query:     The user query to score relevance against.
        n:         Maximum number of results to return after reranking.
        rerank_id: EIS inference endpoint id for the reranker model.

    Returns:
        List of up to *n* result dicts in descending rerank_score order.
    """
    if not results:
        return []

    es = es_client()

    # Build the passage list expected by the inference rerank API
    input_texts = [r.get("text") or r.get("body", "") for r in results]

    resp = es.inference.inference(
        inference_id=rerank_id,
        body={
            "query": query,
            "input": input_texts,
        },
    )

    # resp["rerank"] is a list of {"index": int, "relevance_score": float}
    rerank_entries: list[dict[str, Any]] = resp.get("rerank", [])
    ranked = sorted(rerank_entries, key=lambda x: x["relevance_score"], reverse=True)[:n]

    annotated = []
    for entry in ranked:
        orig = dict(results[entry["index"]])
        orig["rerank_score"] = entry["relevance_score"]
        annotated.append(orig)

    return annotated


# ── Strategy 2: Summarize first ───────────────────────────────────────────────

def summarize_first(
    results: list[dict],
    query: str,
    completion_id: str,
    per_doc_budget: int,
) -> list[dict]:
    """Summarize each result's text to ``per_doc_budget`` tokens before packing.

    M3 pedagogical purpose:
      Rather than truncating passages arbitrarily, learners learn to compress
      each one in a query-focused way.  This keeps key facts while shrinking
      total context size — a real production pattern for long-document RAG.

    Calls the EIS completion endpoint ``completion_id`` with a prompt asking for
    a summary focused on the query, in at most ``per_doc_budget`` tokens.
    Returns the results list with each result's ``body`` replaced by the summary.
    Temperature 0 (deterministic output for reproducibility in graded labs).

    Args:
        results:         Retrieved passage dicts (``text`` or ``body`` field).
        query:           The user query — summary should stay relevant to it.
        completion_id:   EIS inference endpoint id for the completion model.
        per_doc_budget:  Approximate token budget per summarized passage.

    Returns:
        New list of result dicts with ``body`` replaced by the summary text.
    """
    if not results:
        return []

    es = es_client()
    out = []

    for r in results:
        source_text = r.get("text") or r.get("body", "")
        prompt = (
            f"Summarize the following passage in at most {per_doc_budget} tokens, "
            f"focusing only on information relevant to this question: {query}\n\n"
            f"Passage:\n{source_text}\n\nSummary:"
        )
        try:
            resp = es.inference.inference(
                inference_id=completion_id,
                body={
                    "input": prompt,
                    "task_settings": {"temperature": 0},
                },
            )
            summary = resp["completion"][0]["result"]
        except Exception as exc:
            print(f"[ara_pack.summarize_first] warning: completion failed, using original text. {exc}")
            summary = source_text

        new_r = dict(r)
        new_r["body"] = summary
        out.append(new_r)

    return out


# ── Strategy 3: pack_context (pluggable) ──────────────────────────────────────

def pack_context(
    results: list[dict],
    query: str,
    budget: int,
    strategy: str,
) -> str:
    """Pack retrieved results into a context string within ``budget`` tokens.

    M3 pedagogical purpose:
      This is THE function learners replace in track 3.3 (the capstone
      pluggable slot).  The reference implementation ships two strategies;
      learners are expected to implement at least one correctly.

      ``strategy`` values:
        ``'rerank_top_n'``    — rerank, then concatenate passages that fit.
        ``'summarize_first'`` — summarize each passage, then concatenate until
                                budget is reached.

    Uses ``ara_metrics.token_count`` to count tokens, so the budget check is
    consistent with how check scripts measure context length.

    Args:
        results:  Retrieved passage dicts (``text`` or ``body`` field).
        query:    The original user query.
        budget:   Maximum total token count for the returned context string.
        strategy: Which packing strategy to apply.

    Returns:
        A single string containing the packed context, newline-separated.
    """
    completion_id = os.environ.get("ARA_INFERENCE_COMPLETION_ID", "cortex-generation")
    rerank_id = os.environ.get("ARA_RERANK_ID", "")  # spec 06 §1: ARA_RERANK_ID

    if strategy == "rerank_top_n":
        if not rerank_id:
            raise EnvironmentError(
                "ARA_RERANK_ID must be set to use strategy 'rerank_top_n'."
            )
        # Conservative estimate: start with all results, rerank, take top-n=len
        ranked = rerank_top_n(results, query, n=len(results), rerank_id=rerank_id)
        packed_parts: list[str] = []
        running_tokens = 0
        for r in ranked:
            text = r.get("body") or r.get("text", "")
            t = token_count(text)
            if running_tokens + t > budget:
                break
            packed_parts.append(text)
            running_tokens += t
        return "\n\n".join(packed_parts)

    elif strategy == "summarize_first":
        # Determine per-doc budget: split evenly across results, leave head room
        n = max(len(results), 1)
        per_doc = max(int(budget / n * 0.9), 50)  # 10 % head-room per doc
        summarized = summarize_first(results, query, completion_id, per_doc)
        packed_parts = []
        running_tokens = 0
        for r in summarized:
            text = r.get("body") or r.get("text", "")
            t = token_count(text)
            if running_tokens + t > budget:
                break
            packed_parts.append(text)
            running_tokens += t
        return "\n\n".join(packed_parts)

    else:
        raise ValueError(
            f"Unknown strategy '{strategy}'. "
            "Supported values: 'rerank_top_n', 'summarize_first'."
        )
