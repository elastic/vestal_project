#!/usr/bin/env python3
"""
ara-loop.py - the self-improvement loop's helper (Lab 6.2, 6.C): candidate, gate, apply, remeasure, rollback.

Usage (as the learner; the credentials come from ~/env):
  python3 /opt/ara/lib/ara-loop.py candidate prop-review-1   # copy what the proposal changes, apply the change to the copies
  python3 /opt/ara/lib/ara-loop.py gate prop-review-1        # measure the candidate and decide by the rule table
  python3 /opt/ara/lib/ara-loop.py apply prop-review-1       # change production (nothing stops a step that failed its gate)
  python3 /opt/ara/lib/ara-loop.py remeasure prop-review-1   # measure production again and compare with the candidate
  python3 /opt/ara/lib/ara-loop.py rollback prop-review-1    # restore what the apply replaced
  python3 /opt/ara/lib/ara-loop.py propose fix.json          # check your own proposal and store it (6.C); prints its id

Every step except propose is written to cortex-eval-ledger. Exit 0 done, 1 a step could not be done (the message says why),
2 bad input, 3 no grade (an outage: nothing recorded, run it again).
"""
from __future__ import annotations

import datetime
import json
import os
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import ara_eval as E  # noqa: E402
import ara_loop_cli as C  # noqa: E402
from agent_builder import AB, ABError  # noqa: E402
from ara_security import ES  # noqa: E402

HOME = pathlib.Path(os.environ.get("HOME", "/home/elastic"))
GATE = HOME / "cortex-loop" / "gate.json"
# M6's start state carries one learner-readable /opt/ara/thresholds.json (tolerances and the rate card); the eval paths are the overrides.
THRESHOLDS = pathlib.Path(os.environ.get("ARA_THRESHOLDS") or "/opt/ara/thresholds.json")
CARD = pathlib.Path(os.environ.get("ARA_RATE_CARD", "/opt/ara/eval/rate-card.json"))
TESTSET = HOME / "cortex-eval" / "testset.json"
RANK_EVAL = HOME / "cortex-eval" / "rank-eval.json"   # the rated requests for the gate set's policy questions (setup writes it for 6.C)


def with_ndcg(agg: dict, records: list[dict]) -> dict:
    """The aggregates plus the mean nDCG at 5 over the policy-question records (retrieval.ndcg_at_5), None when no record has one."""
    vals = [r["retrieval"]["ndcg_at_5"] for r in records if isinstance(r.get("retrieval"), dict) and r["retrieval"].get("ndcg_at_5") is not None]
    return dict(agg, ndcg_at_5=(sum(vals) / len(vals)) if vals else None)


class Ledger:
    def __init__(self, es: ES):
        self.es = es

    def append(self, entry: dict) -> None:
        nd = json.dumps({"index": {"_index": "cortex-eval-ledger"}}) + "\n" + json.dumps(entry) + "\n"
        code, body = self.es.request_ndjson("POST", "/_bulk?refresh=wait_for", nd)
        if code != 200 or (isinstance(body, dict) and body.get("errors")):
            raise C.LoopError(f"the ledger entry was not stored (HTTP {code})")

    def entries(self) -> list[dict]:
        code, body = self.es.request("POST", "/cortex-eval-ledger/_search", {"size": 1000, "sort": [{"at": "asc"}]})
        if code != 200:
            raise ABError(f"the ledger did not answer (HTTP {code})", 503)
        return [h["_source"] for h in body["hits"]["hits"]]


class Proposals:
    def __init__(self, es: ES):
        self.es = es

    def get(self, pid: str) -> dict | None:
        code, body = self.es.request("POST", "/cortex-eval-proposals/_search", {"size": 1, "query": {"term": {"proposal_id": pid}}})
        hits = body["hits"]["hits"] if code == 200 else []
        return hits[0]["_source"] if hits else None


def _add(self, doc: dict) -> None:
    nd = json.dumps({"index": {"_index": "cortex-eval-proposals"}}) + "\n" + json.dumps(doc) + "\n"
    code, body = self.es.request_ndjson("POST", "/_bulk?refresh=wait_for", nd)
    if code != 200 or (isinstance(body, dict) and body.get("errors")):
        raise C.LoopError(f"the proposal was not stored (HTTP {code})")


Proposals.add = _add


class Deps:
    def __init__(self, env: dict):
        need = lambda n: env.get(n) or sys.exit(f"{n} is not set. Open a new terminal (it loads ~/env) and run this again.")
        key = env.get("ARA_LOOP_KEY") or env.get("ARA_TINA_EVAL_KEY") or need("ES_API_KEY")
        self.es = ES(need("ES_URL").rstrip("/"), f"ApiKey {key}", timeout=60)
        self.ab = AB(need("KIBANA_URL").rstrip("/"), key, env.get("ARA_AB_CONNECTOR_ID"), timeout=60)
        self.ledger, self.proposals = Ledger(self.es), Proposals(self.es)
        self.agent_id = env.get("ARA_AGENT_ID", "tina-compliance")
        self.gate = json.loads(GATE.read_text()) if GATE.exists() else sys.exit(f"{GATE} does not exist: write it from Cortex's change policy first.")
        self.thresholds = json.loads(THRESHOLDS.read_text()) if THRESHOLDS.exists() else {}
        self.card = json.loads(CARD.read_text()) if CARD.exists() else (self.thresholds.get("rate_card") or None)

    def now(self) -> str:
        return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def measure(self, label: str, agent_id: str, index: str | None = None) -> dict:
        """The harness over the gate set, then (where the rated requests exist) the retrieval measurement of its policy questions, against `index`
        for a data fix's candidate and against production's alias otherwise."""
        ev = str(pathlib.Path(__file__).with_name("ara-eval.py"))
        import ara_setcat as SC
        try:
            raw = json.loads(TESTSET.read_text())
        except (OSError, ValueError):
            raise C.LoopError(f"{TESTSET} cannot be read: the gate set is missing or not valid JSON.")
        bad = SC.check_categorised(raw.get("questions") if isinstance(raw, dict) else raw)
        if bad:   # a gate set with a question that has no category would change the category drops: no run, no grade
            raise C.LoopError(f"{TESTSET} has {len(bad)} questions without a valid category; the gate runs only over a fully categorised set.")
        argvs = [[sys.executable, ev, "run", "--label", label, "--testset", str(TESTSET), "--agent", agent_id]]
        if RANK_EVAL.exists():
            argvs.append([sys.executable, ev, "rank-eval", "--label", label, "--testset", str(TESTSET), "--rank-eval", str(RANK_EVAL)] + (["--index", index] if index else []))
        for argv in argvs:
            r = subprocess.run(argv, capture_output=True, text=True)
            if r.returncode == 3:
                raise ABError("the harness had no grade (an outage): nothing was recorded, run the step again", 503)
            if r.returncode != 0:
                raise C.LoopError(f"the harness run {label} did not finish (exit {r.returncode}): {r.stdout[-300:]}")
        return self.measure_existing(label)

    def measure_existing(self, label: str) -> dict:
        code, body = self.es.request("POST", "/cortex-eval-runs/_search", {"size": 1000, "query": {"term": {"run_label": label}}})
        recs = [h["_source"] for h in body["hits"]["hits"]] if code == 200 else []
        if not recs:
            raise C.LoopError(f"no run records labelled {label}")
        return with_ndcg(E.aggregates(recs, self.card), recs)


def main(argv: list[str], make_deps=Deps, env: dict | None = None) -> int:
    if len(argv) != 2 or argv[0] not in C.VERBS:
        print(__doc__)
        return 2
    verb, pid = argv
    try:
        entry = C.VERBS[verb](make_deps(env if env is not None else dict(os.environ)), pid)
    except C.LoopError as e:
        print(f"{verb} {pid}: {e}")
        return 1
    except ABError as e:
        print(f"{verb} {pid}: {e}")
        return 3
    print(C.summary(entry))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
