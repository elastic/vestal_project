"""Query-side recall helpers for lab 2.3 Build 3. The check and eval-rewrite.py both use this file.

run_rewrite(queries, path):
    Runs rewrite() from the learner's file in a separate process as the elastic user,
    up to `workers` queries at a time. For each query it records what rewrite() returned,
    whether the call made a network request (a model call does, a static synonym list does
    not), and how long it took. Results come back as each query finishes.

top_docs(es, index, texts, k=5, field="body"):
    Searches each text with a match query on `field` (default `body`, the semantic_text field), keeps each result's distinct
    documents in rank order, merges several texts round-robin, and returns the first
    k distinct doc ids. A query counts as recalled when its target is among them.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess

REWRITE_PATH = "/home/elastic/rewrite.py"
# The check (root) reads the root-owned copy, never the learner-owned file; the learner's
# eval-rewrite.py (elastic) reads the learner's file (T20)
ENV_FILE = "/opt/ara/env" if os.geteuid() == 0 else "/home/elastic/env"
PYTHON = "/home/elastic/.venv/bin/python"
TAG = "ARA_REWRITE "

_RUNNER = r'''
import concurrent.futures, importlib.util, json, socket, ssl, sys, threading, time
sys.path.insert(0, "/opt/ara/lib")
# Queries run in parallel, so network use is counted per query, not per process. Each thread
# carries the query it works for (owner). A thread that rewrite() starts, or a task it hands to a
# ThreadPoolExecutor, takes the owner of the code that started or submitted it, so a model call
# made from rewrite()'s own threads counts for that query.
_local = threading.local()
_counts, _lock = {}, threading.Lock()
def _owner():
    return getattr(_local, "owner", None)
def _wrap(cls, name):
    orig = getattr(cls, name, None)
    if orig is None:
        return
    def f(self, *a, **k):
        o = _owner()
        if o is not None:
            with _lock:
                _counts[o] = _counts.get(o, 0) + 1
        return orig(self, *a, **k)
    setattr(cls, name, f)
for _cls in (socket.socket, ssl.SSLSocket):
    for _name in ("send", "sendall"):
        _wrap(_cls, _name)
_thread_init, _thread_boot = threading.Thread.__init__, threading.Thread._bootstrap_inner
def _init(self, *a, **k):
    _thread_init(self, *a, **k)
    self._ara_owner = _owner()
def _boot(self):
    _local.owner = getattr(self, "_ara_owner", None)
    return _thread_boot(self)
threading.Thread.__init__, threading.Thread._bootstrap_inner = _init, _boot
_submit = concurrent.futures.ThreadPoolExecutor.submit
def _submit_owned(self, fn, /, *a, **k):
    o = _owner()
    def run(*a, **k):
        prev, _local.owner = _owner(), o
        try:
            return fn(*a, **k)
        finally:
            _local.owner = prev
    return _submit(self, run, *a, **k)
concurrent.futures.ThreadPoolExecutor.submit = _submit_owned
TAG = "ARA_REWRITE "
WORKERS = int(sys.argv[2]) if len(sys.argv) > 2 else 8
try:
    spec = importlib.util.spec_from_file_location("learner_rewrite", sys.argv[1])
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fn = mod.rewrite
except Exception as e:
    print(TAG + json.dumps({"load_error": repr(e)[:300]}), flush=True)
    sys.exit(0)
def _one(q):
    _local.owner = q["query_id"]
    t0 = time.perf_counter()
    try:
        out, err = fn(q["query_text"]), None
    except Exception as e:
        out, err = None, repr(e)[:300]
    ms = (time.perf_counter() - t0) * 1000
    if not (isinstance(out, str) or (isinstance(out, list) and all(isinstance(s, str) for s in out))):
        if err is None:
            err = "rewrite() must return a string or a list of strings, got " + type(out).__name__
        out = None
    return {"query_id": q["query_id"], "out": out, "network": _counts.get(q["query_id"], 0) > 0,
            "ms": round(ms, 1), "error": err}
queries = [json.loads(line) for line in sys.stdin if line.strip()]
pool = concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS)
for fut in concurrent.futures.as_completed([pool.submit(_one, q) for q in queries]):
    print(TAG + json.dumps(fut.result()), flush=True)
pool.shutdown(wait=False)
'''


def _env() -> dict:
    env = {"HOME": "/home/elastic", "PATH": "/home/elastic/.venv/bin:/usr/local/bin:/usr/bin:/bin"}
    if os.path.exists(ENV_FILE):
        for line in open(ENV_FILE):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def run_rewrite(queries: list[dict], path: str = REWRITE_PATH, timeout: int = 600,
                workers: int = 8) -> dict:
    """Return {"load_error": str|None, "results": {query_id: {...}}, "timed_out": bool}."""
    cmd = [PYTHON, "-c", _RUNNER, path, str(workers)]
    if os.geteuid() == 0:
        # absolute path: the child env PATH has no /usr/sbin, where runuser lives
        runuser = shutil.which("runuser") or "/usr/sbin/runuser"
        cmd = [runuser, "-u", "elastic", "--"] + cmd
    stdin = "".join(json.dumps({"query_id": q["query_id"], "query_text": q["query_text"]}) + "\n"
                    for q in queries)
    timed_out = False
    try:
        proc = subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=timeout,
                              env=_env(), cwd="/home/elastic")
        stdout = proc.stdout
    except subprocess.TimeoutExpired as e:
        timed_out = True
        stdout = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
    out = {"load_error": None, "results": {}, "timed_out": timed_out}
    for line in stdout.splitlines():
        if not line.startswith(TAG):
            continue
        rec = json.loads(line[len(TAG):])
        if "load_error" in rec:
            out["load_error"] = rec["load_error"]
        else:
            out["results"][rec["query_id"]] = rec
    return out


def top_docs(es, index: str, texts, k: int = 5, field: str = "body") -> list[str]:
    if isinstance(texts, str):
        texts = [texts]
    ranked = []
    for t in texts:
        if not t or not t.strip():
            continue
        hits = es.search(index=index, size=10, body={"query": {"match": {field: t}}, "_source": ["doc_id"]})
        ranked.append(list(dict.fromkeys(h["_source"].get("doc_id", "") for h in hits["hits"]["hits"])))
    merged = []
    for i in range(max((len(r) for r in ranked), default=0)):
        for r in ranked:
            if i < len(r) and r[i] not in merged:
                merged.append(r[i])
    return merged[:k]
