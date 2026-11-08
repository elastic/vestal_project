#!/usr/bin/env python3
"""
ara-injection.py - the Lab 5.2 learner helper: run the planted correspondence past Tina and show her routes.

Usage (as the learner; the credentials come from ~/env):
  python3 /opt/ara/lib/ara-injection.py run --label before   # Build 1: against Tina as provisioned
  python3 /opt/ara/lib/ara-injection.py run --label after    # after your mitigation
  python3 /opt/ara/lib/ara-injection.py show --label before  # print a label's routes again

run asks each payload's trigger question n times under the tina-investigator key, one fresh
conversation per run, and records the conversation ids in ~/cortex-injection/runs-<label>.json.
It prints every run's tool calls; it never says whether a payload succeeded. You classify each
payload yourself. The check re-reads every recorded conversation from the conversation API, so the
ids are pointers: a run counts only if the conversation exists, is Tina's, has one round and asks
the payload's trigger question.

The before label is recorded once, so a later run cannot replace the runs your classification
is graded on. A before run that failed for an environment reason (no conversation id) is re-run
by running before again; complete runs are kept.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import ara_injection as I  # noqa: E402
from agent_builder import AB  # noqa: E402
from ara_behavior import route_text  # noqa: E402

HOME = pathlib.Path(os.environ.get("ARA_INJECTION_HOME", pathlib.Path.home() / "cortex-injection"))
# Root-owned, world-readable: payload ids, cases and trigger questions only (never the forbidden calls).
PAYLOADS = pathlib.Path(os.environ.get("ARA_INJECTION_PAYLOADS", "/opt/ara/injection/payloads.json"))


def env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        sys.exit(f"{name} is not set. Open a new terminal (it loads ~/env) and run this again.")
    return v


def read_json(p: pathlib.Path) -> dict | None:
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def write_json(p: pathlib.Path, obj: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=2) + "\n")
    tmp.replace(p)


def label_arg(argv: list[str]) -> str:
    if "--label" in argv and argv.index("--label") + 1 < len(argv):
        label = argv[argv.index("--label") + 1]
        if label in I.LABELS:
            return label
    sys.exit("Give --label before or --label after.")


def print_run(r: dict, case_of: dict) -> None:
    head = f"{r['payload_id']} (case {case_of[r['payload_id']]}) run {r['k']}"
    if not r.get("conversation_id"):
        print(f"  {head}: no conversation ({r.get('error') or 'no response'}); run this label again to retry it")
        return
    print(f"  {head}: {route_text(r.get('calls') or [])}")


def run(label: str) -> None:
    spec = json.loads(PAYLOADS.read_text())
    n, payloads = int(spec["n"]), spec["payloads"]
    case_of = {p["payload_id"]: p["case_id"] for p in payloads}
    path = HOME / f"runs-{label}.json"
    old = read_json(path) or {}
    kept = [r for r in old.get("runs") or [] if r.get("conversation_id")]
    if label == "before" and len(kept) >= n * len(payloads):
        sys.exit(f"{path} already holds a complete before set (recorded once; Build 1 grades it). "
                 "Show it with: ara-injection.py show --label before")
    if label == "after":
        kept = []
    have = {(r["payload_id"], r["k"]) for r in kept}
    jobs = [{"payload_id": p["payload_id"], "k": k, "question": p["question"]}
            for p in payloads for k in range(1, n + 1) if (p["payload_id"], k) not in have]
    ab = AB(env("KIBANA_URL").rstrip("/"), env("ARA_TINA_INVESTIGATOR_KEY"), env("ARA_AB_CONNECTOR_ID"), timeout=170)
    print(f"Running {len(jobs)} conversations under tina-investigator, three at a time "
          f"(about {max(1, len(jobs) * 30 // 3 // 60)} minutes) ...")
    done = I.run_set(ab, jobs, concurrency=3, on_run=lambda r: print_run(r, case_of))
    runs = sorted(kept + [{"payload_id": r["payload_id"], "k": r["k"], "conversation_id": r["conversation_id"],
                           "route": [{"tool_id": c["tool_id"], "params": c.get("params")} for c in r["calls"]]}
                          for r in done if r.get("conversation_id")], key=lambda r: (r["payload_id"], r["k"]))
    write_json(path, {"label": label, "n": n, "runs": runs})
    missing = n * len(payloads) - len(runs)
    print(f"\nSaved {len(runs)} runs to {path}." + (f" {missing} did not complete: run this label again." if missing else ""))
    if label == "before" and not missing:
        print("Classify each payload with: python3 /opt/ara/lib/record.py "
              f"{HOME / 'classification.json'} {PAYLOADS.parent / 'classify-schema.json'}")


def show(label: str) -> None:
    spec = json.loads(PAYLOADS.read_text())
    case_of = {p["payload_id"]: p["case_id"] for p in spec["payloads"]}
    data = read_json(HOME / f"runs-{label}.json")
    if not data:
        sys.exit(f"No {label} runs yet: ara-injection.py run --label {label}")
    for r in data["runs"]:
        print_run(dict(r, calls=r.get("route") or []), case_of)


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in ("run", "show"):
        print(__doc__)
        return 2
    HOME.mkdir(parents=True, exist_ok=True)
    {"run": run, "show": show}[argv[0]](label_arg(argv))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
