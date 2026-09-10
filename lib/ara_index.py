"""
ara_index.py — corpus chunking, indexing, and reindexing utilities for ARA tracks.

Used by: challenge 01 provisioning scripts (via provision.sh) and learner notebooks.
Environment variables: ES_URL, ES_API_KEY, ARA_EMBED_ID (set by provisioning).
No credentials or Instruqt-specific paths here.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


@dataclass
class Chunk:
    doc_id: str
    doc_type: str
    title: str
    section: str
    effective_date: str
    body: str

    def token_count(self) -> int:
        return int(len(self.body.split()) * 1.3)


# ── Chunking strategies ───────────────────────────────────────────────────────

def chunk_fixed(doc: dict, max_tokens: int = 512, overlap_tokens: int = 50) -> list[Chunk]:
    """Split body into fixed-size windows measured in approximate tokens (words * 1.3).

    max_tokens: target ceiling in tokens (approx); actual windows are max_tokens/1.3 words.
    overlap_tokens: overlap in tokens between consecutive windows.
    """
    words = doc.get("body", "").split()
    max_words = int(max_tokens / 1.3)
    overlap_words = int(overlap_tokens / 1.3)
    step = max(1, max_words - overlap_words)
    chunks = []
    idx = 0
    for i in range(0, max(len(words), 1), step):
        window = words[i : i + max_words]
        if not window:
            break
        chunks.append(_make_chunk(doc, " ".join(window), idx))
        idx += 1
    return chunks


def chunk_heading_aware(doc: dict, max_tokens: int = 512) -> list[Chunk]:
    """Split at Markdown headings; if a section exceeds max_tokens, split further."""
    body = doc.get("body", "")
    # Split at h1-h3 headings
    parts = re.split(r"(?m)^#{1,3} +", body)
    chunks = []
    for idx, part in enumerate(parts):
        part = part.strip()
        if not part:
            continue
        words = part.split()
        if len(words) <= max_tokens:
            chunks.append(_make_chunk(doc, part, idx))
        else:
            # Overflow: split into fixed windows
            for j in range(0, len(words), max_tokens):
                window = words[j : j + max_tokens]
                chunks.append(_make_chunk(doc, " ".join(window), idx * 1000 + j))
    return chunks or [_make_chunk(doc, body, 0)]


def chunk_unit_preserving(doc: dict, units: list[dict], max_tokens: int = 2048) -> list[Chunk]:
    """Keep each semantic unit (table, list, procedure) intact as one chunk.

    units: list of {"start": int, "end": int} char offsets marking unit boundaries.
    Text between units is split with fixed chunking. Units larger than max_tokens are
    kept whole (they are designated units; splitting them defeats the purpose).
    """
    body = doc.get("body", "")
    # Build sorted, non-overlapping coverage from unit boundaries
    spans = sorted(units, key=lambda u: u["start"])
    chunks = []
    cursor = 0
    idx = 0

    for unit in spans:
        s, e = unit["start"], unit["end"]
        if s > cursor:
            # Gap before this unit — apply fixed chunking
            gap = body[cursor:s]
            for c in chunk_fixed({**doc, "body": gap}, max_tokens=512):
                c.doc_id = doc["doc_id"]
                chunks.append(c)
        # Keep the unit whole regardless of size
        unit_text = body[s:e].strip()
        if unit_text:
            chunks.append(_make_chunk(doc, unit_text, idx + 10000))
        cursor = e
        idx += 1

    # Trailing text after last unit
    if cursor < len(body):
        tail = body[cursor:]
        for c in chunk_fixed({**doc, "body": tail}, max_tokens=512):
            chunks.append(c)

    return chunks or [_make_chunk(doc, body, 0)]


def _make_chunk(doc: dict, body: str, index: int) -> Chunk:
    return Chunk(
        doc_id=doc.get("doc_id", doc.get("_id", "unknown")),
        doc_type=doc.get("doc_type", "unknown"),
        title=doc.get("title", ""),
        section=doc.get("section", ""),
        effective_date=doc.get("effective_date", ""),
        body=body,
    )


# ── Standard corpus mapping ───────────────────────────────────────────────────

def standard_mapping(embed_id: str) -> dict:
    """Return the standard cortex-corpus mapping used across M2 tracks.

    Body fields: semantic_text on embed_id, plus plain text twin for BM25.
    Metadata fields: doc_id, doc_type, title, section, effective_date.
    """
    return {
        "mappings": {
            "properties": {
                "body": {
                    "type": "semantic_text",
                    "inference_id": embed_id,
                },
                "body_text": {"type": "text"},
                "doc_id": {"type": "keyword"},
                "doc_type": {"type": "keyword"},
                "title": {"type": "keyword"},
                "section": {"type": "keyword"},
                "effective_date": {"type": "date"},
            }
        }
    }


# ── Indexer ───────────────────────────────────────────────────────────────────

def index_chunks(
    es,
    index: str,
    chunks: list[Chunk],
    embed_id: str | None = None,
    recreate: bool = False,
    require_existing: bool = False,
) -> dict:
    """Index chunks into ES.

    require_existing=True raises ValueError if the index does not exist yet,
    forcing the caller to create the index and its mapping explicitly first.
    This ensures the mapping is the learner's decision, not the library's.

    Returns a summary dict: {"indexed": int, "errors": int}.
    """
    from elasticsearch.helpers import bulk

    if recreate and es.indices.exists(index=index):
        es.indices.delete(index=index)

    if not es.indices.exists(index=index):
        if require_existing:
            raise ValueError(
                f"Index '{index}' does not exist. "
                "Create it with the correct mapping in Kibana Dev Tools first, "
                "then run this cell."
            )
        eid = embed_id or os.environ.get("ARA_EMBED_ID")
        if not eid:
            raise EnvironmentError("ARA_EMBED_ID is not set and embed_id not supplied")
        es.indices.create(index=index, body=standard_mapping(eid))

    def _actions():
        for chunk in chunks:
            d = asdict(chunk)
            d["body_text"] = d.pop("body")
            # semantic_text field uses same content
            d["body"] = chunk.body
            yield {"_index": index, "_id": _chunk_id(chunk), "_source": d}

    success, errors = bulk(es, _actions(), raise_on_error=False)
    return {"indexed": success, "errors": len(errors) if isinstance(errors, list) else errors}


def _chunk_id(chunk: Chunk) -> str:
    key = f"{chunk.doc_id}|{chunk.body[:80]}"
    return hashlib.md5(key.encode()).hexdigest()[:16]


def reindex_with_inference_id(
    es,
    source_index: str,
    dest_index: str,
    embed_id: str,
    wait_secs: int = 300,
) -> str:
    """Create dest_index with a new embed_id and reindex from source.

    Returns the task id. Caller can poll with wait_for_reindex.
    """
    if es.indices.exists(index=dest_index):
        es.indices.delete(index=dest_index)
    es.indices.create(index=dest_index, body=standard_mapping(embed_id))

    resp = es.reindex(
        body={"source": {"index": source_index}, "dest": {"index": dest_index}},
        wait_for_completion=False,
    )
    return resp["task"]


def wait_for_reindex(es, task_id: str, timeout_secs: int = 300) -> dict:
    """Poll _tasks until the reindex task finishes or times out."""
    deadline = time.time() + timeout_secs
    while time.time() < deadline:
        t = es.tasks.get(task_id=task_id)
        if t.get("completed"):
            return t.get("response", {})
        time.sleep(5)
    raise TimeoutError(f"Reindex task {task_id} did not complete in {timeout_secs}s")


# ── Chunk statistics ──────────────────────────────────────────────────────────

def chunk_report(chunks: list[Chunk]) -> dict:
    """Return summary statistics over a list of chunks."""
    tokens = [c.token_count() for c in chunks]
    if not tokens:
        return {"count": 0}
    tokens.sort()
    n = len(tokens)
    return {
        "count": n,
        "median_tokens": tokens[n // 2],
        "p95_tokens": tokens[min(n - 1, int(math.ceil(0.95 * n)) - 1)],
        "max_tokens": tokens[-1],
        "mean_tokens": round(sum(tokens) / n, 1),
    }


def load_corpus(corpus_dir: str) -> list[dict]:
    """Load corpus documents from a directory.

    Supports two layouts:
    - JSON files: each file is one doc ({"doc_id": ..., "body": ..., ...})
    - Manifest + markdown: reads manifest.json for metadata, .md files for body text.
      doc_id is derived from the stem up to the second hyphen-separated segment
      (e.g. "policy-001-structuring-..." → "policy-001").
    """
    corpus = Path(corpus_dir)
    manifest_path = corpus / "manifest.json"

    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        docs = []
        for entry in manifest:
            fname = entry["filename"]
            fpath = corpus / fname
            if not fpath.exists():
                continue
            body = fpath.read_text().strip()
            stem = Path(fname).stem  # e.g. "policy-001-structuring-...", "wire-fraud-202-..."
            parts = stem.split("-")
            # doc_id: everything up to and including the first purely-numeric segment.
            # "policy-001-..." → "policy-001"; "wire-fraud-202-..." → "wire-fraud-202";
            # "risk-scoring-reference" (no number) → use entire stem.
            id_end = len(parts)
            for i, p in enumerate(parts):
                if p.isdigit():
                    id_end = i + 1
                    break
            doc_id = "-".join(parts[:id_end])
            title_parts = parts[id_end:]
            title = " ".join(title_parts).title() if title_parts else " ".join(parts).title()
            docs.append({
                "doc_id": doc_id,
                "doc_type": entry.get("doc_type", "policy"),
                "title": title,
                "section": "",
                "effective_date": entry.get("effective_date", "2026-01-01"),
                "body": body,
            })
        return docs

    # Fallback: load JSON files
    docs = []
    for p in sorted(corpus.glob("*.json")):
        if p.name == "manifest.json":
            continue
        docs.append(json.loads(p.read_text()))
    return docs
