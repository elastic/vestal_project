"""ara_testset.py - the learner's test-set helper for Lab 5.3 Build 1 (25 section 4): read the question log, label
and select questions, save the test set, and build the rated-request artifact for the retrieval evaluation.

    ara-testset.py log                         the question log: pool id, kind, question (no categories)
    ara-testset.py add ID CATEGORY [ID CATEGORY ...]
    ara-testset.py remove ID [ID ...]
    ara-testset.py show                        the set so far: counts by category and kind
    ara-testset.py save                        store the set in cortex-eval-testsets as version learner-1
    ara-testset.py rank-eval --metric NAME:k=V,... [--metric ...]
                                               rank-eval.json: one rated request per policy question in the set (the
                                               stored template and the pool's ratings) and the metric blocks you name

Files live in ~/cortex-eval (ARA_EVAL_HOME). Standard library only; the ES client is injected for tests.
"""
from __future__ import annotations

import datetime
import json
import os
import pathlib
import sys
from typing import Any

from ara_eval import CATEGORIES
from ara_rank_bundle import INDEX, TEMPLATE_ID

VERSION = "learner-1"
METRIC_NAMES = ("precision", "recall", "dcg")


class Problem(Exception):
    """A message for the learner."""


def home(environ: dict) -> pathlib.Path:
    return pathlib.Path(environ.get("ARA_EVAL_HOME") or pathlib.Path.home() / "cortex-eval")


def _load(path: pathlib.Path, what: str) -> Any:
    try:
        return json.loads(path.read_text())
    except OSError:
        raise Problem(f"Cannot read {what} at {path}.") from None
    except ValueError as e:
        raise Problem(f"{what} at {path} is not valid JSON ({e}).") from None


def pool_of(h: pathlib.Path) -> dict:
    return {q["id"]: q for q in _load(h / "pool.json", "the question labels")["questions"]}


def log_of(h: pathlib.Path) -> list[dict]:
    return _load(h / "question-log.json", "the question log")


def read_set(h: pathlib.Path) -> list[dict]:
    p = h / "testset.json"
    if not p.exists():
        return []
    obj = _load(p, "your test set")
    items = obj.get("questions") if isinstance(obj, dict) else obj
    return [dict(q) for q in items or []]


def write_set(h: pathlib.Path, questions: list[dict]) -> None:
    (h / "testset.json").write_text(json.dumps({"testset_version": VERSION, "questions": questions}, indent=2) + "\n")


def cmd_log(h: pathlib.Path, out) -> None:
    pool = pool_of(h)
    print("pool_id  kind    question", file=out)
    for item in log_of(h):
        q = pool.get(item["pool_id"], {})
        print(f"{item['pool_id']:7}  {q.get('type', '?'):6}  {item['question']}", file=out)


def cmd_add(h: pathlib.Path, pairs: list[str], out) -> None:
    if not pairs or len(pairs) % 2:
        raise Problem("add takes pairs: a pool id and its category, for example: add q-006 straightforward")
    in_log = {i["pool_id"] for i in log_of(h)}
    questions = read_set(h)
    have = {q["question_id"]: q for q in questions}
    for qid, cat in zip(pairs[::2], pairs[1::2]):
        if qid not in in_log:
            raise Problem(f"{qid} is not in your question log. List it with: ara-testset.py log")
        if cat not in CATEGORIES:
            raise Problem(f"{cat} is not a category. The categories are: {', '.join(CATEGORIES)}.")
        if qid in have:
            have[qid]["category"] = cat
        else:
            have[qid] = {"question_id": qid, "category": cat}
            questions.append(have[qid])
    write_set(h, questions)
    print(f"Test set: {len(questions)} questions. Saved to {h / 'testset.json'}.", file=out)


def cmd_remove(h: pathlib.Path, ids: list[str], out) -> None:
    questions = [q for q in read_set(h) if q["question_id"] not in ids]
    write_set(h, questions)
    print(f"Test set: {len(questions)} questions.", file=out)


def cmd_show(h: pathlib.Path, out) -> None:
    questions, pool = read_set(h), pool_of(h)
    by_cat: dict[str, int] = {}
    kinds = {"policy": 0, "agent": 0}
    for q in questions:
        by_cat[q.get("category")] = by_cat.get(q.get("category"), 0) + 1
        kinds[pool.get(q["question_id"], {}).get("type", "agent")] += 1
    print(f"{len(questions)} questions: {kinds['policy']} policy-retrieval, {kinds['agent']} agent-level.", file=out)
    for c in CATEGORIES:
        print(f"  {c:18} {by_cat.get(c, 0)}", file=out)


def cmd_save(h: pathlib.Path, es, out) -> None:
    questions = read_set(h)
    if not questions:
        raise Problem("Your test set is empty. Add questions first: ara-testset.py add ID CATEGORY")
    doc = {"testset_version": VERSION, "created_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "questions": questions}
    es.put_doc("cortex-eval-testsets", VERSION, doc)
    print(f"Saved {len(questions)} questions as version {VERSION} in cortex-eval-testsets.", file=out)


def parse_metric(text: str) -> tuple[str, dict]:
    name, _, rest = text.partition(":")
    if name not in METRIC_NAMES:
        raise Problem(f"Metric {name!r} is not one of {', '.join(METRIC_NAMES)}.")
    params: dict = {}
    for part in filter(None, rest.split(",")):
        k, _, v = part.partition("=")
        if not k or not v:
            raise Problem(f"Metric option {part!r} must look like k=5 or normalize=true.")
        try:
            params[k.strip()] = json.loads(v.strip().lower())
        except ValueError:
            params[k.strip()] = v.strip()
    return name, params


def cmd_rank_eval(h: pathlib.Path, metrics: list[str], out) -> None:
    if not metrics:
        raise Problem("Name the metrics, for example: --metric precision:k=5 --metric recall:k=5 --metric dcg:k=5,normalize=true")
    blocks = [{name: params} for name, params in map(parse_metric, metrics)]
    pool = pool_of(h)
    reqs = []
    for q in read_set(h):
        item = pool.get(q["question_id"], {})
        if item.get("type") != "policy":
            continue
        reqs.append({"id": q["question_id"], "template_id": TEMPLATE_ID, "params": {"query_string": item.get("query_text") or item["input"]},
                     "ratings": [{"_index": INDEX, "_id": i, "rating": 1} for i in item.get("relevant_ids", [])]})
    if not reqs:
        raise Problem("Your test set holds no policy-retrieval questions to rate.")
    (h / "rank-eval.json").write_text(json.dumps({"requests": reqs, "metrics": blocks}, indent=2) + "\n")
    print(f"rank-eval.json: {len(reqs)} rated requests over {TEMPLATE_ID}, metrics {', '.join(m.split(':')[0] for m in metrics)}.", file=out)


def main(argv: list[str], environ: dict | None = None, out=None, es=None) -> int:
    out, environ = out or sys.stdout, dict(os.environ) if environ is None else environ
    h = home(environ)
    try:
        if not argv or argv[0] not in ("log", "add", "remove", "show", "save", "rank-eval"):
            print(__doc__, file=out)
            return 2
        cmd, rest = argv[0], argv[1:]
        if cmd == "log":
            cmd_log(h, out)
        elif cmd == "add":
            cmd_add(h, rest, out)
        elif cmd == "remove":
            cmd_remove(h, rest, out)
        elif cmd == "show":
            cmd_show(h, out)
        elif cmd == "save":
            cmd_save(h, es, out)
        else:
            metrics = [rest[i + 1] for i, a in enumerate(rest) if a == "--metric" and i + 1 < len(rest)]
            cmd_rank_eval(h, metrics, out)
        return 0
    except Problem as e:
        print(str(e), file=out)
        return 2
