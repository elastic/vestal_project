"""
ara_capstone.py - Tina's harness for the Module 3 capstone.

Read this file. Do not edit it: the Check loads it from here, so a change you make
is a change the grader does not see. Everything you write goes in
/home/elastic/pipeline.py.

What the harness gives you:

  retrieval      search(), semantic_body(), hybrid_body(), case_filters(),
                 passage_filters(), rerank()
  generation     complete(), ANSWER_PROMPT, SUMMARY_PROMPT
  packing        pack_naive(), pack_rerank_top_n(), pack_summarize_first(),
                 token_count(), truncate_to_tokens()
  attribution    split_claims(), attribute_by_overlap()
  guardrails     figures_in(), reads_as_refusal(), FALLBACK_MESSAGE,
                 OUT_OF_SCOPE_MESSAGE, HOOKS
  observability  trace()

Every retrieval, every attribution record, and every guardrail that fires is
written to /home/elastic/.traces/capstone-trace.jsonl by the harness. You do not
have to call trace() yourself; the Defend reads that file to check the levers you
claim against the ones it can see.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import sys
import threading
import time

# ── Indices and endpoints ─────────────────────────────────────────────────────

POLICY_INDEX = "cortex-policies"
CASE_INDEX = "cortex-cases"
PASSAGE_INDEX = "cortex-sar-passages"

# The weak configuration searches all three in one request, which is what makes it
# naive: no decision is taken about where a question belongs.
ALL_INDEXES = ",".join((POLICY_INDEX, CASE_INDEX, PASSAGE_INDEX))

# Which index holds the material for each query class.
CLASS_INDEX = {
    "policy": POLICY_INDEX,
    "case": CASE_INDEX,
    "sar": PASSAGE_INDEX,
    "unanswerable": ALL_INDEXES,
}

COMPLETION_ID = os.environ.get("ARA_INFERENCE_COMPLETION_ID", "cortex-generation")
RERANK_ID = os.environ.get("ARA_RERANK_ID", "")
CONTEXT_BUDGET = int(os.environ.get("ARA_CONTEXT_BUDGET", "6000") or "6000")

TRACE_DIR = pathlib.Path(os.environ.get("ARA_TRACE_DIR", "/home/elastic/.traces"))
TRACE_PATH = TRACE_DIR / "capstone-trace.jsonl"
RESULTS_PATH = TRACE_DIR / "capstone-results.json"
DEV_POOL_PATH = pathlib.Path("/home/elastic/dev-sets/dev-pool.json")

# Tina's production answer prompt. It asks for an answer and says nothing about when
# to decline: deciding what reaches the desk is the pipeline's job, in guard(), not
# something to hope the model does on its own.
ANSWER_PROMPT = (
    "You are a compliance assistant for Cortex Bank and Trust. Answer the analyst's "
    "question from the material below, as specifically as the material allows. Quote "
    "every figure, name, and date exactly as it appears in the material.\n\n"
    "Material:\n{context}\n\nQuestion: {question}\nAnswer:"
)

SUMMARY_PROMPT = (
    "Condense the section below to at most six sentences for a compliance analyst "
    "reading it as evidence. Keep every amount, name, account number, and date exactly "
    "as written. Drop procedural narration. Do not add anything that is not in the "
    "section.\n\nSection:\n{text}\n\nCondensed:"
)

FALLBACK_MESSAGE = (
    "I cannot answer this from the compliance corpus. No policy section, case memo, or "
    "narrative section on file supports an answer."
)
OUT_OF_SCOPE_MESSAGE = (
    "That question is outside the Cortex Bank and Trust compliance corpus, which holds "
    "policy sections, case memos, and suspicious activity narratives."
)

# The names a guardrail reports as its hook. guard() returns one of these when it acts;
# submit.py and the Defend count the questions each one held back.
HOOKS = ("scope_check", "confidence_fallback", "validate_output")

_TRACE_LOCK = threading.Lock()
_CLIENT = None


class RemoteUnavailable(RuntimeError):
    """A model, reranker or search call still failed after two retries.

    The harness never answers with something else in its place: no original text for
    a summary, no retrieval order for a rerank, no empty answer for a completion.
    submit.py stops on it, and the Check exits without a grade (principle 8).
    """


def is_outage(exc: Exception) -> bool:
    """No response, a rate limit, an auth failure, or a 5xx. A rejected request is not."""
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "meta", None), "status", None)
    if isinstance(status, int):
        return status in (401, 403, 408, 429) or status >= 500
    try:
        from elastic_transport import TransportError
    except Exception:
        TransportError = OSError  # noqa: N806
    return isinstance(exc, (TransportError, OSError, TimeoutError))


def remote_call(label: str, fn, *args, **kwargs):
    """One remote call: an outage is retried twice, then RemoteUnavailable is raised.

    A request the endpoint rejected is raised at once, unchanged.
    """
    for attempt in range(3):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            if not is_outage(exc):
                raise
            if attempt == 2:
                raise RemoteUnavailable(
                    f"{label} endpoint unreachable after 3 attempts "
                    f"({type(exc).__name__}: {str(exc)[:160]}). Wait a moment and try again."
                ) from exc
            wait = 1.5 * (attempt + 1)
            print(f"[ara_capstone] retry {attempt + 1} of 2: {label} call failed "
                  f"({type(exc).__name__}), trying again in {wait:.0f} s",
                  file=sys.stderr, flush=True)
            time.sleep(wait)


# ── Client, tracing, and small utilities ──────────────────────────────────────

def es_client():
    """One Elasticsearch client for the whole run, built from the sandbox env."""
    global _CLIENT
    if _CLIENT is None:
        from elasticsearch import Elasticsearch
        _CLIENT = Elasticsearch(
            os.environ["ES_URL"],
            api_key=os.environ["ES_API_KEY"],
            request_timeout=180,
        )
    return _CLIENT


def unwrap(resp):
    """Elasticsearch responses are not dicts."""
    return resp.body if hasattr(resp, "body") else resp


def _http_status(exc: BaseException):
    """The HTTP status an exception carries, or None when there was no response."""
    for value in (getattr(exc, "status_code", None),
                  getattr(getattr(exc, "meta", None), "status", None),
                  getattr(getattr(exc, "response", None), "status_code", None)):
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    try:
        from urllib.error import HTTPError
        if isinstance(exc, HTTPError) and isinstance(exc.code, int):
            return exc.code
    except Exception:  # noqa: BLE001
        pass
    return None


def _no_response(exc: BaseException) -> bool:
    """A connection that failed: refused, reset, dropped, or never made.

    A timeout on its own is not counted here: the harness's own calls retry a timeout
    and then raise RemoteUnavailable, so a bare timeout came from the caller's code.
    """
    if isinstance(exc, ConnectionError):
        return True
    import importlib
    for module, names in (("elastic_transport", ("ConnectionError",)),
                          ("requests.exceptions", ("ConnectionError",)),
                          ("httpx", ("NetworkError",)),
                          ("urllib3.exceptions", ("NewConnectionError", "ProtocolError"))):
        try:
            mod = importlib.import_module(module)
        except Exception:  # noqa: BLE001 - library not installed
            continue
        kinds = tuple(k for k in (getattr(mod, n, None) for n in names) if isinstance(k, type))
        if kinds and isinstance(exc, kinds):
            return True
    try:
        from urllib.error import HTTPError, URLError
        if isinstance(exc, URLError) and not isinstance(exc, HTTPError):
            return not isinstance(getattr(exc, "reason", None), TimeoutError)
    except Exception:  # noqa: BLE001
        pass
    return False


def is_remote_error(exc: BaseException) -> bool:
    """True when an error is an outage, judged by its type and HTTP status, never its text.

    An outage is RemoteUnavailable (a harness call that still failed after its retries),
    an HTTP 401, 403, 408, 429 or 5xx, or a connection that failed. Any other error,
    whatever its message says, is the code's own. The error it was raised from or during
    counts too, so wrapping an outage in another exception keeps it an outage.
    """
    seen: set[int] = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, RemoteUnavailable):
            return True
        status = _http_status(exc)
        if status is not None:
            if status in (401, 403, 408, 429) or status >= 500:
                return True
        elif _no_response(exc):
            return True
        exc = exc.__cause__ or exc.__context__
    return False


def trace(record: dict) -> None:
    """Append one line to /home/elastic/.traces/capstone-trace.jsonl."""
    row = dict(record)
    row.setdefault("at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    with _TRACE_LOCK:
        TRACE_DIR.mkdir(parents=True, exist_ok=True)
        with TRACE_PATH.open("a") as handle:
            handle.write(json.dumps(row) + "\n")


def reset_trace() -> None:
    """Start a clean trace. submit.py calls this before a dev-pool run."""
    with _TRACE_LOCK:
        TRACE_DIR.mkdir(parents=True, exist_ok=True)
        TRACE_PATH.write_text("")


def load_dev_pool(path: str | pathlib.Path | None = None) -> list[dict]:
    """The forty public dev questions, ten per query class."""
    return json.loads(pathlib.Path(path or DEV_POOL_PATH).read_text())


def token_count(text: str) -> int:
    """cl100k_base token count. The Check counts the same way."""
    try:
        import tiktoken
        return len(tiktoken.get_encoding("cl100k_base").encode(text or ""))
    except Exception:
        return int(len((text or "").split()) * 1.3)


_CHUNK_SUFFIX = re.compile(r"-s\d+$")
_SECTION_SUFFIX = re.compile(r"^(sar-\d+)-section-\d+$")


def source_ids(retrieved_id: str) -> set[str]:
    """Every id a retrieved unit can be scored against.

    `cortex-policies` holds one chunk per policy section, keyed `policy-011-s37`, and
    `cortex-sar-passages` holds one section per narrative, keyed `sar-031-section-12`.
    A relevant set names source documents, so a unit counts when its own id or its
    source document's id is in that set.
    """
    text = str(retrieved_id or "")
    ids = {text}
    chunk = _CHUNK_SUFFIX.sub("", text)
    if chunk != text:
        ids.add(chunk)
    section = _SECTION_SUFFIX.match(text)
    if section:
        ids.add(section.group(1))
    return ids


def precision_at_k(retrieved: list[str], relevant: list[str], k: int = 10) -> float:
    """Precision@k over retrieved unit ids. The Check measures the same way.

    The denominator is k, not the number retrieved: a pipeline that returns three
    units for a question with thirty relevant documents has not earned 1.0.
    """
    gold = set(relevant or [])
    if not gold:
        return 0.0
    hits = sum(1 for unit in (retrieved or [])[:k] if source_ids(unit) & gold)
    return hits / float(k)


def truncate_to_tokens(text: str, budget: int) -> str:
    """The first `budget` tokens of `text`."""
    if budget <= 0:
        return ""
    try:
        import tiktoken
        encoding = tiktoken.get_encoding("cl100k_base")
        tokens = encoding.encode(text or "")
        if len(tokens) <= budget:
            return text or ""
        return encoding.decode(tokens[:budget])
    except Exception:
        words = (text or "").split()
        return " ".join(words[:max(1, int(budget / 1.3))])


# ── Retrieval ─────────────────────────────────────────────────────────────────

def semantic_body(query_text: str, size: int = 10, filters: list[dict] | None = None) -> dict:
    """Semantic retrieval over the shared `body` field.

    This is the weak default: one shape for every question, no filters.
    """
    query: dict = {"match": {"body": query_text}}  # match on a semantic_text field is a semantic query
    if filters:
        query = {"bool": {"must": [query], "filter": list(filters)}}
    return {"retriever": {"standard": {"query": query}}, "size": size}


def hybrid_body(query_text: str, size: int = 10, filters: list[dict] | None = None) -> dict:
    """BM25 on `body_text` fused with semantic retrieval on `body`.

    Filters are applied inside both legs, because a filter on only one leg leaves the
    other free to return the documents the filter was meant to exclude.
    """
    lexical: dict = {"match": {"body_text": query_text}}
    semantic: dict = {"match": {"body": query_text}}
    if filters:
        lexical = {"bool": {"must": [lexical], "filter": list(filters)}}
        semantic = {"bool": {"must": [semantic], "filter": list(filters)}}
    return {
        "retriever": {
            "rrf": {
                "retrievers": [
                    {"standard": {"query": lexical}},
                    {"standard": {"query": semantic}},
                ],
                "rank_window_size": 50,
                "rank_constant": 60,
            }
        },
        "size": size,
    }


def case_filters(intent: dict | None) -> list[dict]:
    """Filter clauses for `cortex-cases` from the intent the question carries.

    `case_type` and `risk_tier` are keyword fields, so they take a term clause.
    `filing_date` is a date field, so a window takes a range clause.
    """
    intent = intent or {}
    clauses: list[dict] = []
    if intent.get("case_type"):
        clauses.append({"term": {"case_type": intent["case_type"]}})
    if intent.get("risk_tier"):
        clauses.append({"term": {"risk_tier": intent["risk_tier"]}})
    window = {}
    if intent.get("date_from"):
        window["gte"] = intent["date_from"]
    if intent.get("date_to"):
        window["lte"] = intent["date_to"]
    if window:
        clauses.append({"range": {"filing_date": window}})
    return clauses


def passage_filters(intent: dict | None) -> list[dict]:
    """Filter clauses for `cortex-sar-passages`. The same facets, the same types."""
    return case_filters(intent)


def search(index: str, body: dict, query_class: str = "") -> list[dict]:
    """Run one search and return the hits as passage dicts, in rank order.

    Each entry carries `passage_id`, `source_type`, `text`, `tokens`, and `score`.
    The call is written to the trace with the index and the body it ran. An outage is
    retried twice and then raises RemoteUnavailable; a body Elasticsearch rejects
    returns no hits, with the error in the trace.
    """
    es = es_client()
    try:
        resp = unwrap(remote_call("search", es.search, index=index, body=body))
    except Exception as exc:
        trace({"kind": "retrieval", "query_class": query_class, "index": index,
               "body": body, "returned": 0, "error": str(exc)[:200]})
        if isinstance(exc, RemoteUnavailable):
            raise
        return []

    out: list[dict] = []
    for hit in resp.get("hits", {}).get("hits", []):
        source = hit.get("_source", {})
        text = source.get("body_text") or source.get("body") or ""
        if isinstance(text, dict):
            text = text.get("text", "")
        passage_id = (source.get("doc_id") or source.get("case_id")
                      or source.get("section_id") or hit.get("_id", ""))
        out.append({
            "passage_id": str(passage_id),
            "source_type": source.get("source_type") or hit.get("_index", ""),
            "text": text,
            "tokens": int(source.get("token_count") or 0) or token_count(text),
            "score": float(hit.get("_score", 0.0) or 0.0),
        })
    trace({"kind": "retrieval", "query_class": query_class, "index": index,
           "body": body, "returned": len(out),
           "passage_ids": [p["passage_id"] for p in out]})
    return out


def rerank(query_text: str, passages: list[dict]) -> list[dict]:
    """Attach a calibrated relevance score to each passage and order by it.

    Reciprocal rank fusion produces an ordering, not a relevance magnitude, so its
    score cannot carry a confidence threshold. The rerank endpoint returns a score
    between 0 and 1 per passage that can. A failed call is retried twice and then
    raises RemoteUnavailable: the retrieval order is never used in its place, because
    a confidence threshold read off retrieval scores refuses everything.
    """
    if not RERANK_ID or not passages:
        return passages
    inputs = [(p.get("text") or "")[:2000] for p in passages]
    resp = unwrap(remote_call(
        "rerank", es_client().inference.inference,
        inference_id=RERANK_ID,
        body={"query": query_text, "input": inputs},
    ))
    for entry in resp.get("rerank") or []:
        index = int(entry.get("index", -1))
        if 0 <= index < len(passages):
            passages[index]["score"] = float(entry.get("relevance_score", 0.0) or 0.0)
    return sorted(passages, key=lambda p: float(p.get("score", 0.0) or 0.0), reverse=True)


# ── Generation ────────────────────────────────────────────────────────────────

def complete(prompt: str) -> str:
    """One completion at temperature 0.

    An outage is retried twice with a short backoff, then RemoteUnavailable is
    raised. It never returns None in place of an answer: a question the model could
    not answer is not graded, it is run again once the endpoint is back.
    """
    resp = unwrap(remote_call(
        "completion", es_client().inference.inference,
        inference_id=COMPLETION_ID,
        body={"input": prompt, "task_settings": {"temperature": 0}},
    ))
    return (resp.get("completion") or [{}])[0].get("result", "") or ""


# ── Packing ───────────────────────────────────────────────────────────────────

def render(passages: list[dict]) -> str:
    """The context string the answer prompt carries."""
    blocks = [f"[{p['passage_id']} | {p.get('source_type', '')}]\n{p.get('text') or ''}"
              for p in passages]
    return "\n\n".join(blocks)


def fit_to_budget(passages: list[dict], budget: int) -> list[dict]:
    """Drop passages from the tail until the rendered context fits the budget.

    Summing the passages is not the same as measuring the context: `render` adds a
    header line per passage and a blank line between them, and on eight passages that
    overhead is enough to cross a budget the sum said was clear. The Check counts the
    string you sent, so this measures the string.
    """
    kept = list(passages)
    while kept and token_count(render(kept)) > budget:
        kept.pop()
    return kept


def pack_naive(passages: list[dict], budget: int | None = None) -> str:
    """Every retrieved unit, whole, in rank order. Ignores the budget.

    This is what Tina does today. On a policy question it fits comfortably. On a
    narrative question it does not, because one section of a long narrative can carry
    four thousand tokens on its own.
    """
    return render(passages)


def pack_rerank_top_n(query_text: str, passages: list[dict], budget: int | None = None,
                      n: int = 3) -> str:
    """Rerank, then take whole units from the top until the budget is reached.

    A unit that would cross the budget is left out rather than cut in half, because
    half a section is a passage whose figures may no longer be in it. The one
    exception is a first unit larger than the whole budget, which is truncated.
    """
    budget = int(budget or CONTEXT_BUDGET)
    ordered = rerank(query_text, list(passages))[:max(1, n)]
    kept: list[dict] = []
    used = 0
    for passage in ordered:
        tokens = token_count(passage.get("text") or "")
        if not kept and tokens > budget:
            trimmed = dict(passage)
            trimmed["text"] = truncate_to_tokens(passage.get("text") or "", budget - 64)
            kept.append(trimmed)
            break
        if used + tokens > budget:
            continue
        kept.append(passage)
        used += tokens
    return render(fit_to_budget(kept, budget))


def pack_summarize_first(query_text: str, passages: list[dict], budget: int | None = None,
                         n: int = 4, per_unit: int = 700) -> str:
    """Condense any unit over `per_unit` tokens, then pack the condensed set.

    Summarising costs a generation call per long unit and it keeps more units in the
    context than reranking to the top three does, which is the trade the Brief for
    3.3 put in front of you. The summary prompt holds the model to the figures.
    """
    budget = int(budget or CONTEXT_BUDGET)
    ordered = rerank(query_text, list(passages))[:max(1, n)]
    condensed: list[dict] = []
    for passage in ordered:
        text = passage.get("text") or ""
        if token_count(text) > per_unit:
            summary = complete(SUMMARY_PROMPT.format(text=truncate_to_tokens(text, 6000)))
            # A failed call has already raised. An empty summary is the model's answer,
            # and the unit is cut to per_unit tokens rather than sent whole.
            if summary:
                passage = {**passage, "text": summary}
            else:
                passage = {**passage, "text": truncate_to_tokens(text, per_unit)}
        condensed.append(passage)
    kept: list[dict] = []
    used = 0
    for passage in condensed:
        tokens = token_count(passage.get("text") or "")
        if used + tokens > budget:
            continue
        kept.append(passage)
        used += tokens
    return render(fit_to_budget(kept, budget))


# ── Attribution ───────────────────────────────────────────────────────────────

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
# A full stop that ends an abbreviation does not end the sentence: "Holdings Ltd." is
# part of the claim that names the company.
_ABBREVIATIONS = {"ltd.", "inc.", "co.", "corp.", "llc.", "lp.", "no.", "st.", "mr.",
                  "ms.", "mrs.", "dr.", "jr.", "u.s.", "e.g.", "i.e.", "vs."}


def split_claims(answer: str) -> list[str]:
    """One claim per sentence. The Check splits the same way."""
    sentences: list[str] = []
    for part in _SENTENCE_RE.split(answer or ""):
        if sentences and (sentences[-1].split() or [""])[-1].lower() in _ABBREVIATIONS:
            sentences[-1] = f"{sentences[-1]} {part}"
        else:
            sentences.append(part)
    return [s.strip() for s in sentences if len(s.strip()) > 12]


_NUM_RE = re.compile(r"\$?\d[\d,]*(?:\.\d+)?%?")
_STOP = {
    "the", "a", "an", "of", "and", "or", "to", "in", "on", "for", "was", "were", "is",
    "are", "be", "been", "that", "this", "with", "by", "at", "from", "as", "it", "its",
    "must", "may", "not", "no", "any", "all", "which", "within", "during", "over",
    "than", "then", "there", "their", "has", "had", "have", "after", "before", "one",
}
FIGURE_OVERLAP_TARGET = 0.20
WORD_OVERLAP_TARGET = 0.40


def _content_words(text: str) -> set[str]:
    words = re.findall(r"[A-Za-z][A-Za-z'-]+", (text or "").lower())
    return {w for w in words if w not in _STOP and len(w) > 2}


def _normalize_number(value: str) -> str:
    return value.replace(",", "").replace(" ", "")


QUOTED_SPAN_WORDS = 4

# A claim that cites a passage by its id ("Under policy-011-s52: ...") carries the
# digits of the id. They are a reference, not a figure, so they are set aside before
# the claim is matched.
_PASSAGE_REF_RE = re.compile(r"\[?\b(?:policy|case|sar)-[A-Za-z0-9-]*\d[A-Za-z0-9-]*\]?",
                             re.IGNORECASE)


def longest_quoted_span(claim: str, text: str) -> int:
    """The longest run of consecutive claim words that appears verbatim in `text`.

    A quoted span is evidence of the same kind as a figure: the answer prompt asks
    the model to quote names and dates exactly, and a four-word run reproduced from a
    passage is not a coincidence of vocabulary.
    """
    words = re.findall(r"[A-Za-z0-9$,.%'-]+", claim or "")
    lowered = " ".join((text or "").lower().split())
    best = 0
    for start in range(len(words)):
        for end in range(start + best + 1, len(words) + 1):
            span = " ".join(words[start:end]).lower()
            if span in lowered:
                best = max(best, end - start)
            else:
                break
    return best


def attribute_by_overlap(claims: list[str], passages: list[dict],
                         overlap_target: float = WORD_OVERLAP_TARGET) -> list[dict]:
    """Map each claim to the passage that carries it, or to UNSUPPORTED.

    One deterministic rule, no model call: a claim is attributed to a passage when
    every number in the claim appears in that passage and enough of the claim's
    content words do too. The best-scoring passage wins; nothing that reaches the
    target leaves the claim UNSUPPORTED.

    Three kinds of evidence relax the word-overlap bar, in this order:

      1. every figure in the claim appears in exactly one candidate passage. The
         figure identifies the passage on its own, so word overlap cannot overturn
         it, and a terse answer such as "The aggregate was $842,316.50." is
         attributed rather than stripped for having three content words.
      2. a figure in the claim that more than one candidate carries, which lowers
         the bar to ``FIGURE_OVERLAP_TARGET`` and lets overlap pick between them.
      3. a verbatim run of at least ``QUOTED_SPAN_WORDS`` claim words in the
         passage, which means the claim is reproducing the passage rather than
         paraphrasing around it.

    Returns [{"claim", "passage_id", "source_type", "score"}] in claim order, and
    writes one attribution record per claim to the trace.
    """
    out: list[dict] = []
    for claim in claims:
        body = _PASSAGE_REF_RE.sub(" ", claim or "")
        claim_numbers = {_normalize_number(n) for n in _NUM_RE.findall(body)}
        claim_words = _content_words(body)
        candidates = [p for p in passages
                      if not claim_numbers
                      or all(n in _normalize_number(p.get("text") or "")
                             for n in claim_numbers)]
        unique_owner = bool(claim_numbers) and len(candidates) == 1

        best_id, best_type, best_score = "UNSUPPORTED", "", 0.0
        target = overlap_target
        for passage in candidates:
            text = passage.get("text") or ""
            if not claim_words and not unique_owner:
                continue
            score = (len(claim_words & _content_words(text)) / len(claim_words)
                     if claim_words else 0.0)
            if score > best_score or (unique_owner and best_id == "UNSUPPORTED"):
                if unique_owner:
                    target = 0.0
                elif claim_numbers or longest_quoted_span(body, text) >= QUOTED_SPAN_WORDS:
                    target = FIGURE_OVERLAP_TARGET
                else:
                    target = overlap_target
                best_id = passage.get("passage_id", "")
                best_type = passage.get("source_type", "")
                best_score = score
        if best_score < target:
            best_id, best_type = "UNSUPPORTED", ""
        record = {"claim": claim, "passage_id": best_id, "source_type": best_type,
                  "score": round(best_score, 3)}
        trace({"kind": "attribution", "claim": claim[:160], "passage_id": best_id,
               "score": record["score"]})
        out.append(record)
    return out


# ── Guardrail primitives ──────────────────────────────────────────────────────

_DOLLAR_RE = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?")
# "%" is not a word character, so a \b after it would need a letter or digit next:
# "5% of" and "5%." would never match. Only the spelled-out forms take the boundary.
_PERCENT_RE = re.compile(r"\b\d+(?:\.\d+)?\s?(?:%|(?:per\s?cent|percent)\b)", re.IGNORECASE)
_DAYS_RE = re.compile(r"\b\d+(?:\.\d+)?[-\s]+(?:calendar\s+|business\s+)?(?:day|days)\b",
                      re.IGNORECASE)


def figures_in(text: str) -> list[str]:
    """Dollar figures, day counts, and percentages in `text`.

    The Check applies exactly this detector to what your pipeline delivered for the
    questions the corpus cannot answer, and the rule there has no tolerance. Note
    what it does not catch: a figure spelled out in words is not on this list, and
    neither is a bare decimal such as a retrieval score.
    """
    found: list[str] = []
    for pattern in (_DOLLAR_RE, _PERCENT_RE, _DAYS_RE):
        found.extend(match.group(0).strip() for match in pattern.finditer(text or ""))
    return found


# ── Is a delivered claim backed? (the rule the Check counts unsupported claims by) ──

_FIGURE_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def figure_numbers(claim: str) -> list[str]:
    """The numbers in the dollar figures, day counts and percentages a claim states,
    without thousands separators: "$842,316.50" gives "842316.50". A cited passage
    id ("policy-011-s52") is a reference, not a figure."""
    body = _PASSAGE_REF_RE.sub(" ", claim or "")
    out: list[str] = []
    for figure in figures_in(body):
        match = _FIGURE_NUMBER_RE.search(figure)
        if match:
            out.append(match.group(0).replace(",", ""))
    return out


def states_numbers(text: str, numbers: list[str]) -> bool:
    """True when `text` states every one of `numbers` as a number of its own: "30" is
    in "30 days" and "$1,030", not in "300" or "30.5"."""
    flat = (text or "").replace(",", "")
    return all(re.search(rf"(?<![\d.]){re.escape(n)}(?!\.?\d)", flat) for n in numbers)


def unbacked_reason(claim: str, passage_id: str | None, retrieved_ids, texts: dict) -> str:
    """Why a delivered claim has no passage behind it, or "" when it has one.

      "unattributed"     no attribution record names a passage for it (or it says
                         UNSUPPORTED)
      "not_retrieved"    it cites a passage this question did not retrieve
      "figure_missing"   the cited passage does not state a dollar figure, day count
                         or percentage the claim states

    `texts` maps passage ids to their stored text (passage_texts()).
    """
    pid = str(passage_id or "").strip().strip("[]").strip()
    if not pid or pid == "UNSUPPORTED":
        return "unattributed"
    if pid not in {str(i) for i in (retrieved_ids or [])}:
        return "not_retrieved"
    numbers = figure_numbers(claim)
    if numbers and not states_numbers(texts.get(pid, ""), numbers):
        return "figure_missing"
    return ""


def passage_texts(passage_ids) -> dict[str, str]:
    """The stored text of each passage id, from one search across the indices.

    A search outage is retried twice and then raises RemoteUnavailable.
    """
    ids = sorted({str(i) for i in (passage_ids or []) if i})
    if not ids:
        return {}
    body = {"query": {"ids": {"values": ids}}, "size": min(10000, 4 * len(ids)),
            "_source": ["body_text", "body"]}
    resp = unwrap(remote_call("search", es_client().search, index="*", body=body))
    texts: dict[str, list[str]] = {}
    for hit in resp.get("hits", {}).get("hits", []):
        source = hit.get("_source", {})
        text = source.get("body_text") or source.get("body") or ""
        if isinstance(text, dict):
            text = text.get("text", "")
        texts.setdefault(str(hit.get("_id", "")), []).append(str(text))
    return {pid: "\n".join(parts) for pid, parts in texts.items()}


REFUSAL_MARKERS = (
    "cannot find", "could not find", "can not find", "not find this information",
    "cannot answer", "unable to", "do not have", "does not contain", "no passage",
    "no supporting", "insufficient", "outside", "out of scope", "declin",
    "not covered", "no information", "cannot be answered",
)


def reads_as_refusal(text: str) -> bool:
    """True when the text declines rather than answers."""
    lowered = (text or "").lower()
    return any(marker in lowered for marker in REFUSAL_MARKERS)


def guard_fired(hook: str, query_text: str, detail: str = "") -> None:
    """Record that a guardrail acted. The Defend reads these records."""
    trace({"kind": "guard", "hook": hook, "query": (query_text or "")[:160],
           "detail": detail[:200]})
