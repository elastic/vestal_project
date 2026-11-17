"""ara_degrade_live.py - the live half of the degradation seeder (28 section 5, L1 to L3; 07 section 3, C1 to C3) as plans.

A plan is data: ordered HTTP operations to apply the degradation, the operations that revert it (for calibration
and test sandboxes), the truthful change-log entry with one decoy in the same hour, and the key. `execute` runs
operations over an injected client (request(method, path, body) and request_ndjson(method, path, text), each
returning (status, body)), stopping at the first refusal. Nothing here touches a network.

    plan_l1(manual, seed)        a bulk load of about 40 customer-facing FAQ chunks into `cortex-policies`
    plan_l2(manual, mapping, endpoints, seed)   `cortex-policies` becomes an alias over -v1 (old endpoint) and -v2 (new)
    plan_l3(tool, seed)          a deploy that broadens cortex.escalate's description (the before and after are kept)
    execute(client, ops)         run the operations in order
    faq_reachable / endpoint_uniform / l3_restored    the 6.4 B2 ARTIFACT rules for the fixed state, as functions

Which docs go to which index in L2 comes from the chunk id's sha256, so the split is the same on every sandbox
(P3 sets the fraction from measurement; the default is a guess, labelled as one). The FAQ text is built from the
manual chunk it paraphrases, so it sits close to the manual's wording by construction (28: close, customer-facing).
Standard library only.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any

POLICY_INDEX = "cortex-policies"
DEFAULT_SPLIT = 0.5  # fraction of chunks on the new endpoint. P3 (probe r4, dense pair jina-v5-small / e5-small, 89 self-retrieval queries): at 0.5 semantic hit@5 0.528 vs 0.966 single index, lexical (dfs) 1.0 vs 1.0; the gate set's own drop is set at calibration
FAQ_OPENERS = ("What should a customer know about this?", "Why am I being asked about this?",
               "Does this apply to my account?", "What happens if I do not provide this?", "How long does this take?")
BROADENING = (" Use this for any question that concerns more than one account, a customer's circumstances, or a decision about a person.",
              " Escalate whenever the question names two or more accounts, or the analyst sounds unsure.",
              " Call this when the answer could affect a customer, even if a policy or case tool could answer it.")


def _h(*parts: str) -> int:
    return int(hashlib.sha256("|".join(parts).encode()).hexdigest(), 16)


def op(method: str, path: str, body: Any = None, ndjson: str | None = None, idempotent: bool = False, retries: int = 0, wait_s: float = 0.0, expect: int | None = None) -> dict:
    """`idempotent`: an index creation that finds the index already there is fine (a revert after an apply that failed before it deleted the original).
    `retries`: a bulk of `index` operations with fixed ids may be sent again, up to this many times, when a node reports a timeout or overload.
    method `COUNT` (with `expect`, the body is a query or absent): the documents counted must equal `expect`, so a load that came up short after retries fails the seed instead of passing as a smaller index.
    method `WARM` (with `wait_s`): search `path` with `body` until it answers 200, for at most `wait_s` seconds (a cold embedding endpoint)."""
    return {"method": method, "path": path, "body": body, "ndjson": ndjson, "idempotent": idempotent, "retries": retries, "wait_s": wait_s, "expect": expect}


def _bulk(index: str, docs: list[dict], op_type: str = "index") -> str:
    return "".join(json.dumps({op_type: {"_index": index, "_id": d["chunk_id"]}}) + "\n" + json.dumps({k: v for k, v in d.items() if k != "chunk_id"}) + "\n"
                   for d in docs)


def _entry(at: str, kind: str, obj: str, before: str, after: str, seed: str, cause: bool) -> dict:
    return {"at": at, "kind": kind, "object": obj, "before": before, "after": after, "actor": "cortex-ops", "cause": cause,
            "change_id": "chg-" + hashlib.sha256((seed + obj + kind).encode()).hexdigest()[:8]}


def _decoy(at: str, seed: str, kind: str) -> dict:
    return _entry(at, kind, "cortex-misc", "a", "b", seed + "-decoy", False)


# ── L1: retrieval drift ───────────────────────────────────────────────────────

def faq_chunks(manual: list[dict], n: int = 40, seed: str = "", doc_type: str = "faq") -> list[dict]:
    """About n customer-facing chunks, each a Q and A over one manual chunk's own wording (so it ranks like it),
    `doc_type: faq`, ids `faq-<n>`. Manual chunks are {chunk_id, body, ...}; chosen by hash so the set is stable."""
    order = sorted(manual, key=lambda m: _h(seed, m["chunk_id"]))[:n]
    out = []
    for i, m in enumerate(order):
        q = FAQ_OPENERS[_h(seed, m["chunk_id"], "q") % len(FAQ_OPENERS)]
        text = f"Customer FAQ. {q} {m['body']}" if doc_type == "faq" else f"DRAFT (superseded). {m['body']}"
        cid = f"{doc_type}-{i + 1:03d}"
        out.append({"chunk_id": cid, "doc_id": cid, "title": m.get("title", ""), "section": "", "effective_date": m.get("effective_date"), "source_type": doc_type,
                    "body": text, "body_text": text, "doc_type": doc_type,
                    **({"audience": "customer"} if doc_type == "faq" else {"status": "superseded"})})
    return out


def plan_l1(manual: list[dict], at: str, seed: str = "", n: int = 40, doc_type: str = "faq", clean_mapping: bool = False) -> dict:
    """L1 loads FAQ chunks; 6.C's C1 is the same plan with doc_type "draft" and n 30 (`plan_c1`).
    `clean_mapping`: the extra field the chunks carry (`status`, `audience`) stays in _source but is not mapped, so deleting the chunks
    leaves the index mapping as it was; the pin is lifted as soon as the load is counted, so the index setting the learner sees is the one the
    index always had (the revert lifts it too, for a load that failed half way). Without it the load maps that field dynamically and the mapping keeps it after the delete; on 6.C
    that residue alone raised Tina's tool calls per question from 1.40 to 2.09 on the healed index (a clean nine-field copy of
    the same 89 chunks measured 1.42)."""
    docs = faq_chunks(manual, n, seed, doc_type)
    pin = [op("PUT", f"/{POLICY_INDEX}/_mapping", {"dynamic": False})] if clean_mapping else []
    unpin = [op("PUT", f"/{POLICY_INDEX}/_mapping", {"dynamic": True})] if clean_mapping else []
    return {"layer": "L1", "type": "retrieval_drift", "docs": docs,
            "apply": pin + [op("POST", "/_bulk?refresh=wait_for", ndjson=_bulk(POLICY_INDEX, docs, "create")),
                            op("COUNT", f"/{POLICY_INDEX}/_count", {"query": {"term": {"doc_type": doc_type}}}, expect=len(docs))] + unpin,
            "revert": [op("POST", f"/{POLICY_INDEX}/_delete_by_query?refresh=true", {"query": {"term": {"doc_type": doc_type}}})] + unpin,
            "change_log": [_entry(at, "ingest", POLICY_INDEX, "89 manual chunks", f"89 manual chunks and {len(docs)} {doc_type} chunks", seed, True),
                           _decoy(at, seed, "connector_rotation")],
            "key": {"type": "retrieval_drift", "component": "policy_index_content", "affected_class": "policy_retrieval",
                    "signal": "ranking_down_semantic_and_lexical_after_ingest", "faq_ids": [d["chunk_id"] for d in docs], "doc_type": doc_type}}


# ── L2: embedding staleness ───────────────────────────────────────────────────

def split_ids(chunk_ids: list[str], fraction: float = DEFAULT_SPLIT, seed: str = "") -> tuple[list[str], list[str]]:
    """(on the new endpoint, still on the old one): the lowest hashes go to the new endpoint, so a bigger fraction
    only adds chunks."""
    ranked = sorted(chunk_ids, key=lambda c: _h(seed, c))
    k = round(len(ranked) * fraction)
    return sorted(ranked[:k]), sorted(ranked[k:])


WARM_QUERY = {"query": {"semantic": {"field": "body", "query": "warm up the new embedding endpoint"}}, "size": 1, "_source": False}
WARM_WAIT_S = 420.0
BULK_RETRIES = 3
_TRANSIENT = ("task_cancelled", "timed out", "timeout", "es_rejected", "unavailable", "circuit_breaking", "too_many_requests")


def _with_endpoint(mapping: dict, endpoint: str) -> dict:
    m = json.loads(json.dumps(mapping))
    def walk(n):
        if isinstance(n, dict):
            if n.get("type") == "semantic_text":
                n["inference_id"] = endpoint
                n.pop("model_settings", None)   # a read-back mapping carries the old model's dimensions; the new endpoint fills in its own
            for v in n.values():
                walk(v)
    walk(m)
    return m


def plan_l2(manual: list[dict], mapping: dict, old_endpoint: str, new_endpoint: str, at: str, seed: str = "",
            fraction: float = DEFAULT_SPLIT) -> dict:
    """`mapping` is the committed `cortex-policies` mapping body ({"mappings": ...}); its semantic_text fields are pointed at each
    side's endpoint. The concrete index `cortex-policies` is deleted and the alias takes its name."""
    new_ids, old_ids = split_ids([m["chunk_id"] for m in manual], fraction, seed)
    by_id = {m["chunk_id"]: m for m in manual}
    v2 = [by_id[i] for i in new_ids]
    v1 = [by_id[i] for i in old_ids]
    return {"layer": "L2", "type": "embedding_staleness", "v1": old_ids, "v2": new_ids,
            "apply": [op("PUT", f"/{POLICY_INDEX}-v1", _with_endpoint(mapping, old_endpoint)),
                      op("PUT", f"/{POLICY_INDEX}-v2", _with_endpoint(mapping, new_endpoint)),
                      # the new endpoint starts on first use and the first embeddings can take minutes (the v2 bulk timed out at 4.3 min, then the seed failed): start it
                      # with a search before the load, send the load without tying it to a refresh, send it again if a node reports a timeout, then refresh once
                      op("WARM", f"/{POLICY_INDEX}-v2/_search", WARM_QUERY, wait_s=WARM_WAIT_S),
                      op("POST", f"/{POLICY_INDEX}-v1/_bulk", ndjson=_bulk(f"{POLICY_INDEX}-v1", v1), retries=BULK_RETRIES),
                      op("POST", f"/{POLICY_INDEX}-v2/_bulk", ndjson=_bulk(f"{POLICY_INDEX}-v2", v2), retries=BULK_RETRIES),
                      op("POST", f"/{POLICY_INDEX}-v1/_refresh"),
                      op("POST", f"/{POLICY_INDEX}-v2/_refresh"),
                      op("COUNT", f"/{POLICY_INDEX}-v1/_count", expect=len(v1)),
                      op("COUNT", f"/{POLICY_INDEX}-v2/_count", expect=len(v2)),
                      op("DELETE", f"/{POLICY_INDEX}"),
                      op("POST", "/_aliases", {"actions": [{"add": {"index": f"{POLICY_INDEX}-v1", "alias": POLICY_INDEX}},
                                                           {"add": {"index": f"{POLICY_INDEX}-v2", "alias": POLICY_INDEX}}]})],
            "revert": [op("DELETE", f"/{POLICY_INDEX}-v1"), op("DELETE", f"/{POLICY_INDEX}-v2"),
                       op("PUT", f"/{POLICY_INDEX}", _with_endpoint(mapping, old_endpoint), idempotent=True),
                       op("POST", f"/{POLICY_INDEX}/_bulk?refresh=wait_for", ndjson=_bulk(POLICY_INDEX, manual))],
            "change_log": [_entry(at, "endpoint_change", f"{POLICY_INDEX}-v2", f"{len(manual)} chunks on {old_endpoint}",
                                  f"{len(v2)} chunks migrated to {new_endpoint}", seed, True),
                           _decoy(at, seed, "deploy")],
            "key": {"type": "embedding_staleness", "component": "embedding_configuration", "affected_class": "policy_retrieval",
                    "signal": "semantic_recall_down_lexical_flat", "old_endpoint": old_endpoint, "new_endpoint": new_endpoint}}


# ── L3: behavior shift ────────────────────────────────────────────────────────

def plan_l3(tool: dict, at: str, seed: str = "") -> dict:
    """`tool` is the live cortex.escalate definition. The apply PUTs the broadened description; the revert PUTs the
    original back. The change-log entry holds the description before and after (the deploy record)."""
    before = tool["description"]
    after = before.rstrip() + BROADENING[_h(seed, "l3") % len(BROADENING)]
    def put(desc):
        body = {k: v for k, v in tool.items() if k in ("tags", "configuration", "confirmation")}   # a PUT refuses the type (live: AB.put_tool leaves it out) and the read's server fields
        body["description"] = desc
        return op("PUT", f"/api/agent_builder/tools/{tool['id']}", body)
    return {"layer": "L3", "type": "behavior_shift", "before": before, "after": after, "apply": [put(after)], "revert": [put(before)],
            "change_log": [_entry(at, "deploy", tool["id"], before, after, seed, True), _decoy(at, seed, "ingest")],
            "key": {"type": "behavior_shift", "component": "tool_description", "affected_class": None,
                    "signal": "tool_mix_shifted_retrieval_flat", "tool_id": tool["id"]}}


# ── 6.C seeds ─────────────────────────────────────────────────────────────────

def plan_c1(manual: list[dict], at: str, seed: str = "") -> dict:
    """C1: about 30 superseded draft policy chunks (`doc_type: draft`) bulk-loaded overnight."""
    plan = plan_l1(manual, at, seed, 30, "draft", clean_mapping=True)
    plan["layer"] = "C1"
    return plan


C3_SENTENCE = "Escalate any question that names more than one account."


def plan_c3(agent: dict, at: str, seed: str = "") -> dict:
    """C3: a sentence added to Tina's instructions in last night's deploy (an instruction, not a tool description).
    `agent` is the live definition; the apply PUTs it with the sentence appended on a new line, the revert PUTs the
    original. Only the fields the agent endpoint accepts are sent (id goes in the path)."""
    before = agent["configuration"]["instructions"]
    after = before.rstrip("\n") + "\n" + C3_SENTENCE
    def put(text):
        cfg = json.loads(json.dumps(agent["configuration"]))
        cfg["instructions"] = text
        body = {k: v for k, v in agent.items() if k in ("name", "description", "avatar_color", "avatar_symbol", "labels")}
        body["configuration"] = cfg
        return op("PUT", f"/api/agent_builder/agents/{agent['id']}", body)
    return {"layer": "C3", "type": "behavior_shift", "before": before, "after": after, "apply": [put(after)], "revert": [put(before)],
            "change_log": [_entry(at, "deploy", agent["id"], "instructions v1", "instructions v2", seed, True), _decoy(at, seed, "model_pin")],
            "key": {"type": "behavior_shift", "component": "agent_instructions", "affected_class": "cross_domain",
                    "signal": "tool_mix_shifted_retrieval_flat", "agent_id": agent["id"]}}


def plan_c2(manual: list[dict], mapping: dict, old_endpoint: str, new_endpoint: str, at: str, seed: str = "",
            fraction: float = 0.4) -> dict:
    """C2: last night's re-index moved only part of `cortex-policies` to the new endpoint (a smaller migrated share than
    6.4's L2 default, so a 6.4 fix copied by rote does not match the state). Same structure as L2; the change-log entry
    reads as a re-index."""
    plan = plan_l2(manual, mapping, old_endpoint, new_endpoint, at, seed, fraction)
    plan["layer"] = "C2"
    plan["change_log"][1] = _entry(at, "ingest", "cortex-intake", "a", "b", seed + "-decoy", False)  # 6.C's decoy for C2 (07 section 3.2): an ingest into cortex-intake
    plan["change_log"][0].update(kind="endpoint_change", before=f"all {len(manual)} chunks on {old_endpoint}",
                                 after=f"re-index moved {len(plan['v2'])} of {len(manual)} chunks to {new_endpoint}")
    return plan


# ── running a plan ────────────────────────────────────────────────────────────

class PlanFailed(Exception):
    pass


_sleep = time.sleep   # tests replace this


def _answer(fn, *a):
    """(HTTP status, body) of a client call; the live client raises for 401, 408, 429 and 5xx and for no answer at all (ABError, RemoteCallFailed): those become
    (status or 0, message) so the caller can decide whether to wait. Anything that is not such an error still propagates."""
    try:
        return fn(*a)
    except Exception as e:  # noqa: BLE001
        if hasattr(e, "status_code"):
            return int(e.status_code or 0), str(e)[:300]
        raise


def _bulk_error(code, body):
    """The first error of a bulk response (or the HTTP status) as text, or None when the bulk went through."""
    if code >= 300 or code == 0:
        return f"HTTP {code}: {str(body)[:200]}"
    if isinstance(body, dict) and body.get("errors"):
        first = next((next(iter(i.values())).get("error") for i in body.get("items", []) if next(iter(i.values())).get("error")), "unknown")
        return f"bulk had errors: {str(first)[:200]}"
    return None


def execute(client, ops: list[dict]) -> list[tuple[dict, int]]:
    """Run operations in order; 2xx continues (a DELETE of a missing index, 404, also continues: revert is
    idempotent). The first other status raises PlanFailed naming the operation. A `WARM` operation searches until the
    index answers (bounded by its wait_s); a bulk with `retries` is sent again after a timeout or overload (bounded)."""
    done = []
    for o in ops:
        if o["method"] == "WARM":
            end = time.monotonic() + float(o.get("wait_s") or WARM_WAIT_S)
            while True:
                code, body = _answer(client.request, "POST", o["path"], o.get("body"))   # 408 "model deployment timeout" after 10 s while the endpoint starts: keep waiting
                if code == 200:
                    break
                if time.monotonic() > end:
                    raise PlanFailed(f"WARM {o['path']}: no answer within {int(o.get('wait_s') or WARM_WAIT_S)} s (last HTTP {code})")
                _sleep(10)
            done.append((o, code))
            continue
        if o["method"] == "COUNT":
            code, body = _answer(client.request, "POST", o["path"], o.get("body"))
            found = body.get("count") if isinstance(body, dict) else None
            ok = code == 200 and found == o["expect"]
            print(f"SEED-COUNT {o['path']} expected {o['expect']} found {found} {'ok' if ok else 'short'}", flush=True)
            if not ok:
                raise PlanFailed(f"COUNT {o['path']}: {found} documents counted (HTTP {code}), {o['expect']} expected")
            done.append((o, code))
            continue
        if o.get("ndjson") is not None:
            attempt = 0
            while True:
                code, body = _answer(client.request_ndjson, o["method"], o["path"], o["ndjson"])
                err = _bulk_error(code, body)
                if err is None:
                    break
                if attempt < int(o.get("retries") or 0) and any(t in err.lower() for t in _TRANSIENT + ("http 5", "http 429", "http 408", "http 0")):
                    attempt += 1
                    _sleep(15 * attempt)
                    continue
                raise PlanFailed(f"{o['method']} {o['path']}: {err}" + (f" (after {attempt + 1} attempts)" if attempt else ""))
        else:
            code, body = client.request(o["method"], o["path"], o.get("body"))
        if code == 400 and o.get("idempotent") and "resource_already_exists_exception" in str(body):
            done.append((o, code))
            continue
        if code >= 300 and not (o["method"] == "DELETE" and code == 404):
            raise PlanFailed(f"{o['method']} {o['path']}: HTTP {code}: {str(body)[:200]}")
        done.append((o, code))
    return done


# ── the fixed state (6.4 B2 ARTIFACT; 6.C) ────────────────────────────────────

def faq_reachable(search_results: dict[str, list[dict]]) -> list[str]:
    """Question ids whose results (the policy search's `_execute` hits) still hold a `doc_type: faq` chunk."""
    return sorted(q for q, hits in search_results.items() if any(h.get("doc_type") == "faq" or str(h.get("chunk_id") or h.get("id") or "").startswith("faq-") for h in hits))


def endpoint_uniform(index_endpoints: dict[str, str], chunk_ids: list[str], manual_ids: list[str]) -> list[str]:
    """Problems with L2's fixed state. `index_endpoints` maps each index the alias resolves to its field's
    inference_id; `chunk_ids` lists every chunk id across those indices (duplicates kept)."""
    problems = []
    if len(set(index_endpoints.values())) != 1:
        problems.append("the indices behind cortex-policies use different inference endpoints: " + ", ".join(sorted(set(index_endpoints.values()))))
    count = {i: chunk_ids.count(i) for i in manual_ids}
    missing = [i for i, n in count.items() if n == 0]
    dup = [i for i, n in count.items() if n > 1]
    if missing:
        problems.append(f"{len(missing)} manual chunks are missing (first: {missing[0]})")
    if dup:
        problems.append(f"{len(dup)} manual chunks appear more than once (first: {dup[0]})")
    return problems


def l3_restored(current: str, deploy_before: str) -> bool:
    """The description equals the deploy record's `before`, whitespace-normalised."""
    return " ".join((current or "").split()) == " ".join((deploy_before or "").split())
