"""Offline tests for ara_judge.py (25 section 4: the judge contract and the gate's ROW substitution)."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import ara_judge as J  # noqa: E402

REF = pathlib.Path.home() / "ara-working/m5/calibration/judge/judge-reference.esql"  # local only; skipped elsewhere
INF = ".test-judge-completion"
GOOD = f'''FROM cortex-eval-samples
| EVAL p = CONCAT("Grade FAITHFULNESS | FROM other-index // not a comment", passages, answer)
| COMPLETION faithfulness = p WITH {{"inference_id": "{INF}"}}
| EVAL q = CONCAT("Grade RELEVANCE", question, answer)
| COMPLETION answer_relevance = q WITH {{"inference_id": "{INF}"}}
| EVAL r = CONCAT("Grade PRECISION", question, passages)
| COMPLETION context_precision = r WITH {{"inference_id": "{INF}"}}
| KEEP sample_id, faithfulness, answer_relevance, context_precision'''
REC = {"sample_id": "h-1", "question": 'Why "quoted" | piped?', "passage_ids": ["a-s1"], "passages": "[a-s1] text", "answer": "x"}


def test_first_command_ignores_pipes_in_strings_and_comments():
    q = 'FROM /* a | b */ cortex-eval-samples // | no\n| LIMIT 1'
    head, rest = J.split_first_command(q)
    assert head == "FROM cortex-eval-samples" and rest.startswith("| LIMIT 1")
    head, _ = J.split_first_command('FROM cortex-eval-samples | EVAL a = "x | y"')
    assert head == "FROM cortex-eval-samples"
    assert J.split_first_command('FROM x\n| EVAL a = """one | two"""')[1].startswith("| EVAL")


def test_substitute_replaces_only_the_first_command():
    esql, params = J.substitute(GOOD, REC)
    assert esql.startswith("ROW sample_id = ?sid, question = ?q, passage_ids = ?ids, passages = ?p, answer = ?a\n| EVAL p")
    assert "FROM cortex-eval-samples" not in esql.split("\n", 1)[0]
    assert "FROM other-index" in esql  # inside a string: untouched
    assert params == {"sid": "h-1", "q": REC["question"], "ids": ["a-s1"], "p": REC["passages"], "a": "x"}
    assert J.substitute("FROM cortex-eval-samples", REC)[0] == J.row_source(REC)[0]


def test_good_judge_meets_the_contract():
    assert J.contract_violations(GOOD, INF) == []


def test_reference_judge_meets_the_contract_with_its_own_endpoint():
    if not REF.exists():
        return
    text = REF.read_text()
    inf = text.split('"inference_id": "')[1].split('"')[0]
    assert J.contract_violations(text, inf) == []


def test_wrong_first_command_and_other_sources_fail():
    assert J.contract_violations(GOOD.replace("FROM cortex-eval-samples", "FROM cortex-cases"), INF)
    assert J.contract_violations(GOOD.replace("FROM cortex-eval-samples", "FROM cortex-eval-samples, cortex-cases"), INF)
    for extra in ("| LOOKUP JOIN cortex-policies ON sample_id", "| ENRICH pol ON sample_id", "| FROM cortex-cases"):
        assert J.contract_violations(GOOD.replace("| KEEP", extra + "\n| KEEP"), INF), extra
    assert J.contract_violations("ROW a = 1 | EVAL b = 2", INF)


def test_commented_out_source_is_not_a_violation():
    assert J.contract_violations(GOOD.replace("| KEEP", "// | FROM cortex-cases\n| KEEP"), INF) == []


def test_inference_id_must_match_on_every_completion():
    assert J.contract_violations(GOOD.replace(f'"{INF}"', '".other"', 1), INF)
    assert J.contract_violations(GOOD.replace('WITH {"inference_id": "%s"}' % INF, "", 1), INF)
    assert J.contract_violations("FROM cortex-eval-samples | KEEP sample_id", INF)
