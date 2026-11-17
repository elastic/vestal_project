"""ara_manifest_m6.py - the M6 start-state manifests (28 section 8.4) as data, and their lint.

    build() -> {manifest id: manifest}        every manifest, generated here so the chain and the rules are one source
    write(dir)                                write manifests/m6/<id>.json (the committed copies; test_ara_manifest_m6 keeps them in step)
    lint(manifests) -> [problems]             the rules below

A manifest names objects, not secrets or answers: Tina's hardening block and each variant's defect are private overlays (design decision of
2026-11-11; 29 section 3), resolved by setup from the track's private files and applied root-side; no file name is written here.
Rules: every `extends` resolves and the chain has no cycle; no workflow carries a scheduled trigger, anywhere in a chain; Tina
has the hardening overlay from `ara-m5-end` on and no manifest holds the block's text; a manifest that places a held-out defect or
fault points at its overlay; every index has a committed mapping file; a run label is listed once per manifest. Standard library only.
"""
from __future__ import annotations

import json
import pathlib

PRIVATE = "private overlay: resolved by setup from the track's private files, not named here"
HARDEN_OVERLAY = {"tina-compliance": {"append_instructions": PRIVATE}}   # the 5.2 reference's block
LABEL_RULE = "a run label is listed once per manifest (each track re-measures its own m6-baseline on its own start state)"
INDICES = {"cortex-eval-proposals": "data/ara-m6/mappings/cortex-eval-proposals.json", "cortex-eval-ledger": "data/ara-m6/mappings/cortex-eval-ledger.json",
           "cortex-change-log": "data/ara-m6/mappings/cortex-change-log.json", "cortex-audit": "data/ara-m6/mappings/cortex-audit.json",
           "cortex-canary-raw": "data/ara-m6/mappings/cortex-canary-raw.json"}


def wf(wid: str, source: str, attached_to=None) -> dict:
    return {"id": wid, "source": source, "enabled": True, "triggers": ["manual"], **({"attached_to": attached_to} if attached_to else {})}


def build() -> dict[str, dict]:
    m: dict[str, dict] = {}
    m["ara-m5-end"] = {"id": "ara-m5-end", "extends": "ara-m5-5-2-start", "overlay": HARDEN_OVERLAY,
        "_doc": "The M5 reference end M6 builds on (28 section 8.3; design decision of 2026-11-11: unhandicapped Tina, no 5.4 change). Contract, composed by setup from the 5.3 reference end: Tina carries the 5.2 hardening block (private overlay), the read-page guard is in place, leftover reach cleared, PII variant A, tina-eval and cortex-eval-runs exist, test set v1 and the rate card are loaded. Includes nothing from 5.4 or 5.C.",
        "run_labels": []}
    m["ara-m6-6-1-start"] = {"id": "ara-m6-6-1-start", "extends": "ara-m5-end",
        "_doc": "Lab 6.1 (28 section 2): ara-m5-end + trace content settings (includeSystemPrompt and includeUserData off, everything else in 28 section 8.6 on, set before the first conversation) + pack T (A, B or C by seed, loaded and verified) + the variant's defect live in cortex.structuring_deposits (private overlay: the query, parameters and description are as M4 built them) + ticket.md, capabilities.md, and the root-held held-out files.",
        "settings": {"agentBuilder:tracing:includeSystemPrompt": False, "agentBuilder:tracing:includeUserData": False},
        "pack": {"variants": ["A", "B", "C"], "source": "data/ara-m6/traces/T-<variant>/", "verify": "root-held manifest", "load": "ara-packs.py load --end-hours-before 1"},
        "overlay": {"cortex.structuring_deposits": {"query_variant": PRIVATE}},
        "files": ["/home/elastic/cortex-traces/ticket.md", "/home/elastic/cortex-traces/capabilities.md"],
        "heldout": "root-only files in the sandbox, installed from the track's private files and not named here", "run_labels": []}
    m["ara-m6-6-1-end"] = {"id": "ara-m6-6-1-end", "extends": "ara-m6-6-1-start",
        "_doc": "The 6.1 reference end: cortex.structuring_deposits fixed (the defect removed; id, parameters and description unchanged) and the variant's capability tool built and NOT attached (variant A's cortex.account_history is the one 6.2's unattached-tool pattern uses).",
        "overlay": {"cortex.structuring_deposits": {"query_variant": PRIVATE}},
        "tools_added_unattached": ["cortex.account_history"], "run_labels": []}
    m["ara-m6-6-2-start"] = {"id": "ara-m6-6-2-start", "extends": "ara-m6-6-1-end",
        "_doc": "Lab 6.2 (28 section 3): the 6.1 reference end + week pack W (W1-W3) + W's patterns installed live before m6-baseline + the change policy variant + the week's two named proposals + cortex-evaluator-run skeleton + role cortex-evaluator-reader + empty ledger + ara-loop.py + the proposal examples + m6-baseline by setup (detached during the Brief).",
        "pack": {"variants": ["W1", "W2", "W3"], "source": "data/ara-m6/traces/W<n>/"},
        "patterns_live": ["double_search", "short_default_window", "needless_question", "oversized_result", "unattached_tool"],
        "indices": INDICES, "roles": ["cortex-evaluator-reader"], "workflows": [wf("cortex-evaluator-run", "ara_workflows_m6.evaluator_run_yaml")],
        "files": ["/home/elastic/cortex-loop/change-policy.md", "/home/elastic/cortex-loop/proposal-examples/"],
        "seeded_docs": {"cortex-eval-proposals": ["prop-review-1", "prop-review-2"]}, "run_labels": ["m6-baseline"]}
    m["ara-m6-6-2-end"] = {"id": "ara-m6-6-2-end", "extends": "ara-m6-6-2-start",
        "_doc": "The 6.2 reference end: W1's patterns live, W1's good proposal applied, cortex-evaluator built, the ledger filled by the reference run. No scheduled trigger.",
        "agents": [{"id": "cortex-evaluator", "tools": "custom ES|QL, read-only, bounded; no built-ins, skills or sub-agents"}], "run_labels": []}
    m["ara-m6-6-3-start"] = {"id": "ara-m6-6-3-start", "extends": "ara-m6-6-2-end",
        "_doc": "Lab 6.3 (28 section 4): the 6.2 reference end + cortex-canary-run (manual only) + cortex-policy-lexical + cortex-answer-audit (not attached) + cortex-deploy.sh + cortex-change-log + canary-v1 + the ops scenario sheet (O1-O3). No scheduled trigger anywhere.",
        "workflows": [wf("cortex-canary-run", "ara_workflows_m6.canary_run_yaml"), wf("cortex-answer-audit", "ara_workflows_m6.answer_audit_yaml")],
        "files": ["/home/elastic/cortex-ops/cortex-deploy.sh", "/home/elastic/cortex-ops/scenarios.md"], "search_templates": ["cortex-policy-lexical"],
        "testsets": ["canary-v1"], "run_labels": []}
    m["ara-m6-6-3-end"] = {"id": "ara-m6-6-3-end", "extends": "ara-m6-6-3-start",
        "_doc": "The 6.3 reference end (28 section 8.4): cortex-answer-audit attached to Tina (post-execution), no scheduled trigger; the learner's triggers are removed by cleanup.",
        "workflows": [wf("cortex-answer-audit", "ara_workflows_m6.answer_audit_yaml", attached_to="tina-compliance")], "run_labels": []}
    m["ara-m6-6-4-start"] = {"id": "ara-m6-6-4-start", "extends": "ara-m6-6-3-end",
        "_doc": "Lab 6.4 (28 section 5): the 6.3 reference end + 30-day canary history H1-H3 + change log with decoys + one live degradation L1-L3 seeded after m6-baseline, measured as m6-degraded. Every scheduled trigger removed; the canary keeps its manual trigger.",
        "history": {"variants": ["H1", "H2", "H3"], "days": 30, "runs_per_day": 3, "label_prefix": "canary-seed"},
        "degradation": {"variants": ["L1", "L2", "L3"], "applied_by": "ara_seed_driver.seed", "after": "m6-baseline"},
        "run_labels": ["m6-baseline", "m6-degraded"]}
    m["ara-m6-capstone-start"] = {"id": "ara-m6-capstone-start", "extends": "ara-m6-6-3-end",
        "_doc": "Capstone 6.C (07 section 3.2): the 6.3 reference end (not 6.4) + a 30-day canary history whose last night drops + trace pack + change log (cause and decoy) + the change-policy variant with its reference gate.json (incident block included) + ara-loop.py + m6-baseline before the seed + one seed C1-C3 then m6-degraded. Desk: America/New_York, shifts 06:00, 14:00, 22:00, opens 07:00.",
        "history": {"variants": ["C1", "C2", "C3"], "days": 30, "runs_per_day": 3, "last_night_degraded": True},
        "degradation": {"variants": ["C1", "C2", "C3"], "applied_by": "ara_seed_driver.seed", "after": "m6-baseline"},
        "files": ["/home/elastic/cortex-loop/change-policy.md", "/home/elastic/cortex-loop/gate.json"], "run_labels": ["m6-baseline", "m6-degraded"]}
    m["ara-m6-end"] = {"id": "ara-m6-end", "extends": "ara-m6-6-3-end",
        "_doc": "The M6 end (28 section 8.4): the 6.4 reference end with the live degradation fixed and every scheduled trigger removed: Tina with the 6.1 fix and the 6.2 change, cortex-evaluator, the canary and audit workflows, the ledger, the change log, the M5 harness, canary-v1. The exam's practical-task base.",
        "run_labels": []}
    return m


def _chain(ms: dict, mid: str) -> list[str]:
    out, seen = [], set()
    while mid:
        if mid in seen:
            raise ValueError(f"extends cycle at {mid}")
        seen.add(mid)
        out.append(mid)
        mid = (ms.get(mid) or {}).get("extends")
        if mid and mid not in ms and not mid.startswith("ara-m5-"):
            raise ValueError(f"{out[-1]} extends {mid}, which is not defined")
    return out


def lint(ms: dict[str, dict], hardening_text: str | None = None) -> list[str]:
    bad = []
    for mid, m in ms.items():
        try:
            chain = _chain(ms, mid)
        except ValueError as e:
            bad.append(str(e)); continue
        for w in m.get("workflows", []):
            if w.get("enabled") is not True or w.get("triggers") != ["manual"]:
                bad.append(f"{mid}: workflow {w.get('id')} must be enabled with a manual trigger only (no scheduled trigger in any start state)")
        for name in m.get("indices", {}):
            if name not in INDICES or not pathlib.Path(INDICES[name]).name:
                bad.append(f"{mid}: index {name} has no committed mapping")
        labels = m.get("run_labels", [])
        if len(labels) != len(set(labels)):
            bad.append(f"{mid}: {LABEL_RULE}")
        text = json.dumps(m)
        if hardening_text and hardening_text[:60] in text:
            bad.append(f"{mid}: the hardening block's text is in the manifest (it is a private overlay)")
        if "defect" in text.lower() and "overlay" not in m and PRIVATE not in text:
            bad.append(f"{mid}: names a defect without pointing at its private overlay")
    top = ms.get("ara-m5-end")
    if not top or "tina-compliance" not in (top.get("overlay") or {}):
        bad.append("ara-m5-end: Tina's hardening block must be a private overlay")
    return bad


def write(directory: str | pathlib.Path) -> list[str]:
    d = pathlib.Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    for mid, m in build().items():
        (d / f"{mid}.json").write_text(json.dumps(m, indent=1, sort_keys=True) + "\n")
    return sorted(build())
