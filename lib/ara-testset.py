#!/usr/bin/env python3
"""ara-testset.py - the test-set helper for Lab 5.3 Build 1. Run: python3 /opt/ara/lib/ara-testset.py log"""
from __future__ import annotations

import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import ara_testset as T  # noqa: E402
from ara_security import ES  # noqa: E402


class Store:
    def __init__(self, es: ES):
        self.es = es

    def put_doc(self, index: str, doc_id: str, doc: dict) -> None:
        code, body = self.es.request("PUT", f"/{index}/_doc/{doc_id}?refresh=wait_for", doc)
        if code not in (200, 201):
            raise T.Problem(f"Saving to {index} was refused (HTTP {code}). Run it again; if it persists, tell your instructor.")


def live_es():
    key = os.environ.get("ARA_TINA_EVAL_KEY") or os.environ.get("ES_API_KEY")
    url = (os.environ.get("ES_URL") or "").rstrip("/")
    if not key or not url:
        sys.exit("ES_URL and the evaluation key are not set. Open a new terminal (it loads ~/env) and run this again.")
    return Store(ES(url, f"ApiKey {key}", timeout=60))


if __name__ == "__main__":
    es = live_es() if sys.argv[1:2] == ["save"] else None
    sys.exit(T.main(sys.argv[1:], es=es))
