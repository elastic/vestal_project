"""Dev evaluator for Build 2: run after the cell that writes cortex_cache.py.

Usage:
  /home/elastic/.venv/bin/python /home/elastic/dev-sets/eval-cache.py

Empties cortex-semantic-cache, then runs the dev sequence through your cache_lookup
and cache_store exactly as the check runs the held-out sequence (ara_cost.run_learner):
lookup first, and on a miss store one document. Misses are stored with a stub answer,
because what is graded is the hit or miss, not the answer text.
"""
import json, os, pathlib, sys
sys.path.insert(0, "/opt/ara/lib")
env = pathlib.Path("/home/elastic/env")
for line in env.read_text().splitlines() if env.exists() else []:
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())
from elasticsearch import Elasticsearch
from ara_cost import run_learner, score_sequence

T = json.loads(pathlib.Path("/opt/ara/thresholds.json").read_text())["build2"]
seq = json.loads((pathlib.Path(__file__).parent / "dev-cache-sequence.json").read_text())["queries"]
es = Elasticsearch(os.environ["ES_URL"], api_key=os.environ["ES_API_KEY"], request_timeout=60)
es.delete_by_query(index="cortex-semantic-cache", body={"query": {"match_all": {}}}, refresh=True)
recs, err = run_learner("cache", seq)
if err:
    sys.exit(f"Your cache code failed: {err}")
thr = next((r.get("threshold") for r in recs if "threshold" in r), None)
by_id = {r["id"]: r["outcome"] for r in recs if "id" in r}
for q in seq:
    got = by_id.get(q["id"], "absent")
    want = "hit" if q["expected"] == "hit" else "miss"
    print(f"{'PASS' if got == want else 'FAIL'}  {q['id']}  expected {q['expected']:9s} got {got:5s}  {q['text']}")
es.indices.refresh(index="cortex-semantic-cache")
docs = es.count(index="cortex-semantic-cache")["count"]
s = score_sequence(recs, seq)
print(f"\nThreshold {thr}. {s['correct']} of {s['of']} outcomes right; near-misses that missed: "
      f"{s['near_miss_ok']} of {s['near_miss_of']}; cache documents {docs} for {s['misses']} misses.")
print(f"Hit rate on this sequence: {s['hit_rate']} (the Defend uses your held-out hit rate).")
n = T["max_wrong_outcomes"]
print(f"The check allows at most {n} wrong outcome{'' if n == 1 else 's'} on its held-out sequence, "
      "and needs every near-miss to miss and one document per miss.")
