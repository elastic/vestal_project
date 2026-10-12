#!/usr/bin/env python3
"""ara-spend.py - record the curriculum gateway key's spend (22 section 4 setup 5). Root only.

    python3 ara-spend.py <label>      # e.g. setup, defend_check, solve_end

Reads LLM_APIKEY and LLM_PROXY_URL from /home/elastic-serverless/env (written by the image's
generate-llm-key.sh), asks the gateway's key-info endpoint for the key's spend, and merges
{label: {"spend_usd", "max_budget_usd", "at"}} into /opt/ara/results/4-3/spend.json. Prints one line
with the label and the spend; never prints the key. Exit 0 on success, 1 when the gateway did not
answer (the record keeps its other labels).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import sys
import urllib.request

ENV = pathlib.Path("/home/elastic-serverless/env")
OUT = pathlib.Path(os.environ.get("ARA_SPEND_FILE", "/opt/ara/results/4-3/spend.json"))


def gateway() -> tuple[str, str]:
    vals = {}
    for line in ENV.read_text().splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[7:]
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip().strip('"').strip("'")
    url = vals.get("LLM_PROXY_URL", "")
    if url and not url.startswith("http"):
        url = "https://" + url
    return url.rstrip("/"), vals.get("LLM_APIKEY", "")


def key_info(url: str, key: str) -> dict:
    req = urllib.request.Request(f"{url}/key/info", headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=10) as r:
        body = json.loads(r.read() or b"{}")
    return body.get("info", body) if isinstance(body, dict) else {}


def main() -> int:
    label = sys.argv[1] if len(sys.argv) > 1 else "now"
    try:
        url, key = gateway()
        info = key_info(url, key)
    except Exception as e:
        print(f"spend {label}: gateway did not answer ({type(e).__name__})")
        return 1
    try:
        rec = json.loads(OUT.read_text())
    except (OSError, ValueError):
        rec = {}
    rec[label] = {"spend_usd": info.get("spend"), "max_budget_usd": info.get("max_budget"),
                  "at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_name(f".{OUT.name}.{os.getpid()}")
    tmp.write_text(json.dumps(rec, indent=2, sort_keys=True))
    os.chmod(tmp, 0o644)
    os.replace(tmp, OUT)
    print(f"spend {label}: {info.get('spend')} USD of {info.get('max_budget')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
