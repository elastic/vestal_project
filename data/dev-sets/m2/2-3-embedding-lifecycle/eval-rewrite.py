"""Dev evaluator for Build 3: run this after every change to rewrite().

Usage:
  /home/elastic/.venv/bin/python /home/elastic/dev-sets/eval-rewrite.py

It runs rewrite() from /home/elastic/rewrite.py on the dev queries, the same way the check
does: in a separate process, one query at a time. It then runs Tina's keyword search on
cortex-corpus-live with what rewrite() returned and reports whether the target document is among the first k
distinct documents (k and the searched field come from thresholds.json, as in the check). It runs rewrite()
three times (ARA_EVAL_ROUNDS to change) and shows the range, because a rewrite that calls a model varies run
to run. The check runs a separate held-out set of the same kind, once, so its numbers can differ from these.
"""
import json, os, pathlib, sys, time
sys.path.insert(0, "/opt/ara/lib")

env = pathlib.Path("/home/elastic/env")
if env.exists():
    for line in env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from elasticsearch import Elasticsearch
from ara_rewrite import run_rewrite, top_docs

T = json.loads(pathlib.Path("/opt/ara/thresholds.json").read_text())["build3"]
QS = json.loads((pathlib.Path(__file__).parent / "failing-dev.json").read_text())
es = Elasticsearch(os.environ["ES_URL"], api_key=os.environ["ES_API_KEY"], request_timeout=60)
t0 = time.time()

if not pathlib.Path("/home/elastic/rewrite.py").exists():
    sys.exit("/home/elastic/rewrite.py does not exist yet. Run the rewrite cell in the notebook first.")

# N77: a rewrite that calls a model returns different text each run, so one dev run can
# say FAIL while the check passes, or the reverse. Run it ROUNDS times and show the range.
ROUNDS = int(os.environ.get("ARA_EVAL_ROUNDS", "3"))
runs = []
for _ in range(ROUNDS):
    run = run_rewrite(QS)
    if run["load_error"]:
        sys.exit(f"rewrite.py did not load: {run['load_error']}")
    runs.append(run)

ok = lambda b: "PASS" if b else "FAIL"
n = len(QS)
base = {q["query_id"]: q["target_doc_id"] in top_docs(es, "cortex-corpus-live", q["query_text"], k=T["k"], field=T["field"])
        for q in QS}
missed = n - sum(base.values())
per_run_recovered, per_run_lost, calls = [], [], 0
after = {q["query_id"]: 0 for q in QS}
for run in runs:
    rec = lost = 0
    for q in QS:
        r = run["results"].get(q["query_id"], {})
        if r.get("error") or r.get("out") is None:
            continue
        new = q["target_doc_id"] in top_docs(es, "cortex-corpus-live", r["out"], k=T["k"], field=T["field"])
        after[q["query_id"]] += new
        rec += new and not base[q["query_id"]]
        lost += base[q["query_id"]] and not new
        calls += bool(r["network"])
    per_run_recovered.append(rec)
    per_run_lost.append(lost)

last = runs[-1]["results"]
for q in QS:
    r = last.get(q["query_id"], {})
    if r.get("error") or r.get("out") is None:
        print(f"  FAIL  {q['query_id']}  rewrite() failed: {r.get('error', 'no result')}")
        continue
    a = after[q["query_id"]]
    print(f"  {ok(a == ROUNDS)}  {q['query_id']}  target in top {T['k']}: before {'yes' if base[q['query_id']] else 'no'}, "
          f"after in {a} of {ROUNDS} runs   ({r['ms']:.0f} ms, {'network call' if r['network'] else 'no network call'})")
    print(f"        {q['query_text']}")

need = T["recalled_min"] / T["recalled_of"]
passes = sum(1 for rec in per_run_recovered if missed and rec >= need * missed)
lo, hi = min(per_run_recovered), max(per_run_recovered)
span = f"{lo}" if lo == hi else f"{lo} to {hi}"
print()
print(f"{ok(passes == ROUNDS)}  {span} of the {missed} dev queries that missed now find their target, over {ROUNDS} runs; "
      f"{passes} of {ROUNDS} runs pass (the check needs at least {T['recalled_min']} of {T['recalled_of']} held-out misses recovered)")
if lo != hi:
    print("      Your rewrite() gives different results run to run, as a model call does. The check runs it once on its")
    print("      own held-out queries, so it can land anywhere in this range. Aim for every run to pass.")
if max(per_run_lost):
    print(f"      Up to {max(per_run_lost)} dev queries that found their target before the rewrite no longer do.")
print(f"      rewrite() made a network call on {calls} of {n * ROUNDS} calls. The Defend asks what that costs Tina.")
if any(r["timed_out"] for r in runs):
    print("      rewrite() ran out of time before finishing every query.")
print(f"\nDone in {time.time() - t0:.1f} s.")
