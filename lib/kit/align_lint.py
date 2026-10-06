#!/usr/bin/env python3
"""
align_lint.py - checks one traqs track against the alignment kit (2026-10-06).

Usage:
  python3 lib/kit/align_lint.py <traqs track dir> [--assets <vestal_project root>] [--only A,B]

Authoring tool; nothing in a sandbox runs it. It never imports ara_grade: a track on its own
per-track grader lints the same as one on the shared grader. Each rule prints ok or FAIL with
the reason. Exit 1 on any FAIL.

Rules (ids for --only):
  gate        Brief check and solve equal lib/kit/brief-{check,solve}-elastic-serverless,
              comment lines aside (02 section 3.6; A6, A7)
  launcher    ch01 setup carries lib/kit/launcher-brief.sh from its ARA_BRIEF_SRC line on (N2)
  provision   provision.sh opens with lib/kit/provision-head.sh: EXPECTED_MIN set (A7) and
              STEP_TOTAL equal to the step calls; ara_verify_assets defined and called (N2)
  srclock     provision.sh closes /opt/ara/src with lib/kit/src-lock.sh
  wait        every setup after 01 carries lib/kit/wait-block.sh (648 polls, 54 min; N1)
  questions   private/questions.json is the new schema with "shuffle": "seed" on every question (A15)
  track       timelimit = sum of challenge limits + 1800 on a lab (N8), + 3600 on a capstone;
              description at most 90 words (A19);
              title "Lab N.N: ..." or "Capstone N.C: ..." (A18/A20); a capstone has the
              ara/capstone tag and skipping_enabled false
  records     ara-qa-record.yml passes qa_record.py check; calibration.md has the template's sections (N5)
  page        (needs --assets) the module's Brief page passes brief/page.py check, every
              "Brief, '<title>'" citation in the track resolves, and the page h1 equals the track title
  grader      information only: per-track private/checks/ara_grade.py, or the shared install line (N3)
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import re
import sys

import yaml

KIT = pathlib.Path(__file__).resolve().parent
REPO = KIT.parent.parent
TRACK_MARGIN_S = 1800           # labs (N8)
CAPSTONE_MARGIN_S = 3600        # capstones: N8 names the 11 labs; capstones keep sum + 3600 (X6)
CAL_SECTIONS = ("## Runs", "## T9 validation", "## Provisioning", "## See it yourself", "## Defend",
                "## Open", "## History")


def _code(text: str) -> list[str]:
    """Lines that are not comments, for comparing the gate scripts apart from their header."""
    return [l.rstrip() for l in text.splitlines() if not l.lstrip().startswith("#") or l.startswith("#!")]


def _contains_block(text: str, block: list[str]) -> bool:
    lines = [l.rstrip() for l in text.splitlines()]
    n = len(block)
    return any(lines[i:i + n] == block for i in range(len(lines) - n + 1))


def _front(md: pathlib.Path) -> dict:
    t = md.read_text()
    m = re.match(r"---\n(.*?)\n---\n", t, re.S)
    return yaml.safe_load(m.group(1)) if m else {}


def _provision(setup_text: str) -> str:
    m = re.search(r"<< 'PROVISION_EOF'\n(.*?)\nPROVISION_EOF", setup_text, re.S)
    return m.group(1) if m else ""


def _challenges(track: pathlib.Path) -> list[pathlib.Path]:
    return sorted(p for p in track.iterdir() if p.is_dir() and re.match(r"\d\d-", p.name))


class Lint:
    def __init__(self, track: pathlib.Path, assets: pathlib.Path | None):
        self.track, self.assets = track, assets
        self.fails = 0
        self.capstone = bool(re.search(r"-ara-\d-c-", track.name))

    def res(self, rule: str, ok: bool, msg: str = "") -> None:
        print(f"  ok   {rule}" if ok else f"  FAIL {rule}{': ' + msg if msg else ''}")
        self.fails += 0 if ok else 1

    # ── rules ──
    def gate(self):
        ch01 = _challenges(self.track)[0]
        for kind in ("check", "solve"):
            f = ch01 / f"{kind}-elastic-serverless"
            kit = _code((KIT / f"brief-{kind}-elastic-serverless").read_text())
            self.res(f"gate {kind}", f.exists() and _code(f.read_text()) == kit,
                     "" if f.exists() else "missing")

    def launcher(self):
        s = (_challenges(self.track)[0] / "setup-elastic-serverless").read_text()
        kit = (KIT / "launcher-brief.sh").read_text().splitlines()
        i = next(i for i, l in enumerate(kit) if l.startswith("ARA_BRIEF_SRC="))
        m = re.search(r'^ARA_BRIEF_SRC="/opt/ara/src/modules/m\d/[\w.-]+/brief"$', s, re.M)
        self.res("launcher ARA_BRIEF_SRC", bool(m), "no ARA_BRIEF_SRC=\"/opt/ara/src/modules/mN/<track>/brief\" line")
        self.res("launcher block", _contains_block(s, [l.rstrip() for l in kit[i + 1:]]),
                 "the lines after ARA_BRIEF_SRC differ from lib/kit/launcher-brief.sh")

    def provision(self):
        p = _provision((_challenges(self.track)[0] / "setup-elastic-serverless").read_text())
        if not p:
            self.res("provision", False, "no PROVISION_EOF heredoc in the ch01 setup")
            return
        m = re.search(r'^STARTED=\$\(date \+%s\); STEP_TOTAL=(\d+); STEP_N=0; STEP_LABEL="Starting"; '
                      r'EXPECTED_MIN=(\d+)', p, re.M)
        self.res("provision EXPECTED_MIN", bool(m) and int(m.group(2)) > 0,
                 "status writer line lacks STEP_TOTAL/EXPECTED_MIN, or EXPECTED_MIN is 0")
        kit = (KIT / "provision-head.sh").read_text().splitlines()
        body = [l.rstrip() for l in kit[kit.index("step() {"):]]
        self.res("provision step/trap", _contains_block(p, body), "step() and the ERR trap differ from the kit")
        if m:
            calls = len(re.findall(r'^\s*step "', p, re.M))
            self.res("provision STEP_TOTAL", calls == int(m.group(1)), f"STEP_TOTAL={m.group(1)}, {calls} step calls")
        self.res("provision verify", "ara_verify_assets()" in p and "if ! ara_verify_assets /opt/ara/src" in p,
                 "ara_verify_assets not defined and called")

    def srclock(self):
        p = _provision((_challenges(self.track)[0] / "setup-elastic-serverless").read_text())
        kit = [l.rstrip() for l in (KIT / "src-lock.sh").read_text().splitlines() if not l.startswith("#")]
        self.res("srclock", _contains_block(p, kit), "lib/kit/src-lock.sh not found in provision.sh")

    def wait(self):
        kit = [l.rstrip() for l in (KIT / "wait-block.sh").read_text().splitlines() if not l.startswith("#")]
        for ch in _challenges(self.track)[1:]:
            f = ch / "setup-elastic-serverless"
            ok = f.exists() and _contains_block(f.read_text(), kit)
            self.res(f"wait {ch.name}", ok, "missing" if not f.exists() else "no 648 wait block")

    def questions(self):
        f = self.track / "private" / "questions.json"
        if not f.exists():
            self.res("questions", True, "no private/questions.json")
            return
        q = json.loads(f.read_text())
        if not isinstance(q, dict) or "questions" not in q:
            self.res("questions schema", False, "old schema (a bare list): move to the new schema")
            return
        bad = [x.get("id") for x in q["questions"] if x.get("shuffle") != "seed"]
        self.res("questions shuffle", not bad, f"no \"shuffle\": \"seed\" on {bad}")

    def track_yml(self):
        t = yaml.safe_load((self.track / "track.yml").read_text())
        limits = [(_front(c / "assignment.md").get("timelimit") or 0) for c in _challenges(self.track)]
        margin = CAPSTONE_MARGIN_S if self.capstone else TRACK_MARGIN_S
        want = sum(limits) + margin
        self.res("track timelimit", t.get("timelimit") == want,
                 f"{t.get('timelimit')} != sum {sum(limits)} + {margin} = {want}")
        words = len(str(t.get("description", "")).split())
        self.res("track description", words <= 90, f"{words} words")
        title = str(t.get("title", ""))
        form = r"Capstone \d\.C: \S" if self.capstone else r"Lab \d\.\d: \S"
        self.res("track title", bool(re.match(form, title)), repr(title))
        if self.capstone:
            self.res("capstone tag", "ara/capstone" in (t.get("tags") or []), "ara/capstone tag missing")
            self.res("capstone skipping", t.get("skipping_enabled") is False, "skipping_enabled must be false")

    def records(self):
        spec = importlib.util.spec_from_file_location("qa_record", KIT / "qa_record.py")
        qa = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(qa)
        fails = qa.check(self.track)
        self.res("records qa-record", not fails, "; ".join(fails[:3]))
        cal = self.track / "private" / "calibration.md"
        text = cal.read_text() if cal.exists() else ""
        heads = {l.strip() for l in text.splitlines() if l.startswith("## ")}
        missing = [s for s in CAL_SECTIONS if s not in heads
                   and not (self.capstone and s == "## See it yourself")]
        self.res("records calibration", cal.exists() and not missing, f"missing sections {missing}")

    def page(self):
        if self.assets is None:
            self.res("page", True, "skipped (no --assets)")
            return
        setup = (_challenges(self.track)[0] / "setup-elastic-serverless").read_text()
        m = re.search(r"/opt/ara/src/(modules/m\d/[\w.-]+)/brief", setup)
        if not m:
            self.res("page", False, "cannot find the module track dir in the ch01 setup")
            return
        spec = importlib.util.spec_from_file_location("page", self.assets / "brief" / "page.py")
        page = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(page)
        tdir = self.assets / m.group(1)
        cites = sorted(self.track.glob("*/assignment.md")) + sorted((self.track / "private").rglob("*.py")) \
            + sorted((self.track / "private").glob("*.json"))
        fails = page.check(tdir, cite=cites)
        self.res("page check", not fails, "; ".join(fails[:4]))
        served = tdir / "brief" / "index.html"
        h1 = re.search(r"<h1[^>]*>(.*?)</h1>", served.read_text(), re.S) if served.exists() else None
        title = str(yaml.safe_load((self.track / "track.yml").read_text()).get("title", ""))
        self.res("page title", bool(h1) and page._text(h1.group(1)) == title,
                 f"h1 {page._text(h1.group(1)) if h1 else None!r} vs track {title!r}")

    def grader(self):
        own = (self.track / "private" / "checks" / "ara_grade.py").exists()
        shared = "install -m 600 -o root -g root /opt/ara/src/lib/ara_grade.py /opt/ara/checks/ara_grade.py" in \
            (_challenges(self.track)[0] / "setup-elastic-serverless").read_text()
        print(f"  info grader: {'per-track copy' if own else ''}{' + ' if own and shared else ''}"
              f"{'shared install line' if shared else ''}{'none found' if not (own or shared) else ''}")
        if own and shared:  # ara-embed would embed the old copy after the install, and it would win
            self.res("grader", False, "the setup installs the shared grader but private/checks/ara_grade.py "
                     "is still there; delete it so ara-embed.py stops embedding the old copy")


RULES = {"gate": Lint.gate, "launcher": Lint.launcher, "provision": Lint.provision, "srclock": Lint.srclock,
         "wait": Lint.wait, "questions": Lint.questions, "track": Lint.track_yml, "records": Lint.records,
         "page": Lint.page, "grader": Lint.grader}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="ARA alignment lint")
    ap.add_argument("track", type=pathlib.Path)
    ap.add_argument("--assets", type=pathlib.Path)
    ap.add_argument("--only", default="")
    a = ap.parse_args(argv)
    lint = Lint(a.track.resolve(), a.assets.resolve() if a.assets else None)
    only = [x for x in a.only.split(",") if x] or list(RULES)
    print(f"{lint.track.name}")
    for name in only:
        try:
            RULES[name](lint)
        except Exception as exc:  # a rule that cannot run is a failure, never a pass
            lint.res(name, False, f"rule error: {type(exc).__name__}: {exc}")
    print(f"  {lint.fails} FAIL")
    return 1 if lint.fails else 0


if __name__ == "__main__":
    sys.exit(main())
