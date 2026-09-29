"""Dev evaluator for Build 1: run after saving your queries.

Usage:
  /home/elastic/.venv/bin/python /home/elastic/dev-sets/eval-esql.py

Runs each saved query with the dev parameters and compares its rows with a reference
query over the same index, the way the check does (ara_cost.compare). The check uses
different held-out parameters, so write the filter for any threshold, country and days.
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
from ara_cost import compare

saved = pathlib.Path("/home/elastic/esql-queries.json")
if not saved.exists():
    sys.exit("esql-queries.json not found. Run the notebook's save cell first.")
queries = json.loads(saved.read_text())
dev = json.loads((pathlib.Path(__file__).parent / "dev-esql-queries.json").read_text())
es = Elasticsearch(os.environ["ES_URL"], api_key=os.environ["ES_API_KEY"], request_timeout=60)
passed = 0
for d in dev:
    kind = d["type"]
    if not queries.get(kind):
        print(f"FAIL  {kind:13s} no query saved under '{kind}'"); continue
    ok, msg = compare(es, kind, queries[kind], d.get("dev_parameters"))
    passed += ok
    print(f"{'PASS' if ok else 'FAIL'}  {kind:13s} {msg}")
print(f"\n{passed} of {len(dev)} queries match the reference on the dev parameters.")
