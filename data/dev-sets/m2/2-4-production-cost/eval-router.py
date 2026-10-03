"""Dev evaluator for Build 3: run after the cell that writes router.py.

Usage:
  /home/elastic/.venv/bin/python /home/elastic/dev-sets/eval-router.py

Runs your pick_tier on the dev queries exactly as the check runs it on the held-out
queries (ara_cost.run_learner), and prints the count routed correctly and the fast-tier routing recall on the dev set.
"""
import json, pathlib, sys
sys.path.insert(0, "/opt/ara/lib")
from ara_cost import run_learner

T = json.loads(pathlib.Path("/opt/ara/thresholds.json").read_text())["build3"]
dev = json.loads((pathlib.Path(__file__).parent / "dev-routing-queries.json").read_text())
recs, err = run_learner("router", dev)
if err:
    sys.exit(f"Your router failed: {err}")
tier = {r["id"]: r["tier"] for r in recs}
right = 0
for q in dev:
    t = tier.get(q["id"], "absent")
    right += t == q["label"]
    print(f"{'PASS' if t == q['label'] else 'FAIL'}  {q['id']:10s} label {q['label']:6s} got {t:6s} {q['text']}")
single = [q for q in dev if q["query_type"] == "single_hop"]
recall = sum(tier.get(q["id"]) == "fast" for q in single) / len(single)
print(f"\nRouted correctly: {right} of {len(dev)}. The check needs {T['min_correct']} of {T['of']} held-out.")
print(f"fast_tier_routing_recall (single-hop queries sent to the fast tier): {recall:.2f} on these {len(single)}. "
      "The check measures it on its own, larger set, and the Defend asks about that figure.")
