#!/usr/bin/env python3
"""ara-setup6.py - run the M6 setup plan in a sandbox (root, from provision.sh).

  python3 ara-setup6.py plan <track> <seed_mod>     print the ordered steps (no network)
  python3 ara-setup6.py run  <track> <seed_mod>     execute; reads ES_URL, ES_API_KEY, KIBANA_URL, KIBANA_API_KEY from the environment

Steps built here are HTTP and file writes (ara_setup6.Setup6) and subprocess calls to ara-packs.py and ara-eval.py. Steps that need
captured live data (defect, heldout, history_load, change_log, seed, testset, search_template, patterns, proposals_seed, policy_files,
fresh_round) are listed in NEEDS_LIVE and refuse with exit 3 until a builder wires them from the probe results (m6/probes, P1-P9).
Nothing here enables a schedule; the last step lists every workflow and fails if one carries a scheduled trigger.
Exit: 0 done, 1 a step failed, 2 usage, 3 a step is not wired yet.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import ara_setup6 as S  # noqa: E402

NEEDS_LIVE = ()  # steps that refuse until a builder wires them (none now)


class NotWired(RuntimeError):
    pass


def _refuse(name):
    def f(**a):
        raise NotWired(f"step {name} is not wired yet (needs probe results)")
    return f


class Router:
    """One client for plan operations: Kibana API paths (/api, /internal) go to Kibana, everything else to Elasticsearch."""

    def __init__(self, es, kb):
        self.es, self.kb = es, kb

    def _to(self, path):
        return self.kb if path.startswith(("/api/", "/internal/")) else self.es

    def request(self, m, p, b=None):
        return self._to(p).request(m, p, b)

    def request_ndjson(self, m, p, t):
        return self._to(p).request_ndjson(m, p, t)


def handlers(setup: S.Setup6, steps=None) -> dict:
    h = {n: _refuse(n) for n in NEEDS_LIVE}
    if steps is not None:
        h.update(steps.handlers())
    h.update({"settings": setup.settings, "indices": setup.indices, "roles": setup.roles, "workflows": setup.workflows,
              "verify_no_schedule": setup.verify_no_schedule})
    return h


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[0] not in ("plan", "run") or argv[1] not in S.TRACKS or not argv[2].isdigit():
        print(__doc__); return 2
    plan_steps = S.plan(argv[1], int(argv[2]))
    if argv[0] == "plan":
        for st in plan_steps:
            print(json.dumps(st))
        return 0
    import agent_builder as AB
    import ara_workflows_m6 as WM
    import urllib.request

    def call(base, key):
        def f(m, p, b):
            req = urllib.request.Request(base + p, method=m, data=None if b is None else json.dumps(b).encode(),
                                         headers={"Authorization": f"ApiKey {key}", "Content-Type": "application/json", "kbn-xsrf": "true",
                                                      **({"x-elastic-internal-origin": "kibana"} if p.startswith("/internal/") else {})})
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    t = r.read().decode()
                    return r.status, (json.loads(t) if t else {})
            except urllib.error.HTTPError as e:
                try:
                    return e.code, json.loads(e.read().decode() or "{}")
                except ValueError:
                    return e.code, {}
        return f
    env = os.environ
    # The module assets: /opt/ara/src in a sandbox (lib is copied to /opt/ara/lib, so lib's parent has no data/); the repo root when run from a checkout.
    assets_root = pathlib.Path(env.get("ARA_ASSETS") or ("/opt/ara/src" if pathlib.Path("/opt/ara/src/data").is_dir() else str(pathlib.Path(__file__).resolve().parent.parent)))
    ab = AB.AB(env["KIBANA_URL"], env["KIBANA_API_KEY"])
    setup = S.Setup6(ab, call(env["KIBANA_URL"], env["KIBANA_API_KEY"]), call(env["ES_URL"], env["ES_API_KEY"]), pathlib.Path("/"),
                     assets_root,
                     {"cortex-canary-run": WM.canary_run_yaml, "cortex-answer-audit": WM.answer_audit_yaml,
                      "cortex-evaluator-run": lambda: WM.evaluator_run_yaml(env.get("INFERENCE_ID") or env.get("ARA_AB_CONNECTOR_ID", ""), env.get("AGENT_ID", "tina"), "cortex-evaluator-run")})
    import datetime
    import subprocess
    from ara_security import ES
    import ara_setup6_steps as SS
    es = ES(env["ES_URL"].rstrip("/"), f"ApiKey {env['ES_API_KEY']}", timeout=300)
    kb = ES(env["KIBANA_URL"].rstrip("/"), f"ApiKey {env['KIBANA_API_KEY']}", timeout=300)
    lib = pathlib.Path(__file__).resolve().parent
    work = pathlib.Path(env.get("M6_WORKDIR", "/root/m6"))
    work.mkdir(parents=True, exist_ok=True)
    st = SS.Steps6(es.request, es.request_ndjson, lambda argv: subprocess.run(argv, env=dict(env)).returncode,
                   datetime.datetime.now(datetime.timezone.utc), env.get("INSTRUQT_PARTICIPANT_ID", "default"), pathlib.Path("/"),
                   assets_root, lib, argv[1], env.get("AGENT_ID", "tina-compliance"), Router(es, kb), str(work), ab)
    try:
        S.run(plan_steps, handlers(setup, st))
    except (NotWired, SS.DataMissing) as e:
        print(f"ara-setup6: {e}", file=sys.stderr); return 3
    except Exception as e:  # noqa: BLE001
        print(f"ara-setup6: {e}", file=sys.stderr); return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
