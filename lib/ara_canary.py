"""ara_canary.py - the canary scorer: turns a canary conversation into the complete run record the integrity procedure can verify
(28 section 4 and section 1, "the canary scorer"; 28 section 8.8).

    score_question(q, conversation, run, retrieval=None)   one cortex-eval-runs document
    score_run(questions, raw_docs, fetch, retrieval=None)  (documents, problems) for the raw rows of one workflow execution

`cortex-canary-run` writes one raw row per question (question_id, conversation_id, workflow_execution_id, triggered_by,
change_id, run_label, testset_version, at) to `cortex-canary-raw`. This scorer reads each row's conversation, grades the route with the
harness's own matcher (a replay client around the stored round, so there is one route rule), and writes the record in the
same field names as ara-eval.py's run documents plus the canary fields. It is the fallback if P2 shows the platform cannot
write complete records inside the workflow; it is also what the 6.3 check recomputes against. A policy question's record
carries null route fields and the retrieval block it is given (`recall_at_5`, `ndcg_at_5`, `lexical_recall_at_5`).
Nothing here converses with Tina: conversations are read. Standard library only.
"""
from __future__ import annotations

from typing import Any, Callable

from agent_builder import round_usage, route_record
from ara_eval import CATEGORIES
from ara_eval_run import run_question

CANARY_FIELDS = ("workflow_execution_id", "triggered_by", "change_id")


class _Replay:
    """A client whose 'conversation' already happened: converse_timed returns the stored round."""

    def __init__(self, rnd: dict, conversation_id: str):
        self.rnd, self.cid = rnd, conversation_id

    def converse_timed(self, agent_id: str, text: str):
        return dict(self.rnd, conversation_id=self.cid), self.rnd.get("time_to_last_token")


def _round(conversation: dict) -> dict | None:
    rounds = conversation.get("rounds") or []
    return rounds[0] if len(rounds) == 1 else None


def score_question(q: dict, conversation: dict, run: dict, retrieval: dict | None = None) -> dict:
    """`q` is the canary-v1 item ({id|question_id, type|kind, input, expected, ...}); `conversation` is GET /conversations/{id};
    `run` holds run_id, run_label, run_at, workflow_execution_id, triggered_by, change_id, testset_version, agent_id."""
    qid = q.get("id") or q.get("question_id")
    rnd = _round(conversation)
    base = {"run_id": run["run_id"], "run_label": run["run_label"], "run_at": run["run_at"], "provided": False,
            "testset_version": run.get("testset_version", "canary-v1"), "question_id": qid, "agent_id": run["agent_id"],
            "conversation_id": conversation.get("id") or conversation.get("conversation_id"),
            **{k: run.get(k) for k in CANARY_FIELDS}}
    if rnd is None:
        return dict(base, status="unscorable", reason="the conversation does not have exactly one round")
    kind = q.get("type") or q.get("kind")
    usage = round_usage(rnd, rnd.get("time_to_last_token"), base["conversation_id"])
    usage_fields = {k: usage[k] for k in ("tool_call_count", "llm_calls", "input_tokens", "cached_input_tokens", "output_tokens", "latency_ms")}
    trace_id = rnd.get("trace_id") or conversation.get("trace_id")
    if kind == "policy":
        return dict(base, status="graded", category="policy_retrieval", expected_route=None, observed_route=None, route_correct=None,
                    escalated=None, trace_id=trace_id, retrieval=retrieval or {}, **usage_fields)
    if q.get("category") not in CATEGORIES:   # categories come from the root-only key; a question without one is an error, never an uncategorised row
        raise ValueError(f"{qid}: the question has no category from the root-only key; nothing is scored")
    rec = run_question(_Replay(rnd, base["conversation_id"]), run["agent_id"], dict(q, id=qid), label=q.get("category"), attempts=1)
    if rec["status"] != "graded":
        return dict(base, status="unscorable", reason=rec.get("reason"))
    return dict(base, status="graded", category=rec["category"], expected_route=rec["expected_route"], observed_route=rec["observed_route"],
                route_correct=bool(rec["route_correct"]), escalated=any(c["tool_id"] == "cortex.escalate" for c in route_record(rnd)),
                trace_id=trace_id or rec.get("trace_id"), **usage_fields)


def score_run(questions: list[dict], raw_docs: list[dict], fetch: Callable[[str], dict | None],
              retrieval: dict[str, dict] | None = None, agent_id: str = "tina-compliance") -> tuple[list[dict], list[str]]:
    """Documents for every raw row of one execution, in question order, and the problems that make the run incomplete
    (a question with no row, a row with no readable conversation, an unscorable round). A run with problems is not written."""
    if not raw_docs:
        return [], ["the execution wrote no rows"]
    head = raw_docs[0]
    run = {"run_id": f"{head['run_label']}-{head.get('at', '')}", "run_label": head["run_label"], "run_at": head.get("at"),
           "testset_version": head.get("testset_version", "canary-v1"), "agent_id": agent_id,
           **{k: head.get(k) for k in CANARY_FIELDS}}
    by_q = {r["question_id"]: r for r in raw_docs}
    docs, problems = [], []
    for q in questions:
        qid = q.get("id") or q.get("question_id")
        raw = by_q.get(qid)
        if raw is None:
            problems.append(f"{qid}: no row")
            continue
        conv = fetch(raw["conversation_id"]) if raw.get("conversation_id") else None
        if not conv:
            problems.append(f"{qid}: conversation {raw.get('conversation_id')} unreadable")
            continue
        d = score_question(q, conv, run, (retrieval or {}).get(qid))
        if d["status"] != "graded":
            problems.append(f"{qid}: {d.get('reason')}")
            continue
        docs.append(d)
    return docs, problems
