#!/usr/bin/env python3
"""S1 data: the passage-level copy of the SAR narratives, `cortex-sar-passages-fast` (07 section 2.2).

DRAFT, offline. Deterministic, no randomness: one passage per `## ` section of each narrative, section text cut at
MAX_CHARS on a sentence or line boundary, Exhibit sections skipped (ledger rows are not citable prose). Every passage
carries the narrative's `sar_id`, `case_reference`, `case_type`, `risk_tier`, `filing_date` and the three subject
fields, which is exactly what makes the copy a hole: the roles' DLS and FLS name `cortex-sar-narratives`, not this index.

    gen_m5_passages.py <cortex-sar-narratives.ndjson> [--out passages.ndjson] [--stats]

The M5 build commits the output as data/ara-m5/5c/cortex-sar-passages-fast.ndjson and the mapping as
data/ara-m5/mappings/cortex-sar-passages-fast.json (MAPPING below). Passage text keeps names and account numbers as the
narrative has them (FLS hides fields, not text inside a field, as 5.1 teaches), so a probe reads the structured fields
and the document set, never the passage text.
needs_live_check: passage count and size against the embedding time at provisioning, and the priced gain (section 2 of plan.md).
"""
from __future__ import annotations

import argparse
import json
import re
import sys

MAX_CHARS = 1200
SKIP = re.compile(r"^(Exhibit|Appendix)\b", re.I)
KEEP_FIELDS = ("sar_id", "case_reference", "case_type", "risk_tier", "filing_date", "subject_name", "subject_account",
               "subject_tin")

MAPPING = {
    "mappings": {"properties": {
        "passage_id": {"type": "keyword"}, "sar_id": {"type": "keyword"}, "case_reference": {"type": "keyword"},
        "case_type": {"type": "keyword"}, "risk_tier": {"type": "keyword"}, "filing_date": {"type": "date"},
        "section": {"type": "keyword"}, "body_text": {"type": "text"},
        "body": {"type": "semantic_text", "inference_id": ".jina-embeddings-v5-text-small"},
        "subject_name": {"type": "keyword"}, "subject_account": {"type": "keyword"}, "subject_tin": {"type": "keyword"},
    }}
}


def cut(text: str, limit: int = MAX_CHARS) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    head = text[:limit]
    stop = max(head.rfind(". "), head.rfind(".\n"), head.rfind("\n"))
    return (head[:stop + 1] if stop > limit // 2 else head).strip()


def make_passages(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        parts = re.split(r"^## (.+)$", r["body"], flags=re.M)  # ["", title, text, title, text, ...]
        n = 0
        for title, text in zip(parts[1::2], parts[2::2]):
            if SKIP.match(title.strip()) or not text.strip():
                continue
            n += 1
            body = cut(text)
            out.append({"passage_id": f"{r['sar_id']}-p{n:02d}", "section": title.strip(), "body": body, "body_text": body,
                        **{k: r[k] for k in KEEP_FIELDS}})  # body_text: the lexical copy, as the corpus indices carry
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("narratives")
    ap.add_argument("--out")
    ap.add_argument("--stats", action="store_true")
    a = ap.parse_args(argv)
    rows = [json.loads(line) for line in open(a.narratives, encoding="utf-8") if line.strip()]
    passages = make_passages(rows)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            for p in passages:
                f.write(json.dumps(p, ensure_ascii=False) + "\n")
    if a.stats or not a.out:
        sizes = sorted(len(p["body"]) for p in passages)
        print(f"{len(rows)} narratives -> {len(passages)} passages; chars min {sizes[0]}, median {sizes[len(sizes) // 2]}, "
              f"max {sizes[-1]}; narrative chars {sum(len(r['body']) for r in rows)}, passage chars {sum(sizes)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
