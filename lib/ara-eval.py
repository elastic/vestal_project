#!/usr/bin/env python3
"""
ara-eval.py - the Cortex evaluation harness (Lab 5.3 on; M6 calls it too).

Usage (as the learner; the credentials come from ~/env):
  python3 /opt/ara/lib/ara-eval.py rank-eval --label baseline   # one _rank_eval call per metric, per-category retrieval
  python3 /opt/ara/lib/ara-eval.py run --label baseline --testset ~/cortex-eval/testset.json --agent tina-compliance
  python3 /opt/ara/lib/ara-eval.py judge --label diagnose        # your judge.esql over cortex-eval-samples
  python3 /opt/ara/lib/ara-eval.py compare before after         # two labelled runs side by side, priced on the rate card
  python3 /opt/ara/lib/ara-eval.py reset                        # put Tina's reach back to the 5.4 start state after a stray edit

run sends every agent-level question of the test set to Tina, one fresh conversation each, three at a time,
and prints per-category routing accuracy. rank-eval reads ~/cortex-eval/rank-eval.json, checks _rank_eval
against its own recomputation and prints per-category precision, recall and nDCG at 5. judge runs your query,
reads the first number of each score, snaps it to the scale and reports how many fell off it. All three store
their records in cortex-eval-runs. reset prints the objects and fields it restored, never values. No prompts: exit 0 done, 1 a check of the work failed, 2 bad input,
3 no grade (an outage: nothing recorded, run it again), 4 records not stored.
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import ara_eval_cli as C  # noqa: E402
from agent_builder import AB  # noqa: E402
from ara_security import ES  # noqa: E402


class EvalES:
    """The three calls the harness makes, over ara_security.ES (an outage raises ABError; a 4xx becomes ValueError)."""

    def __init__(self, es: ES):
        self.es = es

    def _ok(self, what: str, code: int, body):
        if code != 200:
            reason = (body.get("error") or {}).get("reason") if isinstance(body, dict) and isinstance(body.get("error"), dict) else body
            raise ValueError(f"{what} refused (HTTP {code}): {str(reason)[:240]}")
        return body

    def index_docs(self, index: str, docs: list[dict]) -> int:
        nd = "".join(json.dumps({"index": {"_index": index}}) + "\n" + json.dumps(d) + "\n" for d in docs)
        body = self._ok("bulk index", *self.es.request_ndjson("POST", "/_bulk?refresh=wait_for", nd))
        if body.get("errors"):
            first = next((i["index"].get("error") for i in body["items"] if i["index"].get("error")), "unknown")
            raise ValueError(f"bulk index had errors: {str(first)[:200]}")
        return len(docs)

    def rank_eval(self, index: str, body: dict) -> dict:
        return self._ok("_rank_eval", *self.es.request("POST", f"/{index}/_rank_eval", body))

    def search_runs(self, label: str) -> list[dict]:
        body = self._ok("run search", *self.es.request("POST", "/cortex-eval-runs/_search",
                        {"size": 1000, "query": {"term": {"run_label": label}}}))
        return [h["_source"] for h in body.get("hits", {}).get("hits", [])]

    def esql(self, query: str) -> dict:
        return self._ok("the judge query", *self.es.request("POST", "/_query?format=json", {"query": query}))


class Spans:
    def __init__(self, es: ES):
        self.es = es

    def __call__(self, trace_id: str) -> list[dict]:
        body = {"size": 500, "sort": [{"@timestamp": "asc"}], "query": {"term": {"trace_id": trace_id}}}
        code, resp = self.es.request("POST", "/traces-agent_builder.otel-*/_search", body)
        if code != 200:
            raise C.ABError(f"the trace store did not answer (HTTP {code})", 503)
        return [h["_source"] for h in resp.get("hits", {}).get("hits", [])]


class Reach:
    """Tina's reach for reset: AB's reads, plus create-or-replace and delete per kind. A 4xx on a write raises
    ValueError (the learner's input); an outage raises ABError, as everywhere."""

    def __init__(self, ab: AB):
        self.ab = ab
        for n in ("get_agent", "get_tool", "get_skill", "get_workflow", "connectors", "plugins"):
            setattr(self, n, getattr(ab, n))

    @staticmethod
    def _ok(what: str, res):
        code, body = res
        if not 200 <= code < 300:
            raise ValueError(f"{what} refused (HTTP {code}): {str(body)[:240]}")

    # The fields each Kibana endpoint accepts on a write: a read returns more (experimental, readonly, type
    # details), and an extra property is a 400 ("Additional properties are not allowed").
    WRITABLE = {
        "agent": ("name", "description", "labels", "avatar_color", "avatar_symbol", "configuration"),
        "tool": ("type", "description", "tags", "configuration"),
        "skill": ("name", "description", "content", "tool_ids"),
    }

    @classmethod
    def writable(cls, kind: str, body: dict) -> dict:
        return {k: v for k, v in body.items() if k in cls.WRITABLE[kind]}

    def apply(self, kind: str, oid: str, body: dict) -> None:
        ab = self.ab
        if kind == "agent":
            self._ok(f"agent {oid}", ab.put_agent(dict(self.writable(kind, body), id=oid)))
        elif kind == "tool":
            self._ok(f"tool {oid}", ab.put_tool(dict(self.writable(kind, body), id=oid)))
        elif kind == "skill":
            self._ok(f"skill {oid}", ab.put_skill(dict(self.writable(kind, body), id=oid)))
        elif kind == "workflow":
            self._ok(f"workflow {oid}", ab.put_workflow(oid, body.get("yaml") or ""))
        elif kind == "connector":  # config and name only; its secrets stay as they are
            self._ok(f"connector {oid}", ab.request("PUT", f"/api/actions/connector/{oid}",
                                                    {"name": body.get("name"), "config": body.get("config") or {}}))
        elif kind == "plugin":  # reinstall from the source it came from
            url = body.get("url") or body.get("source_url") or (body.get("source") or {}).get("url")
            if not url:
                raise ValueError(f"plugin {oid} has no source URL in the start copy")
            ab.delete_plugin(oid)
            self._ok(f"plugin {oid}", ab.install_plugin(url))
        else:
            raise ValueError(f"cannot restore a {kind}")

    def remove(self, kind: str, oid: str) -> None:
        ab = self.ab
        fn = {"agent": ab.delete_agent, "tool": ab.delete_tool, "skill": ab.delete_skill, "workflow": ab.delete_workflow,
              "connector": ab.delete_connector, "plugin": ab.delete_plugin}.get(kind)
        if fn is None:
            raise ValueError(f"cannot remove a {kind}")
        code = fn(oid)
        if code >= 400 and code != 404:
            raise ValueError(f"removing {kind} {oid} refused (HTTP {code})")


def make_clients(env: dict):
    from types import SimpleNamespace
    ctx_need = lambda n: env.get(n) or sys.exit(f"{n} is not set. Open a new terminal (it loads ~/env) and run this again.")
    key = env.get("ARA_TINA_EVAL_KEY") or ctx_need("ES_API_KEY")
    es_url = ctx_need("ES_URL").rstrip("/")
    es = ES(es_url, f"ApiKey {key}", timeout=130)  # a judge query may run for its 120 s default
    trace_key = env.get("ES_API_KEY") or key
    ab = AB(ctx_need("KIBANA_URL").rstrip("/"), key, env.get("ARA_AB_CONNECTOR_ID"), timeout=170)
    # reset reads and writes agents, tools, skills, workflows and connectors: the project key, not the harness key
    reach_ab = AB(ctx_need("KIBANA_URL").rstrip("/"), env.get("ES_API_KEY") or key, env.get("ARA_AB_CONNECTOR_ID"), timeout=170)
    return SimpleNamespace(ab=ab, reach=Reach(reach_ab),
                           es=EvalES(es), spans=Spans(ES(es_url, f"ApiKey {trace_key}", timeout=30)))


if __name__ == "__main__":
    sys.exit(C.main(sys.argv[1:], make_clients=make_clients))
