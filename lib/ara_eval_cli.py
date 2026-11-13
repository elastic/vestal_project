"""ara_eval_cli.py - the logic behind ara-eval.py (25 sections 4, 5 and 8.5): run, rank-eval, judge, compare, reset.

Every network call goes through an injected `clients` object, so the same code runs under test, in the
checks and from M6. Non-interactive: no prompts, results on stdout, one exit code per outcome.

    clients.ab      converse_timed(agent_id, text) -> (response, ms); delete_conversation(id)
    clients.es      index_docs(index, docs); rank_eval(index, body) -> dict; esql(query) -> {columns, values};
                    search_runs(label) -> the run documents stored under a label (compare)
    clients.spans   fetch(trace_id) -> span documents (only needed when Tina delegates)
    clients.reach   reset only: get_agent/get_tool/get_skill/get_workflow(id), connectors(), plugins() (reads, None
                    for an object that does not exist), apply(kind, id, body) (create or replace; a 4xx raises
                    ValueError) and remove(kind, id)

reset restores Tina's reach (whatever ara_integrity fingerprints: agents, tools, skills, plugins, workflows,
connectors) to the 5.4 start state, from the copy installed with the track (--from, default
$ARA_START_STATE or /opt/ara/eval/start-state.json; written by ara_integrity.write_start_state). Only objects
whose fingerprint differs are written; a missing one is recreated; an extra one in reach is printed and left
alone unless --remove-extra; a second run changes nothing. It prints object and field names, never values.
An object that cannot be restored from the copy (a deleted connector: its secrets are not in the copy) is
printed and ends the run with exit 1. It is not graded; the run that counts is made after it.

An outage (5xx, 429, timeout) is retried twice, then the command exits EXIT_NO_GRADE and writes nothing;
a refusal (4xx) is the learner's input and exits EXIT_BAD_INPUT with the reason (principle 8).

Exit codes: 0 done; 1 done but a check of the work failed (cross-check, off-contract scores); 2 bad input
or missing environment; 3 no grade (outage); 4 the records could not be stored.

Environment (the sandbox's ~/env): KIBANA_URL, ES_URL, ARA_TINA_EVAL_KEY (the tina-eval key; ES_API_KEY
when it is unset), ARA_AB_CONNECTOR_ID, ARA_JUDGE_INFERENCE_ID, ARA_EVAL_HOME (default ~/cortex-eval),
ARA_EVAL_POOL (default /opt/ara/eval/pool.json). Standard library only.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib
import sys
import time
import uuid
from types import SimpleNamespace
from typing import Any, Callable

from agent_builder import ABError
from ara_eval import CATEGORIES, DEFAULT_SCALE, METRICS, category_means, parse_score
from ara_eval_run import ATTEMPTS, EXIT_NO_GRADE, load_pool, run_testset, summarize
from ara_judge import contract_violations
from ara_rank_bundle import INDEX, METRICS as RB_METRICS, TEMPLATE_ID, cross_check

DEFAULT_START_STATE = "/opt/ara/eval/start-state.json"
EXIT_OK, EXIT_CHECK_FAILED, EXIT_BAD_INPUT, EXIT_STORE = 0, 1, 2, 4
RUNS_INDEX = "cortex-eval-runs"
DEFAULT_HOME = pathlib.Path.home() / "cortex-eval"
DEFAULT_POOL = "/opt/ara/eval/pool.json"
METRIC_KEY = {name: key for key, (name, _, _) in RB_METRICS.items()}  # precision -> precision_at_5
RETRIEVAL_FIELD = {"precision_at_5": "precision_at_5", "recall_at_5": "recall_at_5", "dcg_at_5": "ndcg_at_5"}


class BadInput(Exception):
    """The learner's input (a file, a query, a label) is wrong; the message says how."""


class NoGrade(Exception):
    """A remote call failed after every attempt: nothing is graded or recorded."""


# ── plumbing ──────────────────────────────────────────────────────────────────

def retrying(fn: Callable, *a: Any, attempts: int = ATTEMPTS, sleep: Callable = time.sleep) -> Any:
    """Call fn, retrying an outage (ABError) with a short wait; a ValueError (a 4xx) is the learner's and
    becomes BadInput at once. After the last attempt: NoGrade."""
    last: Exception | None = None
    for i in range(attempts):
        try:
            return fn(*a)
        except ABError as e:
            last = e
            if i + 1 < attempts:
                sleep(1 + i)
        except ValueError as e:
            raise BadInput(str(e)[:300]) from None
    raise NoGrade(f"no answer after {attempts} attempts ({type(last).__name__}: {str(last)[:160]})")


def read_json(path: str | pathlib.Path, what: str) -> Any:
    try:
        return json.loads(pathlib.Path(path).read_text())
    except OSError:
        raise BadInput(f"Cannot read {what} at {path}.") from None
    except ValueError as e:
        raise BadInput(f"{what} at {path} is not valid JSON ({e}).") from None


def read_testset(path: str | pathlib.Path) -> tuple[list[dict], str]:
    """(entries [{question_id, category}], testset version). A list, or {"testset_version", "questions"}."""
    obj = read_json(path, "the test set")
    items = obj.get("questions") if isinstance(obj, dict) else obj
    version = (obj.get("testset_version") if isinstance(obj, dict) else None) or "learner-1"
    if not isinstance(items, list) or not items or not all(isinstance(q, dict) and q.get("question_id") for q in items):
        raise BadInput("The test set must be a list of {question_id, category} entries.")
    return [{"question_id": q["question_id"], "category": q.get("category")} for q in items], str(version)


class Ctx:
    """Everything a command needs besides its arguments: clients, environment, clock, ids, output."""

    def __init__(self, clients: Any, environ: dict, out: Any = None, now: Callable | None = None,
                 new_id: Callable | None = None, sleep: Callable = time.sleep):
        self.clients, self.env, self.out, self.sleep = clients, environ, out or sys.stdout, sleep
        self.now = now or (lambda: datetime.datetime.now(datetime.timezone.utc))
        self.new_id = new_id or (lambda: uuid.uuid4().hex[:8])
        self.home = pathlib.Path(environ.get("ARA_EVAL_HOME") or DEFAULT_HOME)

    def say(self, text: str = "") -> None:
        print(text, file=self.out)

    def require(self, name: str) -> str:
        v = self.env.get(name)
        if not v:
            raise BadInput(f"{name} is not set. Open a new terminal (it loads ~/env) and run this again.")
        return v

    def run_stamp(self, label: str) -> dict:
        t = self.now()
        return {"run_id": f"{label}-{t.strftime('%Y%m%dT%H%M%S')}-{self.new_id()}", "run_label": label,
                "run_at": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "provided": False}

    def store(self, docs: list[dict], local: pathlib.Path) -> None:
        """Index the documents and keep a local copy next to the learner's files."""
        try:
            local.parent.mkdir(parents=True, exist_ok=True)
            with open(local, "w", encoding="utf-8") as f:
                for d in docs:
                    f.write(json.dumps(d, sort_keys=True) + "\n")
        except OSError:
            pass  # the index is the record; a read-only home is not a reason to fail
        try:
            retrying(self.clients.es.index_docs, RUNS_INDEX, docs, sleep=self.sleep)
        except (BadInput, NoGrade) as e:
            raise StoreError(str(e)) from None


class StoreError(Exception):
    pass


def table(rows: list[list[Any]], head: list[str]) -> str:
    cells = [head] + [["-" if c is None else (f"{c:.2f}" if isinstance(c, float) else str(c)) for c in r] for r in rows]
    w = [max(len(r[i]) for r in cells) for i in range(len(head))]
    return "\n".join("  ".join(c.ljust(w[i]) for i, c in enumerate(r)).rstrip() for r in cells)


def parse_scale(text: str | None) -> tuple:
    if not text:
        return DEFAULT_SCALE
    try:
        scale = tuple(sorted(float(x) for x in text.split(",")))
    except ValueError:
        raise BadInput("--scale is a comma-separated list such as 0,0.5,1.") from None
    if not 2 <= len(scale) <= 5 or scale[0] < 0 or scale[-1] > 1:
        raise BadInput("--scale takes two to five values between 0 and 1.")
    return scale


# ── run ───────────────────────────────────────────────────────────────────────

def run_doc(rec: dict, stamp: dict, version: str, connector_id: str | None) -> dict:
    """One 8.5 run document from a graded harness record (judge fields null on an agent run)."""
    return {**stamp, "connector_id": connector_id, "judge_inference_id": None, "testset_version": version,
            "question_id": rec["question_id"], "category": rec.get("category"),
            "expected_route": rec.get("expected_route"), "observed_route": rec.get("observed_route"),
            "route_correct": bool(rec["route_correct"]), "tool_call_count": rec["tool_call_count"],
            "input_tokens": rec["input_tokens"], "output_tokens": rec["output_tokens"],
            "cached_input_tokens": rec["cached_input_tokens"], "llm_calls": rec["llm_calls"],
            "latency_ms": rec["latency_ms"], "conversation_id": rec["conversation_id"],
            "judge": {"faithfulness": None, "answer_relevance": None, "context_precision": None, "raw": None}}


def cmd_run(a: argparse.Namespace, ctx: Ctx) -> int:
    testset, version = read_testset(a.testset)
    pool = load_pool(read_json(a.pool or ctx.env.get("ARA_EVAL_POOL") or DEFAULT_POOL, "the question pool"))
    key = read_json(a.key, "the category key") if a.key else None
    agent_level = [q for q in testset if q["question_id"] not in pool or pool[q["question_id"]].get("type") == "agent"]
    if not agent_level:
        raise BadInput("The test set holds no agent-level questions to send to Tina.")
    skipped = len(testset) - len(agent_level)
    connector = ctx.require("ARA_AB_CONNECTOR_ID")
    stamp = ctx.run_stamp(a.label)
    ctx.say(f"Running {len(agent_level)} agent-level questions through {a.agent}, {a.concurrency} at a time"
            + (f" ({skipped} policy-retrieval questions are scored by rank-eval)" if skipped else "") + " ...")
    spans = getattr(ctx.clients, "spans", None)
    kw: dict = {"sleep": ctx.sleep}
    if spans:
        from ara_behavior import poll_spans  # local: only the live path needs the trace poller
        kw.update(spans=spans, poll=poll_spans)
    recs = run_testset(ctx.clients.ab, a.agent, agent_level, pool, key, concurrency=a.concurrency, **kw)
    s = summarize(recs, key)
    docs = [run_doc(r, stamp, version, connector) for r in recs if r["status"] == "graded"]
    rows = []
    for c in CATEGORIES:
        mine = [r for r in recs if r["status"] == "graded" and (key or {}).get(r["question_id"], r["category"]) == c]
        if mine:
            rows.append([c, len(mine), sum(bool(r["matched"]) for r in mine), s["routing_accuracy"][c]])
    ctx.say(table(rows, ["category", "questions", "correct", "accuracy"]) if rows else "No graded questions.")
    if s["overall"] is not None:
        ctx.say(f"overall {s['graded']} graded, {sum(bool(r['matched']) for r in recs if r['status'] == 'graded')} "
                f"on the expected route ({s['overall'] * 100:.1f} percent)")
    for r in recs:
        if r["status"] != "graded":
            ctx.say(f"  {r['question_id']}: {r['status']}, not graded ({r['reason']})")
    if docs:
        try:
            ctx.store(docs, ctx.home / f"runs-{a.label}.jsonl")
        except StoreError as e:
            ctx.say(f"The records were not stored: {e}")
            return EXIT_STORE
        ctx.say(f"Stored {len(docs)} records in {RUNS_INDEX} under label {a.label} (run {stamp['run_id']}).")
    if s["ungraded"]:
        ctx.say(f"{s['ungraded']} questions were not graded, so this run is not a grade: run it again.")
        return EXIT_NO_GRADE if not any(r["status"] == "refused" for r in recs) else EXIT_BAD_INPUT
    return EXIT_OK


# ── rank-eval ─────────────────────────────────────────────────────────────────

def load_bundle(path: str | pathlib.Path) -> tuple[list[dict], dict]:
    """(requests, {bundle key: _rank_eval body}) from rank-eval.json: the shared `requests` array and the
    `metrics` blocks, one per metric (a list of {name: params}, or a mapping)."""
    obj = read_json(path, "the rank-eval artifact")
    reqs, metrics = (obj.get("requests") if isinstance(obj, dict) else None), (obj.get("metrics") if isinstance(obj, dict) else None)
    if not isinstance(reqs, list) or not reqs:
        raise BadInput("rank-eval.json needs a `requests` array with one rated request per policy question.")
    blocks = list(metrics.items()) if isinstance(metrics, dict) else [tuple(m.items())[0] for m in metrics or [] if isinstance(m, dict) and len(m) == 1]
    if not blocks:
        raise BadInput("rank-eval.json needs `metrics`: one block each for precision, recall and dcg.")
    templates = obj.get("templates") or [{"id": t, "template": {"id": t}} for t in dict.fromkeys(
        r["template_id"] for r in reqs if isinstance(r, dict) and r.get("template_id"))]
    bodies = {}
    for name, params in blocks:
        if name not in METRIC_KEY:
            raise BadInput(f"Metric {name!r} is not one of precision, recall, dcg.")
        body = {"requests": reqs, "metric": {name: params}}
        if templates:
            body["templates"] = templates
        bodies[METRIC_KEY[name]] = body
    missing = [m for m in METRIC_KEY.values() if m not in bodies]
    if missing:
        raise BadInput("rank-eval.json is missing metric blocks for: " + ", ".join(missing) + ".")
    return reqs, bodies


def labelled_from(reqs: list[dict]) -> list[dict]:
    return [{"question_id": r.get("id"), "query_text": (r.get("params") or {}).get("query_string"),
             "relevant_ids": [x["_id"] for x in r.get("ratings") or [] if isinstance(x, dict) and (x.get("rating") or 0) >= 1]}
            for r in reqs]


def cmd_rank_eval(a: argparse.Namespace, ctx: Ctx) -> int:
    path = a.rank_eval or ctx.home / "rank-eval.json"
    reqs, bodies = load_bundle(path)
    labels = {q["question_id"]: q.get("category") for q in read_testset(a.testset or ctx.home / "testset.json")[0]}
    version = read_testset(a.testset or ctx.home / "testset.json")[1]
    index = a.index or INDEX
    stamp = ctx.run_stamp(a.label)
    responses = {}
    for key, body in bodies.items():
        responses[key] = retrying(ctx.clients.es.rank_eval, index, body, sleep=ctx.sleep)
        fails = (responses[key] or {}).get("failures") or {}
        if fails:
            ctx.say(f"_rank_eval reported a failure for {', '.join(sorted(fails))} ({key}): "
                    + str(next(iter(fails.values())))[:200])
            return EXIT_CHECK_FAILED
    labelled = labelled_from(reqs)
    cc = cross_check(responses, labelled)
    ctx.say(table([[k, m["reported"], m["computed"], m["diff"], "ok" if m["ok"] else "MISMATCH"]
                   for k, m in cc["metrics"].items()], ["metric", "_rank_eval", "recomputed", "diff", ""]))
    if not cc["ok"]:
        why = ("no usable response for " + ", ".join(cc["missing"])) if cc["missing"] else "the recomputation disagrees by more than 0.005"
        ctx.say(f"Cross-check failed: {why}. Nothing was stored. Check the metric blocks (k 5, dcg with normalize true, "
                "ignore_unlabeled false for precision) and the ratings.")
        return EXIT_CHECK_FAILED
    docs, rows = [], []
    for c in CATEGORIES:
        ids = [r["id"] for r in reqs if labels.get(r["id"]) == c]
        per = {}
        for key in bodies:
            scores = {rid: (responses[key].get("details", {}).get(rid) or {}).get("metric_score") for rid in ids}
            per[key] = category_means(scores, {rid: c for rid in ids}, (c,))[c]
        if not ids:
            rows.append([c, 0, None, None, None])
            continue
        rows.append([c, len(ids), per["precision_at_5"], per["recall_at_5"], per["dcg_at_5"]])
        docs.append({**stamp, "testset_version": version, "category": c, "question_id": None,
                     "retrieval": {RETRIEVAL_FIELD[k]: v for k, v in per.items()}})
    unlabelled = [r["id"] for r in reqs if labels.get(r["id"]) not in CATEGORIES]
    ctx.say(table(rows, ["category", "questions", "precision@5", "recall@5", "ndcg@5"]))
    if unlabelled:
        ctx.say(f"{len(unlabelled)} rated questions are not in the test set with a category and are left out of the table: "
                + ", ".join(map(str, unlabelled[:5])))
    try:
        ctx.store(docs, ctx.home / f"rank-eval-{a.label}.jsonl")
    except StoreError as e:
        ctx.say(f"The records were not stored: {e}")
        return EXIT_STORE
    ctx.say(f"Stored {len(docs)} category records in {RUNS_INDEX} under label {a.label}.")
    return EXIT_OK


# ── judge ─────────────────────────────────────────────────────────────────────

def judge_rows(result: dict) -> list[dict]:
    cols = [c["name"] if isinstance(c, dict) else c for c in (result or {}).get("columns") or []]
    need = ("sample_id",) + METRICS
    gone = [c for c in need if c not in cols]
    if gone:
        raise BadInput("The judge query must return sample_id, faithfulness, answer_relevance and context_precision; "
                       "missing: " + ", ".join(gone) + ".")
    return [dict(zip(cols, row)) for row in (result.get("values") or [])]


def cmd_judge(a: argparse.Namespace, ctx: Ctx) -> int:
    inference_id = ctx.require("ARA_JUDGE_INFERENCE_ID")  # ARA_MODEL
    scale = parse_scale(a.scale)
    path = pathlib.Path(a.file) if a.file else ctx.home / "judge.esql"
    try:
        esql = path.read_text()
    except OSError:
        raise BadInput(f"Cannot read your judge query at {path}.") from None
    bad = contract_violations(esql, inference_id)
    if bad:
        ctx.say("Your judge query breaks the contract:")
        for m in bad:
            ctx.say(f"  {m}")
        return EXIT_BAD_INPUT
    ctx.say(f"Running {path.name} over cortex-eval-samples ...")
    rows = judge_rows(retrying(ctx.clients.es.esql, esql, sleep=ctx.sleep))
    if not rows:
        raise BadInput("The judge query returned no rows; cortex-eval-samples should hold the sample records.")
    stamp = ctx.run_stamp(a.label)
    docs, table_rows, off, missing = [], [], 0, 0
    for r in rows:
        scores, raw = {}, {}
        for m in METRICS:
            v, is_off = parse_score(r.get(m), scale)
            scores[m], raw[m] = v, None if r.get(m) is None else str(r[m])
            off += bool(is_off and v is not None)
            missing += v is None
        table_rows.append([r["sample_id"]] + [scores[m] for m in METRICS])
        docs.append({**stamp, "connector_id": None, "judge_inference_id": inference_id, "testset_version": None,
                     "sample_id": r["sample_id"], "question_id": None, "category": None, "conversation_id": None,
                     "judge": {**scores, "raw": raw}})
    ctx.say(table(sorted(table_rows), ["sample_id", "faithfulness", "answer_relevance", "context_precision"]))
    total = len(rows) * len(METRICS)
    ctx.say(f"{off} of {total} outputs were off the scale ({', '.join(f'{s:g}' for s in scale)}) and were snapped to the nearest "
            f"value; {missing} had no number." + (" A reply that starts with prose can be read as a different number: "
                                                  "ask for the score first." if off or missing else ""))
    try:
        ctx.store(docs, ctx.home / f"judge-{a.label}.jsonl")
    except StoreError as e:
        ctx.say(f"The records were not stored: {e}")
        return EXIT_STORE
    ctx.say(f"Stored {len(docs)} records in {RUNS_INDEX} under label {a.label}.")
    return EXIT_CHECK_FAILED if missing else EXIT_OK


# ── entry ─────────────────────────────────────────────────────────────────────

# ── compare ───────────────────────────────────────────────────────────────────

DEFAULT_CARD = "/opt/ara/eval/rate-card.json"
CARD_KEYS = ("price_fresh_input", "price_cached_input", "price_output")


def load_card(path: str | pathlib.Path) -> dict:
    card = read_json(path, "the rate card")
    missing = [k for k in CARD_KEYS if not isinstance(card, dict) or not isinstance(card.get(k), (int, float))]
    if missing:
        raise BadInput(f"The rate card must give {', '.join(CARD_KEYS)} (dollars per million tokens).")
    return card


def latest_run(docs: list[dict]) -> list[dict]:
    """The documents of the most recent run under one label (a label may hold several runs)."""
    if not docs:
        return []
    last = max(docs, key=lambda d: (d.get("run_at") or "", d.get("run_id") or ""))["run_id"]
    return [d for d in docs if d.get("run_id") == last]


def p95(values: list[float]) -> float | None:
    v = sorted(x for x in values if x is not None)
    return v[min(len(v) - 1, int(0.95 * len(v)))] if v else None


def cmd_compare(a: argparse.Namespace, ctx: Ctx) -> int:
    from ara_eval import aggregates
    card = load_card(a.card or ctx.env.get("ARA_RATE_CARD") or DEFAULT_CARD)
    side, used = {}, {}
    for name in (a.before, a.after):
        docs = retrying(ctx.clients.es.search_runs, name, sleep=ctx.sleep)
        label = name
        if not docs and not name.endswith("-check"):
            docs = retrying(ctx.clients.es.search_runs, name + "-check", sleep=ctx.sleep)
            label = name + "-check"
        docs = latest_run([d for d in docs if d.get("expected_route") is not None])
        if not docs:
            raise BadInput(f"No agent-level run records are stored under the label {name}. Run `ara-eval.py run --label {name}` first.")
        side[name], used[name] = docs, label
    b, f = (aggregates(side[n], card) for n in (a.before, a.after))
    ctx.say(f"Comparing {used[a.before]} ({b['questions']} questions) with {used[a.after]} ({f['questions']} questions).")
    rows = []
    for c in CATEGORIES:
        x, y = b["routing_accuracy"].get(c), f["routing_accuracy"].get(c)
        rows.append([c, x, y, None if x is None or y is None else round(y - x, 1)])
    rows.append(["overall", b["routing_accuracy_overall"], f["routing_accuracy_overall"],
                 round(f["routing_accuracy_overall"] - b["routing_accuracy_overall"], 1)])
    ctx.say("Routing accuracy, percent (change in points):")
    ctx.say(table(rows, ["category", a.before, a.after, "change"]))
    month = card.get("monthly_questions")
    pct = lambda x, y: None if not x else round(100.0 * (y - x) / x, 1)
    per = [("tool calls per question", "tool_calls_per_question"), ("fresh input tokens per question", "fresh_input_tokens_per_question"),
           ("cached input tokens per question", "cached_input_tokens_per_question"), ("output tokens per question", "output_tokens_per_question"),
           ("cost per question (rate card, dollars)", "cost_per_question")]
    rows = [[lab, b[k], f[k], pct(b[k], f[k])] for lab, k in per]
    rows.append(["cost per 1,000 questions (dollars)", b["cost_per_question"] * 1000, f["cost_per_question"] * 1000, pct(b["cost_per_question"], f["cost_per_question"])])
    if month:
        rows.append([f"cost per month at {int(month):,} questions (dollars)", b["cost_per_question"] * month, f["cost_per_question"] * month,
                     pct(b["cost_per_question"], f["cost_per_question"])])
    lat = {n: [d.get("latency_ms") for d in side[n]] for n in side}
    mean = lambda v: (sum(x for x in v if x is not None) / max(1, sum(x is not None for x in v)))
    rows.append(["latency per question, mean (ms)", mean(lat[a.before]), mean(lat[a.after]), pct(mean(lat[a.before]), mean(lat[a.after]))])
    rows.append(["latency per question, p95 (ms; recorded, not gated)", p95(lat[a.before]), p95(lat[a.after]), pct(p95(lat[a.before]), p95(lat[a.after]))])
    ctx.say("")
    ctx.say(table(rows, ["measure", a.before, a.after, "change %"]))
    ctx.say("")
    ctx.say(f"Cached share of input: {a.before} {100 * (b['cached_share'] or 0):.1f} percent, {a.after} {100 * (f['cached_share'] or 0):.1f} percent. "
            "A token count is not a cost: the rate card prices fresh input, cached input and output separately.")
    return EXIT_OK


# ── reset ─────────────────────────────────────────────────────────────────────

APPLY_ORDER = ("connector", "plugin", "workflow", "tool", "skill", "agent")  # what an object needs comes first


def _reach_now(reader: Any, doc: dict, sleep: Callable) -> dict:
    """The live reach, read with retries; objects of the start copy that the walk did not reach (because the
    agent that held them changed or went) are fetched directly, so a deletion shows as None."""
    import ara_integrity as I
    reach = retrying(I.collect_reach, reader, doc["agent_ids"], doc.get("connector_ids") or [], sleep=sleep)
    getters = {"agent": reader.get_agent, "tool": reader.get_tool, "skill": reader.get_skill, "workflow": reader.get_workflow}
    for key in doc["objects"]:
        kind, _, oid = key.partition("/")
        if key not in reach and kind in getters:
            reach[key] = retrying(getters[kind], oid, sleep=sleep)
    return reach


def cmd_reset(a: argparse.Namespace, ctx: Ctx) -> int:
    import ara_integrity as I
    doc = read_json(a.start_from or ctx.env.get("ARA_START_STATE") or DEFAULT_START_STATE, "the start-state copy")
    if not isinstance(doc, dict) or not isinstance(doc.get("objects"), dict) or not doc.get("agent_ids") \
            or not isinstance(doc.get("fingerprints"), dict):
        raise BadInput("The start-state copy is not in the expected format (objects, fingerprints, agent_ids).")
    reader = ctx.clients.reach
    strip_fields = doc.get("strip_fields") or I.START_STRIP
    start = {"objects": doc["objects"], "fingerprints": doc["fingerprints"]}
    try:
        now = I.snapshot(_reach_now(reader, doc, ctx.sleep), strip_fields)
        now_objs = {k: v for k, v in now["objects"].items() if v is not None}
        extras = sorted(k for k in now_objs if k not in doc["objects"])
        plan = I.reset(start, now)
        gone = {k for k in doc["objects"] if now["objects"].get(k) is None}
        diffs = I.diff(start, now)
        lines: list[str] = []
        stuck: list[str] = []
        for item in sorted(plan, key=lambda i: (APPLY_ORDER.index(i["kind"]) if i["kind"] in APPLY_ORDER else 99, i["id"])):
            key = f"{item['kind']}/{item['id']}"
            if item["kind"] == "connector" and key in gone:
                stuck.append(key)
                lines.append(f"  {key}: deleted, and its secrets are not in the start copy, so it cannot be recreated here")
                continue
            retrying(ctx.clients.reach.apply, item["kind"], item["id"], item["body"], sleep=ctx.sleep)
            if key in gone:
                lines.append(f"  {key}: was missing, recreated")
            else:
                fields = sorted({d["field"] for d in diffs if d["object"] == key and d["field"]})
                lines.append(f"  {key}: restored fields {', '.join(fields) or '(whole object)'}")
        removed: list[str] = []
        if a.remove_extra:
            for key in extras:
                kind, _, oid = key.partition("/")
                if kind in ("agent", "connector") and key in {f"agent/{x}" for x in doc["agent_ids"]}:
                    continue
                retrying(ctx.clients.reach.remove, kind, oid, sleep=ctx.sleep)
                removed.append(key)
    except NoGrade as e:
        ctx.say(f"{e}. Reset did not finish and nothing is reported as done; run `ara-eval.py reset` again "
                "(it only writes what still differs).")
        return EXIT_NO_GRADE
    except BadInput as e:
        ctx.say(f"Reset stopped: {e}")
        return EXIT_BAD_INPUT
    if not lines and not removed:
        ctx.say("Nothing to reset: every object in Tina's reach already matches the 5.4 start state.")
    else:
        done = [l for l in lines if "cannot be recreated" not in l]
        if done:
            ctx.say(f"Restored {len(done)} object(s) to the 5.4 start state:")
            for l in done:
                ctx.say(l)
        for key in removed:
            ctx.say(f"  {key}: not in the start state, removed (--remove-extra)")
        for l in lines:
            if "cannot be recreated" in l:
                ctx.say(l)
    for key in extras:
        if key not in removed:
            ctx.say(f"Extra in Tina's reach, not in the start state, left alone: {key} (use --remove-extra to delete it)")
    if stuck:
        ctx.say("Not everything could be restored. Ask for help with the object(s) above.")
        return EXIT_CHECK_FAILED
    ctx.say("Reset is not graded. Measure again after it: the run that counts is the one made after the reset.")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ara-eval.py", description="The Cortex evaluation harness.")
    sub = p.add_subparsers(dest="cmd")
    r = sub.add_parser("run", help="send the agent-level questions of a test set to Tina and record the routes")
    r.add_argument("--label", required=True)
    r.add_argument("--testset", required=True, help="test set JSON: a list of {question_id, category}")
    r.add_argument("--agent", required=True, help="agent id to evaluate")
    r.add_argument("--pool", help="question pool JSON (default: $ARA_EVAL_POOL)")
    r.add_argument("--key", help="question_id -> category JSON; grades by these categories (checks and M6)")
    r.add_argument("--concurrency", type=int, default=3)
    q = sub.add_parser("rank-eval", help="run the rated requests, one _rank_eval call per metric, and record per category")
    q.add_argument("--label", required=True)
    q.add_argument("--rank-eval", help="the artifact (default: ~/cortex-eval/rank-eval.json)")
    q.add_argument("--testset", help="test set JSON (default: ~/cortex-eval/testset.json)")
    q.add_argument("--index", help=f"index to search (default: {INDEX})")
    j = sub.add_parser("judge", help="run your judge.esql over cortex-eval-samples and record the scores")
    j.add_argument("--label", required=True)
    j.add_argument("--file", help="the judge query (default: ~/cortex-eval/judge.esql)")
    j.add_argument("--scale", help="score scale, comma-separated (default 0,0.5,1)")
    c = sub.add_parser("compare", help="print two labelled runs side by side: accuracy per category, tokens, cost, latency")
    c.add_argument("before")
    c.add_argument("after")
    c.add_argument("--card", help="the rate card JSON (default: $ARA_RATE_CARD or /opt/ara/eval/rate-card.json)")
    x = sub.add_parser("reset", help="restore every object in Tina's reach to the 5.4 start state and print what changed")
    x.add_argument("--from", dest="start_from", help=f"the start-state copy (default: $ARA_START_STATE or {DEFAULT_START_STATE})")
    x.add_argument("--remove-extra", action="store_true", help="also delete objects in reach that the start state does not have")
    return p


COMMANDS = {"run": cmd_run, "rank-eval": cmd_rank_eval, "judge": cmd_judge, "compare": cmd_compare, "reset": cmd_reset}


def main(argv: list[str], clients: Any = None, environ: dict | None = None, out: Any = None,
         make_clients: Callable | None = None, **ctx_kw: Any) -> int:
    """Run one subcommand and return its exit code. clients is injected under test; otherwise
    make_clients(environ) builds the live ones, after the arguments are known to be good."""
    parser = build_parser()
    try:
        a = parser.parse_args(argv)
    except SystemExit as e:
        return EXIT_BAD_INPUT if e.code else EXIT_OK
    if not a.cmd:
        parser.print_help(file=out or sys.stdout)
        return EXIT_BAD_INPUT
    environ = dict(os.environ) if environ is None else environ
    try:
        if clients is None:
            clients = (make_clients or (lambda e: SimpleNamespace()))(environ)
        return COMMANDS[a.cmd](a, Ctx(clients, environ, out, **ctx_kw))
    except BadInput as e:
        print(str(e), file=out or sys.stdout)
        return EXIT_BAD_INPUT
    except NoGrade as e:
        print(f"{e}. Nothing was graded or recorded; run the command again.", file=out or sys.stdout)
        return EXIT_NO_GRADE
