#!/usr/bin/env python3
"""
ara-access.py - the Lab 5.1 learner helper: record a prediction, verify a key, explain mismatches, ask Tina.

Usage (as the learner; the credentials come from ~/env):
  python3 /opt/ara/lib/ara-access.py predict            # Build 1: before creating any key
  python3 /opt/ara/lib/ara-access.py verify             # runs the probes under a key you paste
  python3 /opt/ara/lib/ara-access.py explain            # a mechanism for every item you got wrong
  python3 /opt/ara/lib/ara-access.py ask "<question>"   # one Tina conversation under a key you paste

Files (learner-owned, in ~/cortex-access/): prediction.json, observations.json, conversations.jsonl.

predict records your first prediction once, with the time from the Elasticsearch server clock (the clock
key creation times use), and refuses to overwrite it: Build 1 grades the first prediction. verify prints
what the key reached; it never says whether a prediction is right. The check re-observes everything
itself with keys it mints, so nothing it grades comes from these files except your choices.
"""
from __future__ import annotations

import getpass
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import ara_security as S  # noqa: E402
from agent_builder import AB, route_record  # noqa: E402

HOME = pathlib.Path(os.environ.get("ARA_ACCESS_HOME", pathlib.Path.home() / "cortex-access"))
# The setup stages probes.json here, root-owned and world-readable: /opt/ara/src closes after provisioning.
PROBES = pathlib.Path(os.environ.get("ARA_ACCESS_PROBES", "/opt/ara/access/probes.json"))
CHOICES = {"documents": ("retrievable", "blocked"), "fields": ("visible", "hidden"), "calls": S.OUTCOMES}
AGENT = "tina-compliance"


def env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        sys.exit(f"{name} is not set. Open a new terminal (it loads ~/env) and run this again.")
    return v


def admin() -> S.ES:
    return S.ES(env("ES_ENDPOINT").rstrip("/"), S.api_key_auth(env("ES_API_KEY")))


def server_ms(es: S.ES) -> int:
    """Now on the Elasticsearch server clock, in epoch milliseconds."""
    code, body = es.request("POST", "/_query", {"query": "ROW t = TO_LONG(NOW())"})
    if code != 200:
        sys.exit(f"Could not read the Elasticsearch clock (HTTP {code}). Run this again; if it repeats, ask for help.")
    return int(body["values"][0][0])


def pick(label: str, options) -> str:
    print(f"\n{label}")
    for i, o in enumerate(options, 1):
        print(f"  {i}. {o}")
    while True:
        a = input("Choice (number): ").strip()
        if a.isdigit() and 1 <= int(a) <= len(options):
            return options[int(a) - 1]
        print(f"Enter a number from 1 to {len(options)}.")


def items(probes: dict) -> list[tuple[str, str, str]]:
    """(section, item, label) in the order the helper asks and prints them."""
    out = [("documents", d["id"], f"Document {d['id']} in {d['index']}") for d in probes["documents"]]
    out += [("fields", f, f"Field {f} on {probes['fields']['index']} documents") for f in probes["fields"]["names"]]
    out += [("calls", t["id"], f"Tina's tool {t['tool_id']} with {json.dumps(t['params'])}") for t in probes["tools"]]
    return out


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


def predict() -> None:
    p = HOME / "prediction.json"
    if read_json(p):
        sys.exit(f"{p} already holds your first prediction (recorded once; Build 1 grades the first one). "
                 "If a prediction turns out wrong, record why with: ara-access.py explain")
    probes = json.loads(PROBES.read_text())
    print("Predict what a key with the auditor role descriptors will reach. Answer every item.")
    pred = {s: {} for s in CHOICES}
    for section, item, label in items(probes):
        pred[section][item] = pick(label, CHOICES[section])
    pred["recorded_at_ms"] = server_ms(admin())
    pred["mechanisms"] = {}
    write_json(p, pred)
    print(f"\nPrediction recorded in {p}. Now create cortex-auditor-key in Dev Tools.")


def key_from_prompt() -> tuple[S.ES, AB]:
    enc = getpass.getpass("Paste the key's encoded value (input hidden): ").strip()
    if not enc:
        sys.exit("No key given.")
    return (S.ES(env("ES_ENDPOINT").rstrip("/"), S.api_key_auth(enc)),
            AB(env("KIBANA_URL").rstrip("/"), enc, env("ARA_AB_CONNECTOR_ID"), timeout=170))


def verify() -> None:
    probes = json.loads(PROBES.read_text())
    kes, kab = key_from_prompt()
    code, who = kes.request("GET", "/_security/_authenticate")
    if code != 200:
        sys.exit(f"Elasticsearch refused the key (HTTP {code}). Copy the encoded value from the create response.")
    print("Running the probes under the key (the open_case probe runs a workflow, about 20 s) ...")
    obs = S.observe_probes(kes, kab, probes, admin_ab=AB(env("KIBANA_URL").rstrip("/"), env("ES_API_KEY"),
                                                         env("ARA_AB_CONNECTOR_ID"), timeout=120))
    obs["api_key"] = (who.get("api_key") or {}).get("name")
    write_json(HOME / "observations.json", obs)
    pred = read_json(HOME / "prediction.json") or {}
    print(f"\nObserved under key {obs['api_key']}:")
    for section, item, label in items(probes):
        got = obs[section][item] or "no outcome (run verify again)"
        mine = (pred.get(section) or {}).get(item)
        print(f"  {label}: {got}" + ("" if mine is None else f"   (you predicted {mine})"))
    print(f"\nSaved to {HOME / 'observations.json'}. For every item that differs from your prediction, run: ara-access.py explain")


def explain() -> None:
    p = HOME / "prediction.json"
    pred, obs = read_json(p), read_json(HOME / "observations.json")
    if not pred:
        sys.exit("No prediction recorded yet: run ara-access.py predict first.")
    if not obs:
        sys.exit("No observations yet: run ara-access.py verify with cortex-auditor-key first.")
    mism = S.diff_prediction(pred, obs)
    if not mism:
        print("Every observation matches your prediction. Nothing to explain.")
        return
    probes = json.loads(PROBES.read_text())
    labels = {(s, i): lab for s, i, lab in items(probes)}
    for m in mism:
        k = f"{m['section']}/{m['item']}"
        pred["mechanisms"][k] = pick(f"{labels[(m['section'], m['item'])]}: you predicted {m['predicted']}, observed "
                                     f"{m['observed']}. Which mechanism explains the observation?", S.MECHANISMS)
    write_json(p, pred)
    print(f"\nMechanisms recorded in {p}.")


def ask(question: str) -> None:
    _, kab = key_from_prompt()
    print("Asking Tina (about 30 s) ...")
    resp = kab.converse(AGENT, question)
    route = route_record(resp)
    print("\nTina's tool calls and what each returned:")
    for c in route:
        print(f"  {c.get('tool_id')} {json.dumps(c.get('params'))}")
    for s in resp.get("steps") or []:
        if s.get("type") == "tool_call":
            print(json.dumps(s.get("results"), indent=2, default=str)[:3000])
    print(f"\nTina's answer:\n{(resp.get('response') or {}).get('message', '')}")
    with open(HOME / "conversations.jsonl", "a") as f:
        f.write(json.dumps({"question": question, "conversation_id": resp.get("conversation_id"),
                            "route": [{"tool_id": c.get("tool_id"), "params": c.get("params")} for c in route]}) + "\n")


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in ("predict", "verify", "explain", "ask"):
        print(__doc__)
        return 2
    HOME.mkdir(parents=True, exist_ok=True)
    if argv[0] == "ask":
        if len(argv) < 2:
            sys.exit('Usage: ara-access.py ask "<question>"')
        ask(" ".join(argv[1:]))
    else:
        {"predict": predict, "verify": verify, "explain": explain}[argv[0]]()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
