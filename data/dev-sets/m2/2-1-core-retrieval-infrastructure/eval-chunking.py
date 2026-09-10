"""
Dev evaluation script for Track 2.1 Build 1.
Run from /home/elastic/dev-sets after indexing your corpus:
  source /home/elastic/env
  python3 eval-chunking.py

Checks median chunk tokens and precision@5 on 6 dev queries.
The check uses a different held-out set; this script is for iteration.
"""

import json
import math
import os
import sys
import time

sys.path.insert(0, "/opt/ara/lib")

from elasticsearch import Elasticsearch

es = Elasticsearch(os.environ["ES_URL"], api_key=os.environ["ES_API_KEY"])

# ── Chunk token stats ─────────────────────────────────────────────────────────
print("=== Chunk statistics ===")
try:
    resp = es.search(index="cortex-corpus", body={"query": {"match_all": {}}, "size": 500, "_source": ["body_text"]})
    tokens = sorted(int(len(h["_source"].get("body_text", "").split()) * 1.3) for h in resp["hits"]["hits"])
    total = resp["hits"]["total"]["value"]
    n = len(tokens)
    median = tokens[n // 2] if tokens else 0
    p95 = tokens[min(n - 1, int(math.ceil(0.95 * n)) - 1)] if tokens else 0
    max_t = tokens[-1] if tokens else 0
    print(f"  Total chunks: {total}")
    print(f"  Median tokens: {median}  {'OK (<= 512)' if median <= 512 else 'FAIL (> 512)'}")
    print(f"  p95 tokens:   {p95}")
    print(f"  Max tokens:   {max_t}  {'OK (<= 2048)' if max_t <= 2048 else 'FAIL (> 2048)'}")
except Exception as e:
    print(f"  Error reading cortex-corpus: {e}")
    sys.exit(1)

# ── Alias check ───────────────────────────────────────────────────────────────
print()
print("=== Alias ===")
try:
    aliases = es.indices.get_alias(name="cortex-corpus-live")
    targets = list(aliases.keys())
    print(f"  cortex-corpus-live -> {targets}")
    if "cortex-corpus" in targets:
        print("  OK")
    else:
        print("  FAIL: alias does not point at cortex-corpus")
except Exception as e:
    print(f"  cortex-corpus-live not found: {e}")

# ── Dev precision@5 ───────────────────────────────────────────────────────────
print()
print("=== Precision@5 on 6 dev queries ===")
script_dir = os.path.dirname(os.path.abspath(__file__))
queries_path = os.path.join(script_dir, "dev-queries.json")
queries = json.loads(open(queries_path).read())

hits = 0
for q in queries:
    resp = es.search(index="cortex-corpus-live", body={
        "query": {"semantic": {"field": "body", "query": q["query_text"]}},
        "size": 5,
        "_source": ["doc_id"],
    })
    retrieved = [h["_source"].get("doc_id", h["_id"]) for h in resp["hits"]["hits"]]
    relevant = set(q["relevant_ids"])
    hit = any(r in relevant for r in retrieved)
    hits += int(hit)
    status = "HIT" if hit else "MISS"
    print(f"  [{status}] {q['query_text'][:60]}")
    if not hit:
        print(f"       retrieved: {retrieved}")
        print(f"       expected:  {list(relevant)}")

p5 = hits / len(queries)
print()
print(f"  precision@5: {p5:.2f}  {'OK (>= 0.8)' if p5 >= 0.8 else 'Needs improvement'}")
print()
print("Run 'select Check' when median <= 512 and cortex-corpus-live resolves.")
