"""
rag.py — retrieve-and-generate via Elasticsearch + EIS completion (route B).

rag_answer retrieves from an alias using a pluggable retriever template, then
calls the cortex-generation endpoint to produce a grounded answer. Both the
retrieval results and the generation are recorded in the trace.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


_DEFAULT_RETRIEVER = {
    "retriever": {
        "standard": {
            "query": {"semantic": {"field": "body", "query": "{query_text}"}}
        }
    }
}


def load_retriever(path: str | None = None) -> dict:
    """Load a retriever template from a JSON file, or return the default dense retriever."""
    if path and Path(path).exists():
        return json.loads(Path(path).read_text())
    return _DEFAULT_RETRIEVER


def rag_answer(
    es,
    query: str,
    alias: str,
    completion_id: str | None = None,
    retriever_path: str | None = None,
    n: int = 5,
    trace_dir: str | None = None,
) -> dict:
    """Retrieve from alias and generate a grounded answer through route B (EIS completion).

    Returns:
      {
        "answer": str,
        "retrieved": [{"doc_id": str, "title": str, "body": str}, ...],
        "completion_id": str,
        "latency_ms": {"retrieval": float, "generation": float},
        "query": str,
      }

    Side effect: if trace_dir is set, appends a JSON line to
    {trace_dir}/rag_traces.jsonl so notebooks can inspect the trace.
    """
    eid = completion_id or os.environ.get("ARA_INFERENCE_COMPLETION_ID")
    if not eid:
        raise EnvironmentError(
            "ARA_INFERENCE_COMPLETION_ID is not set and completion_id not supplied"
        )

    retriever = load_retriever(retriever_path)

    # ── Retrieval ──────────────────────────────────────────────────────────────
    body_str = json.dumps(retriever).replace("{query_text}", query)
    body = json.loads(body_str)

    t0 = time.perf_counter()
    resp = es.search(index=alias, body=body, size=n)
    retrieval_ms = (time.perf_counter() - t0) * 1000

    retrieved = []
    context_parts = []
    for hit in resp["hits"]["hits"]:
        src = hit.get("_source", {})
        doc_id = src.get("doc_id") or hit["_id"]
        title = src.get("title", "")
        body_text = src.get("body_text") or src.get("body", "")
        retrieved.append({"doc_id": doc_id, "title": title, "body": body_text})
        context_parts.append(f"[{doc_id}] {title}\n{body_text}")

    context = "\n\n---\n\n".join(context_parts)

    # ── Generation via route B ─────────────────────────────────────────────────
    prompt = (
        f"You are Tina, a compliance assistant at Cortex Bank and Trust. "
        f"Answer the analyst's question using only the provided documents. "
        f"Cite each document you use by its id in brackets, e.g. [policy-003].\n\n"
        f"Documents:\n{context}\n\n"
        f"Question: {query}\nAnswer:"
    )

    t1 = time.perf_counter()
    gen_resp = es.inference.inference(
        inference_id=eid,
        task_type="completion",
        body={"input": prompt, "task_settings": {"temperature": 0}},
    )
    generation_ms = (time.perf_counter() - t1) * 1000

    completions = gen_resp.get("completion", [])
    answer = completions[0].get("result", "") if completions else ""

    trace = {
        "query": query,
        "alias": alias,
        "completion_id": eid,
        "retrieved": retrieved,
        "answer": answer,
        "latency_ms": {"retrieval": round(retrieval_ms, 1), "generation": round(generation_ms, 1)},
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    if trace_dir:
        trace_path = Path(trace_dir) / "rag_traces.jsonl"
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        with open(trace_path, "a") as f:
            f.write(json.dumps(trace) + "\n")

    return trace
