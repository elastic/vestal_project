"""ara_history.py - the history loader's pure core: re-time a recorded span set and build bulk-create bodies
(28 section 8.5, probe P1: re-timed spans bulk-created with explicit _id load without error and survive rollover).

    retime(spans, now, days_before, ...)   copies of the spans shifted so the set ends days_before now; ids kept,
                                           or mapped by one deterministic map when a salt is given
    doc_id(pack, span)                     the deterministic explicit _id of a span
    bulk_body(docs, index, pack)           NDJSON for _bulk with op_type create (`create` action) and explicit _ids
    place_rounds(rounds, ends)             re-time each round to its own end (a pack's schedule)
    business_hour_ends(end, days, per_day, seed)  deterministic round end times, business-hour density
    bulk_result(resp)                      (created, already_loaded, errors): a 409 is a re-load, not an error
    id_map(spans, salt)                    old id -> new id for trace, span and conversation ids

A span set is one or more rounds. A span's end is its @timestamp plus `duration` (nanoseconds); the set's end is the
latest span end. Offsets inside a round never change, so parent/child timing is preserved. Standard library only.
"""
from __future__ import annotations

import copy
import hashlib
import json
import random
from datetime import datetime, timedelta, timezone
from typing import Any

from ara_trace import get, parse_ts

CONV = "attributes.gen_ai.conversation.id"


def fmt_ts(d: datetime) -> str:
    """Millisecond ISO with Z, the format the stream stores."""
    d = d.astimezone(timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def span_end(span: dict) -> datetime:
    return parse_ts(span["@timestamp"]) + timedelta(microseconds=float(span.get("duration", 0) or 0) / 1000)


def set_end(spans: list[dict]) -> datetime:
    return max(span_end(s) for s in spans)


def _hex(*parts: str, n: int) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:n]


def id_map(spans: list[dict], salt: str) -> dict[str, str]:
    """One deterministic map for every id a replay must change: trace ids (32 hex), span ids (16 hex), and
    conversation ids (uuid-shaped). The same map applies to the root-held key (28 section 8.5 item 3)."""
    m: dict[str, str] = {}
    for s in spans:
        for key, n in (("trace_id", 32), ("span_id", 16), ("parent_span_id", 16)):
            v = s.get(key)
            if v and v not in m:
                m[v] = _hex(salt, key, v, n=n)
        c = get(s, CONV)
        if c and c not in m:
            h = _hex(salt, "conv", str(c), n=32)
            m[c] = f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"
    return m


def _set_conv(span: dict, value: str) -> None:
    if CONV in span:
        span[CONV] = value
    else:
        span.setdefault("attributes", {})["gen_ai.conversation.id"] = value


def retime(spans: list[dict], now: datetime, days_before: float, salt: str | None = None) -> list[dict]:
    """Copies of the spans shifted so the set's end is `days_before` days before `now`. Parent/child links and
    every offset are kept. With `salt`, ids are replaced by id_map(spans, salt) (a replay under new ids)."""
    if not spans:
        return []
    target = now - timedelta(days=days_before)
    shift = target - set_end(spans)
    ids = id_map(spans, salt) if salt else {}
    out = []
    for s in spans:
        c = copy.deepcopy(s)
        c["@timestamp"] = fmt_ts(parse_ts(s["@timestamp"]) + shift)
        for key in ("trace_id", "span_id", "parent_span_id"):
            if c.get(key) in ids:
                c[key] = ids[c[key]]
        cid = get(c, CONV)
        if cid in ids:
            _set_conv(c, ids[cid])
        out.append(c)
    return out


def place_rounds(rounds: list[list[dict]], ends: list[datetime], salt: str | None = None) -> list[dict]:
    """Each round (a span list) re-timed to end at its own time; with a salt each gets its own id map
    (salt plus its index), so replaying one recording many times yields distinct traces."""
    if len(rounds) != len(ends):
        raise ValueError("one end time per round")
    out: list[dict] = []
    for i, (rnd, end) in enumerate(zip(rounds, ends)):
        out += retime(rnd, end, 0, f"{salt}:{i}" if salt else None)
    return out


def business_hour_ends(end: datetime, days: int, per_day: int, seed: str) -> list[datetime]:
    """Deterministic round end times over `days` days up to `end`: weekdays only, between 08:00 and 18:00 UTC,
    `per_day` rounds each, none after `end`; sorted ascending."""
    rng = random.Random(seed)
    out: list[datetime] = []
    for d in range(days):
        day = (end - timedelta(days=d)).replace(hour=0, minute=0, second=0, microsecond=0)
        if day.weekday() >= 5:
            continue
        for _ in range(per_day):
            t = day + timedelta(seconds=rng.randrange(8 * 3600, 18 * 3600))
            if t <= end:
                out.append(t)
    return sorted(out)


def doc_id(pack: str, span: dict) -> str:
    """Explicit _id: a hash of the pack, trace and span ids, so a second load of the same span is a no-op."""
    return _hex(pack, str(span.get("trace_id")), str(span.get("span_id")), n=32)


def bulk_body(docs: list[dict], index: str, pack: str) -> str:
    """NDJSON for POST _bulk: one `create` action per span (op_type create, explicit _id), then its source.
    Data streams accept only create. Ends with a newline."""
    lines: list[str] = []
    for d in docs:
        lines.append(json.dumps({"create": {"_index": index, "_id": doc_id(pack, d)}}, separators=(",", ":")))
        lines.append(json.dumps(d, separators=(",", ":"), sort_keys=True))
    return "\n".join(lines) + "\n"


def chunks(docs: list[dict], size: int) -> list[list[dict]]:
    return [docs[i:i + size] for i in range(0, len(docs), size)]


def bulk_result(resp: dict) -> tuple[int, int, list[dict]]:
    """(created, already_loaded, errors) from a _bulk response. A 409 version conflict on create means the
    span is already there (an idempotent re-load); anything else is an error."""
    created = existing = 0
    errors: list[dict] = []
    for item in resp.get("items", []):
        r = item.get("create") or next(iter(item.values()))
        st = int(r.get("status", 0))
        if 200 <= st < 300:
            created += 1
        elif st == 409:
            existing += 1
        else:
            errors.append(r)
    return created, existing, errors


def verify(spans: list[dict], manifest: dict) -> list[str]:
    """Mismatches against a root-held manifest {"span_count": n, "trace_count": n, "sha256": hex of the sorted
    span_ids}; empty when the load matches. Messages never name a fault."""
    bad = []
    if "span_count" in manifest and len(spans) != manifest["span_count"]:
        bad.append(f"span count {len(spans)} != {manifest['span_count']}")
    if "trace_count" in manifest and len({s.get("trace_id") for s in spans}) != manifest["trace_count"]:
        bad.append("trace count differs")
    if "sha256" in manifest:
        h = hashlib.sha256("\n".join(sorted(str(s.get("span_id")) for s in spans)).encode()).hexdigest()
        if h != manifest["sha256"]:
            bad.append("span id hash differs")
    return bad
