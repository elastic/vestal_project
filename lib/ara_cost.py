"""Scoring shared by the lab 2.4 checks and the lab 2.4 dev evaluators.

The check (root) and the evaluators (elastic) both call these functions, so a learner
sees on the dev set exactly what the check measures on the held-out set.

ES|QL (Build 1): the learner's query runs next to a reference query with the same
parameters, and the two row sets are compared.
  filter        rows keyed by (@timestamp, amount). Rows within one day of the ?days
                cutoff are ignored, because DATE_DIFF and a timestamp range can
                disagree on the boundary.
  aggregation   one row per risk_tier: `count` must equal, `total` must be within
                TOLERANCE (relative) of the reference.
  weekly_bucket one row per (week, risk_tier): `volume` within TOLERANCE.

Learner code (Builds 2 and 3) never runs as root (finding N3). run_learner() starts a
child process as `elastic` with a timeout, passes the queries on stdin, and reads
tagged lines back:
  cache   imports /home/elastic/cortex_cache.py; for each query calls cache_lookup,
          and on a miss cache_store(query, <stub answer>). Prints ARA-CACHE lines.
  router  imports /home/elastic/router.py; prints ARA-ROUTE lines with pick_tier(q).

Fast-tier answer accuracy (Build 3, read by the Defend): answer_all() answers each question
the way Tina does (tina_answer: top 5 from cortex-corpus-live, rag_answer's prompt,
temperature 0) with one model, in a bounded thread pool, and grade_answer() checks each
answer against gold facts. The check and the notebook's Dispatch cell both call them.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import pathlib
import re
import signal
import subprocess
import sys

def _thresholds():
    try:
        return json.loads(pathlib.Path("/opt/ara/thresholds.json").read_text()).get("build1", {})
    except Exception:
        return {}

TOLERANCE = _thresholds().get("tolerance_relative", 0.001)   # relative, for float sums
EDGE_DAYS = _thresholds().get("edge_days", 1)
LEARNER_PY = "/home/elastic/.venv/bin/python"
# Under the checks' 50 s deadline (ara_grade.deadline), so a slow learner module gets this
# message and is killed with its process group instead of outliving the check.
CHILD_TIMEOUT_S = 40


# ── ES|QL comparison ──────────────────────────────────────────────────────────

REFERENCE = {
    "filter": ("FROM cortex-transactions "
               "| WHERE amount > ?threshold AND country == ?country "
               '| WHERE DATE_DIFF("day", @timestamp, NOW()) <= ?days '
               "| LIMIT 1000"),
    "aggregation": ("FROM cortex-transactions | WHERE flagged == true "
                    "| STATS count = COUNT(*), total = SUM(amount) BY risk_tier"),
    "weekly_bucket": ("FROM cortex-transactions | WHERE flagged == true "
                      "| EVAL week = DATE_TRUNC(1 week, @timestamp) "
                      "| STATS volume = SUM(amount) BY week, risk_tier"),
}


def _rows(es, query, params=None):
    kw = {"query": query}
    if params:
        kw["params"] = [{k: v} for k, v in params.items()]
    r = es.esql.query(**kw)
    cols = [c["name"] for c in r.get("columns", [])]
    return [dict(zip(cols, v)) for v in r.get("values", [])], cols


def _close(a, b):
    return abs(float(a) - float(b)) <= TOLERANCE * max(1.0, abs(float(b)))


def compare(es, kind, learner_query, params=None):
    """Return (ok, message). The message states counts and the kind of mismatch only."""
    try:
        got, cols = _rows(es, learner_query, params)
    except Exception as e:
        return False, f"the query did not run: {str(e)[:160]}"
    ref, _ = _rows(es, REFERENCE[kind], params)
    if kind == "filter":
        need = {"@timestamp", "amount"}
        if not need <= set(cols):
            return False, "the result must include the @timestamp and amount columns (return whole rows)"
        days = int((params or {}).get("days", 0))
        now = _dt.datetime.now(_dt.timezone.utc)
        def edge(row):
            ts = _dt.datetime.fromisoformat(str(row["@timestamp"]).replace("Z", "+00:00"))
            return abs((now - ts).total_seconds() / 86400 - days) <= EDGE_DAYS
        key = lambda r: (str(r["@timestamp"]), round(float(r["amount"]), 2))
        g = {key(r) for r in got if not edge(r)}
        f = {key(r) for r in ref if not edge(r)}
        extra, missing = len(g - f), len(f - g)
        if extra or missing:
            return False, (f"{len(got)} rows returned; {missing} expected rows missing and {extra} "
                           "rows that should not match")
        return True, f"{len(got)} rows, all match"
    if kind == "aggregation":
        need = {"risk_tier", "count", "total"}
        if not need <= set(cols):
            return False, "the result must have columns named risk_tier, count and total"
        g = {r["risk_tier"]: r for r in got}
        f = {r["risk_tier"]: r for r in ref}
        bad = [t for t in f if t not in g or int(g[t]["count"]) != int(f[t]["count"])
               or not _close(g[t]["total"], f[t]["total"])]
        bad += [t for t in g if t not in f]
        if bad:
            return False, f"{len(bad)} of {len(f)} risk tiers have a wrong or missing count or total"
        return True, f"{len(f)} risk tiers, all match"
    if kind == "weekly_bucket":
        need = {"week", "risk_tier", "volume"}
        if not need <= set(cols):
            return False, "the result must have columns named week, risk_tier and volume"
        k = lambda r: (str(r["week"]), r["risk_tier"])
        g = {k(r): r["volume"] for r in got}
        f = {k(r): r["volume"] for r in ref}
        bad = [x for x in f if x not in g or not _close(g[x], f[x])] + [x for x in g if x not in f]
        if bad:
            return False, f"{len(bad)} of {len(f)} week and tier groups are wrong or missing"
        return True, f"{len(f)} week and tier groups, all match"
    raise ValueError(kind)


# ── Learner code in a child process ───────────────────────────────────────────

def run_learner(mode, queries, timeout=CHILD_TIMEOUT_S):
    """Run the learner's module as `elastic`. Returns (records, error_or_None)."""
    cmd = [LEARNER_PY, __file__, mode]
    if os.geteuid() == 0:
        cmd = ["runuser", "-u", "elastic", "--"] + cmd
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, cwd="/home/elastic", start_new_session=True)
    try:
        out, errout = proc.communicate(json.dumps(queries), timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except Exception:
            proc.kill()
        proc.communicate()
        return [], f"your code did not finish within {timeout} seconds"
    p = subprocess.CompletedProcess(cmd, proc.returncode, out, errout)
    tag = "ARA-CACHE " if mode == "cache" else "ARA-ROUTE "
    recs = [json.loads(line[len(tag):]) for line in p.stdout.splitlines() if line.startswith(tag)]
    err = None
    for line in p.stdout.splitlines():
        if line.startswith("ARA-ERROR "):
            err = line[len("ARA-ERROR "):]
    if err is None and p.returncode != 0:
        err = (p.stderr.strip().splitlines() or ["unknown error"])[-1][:200]
    return recs, err


def _load_env():
    # checks run as root and read the root-owned copy; the eval scripts run as elastic (T20)
    env = pathlib.Path("/opt/ara/env" if os.geteuid() == 0 else "/home/elastic/env")
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def _import(path, name):
    import importlib.util
    if not pathlib.Path(path).exists():
        print(f"ARA-ERROR {path} does not exist. Run the cell that writes it.", flush=True)
        sys.exit(2)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as e:
        print(f"ARA-ERROR {pathlib.Path(path).name} failed to load: {type(e).__name__}: {str(e)[:150]}", flush=True)
        sys.exit(2)
    return mod


def _child(mode):
    _load_env()
    sys.path.insert(0, "/opt/ara/lib")
    queries = json.loads(sys.stdin.read())
    if mode == "router":
        mod = _import("/home/elastic/router.py", "learner_router")
        for q in queries:
            try:
                tier = mod.pick_tier(q["text"])
            except Exception as e:
                tier = f"error: {type(e).__name__}"
            print("ARA-ROUTE " + json.dumps({"id": q["id"], "tier": tier}), flush=True)
    elif mode == "cache":
        mod = _import("/home/elastic/cortex_cache.py", "learner_cache")
        print("ARA-CACHE " + json.dumps({"threshold": getattr(mod, "THRESHOLD", None)}), flush=True)
        for q in queries:
            try:
                ans = mod.cache_lookup(q["text"])
                outcome = "hit" if ans is not None else "miss"
                if outcome == "miss":
                    mod.cache_store(q["text"], f"stub answer for {q['id']}")
            except Exception as e:
                outcome = f"error: {type(e).__name__}: {str(e)[:120]}"
            print("ARA-CACHE " + json.dumps({"id": q["id"], "outcome": outcome}), flush=True)
    else:
        sys.exit(f"unknown mode {mode}")


def score_sequence(records, queries):
    """Cache outcomes against expectations. A near_miss is expected to miss.
    hit_rate is hits over every query in the sequence, the share of generation calls saved."""
    by_id = {r["id"]: r["outcome"] for r in records if "id" in r}
    correct = near_ok = near_n = misses = hits = 0
    for q in queries:
        got = by_id.get(q["id"], "absent")
        want_hit = q["expected"] == "hit"
        if got == "miss":
            misses += 1
        if (got == "hit") == want_hit and got in ("hit", "miss"):
            correct += 1
        if q["expected"] == "near_miss":
            near_n += 1
            near_ok += got == "miss"
        hits += got == "hit"
    return {"correct": correct, "of": len(queries), "near_miss_ok": near_ok, "near_miss_of": near_n,
            "misses": misses, "hits": hits,
            # share of all calls in the sequence the cache answered: what the savings formula needs
            "hit_rate": round(hits / len(queries), 3) if queries else 0.0}


# ── Fast-tier answer accuracy ─────────────────────────────────────────────────

TINA_ALIAS = "cortex-corpus-live"
TINA_TOP_K = 5


def tina_answer(es, proxy, model, query, deadline=None):
    """Answer one question on Tina's path. Retrieval and prompt are tina.rag.rag_answer's
    (match on body, top 5, documents as "[doc_id] title\nbody"); generation goes through the
    LLM proxy with the given tier model, since rag_answer's route B has one model only.
    deadline is a time.monotonic() value: the search and the generation call each time out
    at it, so no call outlives the caller's budget. Returns (answer, retrieved doc ids)."""
    import time as _t
    left = lambda: max(0.5, deadline - _t.monotonic()) if deadline else None
    search = es.options(request_timeout=left()) if deadline else es
    resp = search.search(index=TINA_ALIAS, query={"match": {"body": query}}, size=TINA_TOP_K)
    ids, parts = [], []
    for hit in resp["hits"]["hits"]:
        src = hit.get("_source", {})
        doc_id = src.get("doc_id") or hit["_id"]
        ids.append(doc_id)
        parts.append(f"[{doc_id}] {src.get('title', '')}\n{src.get('body_text') or src.get('body', '')}")
    context = "\n\n---\n\n".join(parts)
    prompt = (
        "You are Tina, a compliance assistant at Cortex Bank and Trust. "
        "Answer the analyst's question using only the provided documents. "
        "Cite each document you use by its id in brackets, e.g. [policy-003].\n\n"
        f"Documents:\n{context}\n\n"
        f"Question: {query}\nAnswer:"
    )
    kw = {"timeout": left()} if deadline else {}
    r = proxy.chat.completions.create(model=model, messages=[{"role": "user", "content": prompt}],
                                      temperature=0, **kw)
    return (r.choices[0].message.content or "") if r.choices else "", ids


def grade_answer(answer, gold):
    """gold is a list of facts; each fact is a list of alternative regexes (case-insensitive).
    An answer is correct when every fact matches. Returns (correct, facts matched)."""
    text = " ".join(str(answer).split())
    hits = sum(any(re.search(p, text, re.I) for p in fact) for fact in gold)
    return hits == len(gold), hits


def answer_all(es, proxy, model, questions, pool=12, budget_s=30.0):
    """Answer and grade every question in a bounded pool. A question with no "gold" is answered
    but not graded. Returns one record per question, in input order:
      {id, text, answer, retrieved, latency_s, correct (None if ungraded or failed), facts, error}
    Every search and generation call times out at budget_s from the start, so the pool's
    threads end by then too (they would otherwise hold the process open at exit); a question
    not answered by then is recorded with error "timeout"."""
    import concurrent.futures as cf
    import time as _t
    end = _t.monotonic() + budget_s

    def one(q):
        t = _t.monotonic()
        if t >= end:
            raise TimeoutError
        try:
            ans, ids = tina_answer(es, proxy, model, q["text"], deadline=end)
        except Exception as e:
            return {"id": q["id"], "text": q["text"], "answer": "", "retrieved": [], "latency_s": round(_t.monotonic() - t, 1),
                    "correct": None, "facts": 0, "error": f"{type(e).__name__}: {str(e)[:150]}"}
        ok, hits = grade_answer(ans, q["gold"]) if q.get("gold") else (None, 0)
        return {"id": q["id"], "text": q["text"], "answer": ans, "retrieved": ids, "latency_s": round(_t.monotonic() - t, 1),
                "correct": ok, "facts": hits, "error": None}

    ex = cf.ThreadPoolExecutor(max_workers=max(1, pool))
    futs = [ex.submit(one, q) for q in questions]
    cf.wait(futs, timeout=budget_s + 1)
    out = []
    for q, f in zip(questions, futs):
        if f.done() and f.exception() is None:
            out.append(f.result())
        else:
            f.cancel()
            out.append({"id": q["id"], "text": q["text"], "answer": "", "retrieved": [], "latency_s": None,
                        "correct": None, "facts": 0, "error": "timeout"})
    ex.shutdown(wait=False, cancel_futures=True)
    return out


if __name__ == "__main__":
    _child(sys.argv[1])
