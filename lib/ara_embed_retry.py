"""ara_embed_retry.py - re-send the documents a managed embedding endpoint refused, at provisioning.

A semantic_text field runs inference inside the bulk request. When the managed endpoint answers 503 (or 429, or times out) the
document is refused with `inference_exception` although the request itself is fine, and the same document is accepted a little
later. Provisioning used to send each bulk once, so one such answer left an empty index and a failed lab. These helpers send the
refused documents again, and only those, after a bounded wait; a different kind of error is never retried.

    errors = bulk_resilient(es, actions, chunk_size=50)             # elasticsearch-py client; returns the errors that are left
    failed = post_docs(es, index, docs, id_of, batch=20)           # ara_security.ES client; returns [(doc, error)] that are left

Every document carries a fixed `_id`, so a re-sent document overwrites its first copy: no duplicates. The wait follows the
M6 seeder's standard (15, 30, 45 seconds) and goes on at 60 seconds, 450 seconds in all; an outage seen on 2026-11-19 lasted at
least four minutes, so three retries would not have been enough. After the last retry the caller decides what the left-over
errors mean (the provisioning steps keep their own count check and failure message).
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Callable

LADDER = (15, 30, 45, 60, 60, 60, 60, 60, 60)   # seconds slept before retry 1 to 9; ten sends at most, 450 s of waiting
_NAME_WORDS = ("task_cancelled", "es_rejected", "circuit_breaking", "too_many_requests")   # exception identifiers (as ara_degrade_live._TRANSIENT)
_PHRASES = ("timed out", "timeout", "unavailable")             # free text; matched only outside [brackets] and quotes, where a field name lives
_UPSTREAM = re.compile(r"status \[(408|429|5\d\d)\]")          # the inference entity's own status, quoted inside a 400 inference_exception
_HTTP = re.compile(r"\bhttp (0|408|429|5\d\d)\b")               # our own "bulk HTTP 503 ..." wording
_CONN = re.compile(r"connection (?:was )?(?:reset|refused|closed|aborted)|connection error|remote end closed|remotedisconnected|broken pipe|"
                   r"connection(?:reset|refused|aborted)error|brokenpipeerror")
_DNS = re.compile(r"name or service not known|nodename nor servname|temporary failure in name resolution|getaddrinfo|gaierror|"
                  r"name resolution|nameresolutionerror|failed to resolve|no address associated|\bdns\b")
_STATUS = frozenset({408, 429, 500, 502, 503, 504})
_QUOTED = re.compile(r"\[[^\]]*\]|\"[^\"]*\"|'[^']*'")


def _reasons(err: Any) -> str:
    """The words an error says about itself: an Elasticsearch error object's `type` and `reason`, down its `caused_by` chain, and nothing
    else (no field names, no values, no document). A string is its own text."""
    if isinstance(err, dict):
        out, node = [], err
        while isinstance(node, dict):
            out += [str(node.get("type", "")), str(node.get("reason", ""))]
            node = node.get("caused_by")
        return " ".join(out)
    return err if isinstance(err, str) else json.dumps(err, default=str)


def _exception_text(err: BaseException) -> str:
    parts, seen, e = [], set(), err
    while e is not None and id(e) not in seen:   # the client wraps the socket error: read the cause too
        seen.add(id(e))
        parts.append(f"{type(e).__name__} {e}")
        e = e.__cause__ or e.__context__
    return " ".join(parts)


def _matches(text: str) -> bool:
    low = text.lower()
    if _UPSTREAM.search(low) or _HTTP.search(low) or any(w in low for w in _NAME_WORDS):
        return True
    plain = _QUOTED.sub(" ", low)   # a quoted or bracketed name (a field called timeout) is not a reason
    return any(w in plain for w in _PHRASES)


def transient_error(err: Any) -> bool:
    """True for an error that a later send can clear: an overloaded or unavailable service, a timeout, a dropped or refused connection.
    Not transient: a mapping error, a bad request or any other 4xx (an inference_exception that quotes status [400] is a bad input), and a
    name that does not resolve (DNS: waiting does not fix an address that is wrong). Only an error's own reason is read, never a field name."""
    if isinstance(err, BaseException):
        text = _exception_text(err)
        if _DNS.search(text.lower()):
            return False
        status = getattr(err, "status_code", None) or getattr(getattr(err, "meta", None), "status", None)
        if isinstance(status, int) and status in _STATUS:
            return True
        if isinstance(err, (ConnectionError, TimeoutError)) or any(
                c.__name__ in ("ConnectionError", "ConnectionTimeout") and c.__module__.split(".")[0] in ("elastic_transport", "elasticsearch")
                for c in type(err).__mro__):
            return True
        return bool(_CONN.search(text.lower())) or _matches(text)
    if isinstance(err, dict):
        # a bulk error item, {"index": {"_id", "status", "error", "data"}} or its inner dict: read the status and the error
        # object only; "data" is the document itself and its words must not decide anything
        item = next(iter(err.values())) if len(err) == 1 and isinstance(next(iter(err.values())), dict) else err
        status = item.get("status")
        if isinstance(status, int) and status in _STATUS:
            return True
        err = item.get("error", {k: v for k, v in item.items() if k != "data"})
    text = _reasons(err)
    if _DNS.search(text.lower()):
        return False
    return bool(_CONN.search(text.lower())) or _matches(text)


def retry_failed(items: list, send: Callable[[list], list], *, sleeps=LADDER, sleep=None, log=print, label: str = "bulk") -> list:
    """send(batch) returns [(item, error or None)] for every item of the batch (a send that raises a transient exception
    counts as every item failing). The failed items are sent again after each wait of `sleeps`, until none fail or the waits are
    spent. A failure that is not transient ends it at once. Returns [(item, error)] that are left (empty on success)."""
    sleep = sleep or time.sleep   # looked up at call time
    pending, failed = list(items), []
    for attempt in range(len(sleeps) + 1):
        try:
            results = send(pending)
        except Exception as e:   # noqa: BLE001 - a transient client error is data here, anything else is a real fault
            if not transient_error(e):
                raise
            results = [(it, e) for it in pending]
        failed = [(it, er) for it, er in results if er]
        if not failed:
            return []
        if any(not transient_error(er) for _, er in failed) or attempt == len(sleeps):
            return failed
        wait = sleeps[attempt]
        log(f"{label}: the embedding service is busy ({len(failed)} of {len(pending)} documents not accepted); sending them again in {wait} s (retry {attempt + 1} of {len(sleeps)})")
        sleep(wait)
        pending = [it for it, _ in failed]
    return failed


def bulk_resilient(es, actions: list[dict], *, chunk_size: int = 50, request_timeout: int = 300, sleeps=LADDER, sleep=None,
                   log=print, bulk=None) -> list:
    """elasticsearch.helpers.bulk with the refused documents sent again. Returns the error items that are left, as the helper
    returns them (the provisioning step prints the first and applies its count check)."""
    if bulk is None:
        from elasticsearch.helpers import bulk  # noqa: PLC0415 - only the check venv has it

    def send(batch):
        _, errs = bulk(es, batch, chunk_size=chunk_size, raise_on_error=False, request_timeout=request_timeout)
        bad = {}
        for e in errs or []:
            item = next(iter(e.values())) if isinstance(e, dict) and e else {}
            bad[item.get("_id")] = e
        if errs and not any(a["_id"] in bad for a in batch):   # errors we cannot attribute: every document of the batch is suspect
            return [(a, errs[0]) for a in batch]
        return [(a, bad.get(a["_id"])) for a in batch]

    return [er for _, er in retry_failed(actions, send, sleeps=sleeps, sleep=sleep, log=log, label="bulk")]


def post_docs(es, index: str, docs: list[dict], id_of: Callable[[dict], str], *, batch: int = 50, query: str = "", sleeps=LADDER,
              sleep=None, log=print, budget_s: float | None = None) -> list:
    """POST documents to /_bulk{query} in batches through an ara_security.ES client (`request_ndjson`), sending the refused ones
    again. Stops at the first batch that is still refused after the waits (the outage is not over, so the next batch would
    fail too). The waits of all the batches together stay within `budget_s` (default: the whole ladder, 450 s), so a long load cannot wait
    once per batch. Returns [(doc, error)] left from that batch, or [] when every document was accepted."""
    sleep = sleep or time.sleep
    left_budget = [float(sum(sleeps) if budget_s is None else budget_s)]

    def spend(s):
        left_budget[0] -= s
        sleep(s)

    def send(items):
        ops = "".join(json.dumps({"index": {"_index": index, "_id": id_of(d)}}) + "\n" + json.dumps(d) + "\n" for d in items)
        code, body = es.request_ndjson("POST", "/_bulk" + query, ops)
        if code != 200 or not isinstance(body, dict):
            err = f"bulk HTTP {code} {str(body)[:300]}"
            return [(d, err) for d in items]
        bad = {}
        for x in body.get("items") or []:
            item = next(iter(x.values()))
            if item.get("error"):
                bad[item.get("_id")] = item
        if body.get("errors") and not bad:
            return [(d, f"bulk reported errors {str(body)[:300]}") for d in items]
        return [(d, bad.get(id_of(d))) for d in items]

    for i in range(0, len(docs), batch):
        allowed, total = [], 0.0
        for s in sleeps:   # the part of the ladder the shared budget still covers
            if total + s > left_budget[0]:
                break
            allowed.append(s)
            total += s
        left = retry_failed(docs[i:i + batch], send, sleeps=tuple(allowed), sleep=spend, log=log, label=f"{index}")
        if left:
            return left
    return []
