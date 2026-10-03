"""Dev evaluator for Build 3: run after the cell that writes router.py.

Usage:
  /home/elastic/.venv/bin/python /home/elastic/dev-sets/eval-router.py

Runs your pick_tier on the dev queries exactly as the check runs it on the held-out
queries (ara_cost.run_learner), and prints the count routed correctly. The notebook's Dispatch
cell prints the other number the check records: how many of the dev answers your router sent
fast came back correct.
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
print(f"\nRouted correctly: {right} of {len(dev)}. The check needs {T['min_correct']} of {T['of']} held-out.")
print("Run the notebook's Dispatch cell for the fast tier's answer accuracy on the dev queries it sends fast.")
