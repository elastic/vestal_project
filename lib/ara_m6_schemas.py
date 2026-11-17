"""ara_m6_schemas.py - the recorder schemas (record.py <config> <schema>) the M6 Builds ask learners to fill, as data.

    schemas(track) -> {file name: [field specs]}      written by setup next to the learner's other files (step `files`)
    DEST[track]                                       the directory under /home/elastic each track's files live in

The option lists are the graders' own vocabularies (ara_tracepack, ara_degrade, ara_ops, ara_eval), so a schema cannot offer a value
the grader does not know. The 6.1 capability list is closed and shared by every variant (a decoy list the learner narrows with
capabilities.md), so the schema does not give the variant's answer away. Standard library only.
"""
from __future__ import annotations

import ara_degrade as D
import ara_eval as E
import ara_ops as O
import ara_tracepack as TP

DEST = {"6-1": "cortex-traces", "6-2": "cortex-loop", "6-3": "cortex-ops", "6-4": "cortex-history", "6-c": "cortex-history"}
COMPONENTS = ("policy_index_content", "embedding_configuration", "tool_description", "agent_instructions", "model", "detection_tool_query")
SIGNALS = tuple(D.SIGNAL.values())
TYPES = tuple(D.ORDERS[0])


def _f(key: str, label: str, options=None, kind: str | None = None) -> dict:
    d = {"key": key, "label": label}
    if options:
        d["options"] = list(options)
    if kind:
        d["type"] = kind
    return d


def schemas(track: str) -> dict[str, list[dict]]:
    if track == "6-1":
        return {"read-schema.json": [_f("failing_span_id", "Failing span", kind="span_id"), _f("failure_class", "Failure class", TP.FAILURE_CLASSES),
                                     _f("costly_span_id", "Costliest span", kind="span_id"), _f("costly_cause", "Cause of the cost", TP.COSTLY_CAUSES),
                                     _f("costly_input_tokens", "Input tokens on that span", kind="integer")],
                "defect-schema.json": [_f("defective_clause", "Defective clause", TP.DEFECTIVE_CLAUSES)],
                "gap-schema.json": [_f("missing_capability", "Missing capability", TP.CAPABILITIES)]}
    if track == "6-3":
        return {"patterns-schema.json": [_f(n, f"Trigger pattern for {n}", tuple(O.PATTERNS.values())) for n in sorted(O.PATTERNS)]}
    if track in ("6-4", "6-c"):
        out = {f"window{i}-schema.json": [_f("change_point_date", "Change point date", kind="date"), _f("type", "Type", TYPES), _f("signal", "Signal", SIGNALS)]
               for i in (1, 2, 3)} if track == "6-4" else {}
        out["isolate-schema.json"] = [_f("component", "Component", COMPONENTS), _f("affected_class", "Affected class", ("policy_retrieval",) + tuple(E.CATEGORIES))]
        return out
    return {}
