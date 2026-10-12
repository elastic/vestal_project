"""ara_m4_data.py - load the committed M4 fraud snapshot into a Serverless project (22 section 8.2).

Used by provision.sh as root, never by a learner. The snapshot (data/ara-m4-fraud/, written once by
scripts/gen_cortex_m4.py) holds gzipped NDJSON per index, mappings.json and planted.json.

Every @timestamp is shifted by one offset, so the newest event across the four fraud indices lands at
load time minus one day; pattern timing survives because the shift is uniform. The loader returns the
offset and writes the rebased planted timestamps a check needs to compute "inside the window".

    python3 ara_m4_data.py load <snapshot dir> <es url> <api key env var name> <rebase record out>
"""
from __future__ import annotations

import datetime as dt
import gzip
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request

FRAUD = ["cortex-wire-transfers", "cortex-cash-movements", "cortex-atm-events", "cortex-brokerage-trades"]
LOOKUPS = ["cortex-ref-accounts", "cortex-ref-banks", "cortex-ref-intbanks", "cortex-ref-brokers", "cortex-ref-merchants"]
ID_FIELD = {"cortex-ref-accounts": "account_id", "cortex-ref-banks": "bank_id", "cortex-ref-intbanks": "intbank_id",
            "cortex-ref-brokers": "broker_id", "cortex-ref-merchants": "merchant_id"}
FMT = "%Y-%m-%dT%H:%M:%S.000Z"


def _parse(ts: str) -> dt.datetime:
    return dt.datetime.strptime(ts, FMT).replace(tzinfo=dt.timezone.utc)


def _req(es: str, key: str, method: str, path: str, body=None, ndjson: bool = False, timeout: int = 120):
    data = None
    if body is not None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
    headers = {"Authorization": f"ApiKey {key}",
               "Content-Type": "application/x-ndjson" if ndjson else "application/json"}
    last = None
    for attempt in range(1, 5):
        r = urllib.request.Request(f"{es}{path}", data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(r, timeout=timeout) as resp:
                txt = resp.read().decode()
                return resp.status, (json.loads(txt) if txt else {})
        except urllib.error.HTTPError as e:
            txt = e.read().decode()
            if e.code in (429, 502, 503, 504):
                last = f"HTTP {e.code}"
            else:
                try:
                    return e.code, json.loads(txt)
                except ValueError:
                    return e.code, {"raw": txt[:300]}
        except Exception as e:  # no answer: retry
            last = f"{type(e).__name__}: {e}"
        time.sleep(3 * attempt)
    raise RuntimeError(f"{method} {path} did not answer after 4 attempts ({last})")


def offset_for(newest: str, now: dt.datetime | None = None) -> dt.timedelta:
    now = now or dt.datetime.now(dt.timezone.utc)
    return (now - dt.timedelta(days=1)) - _parse(newest)


def rebase(ts: str, off: dt.timedelta) -> str:
    return (_parse(ts) + off).strftime(FMT)


def read_docs(snapshot: pathlib.Path, index: str) -> list[dict]:
    with gzip.open(snapshot / f"{index}.ndjson.gz", "rt") as f:
        return [json.loads(line) for line in f if line.strip()]


def load(snapshot: pathlib.Path, es: str, key: str, out: pathlib.Path) -> dict:
    snapshot = pathlib.Path(snapshot)
    maps = json.loads((snapshot / "mappings.json").read_text())
    planted = json.loads((snapshot / "planted.json").read_text())
    off = offset_for(planted["newest_event"])
    counts, rebased_ts = {}, {}
    wanted = {e for v in planted["cortex-wire-transfers"]["structuring_deposits"].values() for e in v}
    wanted |= {e for v in planted["cortex-wire-transfers"]["structuring_out_of_window"].values() for e in v}
    for index in FRAUD + LOOKUPS:
        _req(es, key, "DELETE", f"/{index}?ignore_unavailable=true")
        code, body = _req(es, key, "PUT", f"/{index}", {"mappings": {"properties": maps["data"][index]}})
        if code != 200:
            raise RuntimeError(f"create {index}: HTTP {code} {str(body)[:200]}")
        docs = read_docs(snapshot, index)
        for d in docs:
            if "@timestamp" in d:
                d["@timestamp"] = rebase(d["@timestamp"], off)
                if d.get("event_id") in wanted:
                    rebased_ts[d["event_id"]] = d["@timestamp"]
        for i in range(0, len(docs), 5000):
            chunk = docs[i:i + 5000]
            lines = []
            for d in chunk:
                lines.append(json.dumps({"index": {"_index": index, "_id": d.get("event_id") or d[ID_FIELD[index]]}}))
                lines.append(json.dumps(d))
            code, body = _req(es, key, "POST", "/_bulk", ("\n".join(lines) + "\n").encode(), ndjson=True, timeout=300)
            if code != 200 or body.get("errors"):
                first = next((it for it in body.get("items", []) if it.get("index", {}).get("error")), None)
                raise RuntimeError(f"bulk {index}: HTTP {code} first error {str(first)[:300]}")
        _req(es, key, "POST", f"/{index}/_refresh")
        code, body = _req(es, key, "GET", f"/{index}/_count")
        counts[index] = body.get("count")
        if counts[index] != len(docs):
            raise RuntimeError(f"{index}: {counts[index]} documents after load, expected {len(docs)}")
    for index, props in maps["records"].items():
        _req(es, key, "DELETE", f"/{index}?ignore_unavailable=true")
        code, body = _req(es, key, "PUT", f"/{index}", {"mappings": {"properties": props}})
        if code != 200:
            raise RuntimeError(f"create {index}: HTTP {code} {str(body)[:200]}")
        counts[index] = 0
    record = {"offset_seconds": int(off.total_seconds()), "loaded_at": dt.datetime.now(dt.timezone.utc).strftime(FMT),
              "counts": counts, "rebased": rebased_ts, "planted": planted}
    out = pathlib.Path(out)
    out.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    os.chmod(out, 0o600)
    return record


if __name__ == "__main__":
    if len(sys.argv) != 6 or sys.argv[1] != "load":
        sys.exit(__doc__)
    _, _, snap, es_url, key_var, out_path = sys.argv
    rec = load(pathlib.Path(snap), es_url.rstrip("/"), os.environ[key_var], pathlib.Path(out_path))
    print("Loaded: " + ", ".join(f"{k} {v}" for k, v in rec["counts"].items()))
    print(f"Timestamps shifted by {rec['offset_seconds'] // 3600} h.")
