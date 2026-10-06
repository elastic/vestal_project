"""
test_kit.py - unit tests for the alignment kit's authoring tools: align_lint.py, qa_record.py,
validate_heldout.py, and the shell pieces they compare against.

Run with: python -m pytest lib/kit/test_kit.py -v
or:        python lib/kit/test_kit.py
"""

from __future__ import annotations

import contextlib
import io
import json
import pathlib
import subprocess
import sys
import tempfile

KIT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(KIT))

import align_lint  # noqa: E402
import qa_record  # noqa: E402
import validate_heldout  # noqa: E402

PROBLEM_LINE = 'printf \'launcher: %s\\n\' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> /opt/ara/hotstart-probe.log'


def _kit(name: str) -> str:
    return (KIT / name).read_text()


def _front(slug: str, title: str, limit: int) -> str:
    return f"---\nslug: {slug}\ntype: challenge\ntitle: '{title}'\ntimelimit: {limit}\n---\nBody.\n"


def make_track(root: pathlib.Path, capstone: bool = False) -> pathlib.Path:
    """A minimal track that meets every kit rule, built from the kit pieces themselves."""
    name = "cert-sk-ara-9-c-test" if capstone else "cert-sk-ara-9-1-test"
    t = root / name
    head = _kit("provision-head.sh").replace("STEP_TOTAL=0;", "STEP_TOTAL=2;").replace("EXPECTED_MIN=0 ", "EXPECTED_MIN=20 ")
    verify = _kit("verify-assets.sh")
    launcher = _kit("launcher-brief.sh").replace("<m>/<track>", "m9/9-1-test")
    setup = ("#!/bin/bash\nset -euo pipefail\n" + launcher +
             "cat > /opt/ara/provision.sh << 'PROVISION_EOF'\n" + head + verify +
             'step "Building the start state"\n' + _kit("src-lock.sh") +
             "touch /opt/ara/.ready\nPROVISION_EOF\n")
    chs = [("01-brief-test", "Brief", 3600)] + (
        [("02-build-and-defend-test", "Build and defend", 3600)] if capstone else
        [("02-build-one", "Build 1", 1800), ("03-defend-test", "Defend", 600)])
    for i, (d, title, limit) in enumerate(chs):
        (t / d).mkdir(parents=True)
        (t / d / "assignment.md").write_text(_front(d[3:], title, limit))
        if i == 0:
            (t / d / "setup-elastic-serverless").write_text(setup)
            (t / d / "check-elastic-serverless").write_text(_kit("brief-check-elastic-serverless"))
            (t / d / "solve-elastic-serverless").write_text(_kit("brief-solve-elastic-serverless"))
        else:
            (t / d / "setup-elastic-serverless").write_text("#!/bin/bash\nset -euo pipefail\n\n" + _kit("wait-block.sh"))
    total = sum(x[2] for x in chs) + (3600 if capstone else 1800)
    tags = "- ara/capstone\n" if capstone else "- solution/cert\n"
    title = "Capstone 9.C: Test" if capstone else "Lab 9.1: Test the kit"
    (t / "track.yml").write_text(f"slug: {name}\ntitle: '{title}'\ndescription: A short description.\n"
                                 f"tags:\n{tags}timelimit: {total}\nskipping_enabled: {str(not capstone).lower()}\n")
    (t / "private").mkdir()
    (t / "private" / "questions.json").write_text(json.dumps(
        {"questions": [{"id": "q1", "text": "T", "shuffle": "seed", "choices": []}]}))
    cal = "\n\n".join(align_lint.CAL_SECTIONS)
    (t / "private" / "calibration.md").write_text(f"# 9.1 calibration record\n\n{cal}\n")
    rec = qa_record.migrate(t)
    for ph in sorted(set(__import__("re").findall(r"<[^<>\n]{1,60}>", rec))):
        rec = rec.replace(ph, "2026-10-06" if "YYYY" in ph else "x")
    rec = rec.replace("module: M9", "module: M3").replace("title: x", f"title: '{title}'")
    (t / "ara-qa-record.yml").write_text(rec)
    return t


def lint(track: pathlib.Path, only: str = "") -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = align_lint.main([str(track), "--only", only] if only else [str(track)])
    return rc, buf.getvalue()


def test_compliant_lab_and_capstone_pass():
    with tempfile.TemporaryDirectory() as tmp:
        for cap in (False, True):
            t = make_track(pathlib.Path(tmp), capstone=cap)
            rc, out = lint(t)
            assert rc == 0, out
            assert "info grader: none found" in out


def test_each_rule_catches_its_divergence():
    with tempfile.TemporaryDirectory() as tmp:
        t = make_track(pathlib.Path(tmp))
        ch01 = t / "01-brief-test"
        breaks = {
            "gate": (ch01 / "check-elastic-serverless", "about {s['expected_min']} in total", "about 10 in total"),
            "launcher": (ch01 / "setup-elastic-serverless", '"${ARA_BRIEF_SRC}/." /opt/ara/brief/', '"${ARA_BRIEF_SRC}/." /opt/ara/brief/ 2>/dev/null || true'),
            "provision": (ch01 / "setup-elastic-serverless", "STEP_TOTAL=2", "STEP_TOTAL=3"),
            "srclock": (ch01 / "setup-elastic-serverless", "if grep -rlsF /opt/ara/src /home/elastic/notebooks; then", "if false; then"),
            "wait": (t / "02-build-one" / "setup-elastic-serverless", "seq 1 648", "seq 1 540"),
            "questions": (t / "private" / "questions.json", '"shuffle": "seed", ', ""),
            "track": (t / "track.yml", "timelimit: 7800", "timelimit: 9000"),
            "records": (t / "private" / "calibration.md", "## Defend", "## Decide"),
        }
        for rule, (f, old, new) in breaks.items():
            text = f.read_text()
            assert old in text, (rule, old)
            f.write_text(text.replace(old, new))
            rc, out = lint(t, rule)
            assert rc == 1 and "FAIL" in out, (rule, out)
            f.write_text(text)
            assert lint(t, rule)[0] == 0, rule


def test_old_questions_schema_fails():
    with tempfile.TemporaryDirectory() as tmp:
        t = make_track(pathlib.Path(tmp))
        (t / "private" / "questions.json").write_text("[]")
        rc, out = lint(t, "questions")
        assert rc == 1 and "old schema" in out


def test_kit_gate_is_the_spec_text():
    check = _kit("brief-check-elastic-serverless")
    assert "about {s['expected_min']} in total" in check
    assert "Environment provisioning failed during:" in check
    solve = _kit("brief-solve-elastic-serverless")
    assert "seq 1 648" in solve and "54 minutes" in solve
    for name in ("brief-check-elastic-serverless", "brief-solve-elastic-serverless", "wait-block.sh",
                 "launcher-brief.sh", "provision-head.sh", "verify-assets.sh", "src-lock.sh", "install-grader.sh"):
        r = subprocess.run(["bash", "-n", str(KIT / name)], capture_output=True, text=True)
        assert r.returncode == 0, (name, r.stderr)


def test_qa_record_migrate_keeps_old_data_and_check_flags_placeholders():
    with tempfile.TemporaryDirectory() as tmp:
        t = pathlib.Path(tmp) / "cert-sk-ara-3-9-x"
        t.mkdir()
        old = ("track: cert-sk-ara-3-9-x  # a comment\nassets_tag: \"m3-v1.1\"\nnotes: |\n  line one\n\n  line two\n"
               "round_2026_10_05: green, abc on ara-p2-x\n")
        (t / "ara-qa-record.yml").write_text(old)
        new = qa_record.migrate(t)
        import yaml
        assert yaml.safe_load(new)["history"][qa_record.HISTORY_KEY] == yaml.safe_load(old)
        assert "# a comment" in new
        (t / "ara-qa-record.yml").write_text(new)
        fails = qa_record.check(t)
        assert any("placeholders left" in f for f in fails)
        assert not any("missing key" in f for f in fails)


def _corpus(root: pathlib.Path) -> None:
    c = root / "data" / "cortex-corpus"
    c.mkdir(parents=True)
    (c / "policy-001-a.md").write_text("Report within thirty days. The limit is ten thousand dollars.")
    (c / "policy-002-b.md").write_text("Keep records for seven years. Report within thirty days.")
    (c / "policy-003-c.md").write_text("Keep records for seven years. The limit is ten thousand dollars.")


def test_validate_heldout_generic_checks():
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        assets, track = root / "assets", root / "track"
        _corpus(assets)
        (track / "private" / "heldout").mkdir(parents=True)
        (track / "01-x").mkdir()
        held = [
            {"query_id": "h1", "query_text": "How long do we keep records under policy two?",
             "relevant_ids": ["policy-002"], "required_strings": ["seven years"]},                 # T9-b warn
            {"query_id": "h2", "query_text": "What is the cash limit that policy one sets?",
             "relevant_ids": ["policy-001"], "required_strings": ["ten thousand dollars", "thirty days"]},
            {"query_id": "h3", "query_text": "A question whose gold is not in its document",
             "target_doc": "policy-001", "gold_literals": ["forty days"]},                          # T9-a fail
            {"query_id": "h4", "query_text": "Which limit does policy three state for cash?",
             "relevant_ids": ["policy-003"], "required_strings": ["seven years", "ten thousand dollars"]},
        ]
        (track / "private" / "heldout" / "q.json").write_text(json.dumps(held))
        dev_dir = assets / "data" / "dev-sets"
        dev_dir.mkdir(parents=True)
        (dev_dir / "dev.json").write_text(json.dumps([
            {"query_id": "h2", "query_text": "A dev question that is fine and long enough",
             "relevant_ids": ["policy-001"], "required_strings": ["thirty days"]}]))               # id clash
        nb = assets / "modules" / "m9" / "9-1" / "notebooks"
        nb.mkdir(parents=True)
        (nb / "lab.ipynb").write_text(json.dumps({"cells": [{"source": ["q = 'Which limit does policy three ",
                                                                          "state for cash?'"], "outputs": []}]}))
        (track / "01-x" / "assignment.md").write_text("Try: How long do we keep records under policy two?")
        spec = {"sets": [{"heldout": "private/heldout/q.json", "dev": "data/dev-sets/dev.json"}],
                "leak_scan": ["modules/m9/9-1"]}
        (track / "private" / "heldout-spec.json").write_text(json.dumps(spec))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ctx = validate_heldout.run(track, assets)
        out = buf.getvalue()
        assert "FAIL T9-a q.json:h3: no gold literal" in out
        assert "FAIL T9-c q.json:h1: another document holds every required string: ['policy-003']" in out
        assert "FAIL T9-c dev.json:h2: another document holds every required string: ['policy-002']" in out
        assert "T9-c q.json:h4" not in out and "T9-c q.json:h2" not in out   # no other doc holds both
        assert "WARN T9-b q.json:h1" in out
        assert "FAIL P14 q.json: held-out and dev item ids collide: ['h2']" in out
        assert "FAIL P14 q.json:h4: held-out text appears where the learner can read it: ['modules/m9/9-1/notebooks/lab.ipynb']" in out
        assert "FAIL P14 q.json:h1: held-out text appears where the learner can read it: ['01-x/assignment.md']" in out
        assert ctx.fails == 6, out


def test_validate_heldout_t9c_and_plugin():
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        assets, track = root / "assets", root / "track"
        _corpus(assets)
        (track / "private" / "heldout").mkdir(parents=True)
        (track / "private" / "heldout" / "q.json").write_text(json.dumps({"questions": [
            {"query_id": "h1", "relevant_ids": ["policy-001"],
             "required_strings": ["Report within thirty days."]}]}))
        (track / "private" / "validate_track.py").write_text(
            "def checks(ctx):\n    ctx.fail('track rule: ' + str(len(ctx.docs)))\n")
        (track / "private" / "heldout-spec.json").write_text(json.dumps(
            {"sets": [{"heldout": "private/heldout/q.json"}], "plugin": "private/validate_track.py"}))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ctx = validate_heldout.run(track, assets)
        out = buf.getvalue()
        assert "FAIL T9-c q.json:h1: another document holds every required string: ['policy-002']" in out
        assert "FAIL track rule: 3" in out and ctx.fails == 2



def test_validate_heldout_reads_ndjson_corpus():
    with tempfile.TemporaryDirectory() as tmp:
        p = pathlib.Path(tmp) / "cases.ndjson"
        p.write_text('{"case_id": "c-1", "body": "one"}\n{"case_id": "c-2", "body": "two"}\n')
        assert [r["case_id"] for r in validate_heldout.load_items(p)] == ["c-1", "c-2"]

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
