"""ara_setup6.py - the M6 setup steps as a plan, and a runner over injected handlers (28 section 8; 29 section 3).

    variants(seed_mod)            {"pack": "A"|"B"|"C", "week": 1-3, "policy": 0-2, "ops": "O1"-"O3", "history": 1-3, "live": "L1"-"L3", "capstone": "C1"-"C3"}
    plan(track, seed_mod)         the ordered steps for one track: [{"name", "args", "needs", "detached"}]
    run(plan, handlers, log)      execute in order; a step runs only after its `needs`; the first failure stops the run
    Setup6                        handlers for the steps that are only HTTP and file writes (settings, indices, roles, workflows,
                                  files, the no-schedule check); packs, measures and seeds are callables the caller injects

seed_mod = sum(ord(c) for c in participant) % 30 as M5 (seed % 3 picks a pack, (seed // 3) % 3 the policy, and so on). The order is the
contract: settings before the first conversation; a pack before the defect it records; every pattern or defect applied BEFORE `m6-baseline`
only where the spec says so (6.2: patterns before the baseline; 6.4 and 6.C: the baseline BEFORE the seed, then `m6-degraded`); and
`verify_no_schedule` last in every track, so no start state can carry a scheduled trigger even by a mistake in a step. Standard library only.
"""
from __future__ import annotations

import json
import pathlib
from typing import Any, Callable

import ara_workflow as W

TRACKS = ("6-1", "6-2", "6-3", "6-4", "6-c")
INHERITED_SCHEDULES = ("cortex-structuring-sweep",)  # the 4.2 deliverable Tina carries from M4: scheduled and enabled


def variants(seed_mod: int) -> dict:
    s = seed_mod % 30
    return {"pack": "ABC"[s % 3], "week": s % 3 + 1, "policy": (s // 3) % 3, "ops": f"O{s % 3 + 1}", "history": s % 3 + 1,
            "live": f"L{s % 3 + 1}", "capstone": f"C{s % 3 + 1}", "payload_set": (s // 3) % 5}


def _s(name: str, needs=(), detached: bool = False, **args) -> dict:
    return {"name": name, "args": args, "needs": list(needs), "detached": detached}


def plan(track: str, seed_mod: int) -> list[dict]:
    if track not in TRACKS:
        raise ValueError(f"unknown track {track}")
    v = variants(seed_mod)
    steps = [_s("settings", tracing=True, include_system_prompt=False, include_user_data=False),
             _s("variant", seed_mod=seed_mod % 30, **{k: v[k] for k in ("pack", "week", "policy", "ops", "history", "live", "capstone")})]
    if track == "6-1":
        steps += [_s("exceptions", ["settings"]),
                  _s("pack_load", ["settings"], pack=f"T-{v['pack']}", variant=v["pack"]),
                  _s("defect", ["pack_load"], variant=v["pack"]),
                  _s("files", ["pack_load"], names=["ticket.md", "capabilities.md"], variant=v["pack"]),
                  _s("heldout", ["defect", "exceptions"], names=["structuring.json", "gap.json"], variant=v["pack"]),
                  _s("fresh_round", ["settings"])]
    if track in ("6-2", "6-3", "6-4", "6-c"):
        steps += [_s("indices", ["settings"], names=["cortex-eval-proposals", "cortex-eval-ledger", "cortex-change-log"] + (["cortex-canary-raw", "cortex-audit"] if track != "6-2" else [])),   # the canary and audit workflows write these: keyword ids, not dynamic text
                  _s("roles", ["settings"], names=["cortex-evaluator-reader"])]
    if track == "6-2":
        steps += [_s("pack_load", ["indices"], pack=f"W{v['week']}", variant=f"W{v['week']}"),
                  _s("patterns", ["pack_load"], week=v["week"]),
                  _s("policy_files", ["indices"], variant=v["policy"]),
                  _s("proposals_seed", ["indices", "patterns"], ids=["prop-review-1", "prop-review-2"], week=v["week"], policy=v["policy"]),
                  _s("workflows", ["indices"], ids=["cortex-evaluator-run"]),
                  _s("baseline", ["patterns", "workflows"], detached=True, label="m6-baseline", testset="gate-v1.1"),
                  _s("baseline_agg", ["baseline"]), _s("start_snapshot", ["baseline"])]
    if track in ("6-3",):
        steps += [_s("workflows", ["indices"], ids=["cortex-canary-run", "cortex-answer-audit"]),
                  _s("testset", ["indices"], version="canary-v1"),
                  _s("search_template", ["indices"], id="cortex-policy-lexical"),
                  _s("files", ["workflows"], names=["cortex-deploy.sh", "scenarios.md"], variant=v["ops"]),
                  _s("baseline", ["workflows", "testset"], detached=True, label="m6-baseline"),
                  _s("start_snapshot", ["baseline"])]
    if track in ("6-4", "6-c"):
        # 6.C gates on gate-v1.1 (the module's one gate set, 07 section 3.4): the 8-question canary set cannot resolve a tool-call limit of 10-20 percent (one extra call is 17 percent)
        gs = "gate-v1.1" if track == "6-c" else "canary-v1"
        steps += [_s("workflows", ["indices"], ids=["cortex-canary-run", "cortex-answer-audit"]),
                  _s("testset", ["indices"], version=gs),
                  _s("search_template", ["indices"], id="cortex-policy-lexical"),
                  _s("history_load", ["indices", "testset"], variant=v["history"] if track == "6-4" else v["capstone"], last_night_degraded=(track == "6-c")),
                  _s("change_log", ["history_load"]),
                  _s("baseline", ["workflows", "testset"], detached=True, label="m6-baseline", testset=gs),
                  _s("seed", ["baseline", "change_log"], layer=v["live"] if track == "6-4" else v["capstone"]),
                  _s("degraded", ["seed"], detached=True, label="m6-degraded", testset=gs),
                  _s("baseline_agg", ["baseline"]), _s("start_snapshot", ["degraded"])]
        if track == "6-c":
            steps += [_s("policy_files", ["indices"], variant=v["policy"], incident=True), _s("files", ["workflows"], names=["gate.json"], variant=v["policy"])]
    steps.append(_s("verify_no_schedule", [s["name"] for s in steps]))
    return steps


def run(steps: list[dict], handlers: dict[str, Callable], log: Callable = print) -> list[str]:
    done: list[str] = []
    for st in steps:
        missing = [n for n in st["needs"] if n not in done]
        if missing:
            raise RuntimeError(f"step {st['name']} needs {', '.join(missing)} first")
        fn = handlers.get(st["name"])
        if fn is None:
            raise RuntimeError(f"no handler for step {st['name']}")
        log(f"setup6: {st['name']}{' (detached)' if st['detached'] else ''}")
        fn(**st["args"])
        done.append(st["name"])
    return done


class Setup6:
    """Handlers that are only HTTP and file writes. `ab` is agent_builder.AB; `kb` and `es` are (method, path, body) -> (code, body);
    `root` is the directory the files and held-out files are written under (a sandbox's /; a temp dir in tests)."""

    def __init__(self, ab, kb: Callable, es: Callable, root: pathlib.Path, assets: pathlib.Path, workflow_sources: dict[str, Callable[[], str]]):
        self.ab, self.kb, self.es, self.root, self.assets, self.sources = ab, kb, es, root, assets, workflow_sources

    def settings(self, tracing: bool, include_system_prompt: bool, include_user_data: bool) -> None:
        changes = {"agentBuilder:tracing:enabled": tracing, "agentBuilder:tracing:includeRealNames": True, "agentBuilder:tracing:includeRealIds": True,
                   "agentBuilder:tracing:includeUserPrompts": True, "agentBuilder:tracing:includeToolDetails": True, "agentBuilder:tracing:includeLlmResponses": True,
                   "agentBuilder:tracing:includeSystemPrompt": include_system_prompt, "agentBuilder:tracing:includeUserData": include_user_data}
        code, cur = self.kb("GET", "/internal/kibana/settings", None)  # the platform refuses a write of `enabled` (HTTP 400); it is on already
        cur = ((cur.get("settings") or cur) if code == 200 and isinstance(cur, dict) else {})
        for k, val in changes.items():
            have = cur.get(k)
            if (have.get("userValue") if isinstance(have, dict) else have) == val:
                continue
            code, body = self.kb("POST", "/internal/kibana/settings", {"changes": {k: val}})
            if code != 200:
                raise RuntimeError(f"setting {k} refused (HTTP {code}): {str(body)[:300]}; current read {str({a: b for a, b in cur.items() if 'tracing' in a})[:400]}")

    def indices(self, names: list[str]) -> None:
        for n in names:
            mapping = json.loads((self.assets / "data/ara-m6/mappings" / f"{n}.json").read_text())
            self.es("DELETE", f"/{n}?ignore_unavailable=true", None)
            code, body = self.es("PUT", f"/{n}", mapping)
            if code != 200:
                raise RuntimeError(f"index {n} refused (HTTP {code})")

    def roles(self, names: list[str]) -> None:
        defs = json.loads((self.assets / "data/ara-m6/roles/m6-roles.json").read_text())
        for n in names:
            code, body = self.es("PUT", f"/_security/role/{n}", defs[n])
            if code != 200:
                raise RuntimeError(f"role {n} refused (HTTP {code})")

    def workflows(self, ids: list[str]) -> None:
        import ara_workflows_m6 as WM
        for wid in ids:
            text = self.sources[wid]()
            if W_scheduled(text):
                raise RuntimeError(f"{wid} carries a scheduled trigger")
            code, body = self.ab.put_workflow(wid, text)
            invalid = isinstance(body, dict) and body.get("valid") is False
            if invalid and WM.placeholders_left(text):
                # The skeleton's placeholders make it invalid by design (stored, enabled false, valid false); the learner's fill makes it valid.
                print(f"ara-setup6: workflow {wid} stored with its placeholders (the platform marks it invalid until they are filled)", flush=True)
                continue
            if code >= 300 or invalid:
                raise RuntimeError(f"workflow {wid} refused (HTTP {code}): {str(body)[:900]}")

    def write_file(self, rel: str, text: str, mode: int = 0o644) -> None:
        p = self.root / rel.lstrip("/")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        p.chmod(mode)

    def verify_no_schedule(self) -> None:
        """Every workflow in the space: none may carry a scheduled trigger (29 section 3)."""
        # The list route is not in the probe results (GET /api/workflows/workflow?size=500 is 404). Try the search route, then the
        # collection routes; when none answers, check the workflows this setup knows by id, and say so.
        rows, how = None, None
        for m, path, b in (("POST", "/api/workflows/search", {"size": 500, "page": 1}), ("GET", "/api/workflows?size=500", None),
                           ("GET", "/api/workflows/search?size=500", None)):
            code, body = self.kb(m, path, b)
            if code == 200 and isinstance(body, dict):
                rows, how = body.get("results") or body.get("workflows") or body.get("data") or [], f"{m} {path}"
                break
        if rows is None:
            rows, how = [{"id": w} for w in self.sources], "known ids (no list route answered)"
        print(f"ara-setup6: verify_no_schedule read workflows by {how}: {len(rows)}", flush=True)
        bad = []
        for r in rows:
            wid = r.get("id")
            full = self.ab.get_workflow(wid) or {}
            text = full.get("yaml") or ""
            if wid in INHERITED_SCHEDULES and W_scheduled(text):
                # Tina's M4 end state carries the 4.2 daily sweep, scheduled and enabled. M6 starts without any schedule (29 section 3):
                # strip the trigger, keep the manual one, and read it back.
                import ara_workflows_m6 as WM
                code, _ = self.ab.put_workflow(wid, WM.strip_scheduled(text))
                if code not in (200, 201):
                    raise RuntimeError(f"could not remove the inherited schedule from {wid} (HTTP {code})")
                text = (self.ab.get_workflow(wid) or {}).get("yaml") or ""
                print(f"ara-setup6: removed the inherited scheduled trigger from {wid}", flush=True)
            if W_scheduled(text):
                bad.append(wid)
        if bad:
            raise RuntimeError("scheduled trigger present on: " + ", ".join(bad))


def W_scheduled(text: str) -> bool:
    import ara_workflows_m6 as WM
    return bool(WM.scheduled_triggers(text))
