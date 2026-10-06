#!/usr/bin/env python3
"""
validate_heldout.py - the one T9 validator for every ARA track (alignment N5, P14, P15).

Authoring tool; nothing in a sandbox runs it. It replaces the per-track copies: the generic
checks below run on every track, and a track keeps only what is truly its own in an optional
plugin (private/validate_track.py, a checks(ctx) function).

Usage:
  python3 lib/kit/validate_heldout.py --track <traqs track dir> --assets <vestal_project root>

The track declares its sets in private/heldout-spec.json:
  {
    "corpus": [                                   # vestal paths
      {"path": "data/cortex-corpus", "kind": "md"},
      {"path": "data/cortex-cases/cortex-cases.ndjson", "kind": "jsonl",
       "id": "case_id", "text": ["title", "body"]}
    ],
    "sets": [                                     # held-out (track path) and its dev twin (vestal)
      {"heldout": "private/heldout/02-context-questions.json",
       "dev": "data/dev-sets/m2/2-1-core-retrieval-infrastructure/dev-questions.json",
       "disjoint_docs": false}                    # true: no gold document shared (T9-e)
    ],
    "leak_scan": ["modules/m2/2-1-core-retrieval-infrastructure"],   # vestal paths a learner sees
    "plugin": "private/validate_track.py"         # optional
  }

Generic checks, per item (fields as the graders read them):
  T9-a  every required string / at least one gold literal / the unit text is in its gold document
  T9-b  WARN: a required string also occurs in another document
  T9-c  another document holds every required string together, or the whole unit text
  T9-d  WARN: a gold literal also occurs in another document
  T9-e  (disjoint_docs) held-out and dev items share a gold document
  P14   no held-out item's query or unit text (whitespace-normalised, case-folded) appears in its
        dev set, in a leak_scan path (notebooks, Brief, problem.txt), or in the track's
        assignment.md files; held-out and dev item ids never collide
Matching: required strings are whitespace-normalised, case-sensitive substrings (ara_context.score);
gold literals are case-folded substrings; unit text is whitespace-normalised.

Exit 0 when clean (WARN allowed), 1 on any FAIL, 2 on a usage error.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import re
import sys

LEAK_MIN_CHARS = 20          # shorter strings ("q1", a figure) are not evidence of a leak
LEAK_SUFFIXES = {".md", ".ipynb", ".html", ".txt", ".json", ".jsonl", ".py", ".csv"}
QUERY_FIELDS = ("query_text", "question", "query", "text")
ID_FIELDS = ("query_id", "unit_id", "id", "qid")


def norm(s: str) -> str:
    return " ".join(str(s).split())


class Ctx:
    """What a check sees, and where it reports."""

    def __init__(self, track: pathlib.Path, assets: pathlib.Path, spec: dict):
        self.track, self.assets, self.spec = track, assets, spec
        self.docs: dict[str, str] = {}
        self.fails = 0
        self.warns = 0

    def fail(self, msg: str) -> None:
        print(f"  FAIL {msg}")
        self.fails += 1

    def warn(self, msg: str) -> None:
        print(f"  WARN {msg}")
        self.warns += 1

    def ok(self, msg: str) -> None:
        print(f"  ok   {msg}")

    def path(self, rel: str) -> pathlib.Path:
        """A spec path: the track's own private/ files, else the assets repo."""
        p = self.track / rel
        return p if rel.startswith("private/") or p.exists() else self.assets / rel


def load_items(path: pathlib.Path) -> list[dict]:
    if path.suffix == ".jsonl":
        return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    data = json.loads(path.read_text())
    if isinstance(data, dict):
        for key in ("questions", "items", "queries", "units", "decisions"):
            if isinstance(data.get(key), list):
                return data[key]
        return []
    return data if isinstance(data, list) else []


def load_corpus(ctx: Ctx) -> None:
    for c in ctx.spec.get("corpus", [{"path": "data/cortex-corpus", "kind": "md"}]):
        p = ctx.assets / c["path"]
        if c.get("kind", "md") == "md":
            for f in sorted(p.rglob("*.md")):
                m = re.match(r"^(.+?-\d{3})", f.stem)  # policy-001-..., wire-fraud-201-...; else the stem
                ctx.docs[m.group(1) if m else f.stem] = norm(f.read_text())
        else:
            for row in load_items(p):
                did = row.get(c.get("id", "id"))
                text = " ".join(str(row.get(k, "")) for k in c.get("text", ["text"]))
                if did is not None:
                    ctx.docs[str(did)] = norm(text)


def item_id(q: dict) -> str:
    return next((str(q[k]) for k in ID_FIELDS if k in q), "?")


def gold_docs(q: dict) -> set[str]:
    g = q.get("relevant_ids") or ([q["target_doc"]] if q.get("target_doc") else []) \
        or ([q["doc_id"]] if q.get("doc_id") else [])
    return {str(x) for x in g}


def check_items(ctx: Ctx, label: str, items: list[dict]) -> None:
    docs = ctx.docs
    for q in items:
        qid = f"{label}:{item_id(q)}"
        gold = gold_docs(q)
        if not gold:
            continue
        missing = sorted(g for g in gold if g not in docs)
        if missing:
            if any(k in q for k in ("required_strings", "gold_literals", "text")):
                ctx.fail(f"T9-a {qid}: gold document not in the corpus: {missing}")
            continue
        if "required_strings" in q:
            req = [norm(r) for r in q["required_strings"]]
            for r in req:
                if not any(r in docs[g] for g in gold):
                    ctx.fail(f"T9-a {qid}: not in its gold document: {r!r}")
                others = sorted(d for d in docs if d not in gold and r in docs[d])
                if others:
                    ctx.warn(f"T9-b {qid}: {r!r} also in {others}")
            both = sorted(d for d in docs if d not in gold and all(r in docs[d] for r in req))
            if both:
                ctx.fail(f"T9-c {qid}: another document holds every required string: {both}")
        if "text" in q and ("unit_id" in q or "doc_id" in q):
            t = norm(q["text"])
            if not any(t in docs[g] for g in gold):
                ctx.fail(f"T9-a {qid}: unit text is not verbatim in {sorted(gold)}")
            others = sorted(d for d in docs if d not in gold and t in docs[d])
            if others:
                ctx.fail(f"T9-c {qid}: unit text also in {others}")
        if "gold_literals" in q:
            lits = [str(l).lower() for l in q["gold_literals"]]
            if not any(l in docs[g].lower() for g in gold for l in lits):
                ctx.fail(f"T9-a {qid}: no gold literal in {sorted(gold)}")
            for l in lits:
                others = sorted(d for d in docs if d not in gold and l in docs[d].lower())
                if others:
                    ctx.warn(f"T9-d {qid}: literal {l!r} also in {others}")


def leak_texts(items: list[dict]) -> list[tuple[str, str]]:
    out = []
    for q in items:
        for k in QUERY_FIELDS:
            v = q.get(k)
            if isinstance(v, str) and len(norm(v)) >= LEAK_MIN_CHARS:
                out.append((item_id(q), norm(v).lower()))
                break
    return out


def scan_files(paths: list[pathlib.Path]) -> dict[pathlib.Path, str]:
    texts = {}
    for p in paths:
        files = [p] if p.is_file() else sorted(x for x in p.rglob("*") if x.is_file()) if p.exists() else []
        for f in files:
            if f.suffix in LEAK_SUFFIXES and "private" not in f.parts and "__pycache__" not in f.parts:
                try:
                    raw = f.read_text(errors="replace")
                except OSError:
                    continue
                if f.suffix == ".ipynb":  # notebook cells keep strings split across lines
                    try:
                        cells = json.loads(raw).get("cells", [])
                        raw = "\n".join("".join(c.get("source", [])) + "\n" + json.dumps(c.get("outputs", []))
                                        for c in cells)
                    except ValueError:
                        pass
                texts[f] = norm(raw).lower()
    return texts


def check_leaks(ctx: Ctx, label: str, held: list[dict], dev: list[dict],
                dev_path: pathlib.Path | None) -> None:
    held_ids = {item_id(q) for q in held} - {"?"}
    dev_ids = {item_id(q) for q in dev} - {"?"}
    clash = sorted(held_ids & dev_ids)
    if clash:
        ctx.fail(f"P14 {label}: held-out and dev item ids collide: {clash}")
    dev_texts = {t for _, t in leak_texts(dev)}
    targets = [ctx.path(p) for p in ctx.spec.get("leak_scan", [])]
    targets += sorted(ctx.track.glob("*/assignment.md"))
    if dev_path is not None:
        targets.append(dev_path)
    corpus = scan_files(targets)
    for qid, t in leak_texts(held):
        if t in dev_texts:
            ctx.fail(f"P14 {label}:{qid}: the held-out text is a dev item")
            continue
        hits = sorted(str(f.relative_to(ctx.assets) if ctx.assets in f.parents else f.relative_to(ctx.track))
                      for f, body in corpus.items() if t in body)
        if hits:
            ctx.fail(f"P14 {label}:{qid}: held-out text appears where the learner can read it: {hits}")


def run(track: pathlib.Path, assets: pathlib.Path, spec_path: pathlib.Path | None = None) -> Ctx:
    spec_path = spec_path or track / "private" / "heldout-spec.json"
    if not spec_path.exists():
        print(f"usage: no {spec_path} (see this file's docstring for its shape)", file=sys.stderr)
        sys.exit(2)
    ctx = Ctx(track, assets, json.loads(spec_path.read_text()))
    load_corpus(ctx)
    print(f"corpus: {len(ctx.docs)} documents from {assets}")
    for s in ctx.spec.get("sets", []):
        hp = ctx.path(s["heldout"])
        held = load_items(hp)
        dp = ctx.path(s["dev"]) if s.get("dev") else None
        dev = load_items(dp) if dp and dp.exists() else []
        if dp and not dp.exists():
            ctx.fail(f"dev set missing: {s['dev']}")
        before = (ctx.fails, ctx.warns)
        check_items(ctx, hp.name, held)
        if dev:
            check_items(ctx, dp.name, dev)
        check_leaks(ctx, hp.name, held, dev, dp)
        if s.get("disjoint_docs") and dev:
            shared = sorted(set().union(*[gold_docs(q) for q in held]) & set().union(*[gold_docs(q) for q in dev]))
            if shared:
                ctx.fail(f"T9-e {hp.name}: held-out and dev share gold documents {shared}")
        print(f"{s['heldout']}: {len(held)} held-out, {len(dev)} dev, "
              f"{ctx.fails - before[0]} FAIL, {ctx.warns - before[1]} WARN")
    plugin = ctx.spec.get("plugin")
    if plugin:
        pp = track / plugin
        spec = importlib.util.spec_from_file_location("validate_track", pp)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        before = (ctx.fails, ctx.warns)
        mod.checks(ctx)
        print(f"{plugin}: {ctx.fails - before[0]} FAIL, {ctx.warns - before[1]} WARN")
    print(f"TOTAL: {ctx.fails} FAIL, {ctx.warns} WARN")
    return ctx


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--track", type=pathlib.Path, required=True)
    ap.add_argument("--assets", type=pathlib.Path, required=True)
    ap.add_argument("--spec", type=pathlib.Path)
    a = ap.parse_args(argv)
    ctx = run(a.track.resolve(), a.assets.resolve(), a.spec)
    return 1 if ctx.fails else 0


if __name__ == "__main__":
    sys.exit(main())
