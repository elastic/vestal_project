#!/usr/bin/env python3
"""Generate M5's copy of the M3 corpus with the identifier fields (25 section 8.2).

    python3 scripts/gen_m5_corpus.py [--check]

Reads M3's files on this branch (data/cortex-cases/cases.jsonl, data/cortex-sar-narratives/*.jsonl),
which do not change, and writes data/ara-m5/cortex-cases.ndjson and cortex-sar-narratives.ndjson:
the fields M3 indexed plus subject_name, subject_account and subject_tin on every document.

- Cases: subject_name is cases.jsonl customer_name; subject_account is the account number the body
  names; where the body names none (30 of 120), one is generated in the M3 format NN-NNNNN-N, unused
  anywhere in the corpus.
- SAR narratives: subject_name and subject_account are the M3 generator's own fields.
- subject_tin is new: SSN-shaped AAA-GG-SSSS with area 900 to 999 (never issued), unique, seeded.
- Gold literals, questions and contamination labels are not copied (never indexed, as in M3).

--check exits 1 when the committed files differ from a fresh build.
"""
import glob
import json
import pathlib
import random
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "ara-m5"
SEED = 5
ACCOUNT = re.compile(r"\b\d{2}-\d{5}-\d\b")
CASE_FIELDS = ("case_id", "case_type", "risk_tier", "filing_date", "title", "body")  # M3 3.3 bulk-load fields
SAR_FIELDS = ("sar_id", "case_type", "risk_tier", "filing_date", "case_reference", "body")


def build() -> dict[str, str]:
    rng = random.Random(SEED)
    cases = [json.loads(line) for line in (ROOT / "data/cortex-cases/cases.jsonl").read_text().splitlines() if line.strip()]
    sars = [json.loads(line) for f in sorted(glob.glob(str(ROOT / "data/cortex-sar-narratives/bucket_*.jsonl")))
            for line in pathlib.Path(f).read_text().splitlines() if line.strip()]
    sars.sort(key=lambda r: r["doc_id"])
    used = {a for r in cases + sars for a in ACCOUNT.findall(r["body"])} | {r["subject_account"] for r in sars}
    tins: set[str] = set()

    def new_account() -> str:
        while True:
            a = f"{rng.randint(10, 99)}-{rng.randint(10000, 99999)}-{rng.randint(0, 9)}"
            if a not in used:
                used.add(a)
                return a

    def new_tin() -> str:
        while True:
            t = f"{rng.randint(900, 999)}-{rng.randint(1, 99):02d}-{rng.randint(1, 9999):04d}"
            if t not in tins:
                tins.add(t)
                return t

    case_out = []
    for r in sorted(cases, key=lambda r: r["case_id"]):
        named = sorted(set(ACCOUNT.findall(r["body"])))
        doc = {k: r[k] for k in CASE_FIELDS}
        doc.update(subject_name=r["customer_name"], subject_account=named[0] if named else new_account(),
                   subject_tin=new_tin())
        case_out.append(doc)
    sar_out = []
    for r in sars:
        doc = {"sar_id": r["doc_id"], **{k: r[k] for k in SAR_FIELDS[1:]}}
        doc.update(subject_name=r["subject_name"], subject_account=r["subject_account"], subject_tin=new_tin())
        sar_out.append(doc)
    dump = lambda rows: "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows)
    return {"cortex-cases.ndjson": dump(case_out), "cortex-sar-narratives.ndjson": dump(sar_out)}


def main() -> int:
    files = build()
    if "--check" in sys.argv[1:]:
        stale = [n for n, text in files.items() if not (OUT / n).exists() or (OUT / n).read_text() != text]
        print("data/ara-m5 corpus: " + (f"STALE {stale}" if stale else "current"))
        return 1 if stale else 0
    OUT.mkdir(parents=True, exist_ok=True)
    for n, text in files.items():
        (OUT / n).write_text(text)
        print(f"wrote data/ara-m5/{n}: {text.count(chr(10))} documents")
    return 0


if __name__ == "__main__":
    sys.exit(main())
