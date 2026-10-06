"""
test_page.py - unit tests for brief/page.py (Brief page build, contract check, deck converter).

Run with: python -m pytest brief/test_page.py -v
or:        python brief/test_page.py
"""

from __future__ import annotations

import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import page  # noqa: E402

LAB = """<header>
<p class="track-code">Lab 9.1</p>
<h1>Lab 9.1: Test the page</h1>
<p>One line of scenario.</p>
<p class="tip">Tip.</p>
</header>
<section id="problem">
<h2>The problem</h2>
<pre><!-- include: problem.txt --></pre>
</section>
<section>
<h2>Chunking sets the ceiling</h2>
<p>Concept.</p>
<figure><img src="diagram.svg" alt="d"></figure>
</section>
<section id="rule">
<h2>Decision rule</h2>
<p class="rule-line">Take the first row that applies.</p>
<table><tr><th>When</th><th>Do</th></tr><tr><td>a</td><td>b</td></tr></table>
</section>
<section id="done">
<h2>What done looks like</h2>
<ul><li>At least <strong>3 of 4</strong></li></ul>
</section>
<div id="next-note"><p>This challenge allows 60 minutes.</p></div>
"""

CAPSTONE = """<header><h1>Capstone 9.C: Budget</h1><p>Scenario line.</p></header>
<section id="scenario"><h2>The scenario</h2><pre>capture</pre></section>
<section id="slo"><h2>The SLO</h2><table><tr><th>Metric</th><th>Target</th></tr></table></section>
"""


def _track(tmp: str, src: str, name: str = "9-1-test") -> pathlib.Path:
    d = pathlib.Path(tmp) / name
    (d / "brief").mkdir(parents=True)
    (d / "page.html").write_text(src)
    (d / "problem.txt").write_text("Q: x < y?\nA: <none>\n")
    (d / "diagram.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
    return d


def test_build_and_check_lab_page():
    with tempfile.TemporaryDirectory() as tmp:
        d = _track(tmp, LAB)
        out = page.build(d).read_text()
        assert "<title>Lab 9.1: Test the page</title>" in out
        assert "Q: x &lt; y?\nA: &lt;none&gt;" in out                  # problem.txt verbatim, escaped
        assert 'src="data:image/svg+xml;base64,' in out
        assert out.index("This challenge allows 60 minutes.") > out.index("<h2>Select Check to continue</h2>")
        assert page.check(d) == []


def test_stale_index_and_leftover_slides_fail():
    with tempfile.TemporaryDirectory() as tmp:
        d = _track(tmp, LAB)
        page.build(d)
        (d / "page.html").write_text(LAB.replace("Concept.", "Changed."))
        (d / "brief" / "slides.md").write_text("x")
        fails = page.check(d)
        assert any("stale" in f for f in fails) and any("slides.md" in f for f in fails)


def test_contract_failures():
    poller = (page.TEMPLATE_DIR / "page-poller.js").read_text()
    good = page.render.__globals__["template_parts"]()[0]  # template text, for shape only
    assert "<!-- PAGE_POLLER -->" in good and poller
    with tempfile.TemporaryDirectory() as tmp:
        cases = {
            "rule-line": LAB.replace('<p class="rule-line">Take the first row that applies.</p>', ""),
            "em-dash": LAB.replace("Concept.", "Concept — here."),
            "slide": LAB.replace("Concept.", "See the next slide."),
            "concepts": LAB.replace(LAB[LAB.index("<section>\n<h2>Chunking"):LAB.index('<section id="rule">')], ""),
            "duplicate": LAB.replace("Chunking sets the ceiling", "The problem"),
            "id=": LAB.replace('<section id="done">', "<section>"),
            "no <pre>": LAB.replace("<pre><!-- include: problem.txt --></pre>", "<p>paraphrase</p>"),
        }
        for i, (want, src) in enumerate(cases.items()):
            d = _track(tmp, src, f"9-{i}-case")
            page.build(d)
            fails = page.check(d)
            assert any(want in f for f in fails), (want, fails)


def test_poller_must_be_byte_identical_and_no_external():
    with tempfile.TemporaryDirectory() as tmp:
        d = _track(tmp, LAB)
        html_ = page.render(d)
        assert page.check_html(html_, capstone=False) == []
        bad = html_.replace("Environment ready. Select Check.", "Ready!")
        assert any("shared poller" in f for f in page.check_html(bad, capstone=False))
        ext = html_.replace("</main>", '<script src="https://cdn.example/x.js"></script></main>')
        assert any("external" in f for f in page.check_html(ext, capstone=False))


def test_capstone_page():
    with tempfile.TemporaryDirectory() as tmp:
        d = _track(tmp, CAPSTONE, "9-c-budget")
        page.build(d)
        assert page.check(d) == []
        d2 = _track(tmp, LAB, "9-c-other")
        page.build(d2)
        assert any("capstone sections" in f for f in page.check(d2))


def test_citations_resolve():
    with tempfile.TemporaryDirectory() as tmp:
        d = _track(tmp, LAB)
        page.build(d)
        a = pathlib.Path(tmp) / "assignment.md"
        a.write_text("See the Brief, \"Chunking sets the ceiling\" and Brief, 'Decision rule'.\n")
        assert page.check(d, cite=[a]) == []
        a.write_text('See the Brief, "Key concepts".\n')
        assert any("Key concepts" in f for f in page.check(d, cite=[a]))


SLIDES = """<!-- layout: title -->
<p class="track-code">Lab 9.2</p>
<h1 class="slide-title">Route<br>the queries</h1>
<p class="slide-subtitle">Tina routes badly.</p>

---

<!-- layout: problem -->
<!-- problem -->
<div class="col-left"><div class="terminal-block">
routed  <span style="color:var(--yellow);">agentic</span>
</div></div>
<div class="col-right">
  <h2 class="slide-heading">The problem</h2>
  <p class="slide-body">She loops.</p>
</div>

---

<!-- layout: concept -->
<div class="col-text"><h2 class="slide-heading">The router</h2><p class="slide-body">Order matters.</p></div>

---

<!-- layout: rule -->
<!-- rule -->
<h2 class="slide-heading">Decision rule</h2>
<p class="rule-caption">Take the first row that applies.</p>
<table class="rule-table"><tr><th>A</th><th>B</th></tr></table>

---

<!-- layout: done -->
<h2 class="slide-heading" style="color:var(--white);">What done looks like</h2>
<div class="done-row"><div class="done-item"><span class="big-number">0.80</span>
<span class="big-number-label">router accuracy<br>on held-out</span></div></div>

---

<!-- layout: next -->
<h2 class="slide-heading">Select Check</h2>
"""


def test_convert_deck_to_valid_page():
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp) / "9-2-route"
        (d / "brief").mkdir(parents=True)
        (d / "brief" / "slides.md").write_text(SLIDES)
        src = page.convert(d / "brief" / "slides.md")
        assert "<h1>Lab 9.2: Route the queries</h1>" in src
        assert '<span class="hl">agentic</span>' in src and "style=" not in src
        assert "<li><strong>0.80</strong> router accuracy on held-out</li>" in src
        assert "Select Check" not in src                       # the template supplies it
        (d / "page.html").write_text(src)
        (d / "brief" / "slides.md").unlink()
        page.build(d)
        assert page.check(d) == []


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
