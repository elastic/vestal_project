"""ara_gap6.py - Lab 6.1 B3: the capability card, the policy-exceptions dataset, and the held-out gap sets (28 section 2).

    CARDS[capability]                          tool id, parameter names and types, index and key column for the three buildable capabilities
    card_md()                                  /home/elastic/cortex-traces/capabilities.md (the same card in every variant; decoys by name only)
    EXCEPTIONS                                 the cortex-policy-exceptions documents (static dates; loaded in every variant so the index does not give the variant away)

The reference queries (REFERENCE) are what a learner's tool must match in behaviour, not text. Held-out rows carry the question text
for the leak scan; the check reads only `params` and `expected`. account_history decisions are kept only where no event of the
account flips if the sandbox outlives its load by MARGIN days. Standard library only.
"""
from __future__ import annotations

import datetime as dt
import math

import ara_defects6 as D

MARGIN = D.MARGIN
CARDS = {
    "account_history_window": {"tool_id": "cortex.account_history", "index": "cortex-wire-transfers", "key_column": "event_id",
                               "params": {"account_id": "string", "start_days_ago": "integer", "end_days_ago": "integer"},
                               "meaning": "every event of one account from end_days_ago to start_days_ago whole days back"},
    "counterparty_lookup": {"tool_id": "cortex.counterparty_lookup", "index": "cortex-wire-transfers", "key_column": "account_id",
                            "params": {"counterparty_bank": "string"}, "meaning": "every account that sent or received a wire with that bank"},
    "policy_exception_by_date": {"tool_id": "cortex.policy_exceptions", "index": "cortex-policy-exceptions", "key_column": "exception_id",
                                 "params": {"on_date": "string"}, "meaning": "every policy exception in force on that date (YYYY-MM-DD)"},
}
DECOYS = ("sanctions_screening", "out_of_scope_correctly_escalated")
EXCEPTIONS = [
    {"exception_id": f"pex-{i:03d}", "policy_id": p, "effective_from": a, "effective_to": b, "summary": s}
    for i, (p, a, b, s) in enumerate([
        ("policy-001", "2026-01-12", "2026-03-31", "CX-7 alert review window extended to five business days during the core-banking migration."),
        ("policy-001", "2026-04-01", "2026-06-30", "Level One structuring alerts for payroll-day cash deposits at branch 12 are reviewed in batches."),
        ("policy-003", "2026-02-02", "2026-02-27", "Currency transaction reports for armored-car deposits are filed on the next business day."),
        ("policy-005", "2026-03-16", "2026-05-15", "Wire velocity threshold raised for the municipal payments account during tax season."),
        ("policy-005", "2026-07-01", "2026-09-30", "Wire velocity alerts for the two correspondent accounts are suppressed during the settlement test."),
        ("policy-006", "2026-05-04", "2026-05-29", "Sanctions match triage extended to two business days while the list provider migrates."),
        ("policy-007", "2026-06-01", "2026-08-31", "Regulatory escalation acknowledgements may be signed by the deputy compliance officer."),
        ("policy-008", "2026-01-05", "2026-04-30", "High-risk customer file reviews may be completed within ninety days of the anniversary."),
        ("policy-009", "2026-08-10", "2026-10-31", "Ongoing monitoring sampling reduced to 5 percent for accounts onboarded through the partner portal."),
        ("policy-002", "2026-09-01", "2026-09-30", "KYC refresh for dormant accounts deferred while the document vault is replaced."),
        ("policy-004", "2026-03-02", "2026-03-31", "Beneficial ownership certification accepted by e-signature during the branch outage."),
        ("policy-003", "2026-10-01", "2026-12-31", "Currency transaction reports for the new armored-car vendor are filed within two business days."),
    ], 1)
]
ASK = {
    "account_history_window": "What did account {account_id} do between {end_days_ago} and {start_days_ago} days ago?",
    "counterparty_lookup": "Which of our accounts have wired money with {counterparty_bank}?",
    "policy_exception_by_date": "Which policy exceptions were in force on {on_date}?",
}
VARIANT = {"A": "account_history_window", "B": "counterparty_lookup", "C": "policy_exception_by_date"}


def card_md() -> str:
    out = ["# Capability card", "",
           "The closed list of capabilities Tina might lack. Three can be built here; the other two are named only.", ""]
    for cap, c in CARDS.items():
        out += [f"## `{cap}`", f"- Tool id: `{c['tool_id']}`", "- Parameters: " + ", ".join(f"`{k}` ({t})" for k, t in c["params"].items()),
                f"- Reads the index: `{c['index']}`", f"- Key column: `{c['key_column']}`", f"- Returns {c['meaning']}.", ""]
    out += ["## Named only", *(f"- `{d}`" for d in DECOYS), ""]
    return "\n".join(out)
