"""
ara_synth.py — seeded synthetic transaction generator for ARA track 2.4.

Generates a deterministic set of cortex-transactions documents from a seed
so every learner on the same sandbox gets the same data, but different sandboxes
diverge. The seed is the Instruqt sandbox id (passed by provisioning).
"""

from __future__ import annotations

import hashlib
import json
import random
from datetime import datetime, timedelta, timezone


_COUNTRIES = ["US", "CN", "RU", "NG", "UA", "BR", "DE", "MX", "AE", "TH"]
_RISK_TIERS = ["low", "medium", "high", "critical"]
_TIER_WEIGHTS = [0.5, 0.3, 0.15, 0.05]

_ACCOUNT_PREFIXES = ["CTX", "OFC", "PRM", "WHL", "ENT"]

_TRANSACTION_TYPES = ["wire", "ach", "cash", "check", "crypto"]
_TYPE_WEIGHTS = [0.3, 0.25, 0.2, 0.15, 0.1]


def generate_transactions(seed: str, count: int = 2000) -> list[dict]:
    """Generate `count` synthetic transactions deterministically from `seed`.

    Each document:
      _id: "txn-<hex8>"
      account_id: str
      amount: float
      currency: "USD"
      transaction_type: str
      country: str
      risk_tier: str
      flagged: bool  (True for risk_tier in {high, critical})
      timestamp: ISO-8601 UTC, spread over 90 days ending at the seed date
    """
    rng = random.Random(hashlib.md5(seed.encode()).hexdigest())

    # Anchor date derived from seed so different seeds produce different date ranges
    anchor_ms = int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16)
    anchor = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=anchor_ms % (365 * 24 * 3600))

    docs = []
    for i in range(count):
        txn_id = f"txn-{hashlib.md5(f'{seed}-{i}'.encode()).hexdigest()[:8]}"
        account_id = f"{rng.choice(_ACCOUNT_PREFIXES)}-{rng.randint(10000, 99999)}"
        amount = round(rng.lognormvariate(8.5, 1.8), 2)  # heavy tail, some >10k
        risk_tier = rng.choices(_RISK_TIERS, weights=_TIER_WEIGHTS)[0]
        flagged = risk_tier in ("high", "critical")
        ts = anchor - timedelta(
            days=rng.randint(0, 89),
            hours=rng.randint(0, 23),
            minutes=rng.randint(0, 59),
        )
        docs.append({
            "_id": txn_id,
            "account_id": account_id,
            "amount": amount,
            "currency": "USD",
            "transaction_type": rng.choices(_TRANSACTION_TYPES, weights=_TYPE_WEIGHTS)[0],
            "country": rng.choice(_COUNTRIES),
            "risk_tier": risk_tier,
            "flagged": flagged,
            "@timestamp": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
    return docs


def index_transactions(es, index: str, seed: str, count: int = 2000) -> dict:
    """Generate and index synthetic transactions. Creates the index if needed."""
    from elasticsearch.helpers import bulk

    mapping = {
        "mappings": {
            "properties": {
                "account_id": {"type": "keyword"},
                "amount": {"type": "float"},
                "currency": {"type": "keyword"},
                "transaction_type": {"type": "keyword"},
                "country": {"type": "keyword"},
                "risk_tier": {"type": "keyword"},
                "flagged": {"type": "boolean"},
                "@timestamp": {"type": "date"},
            }
        }
    }
    if not es.indices.exists(index=index):
        es.indices.create(index=index, body=mapping)

    docs = generate_transactions(seed, count)

    def _actions():
        for d in docs:
            doc_id = d.pop("_id")
            yield {"_index": index, "_id": doc_id, "_source": d}
            d["_id"] = doc_id  # restore for caller inspection

    success, errors = bulk(es, _actions(), raise_on_error=False)
    return {"indexed": success, "errors": len(errors) if isinstance(errors, list) else errors}
