#!/usr/bin/env python3
"""ara-ab-behavior.py - send a public dev set to Tina and print what she did (22 section 1).

    python3 /opt/ara/lib/ara-ab-behavior.py --dev 4-1-b1
    python3 /opt/ara/lib/ara-ab-behavior.py --dev 4-1-b1 --only b1-dev-02

Learner mode only: it prints each question, the route Tina took (tools in call order with their
structured parameters) and the route the dev set expects, with no verdict. The checks grade a
different, held-out set the same way (ara_behavior.py). Runs as tina-runtime with the pinned
connector, at most 3 questions at a time, so what you see is what the check sees.

For a set whose cases open workflow runs (4-1-b2), it also prints each execution's status and the
case document that run wrote.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from agent_builder import AB, ABError  # noqa: E402
from ara_behavior import expected_text, route_text, run_cases  # noqa: E402

DEV_DIR = pathlib.Path(os.environ.get("ARA_DEV_SETS", "/home/elastic/dev-sets"))


def case_doc(execution_id: str) -> dict | None:
    es, key = os.environ.get("ES_URL"), os.environ.get("ES_API_KEY")
    if not (es and key and execution_id):
        return None
    body = json.dumps({"size": 2, "query": {"term": {"execution_id": execution_id}}}).encode()
    req = urllib.request.Request(f"{es.rstrip('/')}/cortex-fraud-cases/_search", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"ApiKey {key}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            hits = json.loads(r.read()).get("hits", {}).get("hits", [])
    except Exception:
        return None
    return hits[0]["_source"] if hits else {}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dev", required=True, help="dev set name, for example 4-1-b1")
    ap.add_argument("--only", help="run one case by id")
    ap.add_argument("--agent", default="tina-compliance")
    a = ap.parse_args()
    path = DEV_DIR / f"{a.dev}.json"
    if not path.exists():
        print(f"No dev set at {path}. The names are the files in {DEV_DIR} without .json.")
        return 2
    cases = json.loads(path.read_text())["cases"]
    if a.only:
        cases = [c for c in cases if c["id"] == a.only]
    try:
        ab = AB.from_env(timeout=120)
    except KeyError as e:
        print(f"{e.args[0]} is not set. Open a new Terminal tab, or run: set -a; . /home/elastic/env; set +a")
        return 2
    print(f"Sending {len(cases)} questions to {a.agent}, at most 3 at a time. Each takes about 15 to 30 seconds.")
    try:
        results = run_cases(ab, a.agent, cases, concurrency=3)
    except ABError as e:
        print(f"Kibana did not respond ({e}). Wait a moment and run this again.")
        return 1
    for case, r in zip(cases, results):
        print()
        print(f"[{case['id']}] {case['input']}")
        if r.get("error"):
            print(f"  no answer from Kibana ({r['error'][:120]}); run this case again with --only {case['id']}")
            continue
        print(f"  Tina:     {route_text(r['route'])}")
        print(f"  expected: {expected_text(case)}")
        print(f"  {r['seconds']} s, conversation {r.get('conversation_id')}")
        for call in r["route"]:
            if call.get("execution_id"):
                ex = ab.wait_execution(call["execution_id"], budget_s=60)
                print(f"  execution {call['execution_id']}: {(ex or {}).get('status', 'not found')}")
                doc = case_doc(call["execution_id"])
                if doc is not None:
                    print(f"  case document: {json.dumps(doc, sort_keys=True) if doc else 'none for this execution'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
