"""ara_proposal_schema.py - the canonical proposal JSON Schema (28 section 3, the proposal spec) with the three labelled valid
examples and the invalid set Lab 6.2 B1 grades the learner's schema against.

    SCHEMA                  the root-held canonical schema for the evaluator step's whole output: {"proposals": [proposal, ...]}
    wrap(p)                 {"proposals": [p]}
    VALID                   {label: proposal}: the three examples given to the learner (/home/elastic/cortex-loop/proposal-examples/)
    INVALID                 [(rule, proposal)]: at least one per rule of the spec; each must fail a correct schema (wrapped)
    problems(output)        the schema's errors for an evaluator output, as messages (jsonschema, Draft 2020-12)

ara_loop.validate_proposal is the same rule set in code (the gate and the ledger use it); test_ara_proposal_schema.py
keeps the two in step on every example. The schema never reads `rationale` beyond "a string if present" (prose is never
graded). Evidence ids in the examples are placeholders for the week pack's real conversation and trace ids.
"""
from __future__ import annotations

import copy

KINDS = ["improvement", "incident_fix"]
TYPES = ["instruction_change", "tool_description_change", "tool_query_change", "attach_tool", "detach_tool", "data_change"]
CATEGORIES = ["straightforward", "ambiguous", "time_window_edge", "cross_domain", "adversarial", "out_of_scope"]
_S = {"type": "string", "minLength": 1, "pattern": r"\S"}

_EFFECT = {"type": "object", "required": ["metric", "category"], "properties": {"metric": {"enum": ["routing_accuracy", "ndcg_at_5", "tool_calls", "cost"]}, "category": {"type": "string"}},
           "allOf": [
               {"if": {"properties": {"metric": {"const": "routing_accuracy"}}, "required": ["metric"]}, "then": {"properties": {"category": {"enum": CATEGORIES + ["all"]}}}},
               {"if": {"properties": {"metric": {"const": "ndcg_at_5"}}, "required": ["metric"]}, "then": {"properties": {"category": {"const": "policy_retrieval"}}}},
               {"if": {"properties": {"metric": {"enum": ["tool_calls", "cost"]}}, "required": ["metric"]}, "then": {"properties": {"category": {"const": "all"}}}}]}


def _change_if(types, then):
    return {"if": {"properties": {"proposal_type": {"enum": types}}, "required": ["proposal_type"]}, "then": {"properties": {"change": then}}}


PROPOSAL = {
    "type": "object",
    "required": ["kind", "proposal_type", "target", "change", "evidence", "expected_effect"],
    "properties": {
        "kind": {"enum": KINDS}, "proposal_type": {"enum": TYPES}, "target": _S,
        "change": {"type": "object"},
        "evidence": {"type": "array", "minItems": 1, "items": {"type": "object", "required": ["conversation_id", "trace_id", "observation"],
                     "properties": {"conversation_id": _S, "trace_id": _S, "observation": _S}}},
        "expected_effect": _EFFECT, "rationale": {"type": "string"}},
    "allOf": [
        _change_if(["attach_tool", "detach_tool"], {"type": "object", "required": ["tool_id"], "properties": {"tool_id": _S}}),
        _change_if(["instruction_change", "tool_description_change", "tool_query_change"],
                   {"type": "object", "required": ["field", "text"], "properties": {"field": _S, "text": _S}}),
        _change_if(["data_change"], {"type": "object", "required": ["tool_id", "production_source", "candidate_source", "operation"],
                   "properties": {"tool_id": _S, "production_source": _S, "candidate_source": _S, "operation": {"enum": ["repoint_alias", "delete_matching"]}},
                   "allOf": [{"if": {"properties": {"operation": {"const": "delete_matching"}}, "required": ["operation"]}, "then": {"required": ["query"], "properties": {"query": {"type": "object"}}}}]}),
        {"if": {"properties": {"kind": {"const": "improvement"}}, "required": ["kind"]}, "then": {"properties": {"proposal_type": {"not": {"const": "data_change"}}}}}],
}
SCHEMA = {"$schema": "https://json-schema.org/draft/2020-12/schema", "title": "Cortex evaluator output", "type": "object", "required": ["proposals"],
          "properties": {"proposals": {"type": "array", "items": PROPOSAL}}}


def wrap(p: dict) -> dict:
    return {"proposals": [p]}


_EV = [{"conversation_id": "conv-0001", "trace_id": "trace-0001", "observation": "Tina escalated an account-history question although cortex.account_history exists."}]
VALID = {
    "attach": {"kind": "improvement", "proposal_type": "attach_tool", "target": "tina-compliance", "change": {"tool_id": "cortex.account_history"},
               "evidence": _EV, "expected_effect": {"metric": "routing_accuracy", "category": "cross_domain"}, "rationale": "Account-history questions escalate; the tool exists and is not attached."},
    "tool_description": {"kind": "improvement", "proposal_type": "tool_description_change", "target": "cortex.policy_search",
                         "change": {"field": "description", "text": "Search the policy index once per question."}, "evidence": _EV,
                         "expected_effect": {"metric": "tool_calls", "category": "all"}, "rationale": "Two searches per policy question."},
    "instruction": {"kind": "improvement", "proposal_type": "instruction_change", "target": "tina-compliance",
                    "change": {"field": "configuration.instructions", "text": "When no window is named, look back 7 days."}, "evidence": _EV,
                    "expected_effect": {"metric": "routing_accuracy", "category": "ambiguous"}},
}


def _mut(fn):
    p = copy.deepcopy(VALID["attach"])
    fn(p)
    return p


def _drop(field):
    return lambda p: p.pop(field)


INVALID: list[tuple[str, dict]] = [
    ("missing kind", _mut(_drop("kind"))), ("missing proposal_type", _mut(_drop("proposal_type"))), ("missing target", _mut(_drop("target"))),
    ("missing change", _mut(_drop("change"))), ("missing evidence", _mut(_drop("evidence"))), ("missing expected_effect", _mut(_drop("expected_effect"))),
    ("empty evidence array", _mut(lambda p: p.update(evidence=[]))),
    ("evidence without conversation_id", _mut(lambda p: p["evidence"][0].pop("conversation_id"))),
    ("evidence without trace_id", _mut(lambda p: p["evidence"][0].pop("trace_id"))),
    ("evidence without observation", _mut(lambda p: p["evidence"][0].pop("observation"))),
    ("unknown kind", _mut(lambda p: p.update(kind="refactor"))),
    ("unknown proposal_type", _mut(lambda p: p.update(proposal_type="delete_agent"))),
    ("unknown metric", _mut(lambda p: p.update(expected_effect={"metric": "latency", "category": "all"}))),
    ("category that does not go with the metric", _mut(lambda p: p.update(expected_effect={"metric": "ndcg_at_5", "category": "cross_domain"}))),
    ("unknown category for routing_accuracy", _mut(lambda p: p.update(expected_effect={"metric": "routing_accuracy", "category": "policy_retrieval"}))),
    ("attach_tool without tool_id", _mut(lambda p: p.update(change={}))),
    ("text change without text", _mut(lambda p: p.update(proposal_type="instruction_change", change={"field": "configuration.instructions"}))),
    ("evidence of the wrong type", _mut(lambda p: p.update(evidence="see traces"))),
    ("target of the wrong type", _mut(lambda p: p.update(target=7))),
    ("empty observation", _mut(lambda p: p["evidence"][0].update(observation="  "))),
    ("improvement that changes data", _mut(lambda p: p.update(proposal_type="data_change", change={"tool_id": "t", "production_source": "a", "candidate_source": "b", "operation": "repoint_alias"}))),
    ("delete_matching without its query", _mut(lambda p: p.update(kind="incident_fix", proposal_type="data_change", change={"tool_id": "t", "production_source": "a", "candidate_source": "b", "operation": "delete_matching"}))),
]


def problems(output) -> list[str]:
    """Schema errors for an evaluator output, shortest path first; empty when it validates."""
    import jsonschema
    errs = sorted(jsonschema.Draft202012Validator(SCHEMA).iter_errors(output), key=lambda e: [str(x) for x in e.absolute_path])
    return [f"{'/'.join(str(x) for x in e.absolute_path) or 'output'}: {e.message[:160]}" for e in errs]
