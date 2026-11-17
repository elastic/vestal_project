"""ara_workflows_m6.py - the three provided workflow definitions of M6, as YAML text (28 sections 3, 4; 29 section 3).

    evaluator_run_yaml(inference_id)    `cortex-evaluator-run` (6.2): manual trigger, window inputs, one ai.agent step with
                                        placeholders for with.message and with.schema, a foreach writing each proposal
    canary_run_yaml(agent_id)           `cortex-canary-run` (6.3): manual trigger only, optional change_id; asks Tina the
                                        canary-v1 questions in fresh conversations and records each raw result
    answer_audit_yaml()                 `cortex-answer-audit` (6.3 N3): declares the post-execution inputs, writes one
                                        cortex-audit record when tool_calls include cortex.sar_search

Every definition has `enabled: true` and a manual trigger and NO scheduled trigger (29 section 3: no start state carries
one; the learner adds theirs in 6.3). Syntax is the live one from M4's probes: version "1", `triggers`, `inputs`
(name, type, required, description), Liquid `{{ ... }}`, `foreach`/`if` steps. Three things the specs leave to a probe are
isolated in constants so one edit follows the answer: STRUCTURED_OUTPUT_PATH, TRIGGERED_BY_EXPR (P2), SAR_CONDITION (P6).
`placeholders_left(yaml)` is what B1's check reads to tell the learner has replaced the two placeholders. Standard library only.
"""
from __future__ import annotations

import json
import re

PLACEHOLDER_MESSAGE = "PLACEHOLDER: write the run message for the evaluator here"
PLACEHOLDER_SCHEMA = "PLACEHOLDER: write the proposal JSON Schema here"
STRUCTURED_OUTPUT_PATH = "steps.evaluate.output.structured_output.proposals"  # P7 confirmed (probe r4): step output is {message (the JSON as text), structured_output, metadata}; with.schema must be a YAML mapping, not a quoted string
TRIGGERED_BY_EXPR = "{{ execution.triggeredBy }}"  # P2 confirmed (probe r2): renders "scheduled" for scheduler runs, "manual" for API/manual runs
SAR_CONDITION = "foreach.item.tool_id : cortex.sar_search"  # P6 (probe r4, 2026-11-12): conditions are KQL-style (`:`); `==` and Liquid never matched. Used inside a foreach over inputs.tool_calls; the index step's `id` (the round id) keeps one audit record per round however many calls match
OBJECT_FIELDS = ("change", "evidence", "expected_effect")
PROPOSAL_FIELDS = ("kind", "proposal_type", "target", "change", "evidence", "expected_effect", "rationale")


def _liquid(expr: str) -> str:
    return "{{ " + expr + " }}"


def evaluator_run_yaml(inference_id: str, agent_id: str = "cortex-evaluator", name: str = "cortex-evaluator-run") -> str:
    # change, evidence and expected_effect are objects and arrays: plain {{ }} renders them as strings (document_parsing_exception), so they use the type-preserving ${{ }}
    doc = "\n".join(f"                {f}: \"{'$' if f in OBJECT_FIELDS else ''}{_liquid('foreach.item.' + f)}\"" for f in PROPOSAL_FIELDS)
    return f'''version: "1"
name: {name}
enabled: true
triggers:
  - type: manual
inputs:
  - name: window_start
    type: string
    required: false
    default: now-7d
    description: Start of the window the evaluator reads (default, the last seven days)
  - name: window_end
    type: string
    required: false
    default: now
    description: End of the window the evaluator reads
steps:
  - name: evaluate
    type: ai.agent
    agent-id: {agent_id}
    inference-id: {inference_id}
    with:
      message: "{PLACEHOLDER_MESSAGE}"
      schema: "{PLACEHOLDER_SCHEMA}"
  - name: each_proposal
    type: foreach
    foreach: "{_liquid(STRUCTURED_OUTPUT_PATH)}"
    steps:
      - name: write_proposal
        type: elasticsearch.index
        with:
          index: cortex-eval-proposals
          document:
{doc}
                run_id: "{_liquid('execution.id')}"
                proposal_id: "prop-{_liquid('execution.id')}-{_liquid('foreach.index')}"
                created_at: "{_liquid("execution.startedAt | date: '%Y-%m-%dT%H:%M:%SZ'")}"
                status: proposed
'''


def placeholders_left(yaml_text: str) -> list[str]:
    return [p for p in (PLACEHOLDER_MESSAGE, PLACEHOLDER_SCHEMA) if p in yaml_text]


def canary_run_yaml(agent_id: str = "tina-compliance", testset_version: str = "canary-v1", name: str = "cortex-canary-run") -> str:
    return f'''version: "1"
name: {name}
enabled: true
triggers:
  - type: manual
inputs:
  - name: change_id
    type: string
    required: false
    description: The change this run checks (the deploy script passes its change id)
steps:
  - name: questions
    type: elasticsearch.search
    with:
      index: cortex-eval-testsets
      size: 20
      query:
        term:
          testset_version: {testset_version}
  - name: each_question
    type: foreach
    foreach: "{_liquid('steps.questions.output.hits.hits')}"
    steps:
      - name: ask
        type: ai.agent
        agent-id: {agent_id}
        create-conversation: true
        with:
          message: "{_liquid('foreach.item._source.input')}"
      - name: record
        type: elasticsearch.index
        with:
          index: cortex-canary-raw
          document:
            question_id: "{_liquid('foreach.item._source.question_id')}"
            conversation_id: "{_liquid('steps.ask.output.conversation_id')}"
            workflow_execution_id: "{_liquid('execution.id')}"
            triggered_by: "{TRIGGERED_BY_EXPR}"
            change_id: "{_liquid('inputs.change_id')}"
            run_label: "canary-{_liquid('execution.id')}"
            testset_version: {testset_version}
            at: "{_liquid("execution.startedAt | date: '%Y-%m-%dT%H:%M:%SZ'")}"
'''


def answer_audit_yaml(name: str = "cortex-answer-audit") -> str:
    return f'''version: "1"
name: {name}
enabled: true
triggers:
  - type: manual
inputs:
  - name: round_id
    type: string
    required: true
    description: The round that was answered
  - name: conversation_id
    type: string
    required: true
    description: The conversation the round belongs to
  - name: agent_id
    type: string
    required: true
    description: The agent that answered
  - name: tool_calls
    type: array
    required: true
    description: The tool calls the round made
steps:
  - name: each_call
    type: foreach
    foreach: "{_liquid('inputs.tool_calls')}"
    steps:
      - name: only_sar_answers
        type: if
        condition: "{SAR_CONDITION}"
        steps:
          - name: write_audit
            type: elasticsearch.index
            with:
              index: cortex-audit
              id: "{_liquid('inputs.round_id')}"
              document:
                round_id: "{_liquid('inputs.round_id')}"
                conversation_id: "{_liquid('inputs.conversation_id')}"
                audited_at: "{_liquid("execution.startedAt | date: '%Y-%m-%dT%H:%M:%SZ'")}"
'''


def scheduled_triggers(yaml_text: str) -> list[str]:
    """Lines declaring a scheduled trigger (there must be none in a provided definition)."""
    return re.findall(r"^\s*-\s*type:\s*scheduled\s*$", yaml_text, flags=re.M)


def strip_scheduled(yaml_text: str) -> str:
    """The definition without its scheduled trigger item (the item line and the lines indented under it); the rest is untouched."""
    out, skip = [], None
    for line in yaml_text.split("\n"):
        m = re.match(r"^(\s*)-\s*type:\s*scheduled\s*$", line)
        if m:
            skip = len(m.group(1))
            continue
        if skip is not None and line.strip() and len(line) - len(line.lstrip()) > skip:
            continue
        skip = None
        out.append(line)
    return "\n".join(out)


def step_names(yaml_text: str) -> list[str]:
    body = yaml_text.split("\nsteps:\n", 1)[1] if "\nsteps:\n" in yaml_text else ""
    return re.findall(r"^\s*-\s*name:\s*([\w.-]+)\s*$", body, flags=re.M)


def input_names(yaml_text: str) -> list[str]:
    block = yaml_text.split("\ninputs:\n", 1)[1].split("\nsteps:\n", 1)[0] if "\ninputs:\n" in yaml_text else ""
    return re.findall(r"^\s*-\s*name:\s*(\w+)", block, flags=re.M)


def doc_json(obj) -> str:  # a helper for tests and setup scripts that need a definition as JSON text
    return json.dumps(obj, sort_keys=True)
