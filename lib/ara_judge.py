"""ara_judge.py - the judge query's static contract and the held-out gate's ROW substitution (25 section 4).

Pure functions, standard library only. B2's held-out gate replaces the learner's first command with an inline
ROW source, so the query must start with `FROM cortex-eval-samples`; the same scan finds every other source
command, every COMPLETION's inference id, and the first pipe outside strings and comments.

    scan(esql)                         tokens as (kind, text): code, string, comment
    split_first_command(esql)          (first command text, the rest starting at its pipe)
    row_source(record)                 ('ROW sample_id = ?sid, ...', params) for one record
    substitute(esql, record)           (esql with its first command replaced by the ROW source, params)
    contract_violations(esql, inf_id)  list of messages; empty when the query meets the contract
"""
from __future__ import annotations

import re
from typing import Any

SAMPLE_FIELDS = ("sample_id", "question", "passage_ids", "passages", "answer")
FIRST_COMMAND = re.compile(r"^FROM\s+cortex-eval-samples$", re.IGNORECASE)
# Commands that start a new data source or pull in another one.
SOURCE_COMMANDS = ("FROM", "ROW", "SHOW", "TS", "METRICS", "ENRICH", "LOOKUP", "FORK", "INLINESTATS")
_INF_ID = re.compile(r"""["']inference_id["']\s*:\s*(?:"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)')""")


def scan(esql: str) -> list[tuple[str, str]]:
    """Split a query into ("code" | "string" | "comment", text) runs; the runs concatenate to the query."""
    out: list[tuple[str, str]] = []
    i, n, start = 0, len(esql), 0

    def flush(end: int) -> None:
        if end > start:
            out.append(("code", esql[start:end]))

    while i < n:
        c = esql[i]
        if esql.startswith('"""', i):
            flush(i)
            j = esql.find('"""', i + 3)
            j = n if j < 0 else j + 3
            out.append(("string", esql[i:j]))
            i = start = j
        elif c == '"':
            flush(i)
            j = i + 1
            while j < n and esql[j] != '"':
                j += 2 if esql[j] == "\\" else 1
            j = min(j + 1, n)
            out.append(("string", esql[i:j]))
            i = start = j
        elif esql.startswith("//", i):
            flush(i)
            j = esql.find("\n", i)
            j = n if j < 0 else j
            out.append(("comment", esql[i:j]))
            i = start = j
        elif esql.startswith("/*", i):
            flush(i)
            j = esql.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append(("comment", esql[i:j]))
            i = start = j
        else:
            i += 1
    flush(n)
    return out


def split_first_command(esql: str) -> tuple[str, str]:
    """The first command (comments dropped, whitespace collapsed) and the rest, which starts at its pipe."""
    pos = 0
    for kind, text in scan(esql):
        if kind == "code" and "|" in text:
            cut = pos + text.index("|")
            head = "".join(t for k, t in scan(esql[:cut]) if k != "comment")
            return " ".join(head.split()), esql[cut:]
        pos += len(text)
    return " ".join("".join(t for k, t in scan(esql) if k != "comment").split()), ""


def row_source(record: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """An inline ROW source in the sample schema, every value a named parameter (no quoting of record text)."""
    names = {"sample_id": "sid", "question": "q", "passage_ids": "ids", "passages": "p", "answer": "a"}
    fields = [f for f in SAMPLE_FIELDS if f in record]
    row = "ROW " + ", ".join(f"{f} = ?{names[f]}" for f in fields)
    return row, {names[f]: record[f] for f in fields}


def substitute(esql: str, record: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """The learner's query with its first command replaced by the record as a ROW source."""
    _, rest = split_first_command(esql)
    row, params = row_source(record)
    return row + ("\n" + rest if rest else ""), params


def contract_violations(esql: str, inference_id: str) -> list[str]:
    """Why a query breaks the judge contract; empty when it holds. Messages state the contract, never a record."""
    bad: list[str] = []
    head, rest = split_first_command(esql)
    if not FIRST_COMMAND.match(head):
        bad.append("The judge query's first command must be exactly FROM cortex-eval-samples.")
    code = " ".join(t for k, t in scan(rest) if k == "code")
    for cmd in SOURCE_COMMANDS:
        if re.search(rf"(?:^|\|)\s*{cmd}\b", code, re.IGNORECASE):
            bad.append(f"The judge query may not use {cmd} after its first command: it reads only the fields of "
                       "cortex-eval-samples.")
    if re.search(r"\bJOIN\b", code, re.IGNORECASE):
        bad.append("The judge query may not join another index: it reads only the fields of cortex-eval-samples.")
    ids = [(m.group(1) if m.group(1) is not None else m.group(2))
           for m in _INF_ID.finditer("".join(t for k, t in scan(rest) if k != "comment"))]
    n_complete = len(re.findall(r"(?:^|\|)\s*COMPLETION\b", code, re.IGNORECASE))
    if n_complete == 0:
        bad.append("The judge query must score each metric with a COMPLETION command.")
    elif len(ids) < n_complete or any(i != inference_id for i in ids):
        bad.append("Every COMPLETION in the judge query must use the judge endpoint named in the assignment "
                   "(ARA_JUDGE_INFERENCE_ID).")
    return bad
