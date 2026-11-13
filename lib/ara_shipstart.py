"""ara_shipstart.py - the 5.C start state's pure parts (plan.md sections 2 and 3): the pool and test set the lab runs on, the
question ids each seed's gain is measured over, and the change request text. Standard library only; the 01 setup calls these
and writes the results to root-held files.

    build_pool(pool53, additions)       the 5.3 pool plus the 5.C additions; SAR-citation gold accepts either SAR tool (any_of)
    build_testset(v1, additions, pool)  test set v1c: the 30 v1 questions plus the 12 additions, in pool order
    gain_ids(testset, pool)             {"S1": SAR-citation ids, "S2": regulation ids, "S3": every agent-level id}
    render_change_request(text, seed, values)   the seed's change request; a missing value is an error, never a guess
"""
from __future__ import annotations

import copy
import re

SAR_TOOLS = ["cortex.sar_search", "cortex.sar_passages"]
PAGES_MARK = "/ara-m5-pages/"


def _sar_gold(item: dict) -> bool:
    exp = item.get("expected") or []
    return any(e.get("tool_id") == "cortex.sar_search" for e in exp)


def build_pool(pool53: list[dict], additions: list[dict]) -> list[dict]:
    """Existing items whose gold names cortex.sar_search take any_of [sar_search, sar_passages] on that entry: with S1 staged
    Tina's call goes to the new tool, and a gold of the old tool alone would read as a routing loss."""
    out = []
    for q in pool53:
        q = copy.deepcopy(q)
        if _sar_gold(q):
            q["expected"] = [({"any_of": list(SAR_TOOLS), **{k: v for k, v in e.items() if k != "tool_id"}}
                              if e.get("tool_id") == "cortex.sar_search" else e) for e in q["expected"]]
        out.append(q)
    seen = {q["id"] for q in out}
    for q in additions:
        if q["id"] in seen:
            raise ValueError(f"pool id {q['id']} is already in the 5.3 pool")
        seen.add(q["id"])
        out.append(copy.deepcopy(q))
    return out


def build_testset(v1: list[dict], additions: list[dict], pool: dict) -> list[dict]:
    """v1's entries as they are, then one entry per addition (its category, kind and input from the pool item)."""
    ids = {q["question_id"] for q in v1}
    out = [dict(q) for q in v1]
    for a in additions:
        if a["id"] in ids:
            raise ValueError(f"{a['id']} is already in v1")
        p = pool[a["id"]]
        out.append({"question_id": a["id"], "category": p["category"], "kind": p.get("kind"), "input": p["input"]})
    return out


def gain_ids(testset: list[dict], pool: dict) -> dict[str, list[str]]:
    s1, s2, s3 = [], [], []
    for q in testset:
        item = pool[q["question_id"]]
        exp = item.get("expected") or []
        if item.get("type") == "agent":
            s3.append(q["question_id"])
        if any("cortex.sar_passages" in (e.get("any_of") or []) for e in exp):
            s1.append(q["question_id"])
        if PAGES_MARK in ((item.get("page") or {}).get("url") or ""):
            s2.append(q["question_id"])
    return {"S1": s1, "S2": s2, "S3": s3}


def _section(text: str, seed: str) -> str:
    m = re.search(rf"^## {seed} template: .*?(?=^---$|\Z)", text, re.S | re.M)
    if not m:
        raise ValueError(f"no template for {seed}")
    return m.group(0)


def render_change_request(text: str, seed: str, values: dict) -> str:
    """The common header and closing, plus the seed's section, with every {name} filled from values. A name with no value
    (or None, a number calibration has not set) raises: a draft number never reaches a learner."""
    body = _section(text, seed)
    tail = text[text.index("## What we need from you"):]
    top = text[text.index("# Change request"):text.index("\n---\n")]
    doc = "\n\n---\n\n".join([top.strip(), re.sub(r"^## S\d template: (.*?) = ", r"## ", body, count=1).strip(), tail.strip()]) + "\n"
    missing = sorted({n for n in re.findall(r"\{(\w+)\}", doc) if values.get(n) is None})
    if missing:
        raise ValueError("change request values not set: " + ", ".join(missing))
    return re.sub(r"\{(\w+)\}", lambda m: str(values[m.group(1)]), doc)
