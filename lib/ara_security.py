"""ara_security.py - roles, keys and what a key can reach, for M5 (25 section 1, security helper).

Used by 5.1 (prediction verifier, B1 and B2 checks), 5.2 B3 and 5.C. Standard library only.

Keys. Every key is minted by the project admin user over basic auth (Phase 0 0-c: an API key gets a
400 from _security/api_key with role descriptors, and a role key cannot mint). So one user owns every
key in a sandbox; P4 (conversations belong to the user, not the key) is a Brief fact, never graded.

Observations are made the way the checks make them: _search and ES|QL against Elasticsearch, and
tools/_execute against Kibana, each under the key. A 403 under a key is an observation, not an outage.

    admin = ES(es_url, basic_auth(user, password))
    key = mint_key(admin, "cortex-check-l1", {"cortex-analyst-l1": descriptor})
    k = ES(es_url, api_key_auth(key["encoded"]))
    reach = search_reach(k, "cortex-cases", "case_id")
    outcome = execute_outcome(AB(kibana_url, key["encoded"]), "cortex.case_lookup", {"case_type": "structuring"})
"""
from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.request
from typing import Any

from agent_builder import ENV_ERR, ABError, RemoteCallFailed, run_outcome

# B1's closed list of tool outcome classes (25 section 2, 02-predict-a-keys-reach).
OUTCOMES = ("rows", "no_rows", "error_hidden_field", "error_not_authorized", "error_at_write")
# B1's closed list of mechanisms for a mismatch.
MECHANISMS = ("dls_filtered", "fls_hidden", "query_names_hidden_field", "missing_kibana_privilege",
              "missing_index_privilege", "not_restricted")

# r2 X: an ES|QL tool naming an FLS-hidden column answers 200 with an error result
# "verification_exception ... Unknown column [subject_name]".
HIDDEN_FIELD_ERR = re.compile(r"Unknown column \[", re.I)
# r2 X: a key without workflow_execute gets "Unauthorized to execute workflow '<id>'. The
# 'workflowsManagement' execute privilege is required." The Elasticsearch forms (security_exception,
# "is unauthorized for API key") are for a tool over an index the key cannot read: probe r6 got
# security_exception from _execute for an ES|QL tool and an index search tool.
NOT_AUTHORIZED_ERR = re.compile(r"\bUnauthorized to\b|privilege is required|security_exception|is unauthorized for", re.I)

_OUTAGE = (401, 408, 429)  # 403 is left to the caller: under a learner or check key it is an observation


def basic_auth(username: str, password: str) -> str:
    return "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()


def api_key_auth(encoded: str) -> str:
    return f"ApiKey {encoded}"


class ES:
    """An Elasticsearch client bound to one Authorization header. Errors as agent_builder.AB: no
    answer, 401, 408, 429 and 5xx raise ABError (an outage for ara_grade.remote()); any other status,
    403 included, is returned as (code, body)."""

    def __init__(self, url: str, auth: str, timeout: float = 30):
        self.url = url.rstrip("/")
        self.auth = auth
        self.timeout = timeout

    def request(self, method: str, path: str, body: Any = None) -> tuple[int, Any]:
        return self._send(method, path, json.dumps(body).encode() if body is not None else None, "application/json")

    def request_ndjson(self, method: str, path: str, ndjson: str) -> tuple[int, Any]:
        """_bulk and the other NDJSON endpoints."""
        return self._send(method, path, ndjson.encode(), "application/x-ndjson")

    def _send(self, method: str, path: str, data: bytes | None, content_type: str) -> tuple[int, Any]:
        headers = {"Content-Type": content_type, "Authorization": self.auth}
        req =urllib.request.Request(f"{self.url}{path}", data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                code, txt = resp.status, resp.read().decode()
        except urllib.error.HTTPError as e:
            code, txt = e.code, e.read().decode(errors="replace")
        except Exception as e:  # refused, reset, DNS, timeout
            raise RemoteCallFailed(f"{method} {path}: {type(e).__name__}: {e}") from None
        try:
            parsed = json.loads(txt) if txt else {}
        except ValueError:
            parsed = {"raw": txt[:500]}
        if code in _OUTAGE or code >= 500:
            raise ABError(f"{method} {path}: HTTP {code} {str(parsed)[:300]}", code)
        return code, parsed


# ── roles and keys ───────────────────────────────────────────────────────────

def put_role(admin: ES, name: str, descriptor: dict) -> tuple[int, Any]:
    """Create or replace a named role from a role spec (one role descriptor)."""
    return admin.request("PUT", f"/_security/role/{name}", descriptor)


def get_role(admin: ES, name: str) -> dict | None:
    code, body = admin.request("GET", f"/_security/role/{name}")
    return body.get(name) if code == 200 and isinstance(body, dict) else None


def mint_key(admin: ES, name: str, role_descriptors: dict, expiration: str = "1h",
             metadata: dict | None = None) -> dict:
    """Mint an API key with these role descriptors. admin must carry basic auth (0-c). Returns
    {"id", "name", "encoded"}; raises ValueError with the refusal when Elasticsearch refuses."""
    if not admin.auth.startswith("Basic "):
        raise ValueError("mint_key needs the admin user's basic auth: a key minted by an API key has no authority")
    body = {"name": name, "role_descriptors": role_descriptors, "expiration": expiration}
    if metadata:
        body["metadata"] = metadata
    code, resp = admin.request("POST", "/_security/api_key", body)
    if code != 200:
        raise ValueError(f"key {name} refused: HTTP {code} {str(resp)[:300]}")
    return {"id": resp["id"], "name": resp["name"], "encoded": resp["encoded"]}


def keys_named(admin: ES, name: str) -> list[dict]:
    """Every key with this name, invalidated ones included, each with role_descriptors, limited_by and
    creation (epoch ms). B1 orders the prediction against the creation time of every key carrying the
    variant's descriptors."""
    code, body = admin.request("GET", f"/_security/api_key?name={name}&with_limited_by=true")
    return list(body.get("api_keys") or []) if code == 200 else []


def key_info(admin: ES, key_id: str) -> dict | None:
    code, body = admin.request("GET", f"/_security/api_key?id={key_id}&with_limited_by=true")
    keys = body.get("api_keys") if code == 200 else None
    return keys[0] if keys else None


def invalidate_key(admin: ES, key_id: str) -> bool:
    code, body = admin.request("DELETE", "/_security/api_key", {"ids": [key_id]})
    return code == 200 and key_id in (body.get("invalidated_api_keys") or [])


def _norm_privileges(ps: list | None) -> list:
    return sorted(set(ps or []))


def normalise_descriptor(d: dict) -> dict:
    """A role descriptor in a comparable form: privilege and name lists sorted, DLS queries parsed,
    empty fields dropped. Elasticsearch returns descriptors with defaults filled in (empty run_as,
    metadata, transient_metadata), and a learner may order lists differently."""
    def index(ix: dict) -> dict:
        out = {"names": sorted(ix.get("names") or []), "privileges": _norm_privileges(ix.get("privileges"))}
        q = ix.get("query")
        if q:
            out["query"] = json.loads(q) if isinstance(q, str) else q
        fs = ix.get("field_security") or {}
        if fs.get("grant") or fs.get("except"):
            out["field_security"] = {"grant": sorted(fs.get("grant") or []), "except": sorted(fs.get("except") or [])}
        return out

    def app(a: dict) -> dict:
        return {"application": a.get("application"), "privileges": _norm_privileges(a.get("privileges")),
                "resources": sorted(a.get("resources") or [])}

    return {"cluster": _norm_privileges(d.get("cluster")),
            "indices": sorted((index(i) for i in d.get("indices") or []), key=lambda x: json.dumps(x, sort_keys=True)),
            "applications": sorted((app(a) for a in d.get("applications") or []), key=lambda x: json.dumps(x, sort_keys=True))}


def same_descriptors(a: dict, b: dict) -> bool:
    """Two role_descriptors maps (role name -> descriptor) grant the same, whatever the role names."""
    na = sorted(json.dumps(normalise_descriptor(d), sort_keys=True) for d in (a or {}).values())
    nb = sorted(json.dumps(normalise_descriptor(d), sort_keys=True) for d in (b or {}).values())
    return na == nb


# ── what a key reaches ───────────────────────────────────────────────────────

def search_reach(key: ES, index: str, id_field: str | None = None, size: int = 1000) -> dict:
    """_search under the key. {"status", "ids", "fields"}: ids are id_field values (else _id), fields
    the top-level _source fields seen on any document. A 403 gives status 403 and nothing seen."""
    code, body = key.request("POST", f"/{index}/_search", {"size": size, "query": {"match_all": {}}})
    if code != 200:
        return {"status": code, "ids": [], "fields": [], "error": str(body)[:300]}
    hits = (body.get("hits") or {}).get("hits") or []
    ids, fields = set(), set()
    for h in hits:
        src = h.get("_source") or {}
        ids.add(str(src.get(id_field)) if id_field and src.get(id_field) is not None else h.get("_id"))
        fields.update(src)
    return {"status": code, "ids": sorted(ids), "fields": sorted(fields)}


def esql(key: ES, query: str) -> dict:
    """ES|QL under the key: {"status", "columns", "rows"} or {"status", "error"}."""
    code, body = key.request("POST", "/_query", {"query": query})
    if code != 200:
        err = (body.get("error") or {}) if isinstance(body, dict) else {}
        return {"status": code, "error": str(err.get("reason") or err or body)[:300]}
    return {"status": code, "columns": [c.get("name") for c in body.get("columns") or []],
            "rows": list(body.get("values") or [])}


def _walk_keys(o: Any, out: set) -> None:
    if isinstance(o, dict):
        for k, v in o.items():
            out.add(k)
            _walk_keys(v, out)
    elif isinstance(o, list):
        for v in o:
            _walk_keys(v, out)


def execute_outcome(ab, tool_id: str, params: dict, admin_ab=None, id_field: str | None = None,
                    run_budget_s: float = 60) -> dict:
    """Run one tool through tools/_execute under the key ab is bound to, and classify the outcome into
    OUTCOMES. Returns {"class", "ids", "fields", "error", "execution_id"}; class None means the call
    did not reach an outcome the closed list covers (a refused request, an environment error, an
    unknown result shape): that is the check's fault or the environment's, never the learner's.

    ES|QL tool: esql_results with values -> rows, without -> no_rows; error "Unknown column [" ->
    error_hidden_field. Index search tool: resource_list with resources -> rows, else no_rows.
    Workflow tool: the run is read with admin_ab (a role key may lack workflow read); completed -> rows
    (the run did its work; 5.1 Defend Q1 calls it "nothing stopped it"), failed -> error_at_write (r2:
    a key without index on the write index runs the workflow, which fails at its write step).
    Unauthorized to execute the workflow -> error_not_authorized."""
    # A 403 under a role key is an observation (AB.execute_tool would raise it as an outage).
    code, body = ab.request("POST", "/api/agent_builder/tools/_execute",
                            {"tool_id": tool_id, "tool_params": params}, ok_codes=(403,))
    out ={"class": None, "ids": [], "fields": [], "error": None, "execution_id": None}
    if code != 200:
        out["error"] = f"HTTP {code} {str(body)[:300]}"
        if code == 403:
            out["class"] = "error_not_authorized"
        return out
    ids, fields = set(), set()
    cls = None
    for r in (body or {}).get("results") or []:
        if not isinstance(r, dict):
            continue
        t, d = r.get("type"), r.get("data") or {}
        if t == "error":
            msg = str(d.get("message") or d)
            out["error"] = msg[:400]
            if HIDDEN_FIELD_ERR.search(msg):
                cls = "error_hidden_field"
            elif NOT_AUTHORIZED_ERR.search(msg):
                cls = "error_not_authorized"
            break
        if t == "esql_results":
            cols = [c.get("name") for c in d.get("columns") or []]
            vals = list(d.get("values") or [])
            fields.update(cols)
            if id_field in cols:
                ids.update(str(v[cols.index(id_field)]) for v in vals)
            cls = "rows" if vals else "no_rows"
        elif t == "resource_list":
            res = list(d.get("resources") or [])
            for x in res:
                ref = x.get("reference") or {}
                if ref.get("id") is not None:
                    ids.add(str(ref["id"]))
                content = x.get("content")
                if isinstance(content, dict):
                    _walk_keys({k: v for k, v in content.items() if k not in ("snippets", "highlights")}, fields)
            cls = "rows" if res else "no_rows"
        elif isinstance(d.get("execution"), dict):
            ex = d["execution"]
            out["execution_id"] = ex.get("execution_id")
            if admin_ab is not None and ex.get("execution_id"):
                # The whole run, step errors included: a failure the environment explains is not a class.
                oc = run_outcome(admin_ab.wait_execution(ex["execution_id"], budget_s=run_budget_s))
                kind, err = oc["kind"], oc.get("error") or ""
            else:
                status, err = ex.get("status"), str(ex.get("error") or "")
                kind = ("completed" if status == "completed" else
                        "learner" if status == "failed" and not ENV_ERR.search(err) else "env")
            out["error"] = err[:400] or None
            cls = {"completed": "rows", "learner": "error_at_write"}.get(kind)
            break
    out.update({"class": cls, "ids": sorted(ids), "fields": sorted(fields)})
    return out


def contains_any(obj: Any, needles: list[str] | tuple[str, ...]) -> list[str]:
    """Which of these strings (blocked ids, hidden values such as a TIN) occur anywhere in obj."""
    text = json.dumps(obj, default=str)
    return [n for n in needles if n and n in text]


# ── prediction against observation ───────────────────────────────────────────

def diff_prediction(prediction: dict, observation: dict) -> list[dict]:
    """Items where the prediction and the observation differ. Both have the same shape:
    {"documents": {doc_id: "retrievable"|"blocked"}, "fields": {name: "visible"|"hidden"},
     "calls": {probe_name: outcome class}}. An item the prediction leaves out counts as a mismatch."""
    out = []
    for section in ("documents", "fields", "calls"):
        want, got = prediction.get(section) or {}, observation.get(section) or {}
        for item in sorted(got):
            if want.get(item) != got[item]:
                out.append({"section": section, "item": item, "predicted": want.get(item), "observed": got[item]})
    return out


ID_FIELDS = {"cortex-cases": "case_id", "cortex-sar-narratives": "sar_id"}


def observe_probes(key: ES, ab, probes: dict, admin_ab=None) -> dict:
    """Make 5.1 B1's observations under one key, in diff_prediction's shape. probes is
    modules/m5/5-1-access-control/access/probes.json. Documents: retrievable when _search under the key
    returns it. Fields: visible when any document _search returns carries it (an index the key cannot
    read shows every field hidden). Calls: the tool's outcome class through _execute. "detail" keeps
    what each observation rests on, for the verifier's printout and the check's messages; a call whose
    class is None did not reach a classified outcome (environment), and the caller must not grade it."""
    reach = {ix: search_reach(key, ix, ID_FIELDS.get(ix))
             for ix in sorted({d["index"] for d in probes["documents"]} | {probes["fields"]["index"]})}
    docs = {d["id"]: "retrievable" if d["id"] in reach[d["index"]]["ids"] else "blocked" for d in probes["documents"]}
    seen = reach[probes["fields"]["index"]]["fields"]
    fields = {f: "visible" if f in seen else "hidden" for f in probes["fields"]["names"]}
    calls, detail = {}, {}
    for t in probes["tools"]:
        oc = execute_outcome(ab, t["tool_id"], t["params"], admin_ab=admin_ab)
        calls[t["id"]] = oc["class"]
        detail[t["id"]] = {"error": oc["error"], "execution_id": oc["execution_id"]}
    detail["search"] = {ix: {"status": r["status"], "count": len(r["ids"])} for ix, r in reach.items()}
    return {"documents": docs, "fields": fields, "calls": calls, "detail": detail}


def judge_prediction(prediction: dict, observation: dict, truth: dict) -> dict:
    """5.1 B1 DIAGNOSE. Passes when the prediction matches every observation, or when every mismatched
    item carries the mechanism the variant's truth table names. truth has diff_prediction's sections,
    each item -> mechanism; prediction carries "mechanisms" {"<section>/<item>": mechanism}.
    Returns {"passed", "mismatches", "wrong": [mismatches whose mechanism is missing or wrong], "score"}:
    score is the share of items the first prediction got right (calibration and the QA record)."""
    mism = diff_prediction(prediction, observation)
    named = prediction.get("mechanisms") or {}
    wrong = [dict(m, mechanism=named.get(f"{m['section']}/{m['item']}"), expected=truth[m["section"]][m["item"]])
             for m in mism if named.get(f"{m['section']}/{m['item']}") != truth[m["section"]][m["item"]]]
    total = sum(len(observation.get(s) or {}) for s in ("documents", "fields", "calls"))
    return {"passed": not wrong, "mismatches": mism, "wrong": wrong,
            "score": round((total - len(mism)) / total, 3) if total else None}
