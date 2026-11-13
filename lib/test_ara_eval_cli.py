"""Offline tests for ara_eval_cli.py (ara-eval.py) with fake clients."""
from __future__ import annotations

import datetime
import importlib.util
import io
import json
import pathlib
import re
import sys
import threading
from types import SimpleNamespace

import pytest

LIB = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(LIB))

import agent_builder as A  # noqa: E402
import ara_eval_cli as C  # noqa: E402
from ara_metrics import rank_eval_at_k  # noqa: E402

JID = "judge-endpoint-x"
NOW = lambda: datetime.datetime(2026, 11, 10, 12, 0, 0, tzinfo=datetime.timezone.utc)


def resp(*tools, text="ok"):
    steps = [{"type": "tool_call", "tool_id": t, "params": p, "results": []} for t, p in tools]
    return {"conversation_id": "c-" + text, "trace_id": "t", "steps": steps, "response": {"message": text},
            "model_usage": {"input_tokens": 1000, "cached_input_tokens": 400, "output_tokens": 50, "llm_calls": 2}}


class FakeAB:
    def __init__(self, script):
        self.script, self.calls, self.lock = script, {}, threading.Lock()

    def converse_timed(self, agent_id, text):
        with self.lock:
            self.calls[text] = self.calls.get(text, 0) + 1
        r = self.script[text]
        if isinstance(r, Exception):
            raise r
        return r, 900


class FakeES:
    def __init__(self, hits=None, esql=None, scale=1.0, fail=None):
        self.indexed, self.hits, self.esql_result, self.scale, self.fail = [], hits or {}, esql, scale, fail
        self.rank_calls, self.esql_calls = [], []

    def index_docs(self, index, docs):
        if self.fail:
            raise A.ABError("503", 503)
        self.indexed.append((index, list(docs)))
        return len(docs)

    def rank_eval(self, index, body):
        self.rank_calls.append((index, body))
        name = next(iter(body["metric"]))
        field = {"precision": "precision_at_k", "recall": "recall_at_k", "dcg": "ndcg_at_k"}[name]
        details, scores = {}, []
        for r in body["requests"]:
            rid = r["id"]
            got = self.hits[r["params"]["query_string"]]
            rel = {x["_id"] for x in r["ratings"] if x["rating"] >= 1}
            s = rank_eval_at_k({rid: got}, {rid: rel}, 5)[field] * self.scale
            scores.append(s)
            details[rid] = {"metric_score": s, "hits": [{"hit": {"_id": h}} for h in got]}
        return {"metric_score": sum(scores) / len(scores), "details": details, "failures": {}}

    def esql(self, query):
        self.esql_calls.append(query)
        if isinstance(self.esql_result, Exception):
            raise self.esql_result
        return self.esql_result


def out_of(argv, clients, env, tmp, **kw):
    buf = io.StringIO()
    code = C.main(argv, clients=clients, environ=dict({"ARA_EVAL_HOME": str(tmp / "home")}, **env), out=buf, now=NOW,
                  new_id=lambda: "abc", sleep=lambda s: None, **kw)
    return code, buf.getvalue()


# ── run ───────────────────────────────────────────────────────────────────────

POOL = {"questions": [
    {"id": "q1", "type": "agent", "input": "dep 476", "expected": [{"tool_id": "cortex.structuring_deposits", "params": {"account_id": "476"}}]},
    {"id": "q2", "type": "agent", "input": "close it", "expected": [{"tool_id": "cortex.escalate"}]},
    {"id": "p1", "type": "policy", "input": "pep?", "relevant_ids": ["policy-001-s1"]}]}
GOOD = {"dep 476": resp(("cortex.structuring_deposits", {"account_id": "476"})), "close it": resp(("cortex.escalate", {}))}


@pytest.fixture
def files(tmp_path):
    (tmp_path / "pool.json").write_text(json.dumps(POOL))
    (tmp_path / "ts.json").write_text(json.dumps([{"question_id": "q1", "category": "straightforward"},
                                                  {"question_id": "q2", "category": "out_of_scope"},
                                                  {"question_id": "p1", "category": "straightforward"}]))
    return tmp_path


def run_args(files, label="baseline"):
    return ["run", "--label", label, "--testset", str(files / "ts.json"), "--agent", "tina-compliance", "--pool", str(files / "pool.json")]


def test_run_records_agent_level_questions_and_prints_a_category_table(files):
    es = FakeES()
    code, out = out_of(run_args(files), SimpleNamespace(ab=FakeAB(GOOD), es=es), {"ARA_AB_CONNECTOR_ID": "conn"}, files)
    assert code == 0
    index, docs = es.indexed[0]
    assert index == "cortex-eval-runs" and [d["question_id"] for d in docs] == ["q1", "q2"]
    d = docs[0]
    assert d["run_label"] == "baseline" and d["run_id"].startswith("baseline-20261110T120000-abc") and d["provided"] is False
    assert d["connector_id"] == "conn" and d["route_correct"] is True and d["llm_calls"] == 2 and d["cached_input_tokens"] == 400
    assert d["testset_version"] == "learner-1" and d["category"] == "straightforward" and d["judge"]["faithfulness"] is None
    assert d["conversation_id"] == "c-ok" and d["run_at"] == "2026-11-10T12:00:00Z"
    assert re.search(r"out_of_scope\s+1\s+1\s+1\.00", out) and "policy-retrieval" in out
    assert (files / "home" / "runs-baseline.jsonl").read_text().count("\n") == 2


def test_run_outage_is_no_grade_and_a_wrong_route_is_just_wrong(files):
    bad = dict(GOOD, **{"close it": A.ABError("503", 503)})
    es = FakeES()
    code, out = out_of(run_args(files), SimpleNamespace(ab=FakeAB(bad), es=es), {"ARA_AB_CONNECTOR_ID": "c"}, files)
    assert code == C.EXIT_NO_GRADE and "not graded" in out and [d["question_id"] for d in es.indexed[0][1]] == ["q1"]
    wrong = dict(GOOD, **{"close it": resp(("cortex.policy_search", {}))})
    code, _ = out_of(run_args(files, "w"), SimpleNamespace(ab=FakeAB(wrong), es=FakeES()), {"ARA_AB_CONNECTOR_ID": "c"}, files)
    assert code == 0


def test_run_refusal_is_bad_input_and_env_is_checked(files):
    code, out = out_of(run_args(files), SimpleNamespace(ab=FakeAB(dict(GOOD, **{"dep 476": ValueError("HTTP 400 no agent")})), es=FakeES()),
                       {"ARA_AB_CONNECTOR_ID": "c"}, files)
    assert code == C.EXIT_BAD_INPUT and "refused" in out
    code, out = out_of(run_args(files), SimpleNamespace(ab=FakeAB(GOOD), es=FakeES()), {}, files)
    assert code == C.EXIT_BAD_INPUT and "ARA_AB_CONNECTOR_ID" in out


def test_run_store_failure_and_missing_files(files):
    code, out = out_of(run_args(files), SimpleNamespace(ab=FakeAB(GOOD), es=FakeES(fail=True)), {"ARA_AB_CONNECTOR_ID": "c"}, files)
    assert code == C.EXIT_STORE and "not stored" in out
    code, out = out_of(["run", "--label", "x", "--testset", str(files / "none.json"), "--agent", "t"], SimpleNamespace(), {}, files)
    assert code == C.EXIT_BAD_INPUT and "test set" in out


def test_run_key_overrides_the_learners_category(files):
    (files / "key.json").write_text(json.dumps({"q1": "ambiguous", "q2": "out_of_scope"}))
    es = FakeES()
    out_of(run_args(files) + ["--key", str(files / "key.json")], SimpleNamespace(ab=FakeAB(GOOD), es=es), {"ARA_AB_CONNECTOR_ID": "c"}, files)
    assert [d["category"] for d in es.indexed[0][1]] == ["ambiguous", "out_of_scope"]


# ── rank-eval ─────────────────────────────────────────────────────────────────

def bundle(ndcg_normalize=True):
    reqs = [{"id": "p1", "template_id": "cortex-policy-retrieval", "params": {"query_string": "pep?"},
             "ratings": [{"_index": "cortex-policies", "_id": "policy-001-s1", "rating": 1}]},
            {"id": "p2", "template_id": "cortex-policy-retrieval", "params": {"query_string": "sar?"},
             "ratings": [{"_index": "cortex-policies", "_id": "policy-002-s2", "rating": 1}, {"_index": "cortex-policies", "_id": "policy-002-s3", "rating": 1}]}]
    return {"requests": reqs, "metrics": [{"precision": {"k": 5, "relevant_rating_threshold": 1, "ignore_unlabeled": False}},
                                          {"recall": {"k": 5, "relevant_rating_threshold": 1}},
                                          {"dcg": {"k": 5, "normalize": ndcg_normalize}}]}


HITS = {"pep?": ["policy-001-s1", "x1", "x2", "x3", "x4"], "sar?": ["x1", "policy-002-s2", "x2", "x3", "x4"]}


@pytest.fixture
def home(files):
    h = files / "home"
    h.mkdir()
    (h / "rank-eval.json").write_text(json.dumps(bundle()))
    (h / "testset.json").write_text(json.dumps({"testset_version": "learner-1", "questions": [
        {"question_id": "p1", "category": "straightforward"}, {"question_id": "p2", "category": "time_window_edge"}]}))
    return h


def test_rank_eval_one_call_per_metric_cross_check_and_category_records(home, files):
    es = FakeES(hits=HITS)
    code, out = out_of(["rank-eval", "--label", "baseline"], SimpleNamespace(es=es), {}, files)
    assert code == 0 and len(es.rank_calls) == 3
    assert sorted(next(iter(b["metric"])) for _, b in es.rank_calls) == ["dcg", "precision", "recall"]
    assert all(i == "cortex-policies" and b["templates"] == [{"id": "cortex-policy-retrieval", "template": {"id": "cortex-policy-retrieval"}}]
               for i, b in es.rank_calls)
    docs = {d["category"]: d for d in es.indexed[0][1]}
    assert set(docs) == {"straightforward", "time_window_edge"}  # categories with no policy question are not written as zero
    assert docs["straightforward"]["retrieval"]["precision_at_5"] == pytest.approx(0.2)
    assert docs["straightforward"]["retrieval"]["recall_at_5"] == 1.0 and docs["time_window_edge"]["retrieval"]["recall_at_5"] == 0.5
    assert "ok" in out and "MISMATCH" not in out and re.search(r"cross_domain\s+0\s+-", out)


def test_rank_eval_cross_check_mismatch_stores_nothing(home, files):
    es = FakeES(hits=HITS, scale=0.9)
    code, out = out_of(["rank-eval", "--label", "baseline"], SimpleNamespace(es=es), {}, files)
    assert code == C.EXIT_CHECK_FAILED and "MISMATCH" in out and es.indexed == []


def test_rank_eval_failures_missing_metric_and_outage(home, files):
    es = FakeES(hits=HITS)
    orig = es.rank_eval
    es.rank_eval = lambda i, b: dict(orig(i, b), failures={"p2": {"error": "boom"}})
    code, out = out_of(["rank-eval", "--label", "b"], SimpleNamespace(es=es), {}, files)
    assert code == C.EXIT_CHECK_FAILED and "p2" in out and es.indexed == []
    (home / "rank-eval.json").write_text(json.dumps(dict(bundle(), metrics=[{"precision": {"k": 5}}])))
    code, out = out_of(["rank-eval", "--label", "b"], SimpleNamespace(es=FakeES(hits=HITS)), {}, files)
    assert code == C.EXIT_BAD_INPUT and "missing metric blocks" in out
    (home / "rank-eval.json").write_text(json.dumps(bundle()))
    boom = FakeES(hits=HITS)
    boom.rank_eval = lambda i, b: (_ for _ in ()).throw(A.ABError("429", 429))
    code, out = out_of(["rank-eval", "--label", "b"], SimpleNamespace(es=boom), {}, files)
    assert code == C.EXIT_NO_GRADE and "Nothing was graded" in out


def test_rank_eval_without_normalize_is_caught_by_the_cross_check(home, files):
    (home / "rank-eval.json").write_text(json.dumps(bundle(ndcg_normalize=False)))
    es = FakeES(hits=HITS)
    real = es.rank_eval

    def raw_dcg(i, b):  # a real cluster returns the un-normalised DCG here
        r = real(i, b)
        if "dcg" in b["metric"] and not b["metric"]["dcg"].get("normalize"):
            r["metric_score"] = r["metric_score"] * 2.5
        return r
    es.rank_eval = raw_dcg
    code, out = out_of(["rank-eval", "--label", "b"], SimpleNamespace(es=es), {}, files)
    assert code == C.EXIT_CHECK_FAILED and "dcg_at_5" in out


# ── judge ─────────────────────────────────────────────────────────────────────

GOOD_ESQL = f"""FROM cortex-eval-samples
| EVAL p = CONCAT("Q: ", question)
| COMPLETION faithfulness = p WITH {{ "inference_id": "{JID}" }}
| COMPLETION answer_relevance = p WITH {{ "inference_id": "{JID}" }}
| COMPLETION context_precision = p WITH {{ "inference_id": "{JID}" }}
| KEEP sample_id, faithfulness, answer_relevance, context_precision"""
COLS = [{"name": n} for n in ("sample_id", "faithfulness", "answer_relevance", "context_precision")]


def judge_env(files, esql=GOOD_ESQL):
    (files / "home").mkdir(exist_ok=True)
    (files / "home" / "judge.esql").write_text(esql)
    return {"ARA_JUDGE_INFERENCE_ID": JID}


def test_judge_parses_snaps_reports_off_scale_and_keeps_raw(files):
    env = judge_env(files)
    es = FakeES(esql={"columns": COLS, "values": [
        ["s-103", "0.0 - the answer swaps two figures", "1", "1.0"],
        ["s-101", "1", "0.8 - mostly", "The 68% threshold is stated, so 1"]]})
    code, out = out_of(["judge", "--label", "diagnose"], SimpleNamespace(es=es), env, files)
    assert code == 0 and es.esql_calls == [GOOD_ESQL]
    docs = {d["sample_id"]: d for d in es.indexed[0][1]}
    assert docs["s-103"]["judge"]["faithfulness"] == 0.0 and docs["s-103"]["judge"]["raw"]["faithfulness"].startswith("0.0 - the answer")
    assert docs["s-101"]["judge"]["answer_relevance"] == 1.0  # 0.8 snaps to 1
    assert docs["s-101"]["judge"]["context_precision"] == 1.0
    assert docs["s-103"]["question_id"] is None and docs["s-103"]["conversation_id"] is None and docs["s-103"]["judge_inference_id"] == JID
    assert "2 of 6 outputs were off the scale" in out and "ask for the score first" in out


def test_judge_missing_number_exits_1_and_stores_null_not_zero(files):
    env = judge_env(files)
    es = FakeES(esql={"columns": COLS, "values": [["s-1", "no idea", "1", "1"]]})
    code, out = out_of(["judge", "--label", "d"], SimpleNamespace(es=es), env, files)
    assert code == C.EXIT_CHECK_FAILED and es.indexed[0][1][0]["judge"]["faithfulness"] is None and "1 had no number" in out


def test_judge_contract_is_checked_before_any_call(files):
    env = judge_env(files, "FROM cortex-policies\n| COMPLETION a = x WITH { \"inference_id\": \"other\" }")
    es = FakeES(esql={"columns": COLS, "values": []})
    code, out = out_of(["judge", "--label", "d"], SimpleNamespace(es=es), env, files)
    assert code == C.EXIT_BAD_INPUT and es.esql_calls == [] and "first command" in out and "ARA_JUDGE_INFERENCE_ID" in out
    assert JID not in out


def test_judge_bad_columns_refusal_outage_and_env(files):
    env = judge_env(files)
    code, out = out_of(["judge", "--label", "d"], SimpleNamespace(es=FakeES(esql={"columns": [{"name": "sample_id"}], "values": []})), env, files)
    assert code == C.EXIT_BAD_INPUT and "missing: faithfulness" in out
    code, out = out_of(["judge", "--label", "d"], SimpleNamespace(es=FakeES(esql=ValueError("the judge query refused (HTTP 400): bad"))), env, files)
    assert code == C.EXIT_BAD_INPUT and "HTTP 400" in out
    code, out = out_of(["judge", "--label", "d"], SimpleNamespace(es=FakeES(esql=A.ABError("503", 503))), env, files)
    assert code == C.EXIT_NO_GRADE
    code, out = out_of(["judge", "--label", "d"], SimpleNamespace(es=FakeES()), {"ARA_EVAL_HOME": str(files / "home")}, files)
    assert code == C.EXIT_BAD_INPUT and "ARA_JUDGE_INFERENCE_ID" in out


def test_usage_errors_and_no_model_id_in_source():
    assert C.main([], clients=SimpleNamespace(), environ={}, out=io.StringIO()) == C.EXIT_BAD_INPUT
    assert C.main(["run"], clients=SimpleNamespace(), environ={}, out=io.StringIO()) == C.EXIT_BAD_INPUT
    for name in ("ara_eval_cli.py", "ara-eval.py"):
        src = (LIB / name).read_text().lower()
        assert not re.search(r"gpt-\d|openai|claude|sonnet|gemini|\.[a-z0-9-]+-completion", src), name


def test_live_entry_point_loads():
    spec = importlib.util.spec_from_file_location("ara_eval_entry", LIB / "ara-eval.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert callable(mod.make_clients) and callable(mod.EvalES)


# ── compare ───────────────────────────────────────────────────────────────────

def _runs(label, run_id, correct, tokens=(1000, 400, 50), calls=2, at="2026-11-10T10:00:00Z"):
    cats = ["straightforward", "ambiguous", "ambiguous", "out_of_scope"]
    return [{"run_id": run_id, "run_label": label, "run_at": at, "question_id": f"q{i}", "category": c,
             "expected_route": [{"tool_id": "t"}], "observed_route": [], "route_correct": ok, "tool_call_count": calls,
             "input_tokens": tokens[0], "cached_input_tokens": tokens[1], "output_tokens": tokens[2], "latency_ms": 1000 + i}
            for i, (c, ok) in enumerate(zip(cats, correct))]


class RunsES(FakeES):
    def __init__(self, by_label):
        super().__init__()
        self.by_label = by_label

    def search_runs(self, label):
        return self.by_label.get(label, [])


CARD = {"price_fresh_input": 2.0, "price_cached_input": 0.2, "price_output": 8.0, "monthly_questions": 100000}


def test_compare_prints_category_change_tokens_and_a_priced_bill(tmp_path):
    (tmp_path / "card.json").write_text(json.dumps(CARD))
    es = RunsES({"before": _runs("before", "r1", [1, 0, 1, 1]), "after": _runs("after", "r2", [1, 1, 1, 1], calls=3)})
    code, out = out_of(["compare", "before", "after", "--card", str(tmp_path / "card.json")], SimpleNamespace(es=es), {}, tmp_path)
    assert code == 0
    assert "ambiguous" in out and "50.00" in out and "100.00" in out          # 1 of 2 -> 2 of 2
    assert "tool calls per question" in out and "50.0" in out                    # 2 -> 3 calls
    assert "cost per month at 100,000 questions" in out
    # (600 fresh * 2 + 400 cached * 0.2 + 50 * 8) / 1e6 = 0.00168 per question
    assert "1.68" in out                                                          # per 1,000 questions
    assert "not gated" in out


def test_compare_reads_the_check_label_when_the_plain_one_is_empty_and_the_latest_run(tmp_path):
    (tmp_path / "card.json").write_text(json.dumps(CARD))
    es = RunsES({"before-check": _runs("before-check", "r1", [1, 1, 1, 1]) + _runs("before-check", "r0", [0, 0, 0, 0], at="2026-11-10T09:00:00Z"),
                 "after-check": _runs("after-check", "r2", [1, 1, 1, 0])})
    code, out = out_of(["compare", "before", "after", "--card", str(tmp_path / "card.json")], SimpleNamespace(es=es), {}, tmp_path)
    assert code == 0 and "before-check" in out and "after-check" in out
    assert "100.0" in out and "75.0" in out                                       # the later run, not the 0 percent one


def test_compare_with_no_records_or_a_bad_card_is_bad_input(tmp_path):
    (tmp_path / "card.json").write_text(json.dumps(CARD))
    code, out = out_of(["compare", "before", "after", "--card", str(tmp_path / "card.json")], SimpleNamespace(es=RunsES({})), {}, tmp_path)
    assert code == 2 and "before" in out
    (tmp_path / "bad.json").write_text(json.dumps({"price_output": 8}))
    code, out = out_of(["compare", "before", "after", "--card", str(tmp_path / "bad.json")], SimpleNamespace(es=RunsES({})), {}, tmp_path)
    assert code == 2 and "price_fresh_input" in out


# ── reset ─────────────────────────────────────────────────────────────────────

import copy  # noqa: E402

import ara_integrity as I  # noqa: E402


def _world():
    return {
        "agent/tina": {"id": "tina", "instructions": "Never show a TIN.", "tool_ids": ["t1", "t2"], "skill_ids": ["s1"],
                       "updated_at": "2026-11-01"},
        "tool/t1": {"id": "t1", "description": "Search cases.", "configuration": {"workflow_id": "w1"}},
        "tool/t2": {"id": "t2", "description": "Read a page."},
        "skill/s1": {"id": "s1", "content": "Triage steps.", "tool_ids": []},
        "workflow/w1": {"id": "w1", "yaml": "name: w1\n"},
    }


class FakeReach:
    def __init__(self, world, fail=None, refuse=None):
        self.w, self.fail, self.refuse, self.writes, self.reads = world, fail, refuse, [], 0

    def _get(self, key):
        self.reads += 1
        if self.fail == "read":
            raise A.ABError("503", 503)
        return copy.deepcopy(self.w.get(key))

    get_agent = lambda self, i: self._get(f"agent/{i}")
    get_tool = lambda self, i: self._get(f"tool/{i}")
    get_skill = lambda self, i: self._get(f"skill/{i}")
    get_workflow = lambda self, i: self._get(f"workflow/{i}")
    connectors = lambda self: []
    plugins = lambda self: [v for k, v in self.w.items() if k.startswith("plugin/")]

    def apply(self, kind, oid, body):
        if self.fail == "write":
            raise A.ABError("429", 429)
        if self.refuse:
            raise ValueError("tool t1 refused (HTTP 400): bad body")
        self.writes.append(f"{kind}/{oid}")
        self.w[f"{kind}/{oid}"] = dict(body, id=oid)

    def remove(self, kind, oid):
        self.writes.append(f"-{kind}/{oid}")
        self.w.pop(f"{kind}/{oid}", None)


def _start(tmp_path):
    path = tmp_path / "start-state.json"
    I.write_start_state(path, FakeReach(_world()), ["tina"])
    return path


def _reset(tmp_path, reach, *extra):
    path = _start(tmp_path)
    buf = io.StringIO()
    code = C.main(["reset", "--from", str(path), *extra], clients=SimpleNamespace(reach=reach), environ={}, out=buf,
                  sleep=lambda s: None)
    return code, buf.getvalue()


def test_start_state_file_format_and_no_secrets(tmp_path):
    w = _world()
    w["plugin/p1"] = {"id": "p1", "secrets": {"k": "hunter2"}, "updated_at": "x"}
    path = tmp_path / "s.json"
    doc = I.write_start_state(path, FakeReach(w), ["tina"])
    on_disk = json.loads(path.read_text())
    assert on_disk == json.loads(json.dumps(doc))
    assert set(on_disk) == {"version", "agent_ids", "connector_ids", "strip_fields", "objects", "fingerprints"}
    assert "agent/tina" in on_disk["objects"] and "updated_at" not in on_disk["objects"]["agent/tina"]
    assert "hunter2" not in path.read_text()
    with pytest.raises(ValueError):
        I.write_start_state(tmp_path / "x.json", FakeReach({}), ["tina"])


def test_reset_nothing_changed(tmp_path):
    r = FakeReach(_world())
    code, out = _reset(tmp_path, r)
    assert code == 0 and "Nothing to reset" in out and r.writes == []


@pytest.mark.parametrize("key,field,path", [
    ("tool/t2", "description", "/description"),
    ("skill/s1", "content", "/content"),
    ("agent/tina", "instructions", "/instructions"),
])
def test_reset_restores_one_edited_object_by_field_name_only(tmp_path, key, field, path):
    w = _world()
    w[key][field] = "SECRET-LOOKING NEW TEXT"
    r = FakeReach(w)
    code, out = _reset(tmp_path, r)
    assert code == 0 and r.writes == [key] and f"{key}: restored fields {path}" in out
    assert "SECRET-LOOKING" not in out
    assert r.w[key][field] == _world()[key][field]


def test_reset_recreates_a_deleted_object_and_is_idempotent(tmp_path):
    w = _world()
    del w["tool/t2"]
    r = FakeReach(w)
    code, out = _reset(tmp_path, r)
    assert code == 0 and r.writes == ["tool/t2"] and "tool/t2: was missing, recreated" in out
    r.writes.clear()
    buf = io.StringIO()
    code = C.main(["reset", "--from", str(tmp_path / "start-state.json")], clients=SimpleNamespace(reach=r), environ={},
                  out=buf, sleep=lambda s: None)
    assert code == 0 and r.writes == [] and "Nothing to reset" in buf.getvalue()


def test_reset_reports_an_extra_object_and_leaves_it(tmp_path):
    w = _world()
    w["plugin/p9"] = {"id": "p9", "name": "stray"}
    r = FakeReach(w)
    code, out = _reset(tmp_path, r)
    assert code == 0 and r.writes == [] and "left alone: plugin/p9" in out and "--remove-extra" in out
    assert "plugin/p9" in r.w


def test_reset_remove_extra_deletes_it(tmp_path):
    w = _world()
    w["plugin/p9"] = {"id": "p9", "name": "stray"}
    r = FakeReach(w)
    code, out = _reset(tmp_path, r, "--remove-extra")
    assert code == 0 and r.writes == ["-plugin/p9"] and "plugin/p9: not in the start state, removed" in out


def test_reset_outage_retries_twice_then_no_grade_and_reports_nothing_done(tmp_path):
    w = _world()
    w["tool/t2"]["description"] = "edited"
    r = FakeReach(w, fail="write")
    code, out = _reset(tmp_path, r)
    assert code == C.EXIT_NO_GRADE == 3 and "Restored" not in out and "Nothing to reset" not in out
    r2 = FakeReach(_world(), fail="read")
    code, out = _reset(tmp_path, r2)
    assert code == 3 and "again" in out


def test_reset_a_refused_write_is_bad_input_with_the_reason(tmp_path):
    w = _world()
    w["tool/t1"]["description"] = "edited"
    code, out = _reset(tmp_path, FakeReach(w, refuse=True))
    assert code == C.EXIT_BAD_INPUT and "HTTP 400" in out and "bad body" in out


def test_reset_bad_start_copy_is_bad_input(tmp_path):
    buf = io.StringIO()
    p = tmp_path / "bad.json"
    p.write_text("{}")
    code = C.main(["reset", "--from", str(p)], clients=SimpleNamespace(reach=FakeReach({})), environ={}, out=buf)
    assert code == C.EXIT_BAD_INPUT and "expected format" in buf.getvalue()
    code = C.main(["reset", "--from", str(tmp_path / "none.json")], clients=SimpleNamespace(reach=FakeReach({})), environ={}, out=buf)
    assert code == C.EXIT_BAD_INPUT


def test_reach_writes_only_the_fields_an_endpoint_accepts():
    import importlib.util
    spec = importlib.util.spec_from_file_location("ara_eval_exe", LIB / "ara-eval.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    tool = {"id": "t", "type": "esql", "description": "d", "tags": [], "configuration": {}, "experimental": True, "readonly": False}
    assert mod.Reach.writable("tool", tool) == {"type": "esql", "description": "d", "tags": [], "configuration": {}}
    assert "experimental" not in mod.Reach.writable("skill", {"name": "n", "content": "c", "experimental": 1, "id": "s"})
