#!/usr/bin/env python3
"""ara-ab-behavior.py - send a public dev set to Tina and print what she did (22 section 1).

    python3 /opt/ara/lib/ara-ab-behavior.py --dev 4-1-b1
    python3 /opt/ara/lib/ara-ab-behavior.py --dev 4-1-b1 --only b1-dev-02

Learner mode only: it prints each question, the route Tina took (tools in call order with their
structured parameters) and the route the dev set expects, with no verdict. The checks grade a
different, held-out set the same way (ara_behavior.py). Runs as tina-runtime with the pinned
connector, at most 3 questions at a time, so what you see is what the check sees.

For a set whose cases open workflow runs (4-1-b2), it also prints each execution's status and the
case document that run wrote. When Tina delegates to a sub-agent, the sub-agent's own tool calls are
read from the traces (traces-agent_builder.otel-*) and shown after the delegation, as the check
reads them.
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
from ara_desk import AML, COORDINATOR, find_aml, resolve  # noqa: E402

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


def trace_spans(trace_id: str) -> list[dict]:
    es, key = os.environ.get("ES_URL"), os.environ.get("ES_API_KEY")
    if not (es and key):
        return []
    body = json.dumps({"size": 500, "sort": [{"@timestamp": "asc"}], "query": {"term": {"trace_id": trace_id}}}).encode()
    req = urllib.request.Request(f"{es.rstrip('/')}/traces-agent_builder.otel-*/_search", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"ApiKey {key}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return [h["_source"] for h in json.loads(r.read()).get("hits", {}).get("hits", [])]
    except Exception:
        return []


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
        ab = AB.from_env(timeout=150)
    except KeyError as e:
        print(f"{e.args[0]} is not set. Open a new Terminal tab, or run: set -a; . /home/elastic/env; set +a")
        return 2
    if AML in json.dumps(cases):
        # 4.C: the AML specialist's id is yours; it is found the way the check finds it (ara_desk).
        try:
            aml_id, is_sub = find_aml(ab.get_agent(COORDINATOR), ab.agents() or [])
        except ABError as e:
            print(f"Kibana did not respond ({e}). Wait a moment and run this again.")
            return 1
        if aml_id is None:
            print("No AML specialist yet: no agent other than Tina and the securities specialist holds an AML tool. "
                  "The AML requests below expect one.")
        elif not is_sub:
            print(f"{aml_id} holds an AML tool but is not one of Tina's sub-agents, so she cannot delegate to it.")
        else:
            print(f"AML specialist: {aml_id} (one of Tina's sub-agents, holding an AML tool).")
        cases = resolve(cases, aml_id)
    print(f"Sending {len(cases)} questions to {a.agent}, at most 3 at a time. Each takes about 15 to 30 seconds, "
          "a delegated one about a minute, but it can take longer.")
    try:
        results = run_cases(ab, a.agent, cases, concurrency=3, spans=trace_spans)
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
