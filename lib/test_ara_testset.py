import io, json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ara_testset as T


def home(tmp_path):
    (tmp_path / "question-log.json").write_text(json.dumps([{"pool_id": "q-1", "question": "A?"}, {"pool_id": "q-2", "question": "B?"}]))
    (tmp_path / "pool.json").write_text(json.dumps({"questions": [
        {"id": "q-1", "type": "policy", "input": "A?", "query_text": "A?", "relevant_ids": ["policy-001-s1"]},
        {"id": "q-2", "type": "agent", "input": "B?", "expected": []}]}))
    return {"ARA_EVAL_HOME": str(tmp_path)}


def run(env, *argv, es=None):
    out = io.StringIO()
    return T.main(list(argv), env, out, es), out.getvalue()


def test_add_show_remove_and_unknown_inputs(tmp_path):
    env = home(tmp_path)
    assert run(env, "add", "q-1", "straightforward", "q-2", "ambiguous")[0] == 0
    assert [q["category"] for q in T.read_set(tmp_path)] == ["straightforward", "ambiguous"]
    rc, text = run(env, "show")
    assert "1 policy-retrieval, 1 agent-level" in text
    assert run(env, "add", "q-9", "ambiguous")[0] == 2
    rc, text = run(env, "add", "q-1", "nope")
    assert rc == 2 and "not a category" in text
    run(env, "remove", "q-2")
    assert [q["question_id"] for q in T.read_set(tmp_path)] == ["q-1"]


def test_log_shows_kind_and_no_category(tmp_path):
    env = home(tmp_path)
    rc, text = run(env, "log")
    assert "q-1" in text and "policy" in text and "straightforward" not in text


def test_save_puts_the_set_under_learner_1(tmp_path):
    env = home(tmp_path)
    run(env, "add", "q-1", "straightforward")
    seen = {}
    class Es:
        def put_doc(self, index, doc_id, doc): seen.update(index=index, id=doc_id, doc=doc)
    assert run(env, "save", es=Es())[0] == 0
    assert seen["index"] == "cortex-eval-testsets" and seen["id"] == "learner-1" and seen["doc"]["questions"][0]["question_id"] == "q-1"


def test_rank_eval_builds_requests_for_policy_questions_and_the_named_metrics(tmp_path):
    env = home(tmp_path)
    run(env, "add", "q-1", "straightforward", "q-2", "ambiguous")
    rc, text = run(env, "rank-eval", "--metric", "precision:k=5", "--metric", "recall:k=5", "--metric", "dcg:k=5,normalize=true")
    assert rc == 0
    obj = json.loads((tmp_path / "rank-eval.json").read_text())
    assert [r["id"] for r in obj["requests"]] == ["q-1"] and obj["requests"][0]["template_id"] == "cortex-policy-retrieval"
    assert obj["requests"][0]["ratings"] == [{"_index": "cortex-policies", "_id": "policy-001-s1", "rating": 1}]
    assert obj["metrics"] == [{"precision": {"k": 5}}, {"recall": {"k": 5}}, {"dcg": {"k": 5, "normalize": True}}]
    assert run(env, "rank-eval")[0] == 2
    assert run(env, "rank-eval", "--metric", "mrr:k=5")[0] == 2
