"""
test_ara_grade.py - unit tests for the shared grader (lib/ara_grade.py).

Run with: python -m pytest lib/test_ara_grade.py -v
or:        python lib/test_ara_grade.py

Exit paths run in a child process with a stub fail-message on PATH, so each test sees exactly
what Check (fail-message) and Defend feedback (stdout) would show, and whether a grade was written.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import textwrap

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import ara_grade as G  # noqa: E402

PRELUDE = """
import sys, pathlib
sys.path.insert(0, {lib!r})
import ara_grade as G
G.GRADES_DIR = pathlib.Path({tmp!r}) / "grades"
G.RESULTS_DIR = pathlib.Path({tmp!r}) / "results"
G.REMOTE_BACKOFF_S = (0.01, 0.01)
"""


def run(body: str, feedback: bool = False, timeout: int = 20):
    """Run body after the prelude. Returns (rc, stdout, fail-message text, grades written)."""
    with tempfile.TemporaryDirectory() as tmp:
        bindir = pathlib.Path(tmp) / "bin"
        bindir.mkdir()
        log = pathlib.Path(tmp) / "fail-message.log"
        stub = bindir / "fail-message"
        stub.write_text(f'#!/bin/sh\nprintf "%s\\n" "$1" >> {log}\n')
        stub.chmod(0o755)
        env = dict(os.environ, PATH=f"{bindir}:{os.environ.get('PATH', '')}")
        env.pop("ARA_DEFEND_FEEDBACK", None)
        if feedback:
            env["ARA_DEFEND_FEEDBACK"] = "1"
        src = PRELUDE.format(lib=str(HERE), tmp=tmp) + textwrap.dedent(body)
        p = subprocess.run([sys.executable, "-c", src], capture_output=True, text=True,
                           env=env, timeout=timeout)
        shown = log.read_text().strip() if log.exists() else ""
        grades = sorted(x.name for x in (pathlib.Path(tmp) / "grades").glob("*.json"))
        return p.returncode, p.stdout.strip(), shown, grades


# ── fail paths ────────────────────────────────────────────────────────────────

def test_fail_check_mode_shows_message():
    rc, out, shown, grades = run('G.fail("Build 2 was skipped.")')
    assert rc == 1 and shown == "Build 2 was skipped." and out == "" and grades == []


def test_fail_silent_in_feedback():
    rc, out, shown, _ = run('G.fail("Build 2 was skipped.")', feedback=True)
    assert rc == 1 and out == "" and shown == ""


def test_env_fail_same_as_fail():
    assert run('G.env_fail("x.")')[2] == "x."
    assert run('G.env_fail("x.")', feedback=True)[1] == ""


def test_answer_fail_prints_in_both_modes():
    assert run('G.answer_fail("Q1 does not match.")')[2] == "Q1 does not match."
    rc, out, shown, _ = run('G.answer_fail("Q1 does not match.")', feedback=True)
    assert rc == 1 and out == "Q1 does not match." and shown == ""


def test_verdict_fail_writes_grade_and_shows_first_failure():
    rc, out, shown, grades = run("""
        g = G.Grade("04-defend")
        g.criterion("a", True, "A ok")
        g.criterion("b", False, "B wrong")
        g.criterion("c", False, "C wrong")
        g.verdict()
    """)
    assert rc == 1 and shown == "B wrong" and grades == ["04-defend.json"]


def test_verdict_in_feedback_prints_and_writes_nothing():
    rc, out, shown, grades = run("""
        g = G.Grade("04-defend")
        g.criterion("b", False, "B wrong")
        g.verdict()
    """, feedback=True)
    assert rc == 1 and out == "B wrong" and shown == "" and grades == []


def test_verdict_pass_and_tier_pass():
    rc, out, shown, grades = run("""
        g = G.Grade("ok"); g.criterion("a", True, "fine"); g.verdict()
        """)
    assert rc == 0 and shown == "" and grades == ["ok.json"]
    rc, out, shown, grades = run("""
        import json
        g = G.Grade("cap"); g.criterion("q2", False, "Q2 off"); g.verdict(passed=True)
        print(json.loads((G.GRADES_DIR / "cap.json").read_text())["passed"])
        """)
    assert rc == 0 and shown == "" and out == "True"


def test_guidance_appended_from_second_showing():
    body = """
        g = G.Grade("d", tries=str(G.GRADES_DIR.parent / "private" / "tries.json"))
        g.criterion("q1", False, "Q1 off.", guide="Take the first row.")
        g.verdict()
    """
    with tempfile.TemporaryDirectory() as tmp:
        tries = pathlib.Path(tmp) / "tries.json"
        two = body.replace('str(G.GRADES_DIR.parent / "private" / "tries.json")', repr(str(tries)))
        assert run(two)[2] == "Q1 off."
        assert run(two)[2] == "Q1 off. Take the first row."
        assert json.loads(tries.read_text()) == {"q1": 2}


# ── outages and the deadline ──────────────────────────────────────────────────

def test_remote_retries_then_unreachable_without_grade():
    rc, out, shown, grades = run("""
        n = {"calls": 0}
        def down():
            n["calls"] += 1
            raise ConnectionError("refused")
        try:
            G.remote(down, what="Elasticsearch")
        finally:
            print(n["calls"])
    """)
    assert rc == 1 and out == "3" and grades == []
    assert shown == "Elasticsearch did not respond. Wait a moment and select Check again."


def test_remote_outage_silent_in_feedback():
    rc, out, shown, _ = run("""
        def down(): raise ConnectionError("refused")
        G.remote(down)
    """, feedback=True)
    assert rc == 1 and out == "" and shown == ""


def test_remote_call_uses_whole_message_and_hides_detail():
    rc, out, shown, _ = run("""
        class E(Exception):
            status_code = 503
        def down(): raise E("upstream 503 for held-out question X")
        G.remote_call(down, _message=G.LLM_UNREACHABLE)
    """)
    assert rc == 1 and shown == G.LLM_UNREACHABLE


def test_remote_reraises_learner_error_and_returns_value():
    rc, out, shown, _ = run("""
        class E(Exception):
            status_code = 400
        print(G.remote(lambda x: x + 1, 1))
        try:
            G.remote(lambda: (_ for _ in ()).throw(E("bad request")))
        except E:
            print("raised")
    """)
    assert rc == 0 and out.splitlines() == ["2", "raised"] and shown == ""


def test_remote_budgets_against_deadline():
    rc, out, shown, _ = run("""
        import time
        G.REMOTE_BACKOFF_S = (30.0, 30.0)
        G.deadline(20)
        t = time.monotonic()
        def down(): raise ConnectionError("x")
        try:
            G.remote(down)
        finally:
            print(round(time.monotonic() - t))
    """)
    # 30 s of backoff + 5 s margin would pass the 20 s deadline: no wait, the outage message now.
    assert rc == 1 and int(out) < 3 and "did not respond" in shown


def test_unreachable_forms():
    assert run('G.unreachable("The reranker")')[2] == G.RERANKER_UNREACHABLE
    assert run('G.unreachable(G.ES_UNREACHABLE, "ConnectTimeout after 3 attempts")')[2] == G.ES_UNREACHABLE


def test_deadline_check_mode_and_feedback():
    rc, out, shown, grades = run("""
        import time
        G.deadline(1)
        time.sleep(5)
    """)
    assert rc == 1 and grades == []
    assert shown == G.DEADLINE_MESSAGE.replace("{seconds}", "1")
    rc, out, shown, _ = run("""
        import time
        G.deadline(1, message="Custom wait. Select Check again.")
        time.sleep(5)
    """, feedback=True)
    assert rc == 1 and out == "" and shown == ""


def test_excepthook_outage_message():
    rc, out, shown, grades = run('raise ConnectionError("no route")')
    assert rc == 1 and shown == G.ES_UNREACHABLE and grades == []
    rc, out, shown, _ = run('raise ConnectionError("no route")', feedback=True)
    assert out == "" and shown == ""
    rc, out, shown, _ = run('raise KeyError("learner bug")')
    assert rc == 1 and shown == ""


def test_is_outage_and_outage_text():
    class S(Exception):
        def __init__(self, code):
            self.status_code = code
    assert G.is_outage(S(503)) and G.is_outage(S(429)) and G.is_outage(S(401))
    assert not G.is_outage(S(400)) and not G.is_outage(S(404))
    assert G.is_outage(ConnectionError()) and G.is_outage(TimeoutError())
    assert not G.is_outage(FileNotFoundError()) and not G.is_outage(ValueError())
    assert G.outage_text("error: APIConnectionError(...)")
    assert G.outage_text("BadRequestError: Error code: 503 - x")
    assert not G.outage_text("BadRequestError: Error code: 400 - x")
    assert not G.outage_text("KeyError: 'answer'")


# ── scrub (A23) ───────────────────────────────────────────────────────────────

def test_scrub_forms_and_longest_first():
    q = "What is the CTR threshold for cash?"
    assert G.scrub(f"failed on {q}", [q]) == f"failed on {G.HELDOUT_PLACEHOLDER}"
    assert G.scrub(f"KeyError({q!r})", [q], "<question>") == "KeyError('<question>')"
    assert G.scrub('{"q": "it\\"s"}', ['it"s'], "<q>") == '{"q": "<q>"}'
    assert G.scrub("abc abcdef", ["abc", "abcdef"], "X") == "X X"
    assert G.scrub(None, ["x"]) == ""


def test_register_heldout_scrubs_every_message():
    rc, out, shown, _ = run("""
        G.register_heldout(["dec-0042 Emberline Marine", "ab"], "<decision>")
        G.fail("Your validator raised on dec-0042 Emberline Marine; ab stays.")
    """)
    assert shown == "Your validator raised on <decision>; ab stays."
    assert G.heldout_strings([{"q": "a", "ids": ["b", 3]}, "x"], ["q", "ids"]) == ["a", "b"]


# ── files and helpers ─────────────────────────────────────────────────────────

def test_results_for_defend_replaces_symlink_and_skips_feedback():
    with tempfile.TemporaryDirectory() as tmp:
        target = pathlib.Path(tmp) / "victim"
        target.write_text("keep")
        link = pathlib.Path(tmp) / "r.json"
        link.symlink_to(target)
        G.Grade("x").results_for_defend(str(link), {"n": 1})
        assert target.read_text() == "keep" and not link.is_symlink()
        assert json.loads(link.read_text())["metrics"] == {"n": 1}
        assert (link.stat().st_mode & 0o777) == 0o644
    rc, out, shown, _ = run("""
        p = G.RESULTS_DIR / "r.json"
        G.Grade("x").results_for_defend(str(p), {"n": 1})
        print(p.exists())
    """, feedback=True)
    assert out == "False"


def test_read_learner_text_rejects_symlink():
    with tempfile.TemporaryDirectory() as tmp:
        real = pathlib.Path(tmp) / "real.json"
        real.write_text("{}")
        (pathlib.Path(tmp) / "l.json").symlink_to(real)
        rc, out, shown, _ = run(f"""
            print(G.read_learner_text({str(real)!r}))
            print(G.read_learner_text({str(pathlib.Path(tmp) / 'none.json')!r}))
            G.read_learner_text({str(pathlib.Path(tmp) / 'l.json')!r})
        """)
        assert out.splitlines() == ["{}", "None"] and rc == 1 and "symbolic link" in shown


def test_learner_json_and_decision_answers():
    with tempfile.TemporaryDirectory() as tmp:
        good = pathlib.Path(tmp) / "decision.json"
        good.write_text(json.dumps({"answers": [{"question_id": "q1", "choice": "a", "reason": "r"}]}))
        assert G.decision_answers(str(good)) == {"q1": {"question_id": "q1", "choice": "a", "reason": "r"}}
        bad = pathlib.Path(tmp) / "bad.json"
        bad.write_text(json.dumps({"answers": [{"question_id": 1}]}))
        rc, out, shown, _ = run(f'G.decision_answers({str(bad)!r})')
        assert rc == 1 and shown.startswith("bad.json is not in the form this check reads")


def test_thresholds_missing():
    rc, out, shown, _ = run('G.THRESHOLDS = pathlib.Path("/nonexistent/t.json"); G.thresholds("build1")')
    assert rc == 1 and shown == G.MISSING_THRESHOLDS


def test_parse_llm_json():
    assert G.parse_llm_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert G.parse_llm_json(' {"a": 1}') == {"a": 1}
    assert G.parse_llm_json("[1, 2]") is None and G.parse_llm_json("nope") is None
    assert G.parse_llm_json(None) is None


def test_number_matching():
    assert G.contains_value("The threshold is $10,000.", "10000")
    assert G.contains_value("ten thousand dollars", "10000")
    assert G.contains_value("twenty-four hours", "24")
    assert not G.contains_value("1100", "100")
    assert G.contains_value(G.money_forms("about 12.5k"), "12500")
    assert G.normalise("one hundred and twenty") == "120"


def test_to_jsonable_and_fmt_num():
    class R:
        body = {"x": (1, 2)}
    assert G.to_jsonable(R()) == {"x": [1, 2]}
    assert [G.fmt_num(v) for v in (60000, 999, 1234.5, 12000.0, 0.83, -2048, True, "60000", None)] == \
        ["60,000", "999", "1,234.5", "12,000", "0.83", "-2,048", "True", "60000", "None"]


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  ok    {fn.__name__}")
        except Exception as exc:
            print(f"  FAIL  {fn.__name__}: {exc!r}")
            failed += 1
    print(f"\n{len(fns) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
