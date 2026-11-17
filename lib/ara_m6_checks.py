"""ara_m6_checks.py - the M6 grading logic that needs no live answers (28 sections 2-7; 07 section 3.6).

Pure functions over dicts the check scripts read from the sandbox; no HTTP. Platform shape guesses are one-line constants (GUESS).

    diagnose(record, key)                  messages naming the fields that differ (never the answer)       6.1 DIAGNOSE, 6.4 DIAGNOSE
    tool_artifact(new, original)           6.1 ARTIFACT: same id/type/params/description; only the query changed
    gap_tool_artifact(tool, gap)           6.1 gap tool: esql, a parameter per ?name used, description, names the gap's index
    evaluator_artifact(agent, tools)       6.2: only custom, bounded, read-only ES|QL tools (two or more); no built-ins, skills, sub-agents
    learner_schema_check(schema)           6.2: the learner's output schema accepts VALID and rejects every INVALID
    gate_equals_key(gate, key)             6.2: the learner's gate.json equals the variant key (whitespace and key order aside)
    post_exec_artifact(ids)                6.3 N3: the post-execution agent list is exactly [cortex-answer-audit]
    tier(...)                              6.C: tiers 100/75/50/25/0 and the grade.json body (schema 6c-1)
"""
from __future__ import annotations

import json
import re
from typing import Any

import ara_proposal_schema as PS
import ara_tracepack as TP

CAPS_OFF_FIELD = "enable_elastic_capabilities"  # P7 (probe r2): configuration.enable_elastic_capabilities: false is accepted; the other candidate names are refused
GUESS = {"QUERY_PATH": ("configuration", "query"), "PARAMS_PATH": ("configuration", "params"), "BUILTIN_PREFIX": "platform.",
         "POST_EXEC_AUDIT_ID": "cortex-answer-audit"}
QUERY_PATH, PARAMS_PATH, BUILTIN_PREFIX, AUDIT_ID = GUESS["QUERY_PATH"], GUESS["PARAMS_PATH"], GUESS["BUILTIN_PREFIX"], GUESS["POST_EXEC_AUDIT_ID"]
FIELD_MESSAGES = {"failing_span_id": "the failing span is not the one that failed", "failure_class": "the failure class does not match the evidence",
                  "costly_span_id": "the costliest span is not the one you named", "costly_cause": "the cause of the cost does not match the evidence",
                  "costly_input_tokens": "the input-token count does not match the span you named"}


def _ws(s: Any) -> Any:
    return re.sub(r"\s+", " ", s).strip() if isinstance(s, str) else s


def _get(d: dict, path: tuple) -> Any:
    for k in path:
        d = d.get(k) if isinstance(d, dict) else None
    return d


def _without(d: dict, path: tuple) -> dict:
    import copy
    d = copy.deepcopy(d)
    node = d
    for k in path[:-1]:
        node = node.get(k) if isinstance(node, dict) else {}
    if isinstance(node, dict):
        node.pop(path[-1], None)
    return d


def diagnose(record: dict, key: dict, fields: tuple = TP.KEY_FIELDS) -> list[str]:
    return [FIELD_MESSAGES.get(f, f"{f} does not match") for f in TP.compare_record(record, key, fields)]


def _norm(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: _norm(x) for k, x in sorted(v.items())}
    if isinstance(v, list):
        return [_norm(x) for x in v]
    return _ws(v)


def tool_artifact(new: dict, original: dict) -> list[str]:
    """The fix changes the query and nothing else; whitespace is not a change. Problems empty when it holds."""
    out = []
    if _ws(_get(new, QUERY_PATH)) == _ws(_get(original, QUERY_PATH)):
        out.append("the tool's query is unchanged")
    a, b = _norm(_without(new, QUERY_PATH)), _norm(_without(original, QUERY_PATH))
    for k in sorted(set(a) | set(b)):
        if k in ("created_at", "updated_at", "readonly", "permissions"):
            continue
        if a.get(k) != b.get(k):
            out.append(f"{k} changed; only the query may change")
    return out


def gap_tool_artifact(tool: dict, gap_index: str | None = None) -> list[str]:
    out = []
    q, params = _get(tool, QUERY_PATH) or "", _get(tool, PARAMS_PATH) or {}
    if tool.get("type") != "esql":
        out.append("the tool is not an ES|QL tool")
    if not _ws(tool.get("description")):
        out.append("the tool has no description")
    if not re.match(r"\s*(FROM|ROW|TS)\b", q, re.I):
        out.append("the query does not start with FROM")
    used = set(re.findall(r"\?(\w+)", q))
    if not used:
        out.append("the query takes no parameter")
    if used != set(params):
        out.append("the declared parameters do not match the ?names the query uses")
    if gap_index and gap_index not in q:
        out.append(f"the query does not read {gap_index}")
    return out


def evaluator_artifact(agent: dict, tools: dict[str, dict], min_tools: int = 2) -> list[str]:
    import ara_loop as L
    ids = list(L.tool_id_list(agent))
    out = []
    if len(ids) < min_tools:
        out.append(f"the evaluator needs at least {min_tools} tools")
    for i in ids:
        t = tools.get(i)
        if i.startswith(BUILTIN_PREFIX) or t is None:
            out.append(f"{i} is not a custom tool"); continue
        q = _get(t, QUERY_PATH) or ""
        lim = [int(x) for x in re.findall(r"\bLIMIT\s+(\d+)", q, re.I)]
        if t.get("type") != "esql":
            out.append(f"{i} is not an ES|QL tool")
        elif not re.match(r"\s*FROM\s+(traces-agent_builder[\w.*-]*|cortex-eval-runs)\b", q, re.I):
            out.append(f"{i} does not read the trace stream or cortex-eval-runs")
        elif not (lim and max(lim) <= 200) and not re.search(r"\bSTATS\b", q, re.I):
            out.append(f"{i} has no bound: end it in STATS or add LIMIT 200 or less")
        elif re.search(r"\b(DELETE|INSERT|UPDATE)\b", q, re.I):
            out.append(f"{i} is not read-only")
    if (agent.get("configuration") or {}).get(CAPS_OFF_FIELD) is not False:
        out.append("the evaluator's built-in capabilities are not switched off")
    if agent.get("skill_ids"):
        out.append("the evaluator has skills attached")
    if agent.get("subagent_ids") or agent.get("sub_agents"):
        out.append("the evaluator has sub-agents attached")
    return out


def learner_schema_check(schema: dict) -> list[str]:
    import jsonschema
    try:
        v = jsonschema.Draft202012Validator(schema)
        v.check_schema(schema)
    except Exception as e:  # noqa: BLE001
        return [f"the schema is not valid JSON Schema: {str(e)[:80]}"]
    out = []
    for name, p in PS.VALID.items():
        if not v.is_valid(PS.wrap(p)):
            out.append(f"the schema rejects a valid proposal ({name})")
    for label, doc in PS.INVALID:
        if v.is_valid(doc):
            out.append(f"the schema accepts an invalid proposal ({label})")
    return out


def gate_equals_key(gate: dict, key: dict) -> list[str]:
    a, b = _norm(gate), _norm(key)
    return [f"gate.json: {k} differs from Cortex's policy" for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)]


def post_exec_artifact(ids: list[str]) -> list[str]:
    return [] if list(ids) == [AUDIT_ID] else [f"the post-execution list is {ids}, expected [{AUDIT_ID}]"]


def tier(changed: bool, recovered: bool, gate_before_apply: bool, fixed_state: bool, monitor_pass: bool, defend_consistent: bool) -> int:
    """07 section 3.6. 0 nothing changed; 25 changed, no recovery; 50 recovered but gate-before-apply, fixed state or monitor fails
    (a failed gate caps at 50 whatever else passes); 75 recovered, all constraints pass, Defend inconsistent; 100 all met."""
    if not changed:
        return 0
    if not recovered:
        return 25
    if not (gate_before_apply and fixed_state and monitor_pass):
        return 50
    return 100 if defend_consistent else 75


def grade_json(seed: str, decoy: str, root_cause: dict, gate: dict, remeasure: dict, state: dict, monitor: dict, defend: dict,
               assets_ref: str, connector_id: str, tier_value: int) -> dict:
    return {"schema": "6c-1", "tier": tier_value, "seed": seed, "decoy": decoy, "root_cause": root_cause, "gate": gate, "remeasure": remeasure,
            "state": state, "monitor": monitor, "defend": defend,
            "behavior_measurement": {"metric": remeasure.get("affected_metric"), "baseline": remeasure.get("baseline"), "degraded": remeasure.get("degraded"), "after": remeasure.get("after")},
            "assets_ref": assets_ref, "connector_id": connector_id}


def passed(tier_value: int) -> bool:
    return tier_value >= 75


# ── added for the graders (28 sections 2 to 5, 07 section 3.4) ────────────────────────────────────────────────

def gap_card_match(tool: dict, card: dict) -> list[str]:
    """6.1 B3 ARTIFACT beyond gap_tool_artifact: the card's id, exactly the card's parameter names and types, and the card's index."""
    out = []
    if tool.get("id") != card["tool_id"]:
        out.append(f"the tool's id is not {card['tool_id']}")
    declared = {k: (v or {}).get("type") for k, v in (_get(tool, PARAMS_PATH) or {}).items()}
    if declared != dict(card["params"]):
        out.append("the declared parameters do not equal the card's names and types")
    return out + gap_tool_artifact(tool, card["index"])


def windows_check(found: list[dict], key: list[dict], days: int = 1) -> list[str]:
    """6.4 B1: each learner window (change_point_date, type, signal) matches one key window; date within `days`, type and signal equal.
    The message names the window by its number in the learner's records, never the answer."""
    import datetime as dt
    out, used = [], set()
    for n, w in enumerate(found, 1):
        try:
            d = dt.date.fromisoformat(str(w.get("change_point_date")))
        except ValueError:
            out.append(f"window {n}: the date is not a date")
            continue
        best = min(((abs((d - dt.date.fromisoformat(k["change_point_date"])).days), i) for i, k in enumerate(key) if i not in used), default=None)
        if best is None or best[0] > days:
            out.append(f"window {n}: no incident begins near that date")
            continue
        used.add(best[1])
        k = key[best[1]]
        if w.get("type") != k["type"]:
            out.append(f"window {n}: the type does not match the evidence")
        elif w.get("signal") != k["signal"]:
            out.append(f"window {n}: the signal does not match the type's evidence")
    if len(found) != len(key):
        out.append(f"record {len(key)} windows, one per incident")
    return out


# A conversation outside the week's pack can show a pattern for real: the live defect is installed in Tina, so the sandbox's own rounds repeat it
# (in a recorded failure every double search the evaluator found was one of those, and none was in the pack). The trace defines this one without a threshold, so a conversation that shows it
# counts as evidence like the pack's own. Oversized results and the other patterns need a judgement, so they stay with the pack's conversations.
SHOWN_ESQL = {"double_search": ("FROM traces-agent_builder.otel-default\n| WHERE attributes.gen_ai.operation.name == \"execute_tool\" AND attributes.gen_ai.tool.name == \"cortex.policy_search\"\n"
                                "| STATS calls = COUNT(*) BY conversation_id = attributes.gen_ai.conversation.id, trace_id\n| WHERE calls >= 2\n| KEEP conversation_id\n| LIMIT 10000")}


def shown_ids(body: dict | None) -> set:
    """Conversation ids out of an ES|QL answer (rows of [conversation_id]). An answer without `values` is not an empty answer: ValueError, so the check ends with no grade."""
    if not isinstance(body, dict) or not isinstance(body.get("values"), list):
        raise ValueError("the traces query answered without values")
    return {r[0] for r in body["values"] if r and r[0]}


def grounding(proposals: list[dict], key: dict, min_patterns: int = 2, evidence_floor: int = 1, known: set | None = None,
              shown: dict | None = None) -> tuple[list[str], list[str]]:
    """6.2 B1: the evaluator's proposals against the week pack's key. `key` = {"patterns": {name: {"target", "types", "conversation_ids"}}, "live": [names]}.
    A pattern is named when a proposal has its target, one of its types, and evidence citing a conversation from that pattern's set; a made-up conversation id
    fails. `known` is every conversation id that exists in the trace stream (a real conversation outside the week's patterns is not a made-up one); default, the
    patterns' own conversations. `shown` = {pattern: conversation ids the trace stream shows with it} (SHOWN_ESQL); they count with the pack's own. Returns (problems, patterns named)."""
    named, problems = [], []
    ids = set(known) if known is not None else {c for p in key["patterns"].values() for c in p["conversation_ids"]}
    for p in proposals:
        for e in p.get("evidence") or []:
            if e.get("conversation_id") not in ids:
                problems.append("a proposal cites a conversation that is not in the week")
                break
    for name in key["live"]:
        spec = key["patterns"][name]
        own = set(spec["conversation_ids"]) | set((shown or {}).get(name) or ())
        hit = [p for p in proposals if p.get("target") == spec["target"] and p.get("proposal_type") in spec["types"]
               and sum(1 for e in p.get("evidence") or [] if e.get("conversation_id") in own) >= evidence_floor]
        if hit:
            named.append(name)
    if len(named) < min_patterns:
        problems.append(f"the proposals name {len(named)} of the week's patterns with evidence from their conversations; {min_patterns} are needed")
    if any(p.get("proposal_type") == "data_change" for p in proposals):
        problems.append("an improvement proposal proposed a data change")
    return list(dict.fromkeys(problems)), named


_LITERAL = re.compile(r"(\d{4}-\d{2}-\d{2}|run_label\s*==|workflow_execution_id\s*==|conversation_id\s*==|question_id\s*==|canary-[0-9a-f]{8})", re.I)


def monitor_literals(esql: str) -> list[str]:
    """07 section 3.4: a rule may not filter on a literal timestamp or date, a run label, an execution id, a conversation id or a question id."""
    return [f"the rule's query filters on a literal ({m.group(0)[:20]})" for m in _LITERAL.finditer(esql or "")][:1]


def monitor_verdict(degraded_rows: int, healthy_rows: list[int], post_fix_rows: int, window_hours: float, latest_alert: str | None, desk_opening: str,
                    min_window_hours: float = 8.0) -> list[str]:
    out = []
    if degraded_rows < 1:
        out.append("the rule returns nothing over last night's degraded window")
    if any(healthy_rows):
        out.append("the rule fires on a healthy night")
    if post_fix_rows:
        out.append("the rule still fires after the fix")
    if window_hours < min_window_hours:
        out.append(f"the rule's window is shorter than the {min_window_hours:g} hours between canary runs")
    if latest_alert is None or latest_alert > desk_opening:
        out.append("the rule would alert after the desk opens")
    return out
