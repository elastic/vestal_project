"""ara_loop_cli.py - the verbs of ara-loop.py (28 section 3, B2) over injected clients, so they test offline.

    candidate <proposal_id>    copy what the proposal changes (candidate agent, candidate tool copies), apply the
                               change to the copies only, record a `candidate` ledger entry
    gate <proposal_id>         measure the candidate (label gate-<id>), decide by the rule table against the
                               comparison run, record a `gate` entry
    apply <proposal_id>        snapshot what production holds, apply the change to production, record `apply`
    remeasure <proposal_id>    measure production (label remeasure-<id>), compare with the candidate's numbers,
                               record `remeasure` with its outcome
    rollback <proposal_id>     restore the apply's snapshot, record `rollback`
    propose <file.json>        check a proposal against the spec, add proposal_id and run_id, store it in
                               cortex-eval-proposals (6.C's incident fix; 28 section 3: "or by ara-loop.py propose")

The helper stops nothing: apply runs whatever the learner asks (28 section 3, B2: "nothing in the helper stops a
wrong step"); it prints a warning when the gate entry says fail or is missing. The check recomputes everything.

Deps (duck-typed): ab (get_agent, put_agent, get_tool, put_tool, get_skill, put_skill), proposals.get(pid), ledger.append(entry) and
ledger.entries(), measure(label, agent_id) -> trusted-style aggregates, gate (gate.json dict), thresholds (dict),
now() -> ISO string, agent_id (production's agent). P4 (a copy by re-posting a definition) is unverified live: the
fields stripped from a copy are SERVER_FIELDS and the one place to change if a probe says otherwise.
"""
from __future__ import annotations

import copy
import re
from typing import Any

import ara_ledger as G
import ara_loop as L
from agent_builder import is_internal
from ara_integrity import _find

SERVER_FIELDS = ("created_at", "updated_at", "permissions", "readonly")
# P4 (probe r2, 2026-11-12): re-posting a copy is refused (400, "Additional properties are not allowed") for these fields; with them removed the
# agent, ES|QL tool, workflow-type tool and skill copies all created (200) and were visible under the investigator key.
EXTRA_STRIP = {"agent": ("type", "created_by", "updated_by", "hidden"), "tool": ("experimental", "schema"), "skill": ("experimental",)}


def _find_ids(obj: Any, key: str) -> list[str]:
    return _find(obj, (key,)) if obj else []


class LoopError(Exception):
    """A step the helper cannot do (bad input, missing object); the message is for the learner."""


def cand_id(obj_id: str, pid: str) -> str:
    return f"{obj_id}--cand-{pid}"


def _clean(defn: dict, new_id: str, kind: str = "") -> dict:
    drop = set(SERVER_FIELDS) | set(EXTRA_STRIP.get(kind, ()))
    out = {k: copy.deepcopy(v) for k, v in defn.items() if k not in drop}
    if kind == "agent" and isinstance(out.get("access_control"), dict):
        out["access_control"].pop("entries", None)
    out["id"] = new_id
    if kind == "skill":
        out["name"] = new_id  # a skill's name takes letters, numbers, spaces, hyphens and underscores only (" (candidate)" was refused)
    elif "name" in out and isinstance(out["name"], str):
        out["name"] = f"{out['name']} (candidate)"
    return out


def _writable(defn: dict, kind: str) -> dict:
    """A production definition as a write accepts it: the read's server fields left out, nothing renamed (apply and rollback: `readonly` was refused)."""
    drop = set(SERVER_FIELDS) | set(EXTRA_STRIP.get(kind, ()))
    out = {k: copy.deepcopy(v) for k, v in defn.items() if k not in drop}
    if kind == "agent" and isinstance(out.get("access_control"), dict):
        out["access_control"].pop("entries", None)
    return out


def _proposal(d, pid: str) -> dict:
    p = d.proposals.get(pid)
    if p is None:
        raise LoopError(f"no proposal {pid} in cortex-eval-proposals")
    bad = L.validate_proposal(p)
    if bad:
        raise LoopError(f"{pid} does not meet the proposal spec: " + "; ".join(bad))
    return dict(p, proposal_id=pid)


def _entries(d, pid: str, action: str) -> list[dict]:
    return [e for e in d.ledger.entries() if e.get("proposal_id") == pid and e.get("action") == action]


def _prod_object(d, p: dict) -> tuple[str, dict]:
    t = p["target"]
    kind_agent = p["proposal_type"] in ("instruction_change", "attach_tool", "detach_tool")
    obj = d.ab.get_agent(t) if kind_agent else d.ab.get_tool(t)
    if obj is None:
        raise LoopError(f"the {'agent' if kind_agent else 'tool'} {t} does not exist")
    return t, obj


def _remap(obj: Any, key: str, mapping: dict[str, str]) -> None:
    """Replace, in place and wherever a list sits under `key`, each id the mapping names."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key and isinstance(v, list):
                v[:] = [mapping.get(i, i) if isinstance(i, str) else i for i in v]
            else:
                _remap(v, key, mapping)
    elif isinstance(obj, list):
        for v in obj:
            _remap(v, key, mapping)


def _put(put, defn: dict, what: str) -> None:
    code, body = put(defn)
    if code >= 300:
        raise LoopError(f"the candidate {what} {defn['id']} was refused (HTTP {code}): {str(body)[:200]}")


def _swap_source(obj: Any, old: str, new: str) -> int:
    """Point every string in obj that names the index or alias `old` at `new`, in place; returns how many strings changed.
    `old` matches as a whole name: cortex-policies does not match cortex-policies-v1."""
    pat = re.compile(r"(?<![\w.-])" + re.escape(old) + r"(?![\w-])")
    n = 0
    if isinstance(obj, dict):
        for k, v in list(obj.items()):
            if isinstance(v, str):
                nv = pat.sub(new, v)
                if nv != v:
                    obj[k], n = nv, n + 1
            else:
                n += _swap_source(v, old, new)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            if isinstance(v, str):
                nv = pat.sub(new, v)
                if nv != v:
                    obj[i], n = nv, n + 1
            else:
                n += _swap_source(v, old, new)
    return n


def _es(d, method: str, path: str, body: Any = None):
    code, resp = d.es.request(method, path, body)
    return code, resp


def _alias_indices(d, alias: str) -> list[str]:
    code, body = _es(d, "GET", f"/_alias/{alias}")
    return sorted(body) if code == 200 and isinstance(body, dict) else []


def candidate(d, pid: str) -> dict:
    """Candidate copies of the agent, every tool it holds and every skill attached (28 section 1; 29 section 3):
    skill copies point at the tool copies; the sub-agent, workflows and connectors are shared. The proposal's
    change is applied to the copies only; production is read, never written."""
    p = _proposal(d, pid)
    dc = p["change"] if p["proposal_type"] == "data_change" else None
    if dc is not None:
        code, _ = _es(d, "GET", f"/{dc['candidate_source']}/_count")
        if code != 200:
            raise LoopError(f"the candidate_source {dc['candidate_source']} does not exist: build the index or alias that holds the fixed data first")
    agent = d.ab.get_agent(d.agent_id)
    if agent is None:
        raise LoopError(f"the agent {d.agent_id} does not exist")
    if p["proposal_type"] in ("instruction_change", "attach_tool", "detach_tool") and p["target"] != d.agent_id:
        raise LoopError(f"{p['proposal_type']} targets the agent {d.agent_id}, not {p['target']}")
    skills = {sid: d.ab.get_skill(sid) for sid in _find_ids(agent, "skill_ids")}
    for sid, sk in skills.items():
        if sk is None:
            raise LoopError(f"the skill {sid} does not exist")
    wanted = list(_find_ids(agent, "tool_ids"))
    for sk in skills.values():
        wanted += [t for t in _find_ids(sk, "tool_ids") if t not in wanted]
    if p["proposal_type"] == "attach_tool" and p["change"]["tool_id"] not in wanted:
        wanted.append(p["change"]["tool_id"])
    tool_map: dict[str, str] = {}
    tools: dict[str, dict] = {}
    for tid in wanted:
        if is_internal(tid):
            continue
        t = d.ab.get_tool(tid)
        if t is None:
            raise LoopError(f"the tool {tid} does not exist")
        tool_map[tid] = cand_id(tid, pid)
        tools[tid] = _clean(t, tool_map[tid], "tool")
    if p["proposal_type"] in ("tool_description_change", "tool_query_change"):
        if p["target"] not in tools:
            raise LoopError(f"{d.agent_id} does not hold {p['target']}, so a candidate would not read the copy")
        tools[p["target"]] = L.apply_change(tools[p["target"]], p)
    if dc is not None:
        if dc["tool_id"] not in tools:
            raise LoopError(f"{d.agent_id} does not hold {dc['tool_id']}, so a candidate would not read the copy")
        if not _swap_source(tools[dc["tool_id"]], dc["production_source"], dc["candidate_source"]):
            raise LoopError(f"{dc['tool_id']} does not read {dc['production_source']}: nothing to point at {dc['candidate_source']}")
    ca = _clean(agent, cand_id(d.agent_id, pid), "agent")
    skill_map = {sid: cand_id(sid, pid) for sid in skills}
    _remap(ca, "tool_ids", tool_map)
    _remap(ca, "skill_ids", skill_map)
    if p["proposal_type"] == "attach_tool":
        ids = L.tool_id_list(ca)
        if tool_map.get(p["change"]["tool_id"], p["change"]["tool_id"]) not in ids:
            ids.append(tool_map.get(p["change"]["tool_id"], p["change"]["tool_id"]))
    elif p["proposal_type"] == "detach_tool":
        ids = L.tool_id_list(ca)
        ids[:] = [i for i in ids if i not in (p["change"]["tool_id"], tool_map.get(p["change"]["tool_id"]))]
    elif p["proposal_type"] == "instruction_change":
        ca = L.apply_change(ca, dict(p, target=ca["id"]))
    for t in tools.values():
        _put(d.ab.put_tool, t, "tool")
    for sid, sk in skills.items():
        sc = _clean(sk, skill_map[sid], "skill")
        _remap(sc, "tool_ids", tool_map)
        _put(d.ab.put_skill, sc, "skill")
    _put(d.ab.put_agent, ca, "agent")
    entry = {"proposal_id": pid, "action": "candidate", "at": d.now(), "candidate_agent_id": ca["id"],
             "tool_copies": {v: k for k, v in tool_map.items()}, "skill_copies": {v: k for k, v in skill_map.items()},
             "comparison_label": G.comparison_label(d.ledger.entries(), pid)}
    if dc is not None:
        entry["candidate_source"] = dc["candidate_source"]
    d.ledger.append(entry)
    return entry


def gate(d, pid: str) -> dict:
    p = _proposal(d, pid)
    cand = _entries(d, pid, "candidate")
    if not cand:
        raise LoopError(f"{pid} has no candidate: run candidate first")
    c = cand[-1]
    label = f"gate-{pid}"
    if p["proposal_type"] == "data_change":   # the policy questions are scored against the candidate's own data
        cand_agg = d.measure(label, c["candidate_agent_id"], index=p["change"]["candidate_source"])
    else:
        cand_agg = d.measure(label, c["candidate_agent_id"])
    comp_label = c["comparison_label"]
    comp_agg = d.measure_existing(comp_label)
    base = d.measure_existing("m6-baseline") if p["kind"] == "incident_fix" else None
    decision, reason, inputs, rows = L.decide(p, comp_agg, cand_agg, d.gate, baseline=base)
    entry = {"proposal_id": pid, "action": "gate", "at": d.now(), "run_label": label, "comparison_label": comp_label,
             "candidate_agent_id": c["candidate_agent_id"],
             "gate": {"testset_version": d.gate.get("testset_version"), "rules": rows, "inputs": inputs,
                      "decision": decision, "reason": reason}}
    d.ledger.append(entry)
    return entry


def copy_name(source: str, pid: str) -> str:
    """The index that holds what a delete_matching apply removed (one per proposal; the ledger snapshot names it)."""
    return f"{source}-deleted-{pid}".lower()


def _apply_data(d, p: dict, pid: str) -> dict:
    """Production's data changes; the production tool is never repointed (28 section 14 item 42). Returns the snapshot that rollback restores."""
    ch = p["change"]
    src, cand = ch["production_source"], ch["candidate_source"]
    if ch["operation"] == "repoint_alias":
        before = _alias_indices(d, src)
        if not before:
            raise LoopError(f"{src} is not an alias: repoint_alias moves an alias, so name the alias the tool reads")
        code, _ = _es(d, "GET", f"/{cand}/_count")
        if code != 200:
            raise LoopError(f"the candidate_source {cand} does not exist")
        if cand in before:
            raise LoopError(f"{src} already points at {cand}")
        actions = [{"remove": {"index": i, "alias": src}} for i in before] + [{"add": {"index": cand, "alias": src}}]
        code, body = _es(d, "POST", "/_aliases", {"actions": actions})
        if code >= 300:
            raise LoopError(f"the alias move was refused (HTTP {code}): {str(body)[:200]}")
        return {"alias": src, "indices": before, "moved_to": cand}
    keep = copy_name(src, pid)   # delete_matching: keep a copy of what goes, then delete it
    code, body = _es(d, "POST", "/_reindex?refresh=true", {"source": {"index": src, "query": ch["query"]}, "dest": {"index": keep}})
    if code >= 300 or (isinstance(body, dict) and body.get("failures")):
        raise LoopError(f"the copy of the documents to delete was refused (HTTP {code}): {str(body)[:200]}")
    code, body = _es(d, "POST", f"/{src}/_delete_by_query?refresh=true&conflicts=proceed", {"query": ch["query"]})
    if code >= 300:
        raise LoopError(f"the delete was refused (HTTP {code}): {str(body)[:200]}")
    return {"copy": keep, "source": src, "deleted": (body or {}).get("deleted") if isinstance(body, dict) else None}


def _restore_data(d, p: dict, snap: dict) -> None:
    if "alias" in snap:
        now = _alias_indices(d, snap["alias"])
        actions = [{"remove": {"index": i, "alias": snap["alias"]}} for i in now] + [{"add": {"index": i, "alias": snap["alias"]}} for i in snap["indices"]]
        code, body = _es(d, "POST", "/_aliases", {"actions": actions})
        if code >= 300:
            raise LoopError(f"the alias restore was refused (HTTP {code}): {str(body)[:200]}")
        return
    code, body = _es(d, "POST", "/_reindex?refresh=true", {"source": {"index": snap["copy"]}, "dest": {"index": snap["source"]}})
    if code >= 300 or (isinstance(body, dict) and body.get("failures")):
        raise LoopError(f"the restore of the deleted documents was refused (HTTP {code}): {str(body)[:200]}")


def apply(d, pid: str) -> dict:
    p = _proposal(d, pid)
    warn = None
    gates = _entries(d, pid, "gate")
    if not gates:
        warn = f"{pid} has not been gated"
    elif gates[-1]["gate"]["decision"] != "pass":
        warn = f"{pid} failed its gate ({gates[-1]['gate']['reason']})"
    if _entries(d, pid, "apply") and not _entries(d, pid, "rollback"):
        raise LoopError(f"{pid} is already applied")
    if p["proposal_type"] == "data_change":
        snap = _apply_data(d, p, pid)
        entry = {"proposal_id": pid, "action": "apply", "at": d.now(), "snapshot": snap}
        if warn:
            entry["warning"] = warn
        d.ledger.append(entry)
        return entry
    obj_id, prod = _prod_object(d, p)
    try:
        new = L.apply_change(prod, p)
    except KeyError as k:
        raise LoopError(f"the field {k.args[0]} is not in {obj_id}") from None
    is_agent = p["proposal_type"] in ("instruction_change", "attach_tool", "detach_tool")
    put = d.ab.put_agent if is_agent else d.ab.put_tool
    code, body = put(_writable(new, "agent" if is_agent else "tool"))
    if code >= 300:
        raise LoopError(f"production refused the change (HTTP {code}): {str(body)[:200]}")
    entry = {"proposal_id": pid, "action": "apply", "at": d.now(), "snapshot": {obj_id: prod}}
    if warn:
        entry["warning"] = warn
    d.ledger.append(entry)
    return entry


def remeasure(d, pid: str) -> dict:
    p = _proposal(d, pid)
    if not _entries(d, pid, "apply"):
        raise LoopError(f"{pid} has not been applied")
    gates = _entries(d, pid, "gate")
    label = f"remeasure-{pid}"
    agg = d.measure(label, d.agent_id)
    cand_agg = d.measure_existing(gates[-1]["run_label"]) if gates else None
    outcome = G.remeasure_outcome(p, cand_agg, agg, d.thresholds) if cand_agg else "not_confirmed"
    entry = {"proposal_id": pid, "action": "remeasure", "at": d.now(), "run_label": label, "outcome": outcome}
    d.ledger.append(entry)
    return entry


def rollback(d, pid: str) -> dict:
    p = _proposal(d, pid)
    applies = _entries(d, pid, "apply")
    if not applies:
        raise LoopError(f"{pid} has not been applied")
    snap = applies[-1]["snapshot"]
    if p["proposal_type"] == "data_change":
        _restore_data(d, p, snap)
        entry = {"proposal_id": pid, "action": "rollback", "at": d.now()}
        d.ledger.append(entry)
        return entry
    is_agent = p["proposal_type"] in ("instruction_change", "attach_tool", "detach_tool")
    put = d.ab.put_agent if is_agent else d.ab.put_tool
    for obj_id, defn in snap.items():
        code, body = put(_writable(defn, "agent" if is_agent else "tool"))
        if code >= 300:
            raise LoopError(f"production refused the restore of {obj_id} (HTTP {code}): {str(body)[:200]}")
    entry = {"proposal_id": pid, "action": "rollback", "at": d.now()}
    d.ledger.append(entry)
    return entry


def propose(d, path: str) -> dict:
    """Store a proposal the learner wrote (6.C). The file holds one proposal object, or {"proposals": [one]}.
    proposal_id is `prop-` plus eight hex digits of the proposal's own content (so storing the same proposal twice
    gives the same id and is refused), run_id is `manual`. Nothing about prose is checked."""
    import hashlib
    import json
    import pathlib
    try:
        obj = json.loads(pathlib.Path(path).read_text())
    except (OSError, ValueError) as e:
        raise LoopError(f"{path} is not a readable JSON file ({type(e).__name__})") from None
    if isinstance(obj, dict) and isinstance(obj.get("proposals"), list) and len(obj["proposals"]) == 1:
        obj = obj["proposals"][0]
    bad = L.validate_proposal(obj)
    if bad:
        raise LoopError("the proposal does not meet the spec: " + "; ".join(bad))
    body = {k: v for k, v in obj.items() if k not in ("proposal_id", "run_id", "rationale")}
    pid = "prop-" + hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:8]
    if d.proposals.get(pid) is not None:
        raise LoopError(f"{pid} is already stored: it is the same proposal")
    doc = dict(obj, proposal_id=pid, run_id="manual", created_at=d.now(), status="proposed")
    d.proposals.add(doc)
    return {"proposal_id": pid, "action": "propose", "at": doc["created_at"]}


VERBS = {"candidate": candidate, "gate": gate, "apply": apply, "remeasure": remeasure, "rollback": rollback, "propose": propose}


def summary(entry: dict) -> str:
    """One line the learner reads after a verb."""
    a, pid = entry["action"], entry["proposal_id"]
    if a == "gate":
        g = entry["gate"]
        return f"{pid}: gate {g['decision']} ({g['reason']}) against {entry['comparison_label']}"
    if a == "remeasure":
        return f"{pid}: re-measure {entry['outcome']}"
    if a == "candidate":
        return f"{pid}: candidate {entry['candidate_agent_id']} built; compared with {entry['comparison_label']}"
    if a == "propose":
        return f"{pid}: stored in cortex-eval-proposals; next: candidate {pid}"
    return f"{pid}: {a} recorded" + (f" (warning: {entry['warning']})" if entry.get("warning") else "")
