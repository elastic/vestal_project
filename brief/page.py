#!/usr/bin/env python3
"""
page.py - ARA Brief page builder, checker and deck converter (alignment round A1-A5, 2026-10-06).

Every Brief is one scrolling page (brief/index.html), built from a hand-edited source fragment
(<track>/page.html) and the shared template in brief/template/ (page.html, page.css,
page-poller.js). Sections are <h2> headings, so assignments cite them by title.

Usage:
  python3 brief/page.py build   <module-track-dir>                 # page.html -> brief/index.html
  python3 brief/page.py check   <module-track-dir> [--cite FILE...]  # contract + drift; exit 1 on failure
  python3 brief/page.py convert <slides.md|index.html> [-o <track>/page.html]
                                        # deck, or an older hand-written page -> draft page source

<module-track-dir> is modules/mN/<track>/ in this repo.

Source fragment (page.html), in order. A lab page:
  <header> with <p class="track-code">, one <h1> (the track title), a one-line scenario,
           and <p class="tip"> (the Hide Instructions tip)
  <section id="problem"><h2>The problem</h2> ... <pre> the real capture ... </section>
           <!-- include: problem.txt --> inside a <pre> pastes problem.txt verbatim (escaped)
  <section><h2>One concept</h2> ...</section>        one per concept, never a glossary
  <section id="rule"><h2>Decision rule</h2><p class="rule-line">Take the first row that applies.</p><table>...
  <section id="done"><h2>What done looks like</h2> ...</section>
A capstone page (--capstone, or a track dir named N-c-*):
  <header>, <section id="scenario"><h2>The scenario</h2>, <section id="slo"><h2>The SLO</h2>
Optional, either kind: <div id="next-note">...</div> moves into the closing section.
The template adds the closing "Select Check to continue" section and the shared poller.

Figures (Brief review, 2026-10-09). Every <img> sits in a <figure> and carries no width or height:
the build sizes each SVG at SVG_SCALE CSS px per viewBox unit, so text in every figure renders at
one size across pages, and figures shrink on narrow screens but never grow. The brand fonts are
inlined as data URIs, so the page makes no network requests.
"""
from __future__ import annotations

import argparse
import base64
import html
import pathlib
import re
import sys
from html.parser import HTMLParser

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
TEMPLATE_DIR = REPO_ROOT / "brief" / "template"
SOURCE_NAME = "page.html"

LAB_SECTIONS_HEAD = ["The problem"]
LAB_SECTIONS_TAIL = ["Decision rule", "What done looks like", "Select Check to continue"]
CAPSTONE_SECTIONS = ["The scenario", "The SLO", "Select Check to continue"]
SECTION_IDS = {"The problem": "problem", "Decision rule": "rule", "What done looks like": "done",
               "The scenario": "scenario", "The SLO": "slo", "Select Check to continue": "next"}
SVG_SCALE = 1.25            # CSS px per SVG viewBox unit, for every figure
MIN_FIGURE_TEXT_PX = 12     # smallest text a figure may render, at the narrowest content width
NARROW_CONTENT_PX = 536     # figure content width in a 600 px viewport (page.css narrow rules)
FIGURE_PAD_PX = 12          # the white panel's padding (page.css figure img)
FONTS = [  # (family, weight CSS, file under brand/fonts). Inter is one variable font.
    ("Inter", "100 900", "Inter/weight-400.woff2"),
    ("Space Grotesk", "700", "SpaceGrotesk/weight-700.woff2"),
    ("Space Mono", "400", "SpaceMono/weight-400.woff2"),
    ("Space Mono", "700", "SpaceMono/weight-700.woff2"),
]
FONT_DIR = REPO_ROOT / "brand" / "fonts"
CITE_RE = re.compile(r"Brief[,:]?\s+[\"'‘“]([^\"'’”\n]{2,100})[\"'’”]")


def template_parts() -> tuple[str, str, str]:
    return ((TEMPLATE_DIR / "page.html").read_text(), (TEMPLATE_DIR / "page.css").read_text(),
            (TEMPLATE_DIR / "page-poller.js").read_text())


# ── Build ─────────────────────────────────────────────────────────────────────

def _include(src: str, base: pathlib.Path) -> str:
    def rep(m: re.Match) -> str:
        path = (base / m.group(1).strip()).resolve()
        if not path.exists():
            raise SystemExit(f"include not found: {path}")
        return html.escape(path.read_text().rstrip("\n"), quote=False)
    return re.sub(r"<!--\s*include:\s*([^>]+?)\s*-->", rep, src)


def svg_geometry(svg: str) -> tuple[float, float, float | None]:
    """(viewBox width, viewBox height, smallest font-size in viewBox units or None)."""
    m = re.search(r'viewBox="\s*[-\d.]+[\s,]+[-\d.]+[\s,]+([\d.]+)[\s,]+([\d.]+)\s*"', svg)
    if not m:
        raise ValueError("SVG has no viewBox")
    sizes = [float(x) for x in re.findall(r'font-size(?:="|:\s*)([\d.]+)', svg)]
    return float(m.group(1)), float(m.group(2)), (min(sizes) if sizes else None)


def svg_size(svg: str) -> tuple[int, int]:
    w, h, _ = svg_geometry(svg)
    return round(w * SVG_SCALE), round(h * SVG_SCALE)


def _inline_images(src: str, base: pathlib.Path) -> str:
    """<img src="x.svg|png"> relative to the track dir or its brief/ becomes a data URI.
    An SVG also gets width and height from its viewBox at SVG_SCALE."""
    def rep(m: re.Match) -> str:
        url = m.group(2)
        if url.startswith(("data:", "http:", "https:")):
            return m.group(0)
        for root in (base, base / "brief"):
            p = (root / url).resolve()
            if p.exists():
                ext = p.suffix.lower().lstrip(".")
                mime = {"svg": "image/svg+xml", "png": "image/png", "jpg": "image/jpeg",
                        "jpeg": "image/jpeg"}.get(ext, "application/octet-stream")
                size = ""
                if ext == "svg":
                    try:
                        w, h = svg_size(p.read_text())
                    except ValueError as exc:
                        raise SystemExit(f"{url}: {exc}")
                    size = f' width="{w}" height="{h}"'
                data = base64.b64encode(p.read_bytes()).decode()
                return f'{m.group(1)}data:{mime};base64,{data}"{size}{m.group(3)[1:]}'
        raise SystemExit(f"image not found: {url}")
    return re.sub(r'(<img\b[^>]*\bsrc=")([^"]+)("[^>]*>)', rep, src)


def font_faces() -> str:
    out = []
    for family, weight, rel in FONTS:
        data = base64.b64encode((FONT_DIR / rel).read_bytes()).decode()
        out.append(f"@font-face {{ font-family: '{family}'; font-weight: {weight}; font-style: normal; "
                   f"font-display: swap; src: url(data:font/woff2;base64,{data}) format('woff2'); }}")
    return "\n".join(out)


def render(track_dir: pathlib.Path) -> str:
    src_path = track_dir / SOURCE_NAME
    src = src_path.read_text()
    src = _inline_images(_include(src, track_dir), track_dir)
    note = ""
    m = re.search(r'<div id="next-note">.*?</div>\s*', src, re.S)
    if m:
        note, src = m.group(0).strip(), src[:m.start()] + src[m.end():]
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", src, re.S)
    title = _text(h1.group(1)) if h1 else "ARA Brief"
    page, css, poller = template_parts()
    out = page.replace("<!-- PAGE_TITLE -->", html.escape(title, quote=False))
    out = out.replace("<!-- PAGE_CSS -->", font_faces() + "\n" + css.rstrip("\n"))
    out = out.replace("<!-- PAGE_BODY -->", src.strip("\n"))
    out = out.replace("<!-- PAGE_NEXT_NOTE -->\n", (note + "\n") if note else "")
    out = out.replace("<!-- PAGE_POLLER -->", poller.rstrip("\n"))
    return out


def build(track_dir: pathlib.Path) -> pathlib.Path:
    out = track_dir / "brief" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(track_dir))
    return out


# ── Check ─────────────────────────────────────────────────────────────────────

def _text(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


class _Outline(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.h1: list[str] = []
        self.sections: list[dict] = []    # {"id", "h2", "children": [tag...]}
        self.scripts: list[str] = []
        self.ext: list[str] = []
        self.status = False
        self.loose_imgs: list[str] = []    # <img> outside a <figure>
        self.svgs: list[tuple[str, str]] = []  # (alt, data URI) of inlined SVGs
        self.bare_spans = 0
        self.title = ""
        self._stack: list[str] = []
        self._cap: str | None = None
        self._buf = ""
        self._depth_in_section = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "link", "img", "iframe", "source") and any(
                (a.get(k) or "").startswith(("http:", "https:", "//")) for k in ("src", "href")):
            self.ext.append(a.get("src") or a.get("href"))
        if tag == "script" and a.get("src"):
            self.ext.append(a["src"])
        if a.get("id") == "status":
            self.status = True
        if tag == "img":
            if "figure" not in self._stack:
                self.loose_imgs.append(a.get("alt") or a.get("src", "")[:40])
            if (a.get("src") or "").startswith("data:image/svg+xml;base64,"):
                self.svgs.append((a.get("alt") or "", a["src"]))
        if tag == "span" and not a.get("class"):
            self.bare_spans += 1
        if tag == "section":
            self.sections.append({"id": a.get("id"), "h2": None, "children": []})
            self._depth_in_section = 0
        elif self.sections and self._stack and self._stack[-1] == "section":
            self.sections[-1]["children"].append((tag, a.get("class")))
        if tag in ("h1", "h2", "title", "script"):
            self._cap, self._buf = tag, ""
        if tag not in ("img", "br", "meta", "link", "hr", "input", "source"):
            self._stack.append(tag)

    def handle_endtag(self, tag):
        if self._cap == tag:
            text = self._buf if tag == "script" else " ".join(self._buf.split())
            if tag == "h1":
                self.h1.append(text)
            elif tag == "h2" and self.sections and self.sections[-1]["h2"] is None:
                self.sections[-1]["h2"] = text
            elif tag == "title":
                self.title = text
            elif tag == "script":
                self.scripts.append(text)
            self._cap = None
        while self._stack:
            if self._stack.pop() == tag:
                break

    def handle_data(self, data):
        if self._cap:
            self._buf += data


def is_capstone(track_dir: pathlib.Path) -> bool:
    return bool(re.match(r"\d+-c-", track_dir.name))


def check_html(page: str, capstone: bool) -> list[str]:
    """Contract checks on a served page. Returns failure strings."""
    fails: list[str] = []
    o = _Outline()
    o.feed(page)
    if len(o.h1) != 1:
        fails.append(f"expected one <h1>, found {len(o.h1)}")
    elif o.title != o.h1[0]:
        fails.append(f"<title> {o.title!r} differs from <h1> {o.h1[0]!r}")
    heads = [s["h2"] for s in o.sections]
    if None in heads:
        fails.append("a <section> has no <h2>")
        heads = [h for h in heads if h]
    if len(set(heads)) != len(heads):
        fails.append(f"duplicate section titles (each must be citable): {heads}")
    if capstone:
        if heads != CAPSTONE_SECTIONS:
            fails.append(f"capstone sections must be {CAPSTONE_SECTIONS}, found {heads}")
    else:
        if heads[:1] != LAB_SECTIONS_HEAD or heads[-3:] != LAB_SECTIONS_TAIL or len(heads) < 5:
            fails.append("lab sections must be: The problem, one or more concepts, Decision rule, "
                         f"What done looks like, Select Check to continue; found {heads}")
        for s in o.sections:
            if s["h2"] == "Decision rule":
                kids = [t for t in s["children"] if t[0] != "h2"]
                if not (kids and kids[0][0] == "p" and "rule-line" in (kids[0][1] or "")
                        and len(kids) > 1 and kids[1][0] == "table"):
                    fails.append('Decision rule must open with <p class="rule-line"> then the <table>')
            if s["h2"] == "The problem" and not any(t[0] == "pre" for t in s["children"]):
                fails.append("The problem has no <pre> capture (problem.txt)")
    for s in o.sections:
        want = SECTION_IDS.get(s["h2"] or "")
        if want and s["id"] != want:
            fails.append(f'section {s["h2"]!r} needs id="{want}", has {s["id"]!r}')
    poller = (TEMPLATE_DIR / "page-poller.js").read_text().strip()
    if not o.status:
        fails.append('no id="status" indicator')
    if [x.strip() for x in o.scripts] != [poller]:
        fails.append("the page must carry exactly one script, the shared poller, byte for byte")
    if o.ext:
        fails.append(f"external resources: {o.ext[:3]}")
    if o.loose_imgs:
        fails.append(f"<img> outside a <figure>: {o.loose_imgs[:3]}")
    for alt, uri in o.svgs:
        fails += [f"figure {alt[:40]!r}: {f}" for f in figure_text_fails(
            base64.b64decode(uri.split(",", 1)[1]).decode())]
    if o.bare_spans:
        fails.append(f"{o.bare_spans} <span> without a class (highlight lost)")
    for family, _, _ in FONTS:
        if f"font-family: '{family}'" not in page:
            fails.append(f"brand font {family} not inlined")
    body = re.sub(r"<(script|style)\b.*?</\1>", "", page, flags=re.S)
    if "—" in body:
        fails.append("em-dash in page text")
    if re.search(r"\bslides?\b", _text(body), re.I):
        fails.append('page text says "slide": it is a page now')
    return fails


def figure_text_fails(svg: str) -> list[str]:
    """The smallest text in an SVG at SVG_SCALE, shrunk to the narrow content width."""
    try:
        w, _, smallest = svg_geometry(svg)
    except ValueError as exc:
        return [str(exc)]
    if smallest is None:
        return []
    shrink = min(1.0, (NARROW_CONTENT_PX - 2 * FIGURE_PAD_PX) / (w * SVG_SCALE))
    px = smallest * SVG_SCALE * shrink
    if px < MIN_FIGURE_TEXT_PX:
        return [f"text renders at {px:.1f} px at narrow width (minimum {MIN_FIGURE_TEXT_PX})"]
    return []


def citations(paths: list[pathlib.Path]) -> list[str]:
    out = []
    for p in paths:
        out.extend(CITE_RE.findall(p.read_text(errors="replace")))
    return out


def check(track_dir: pathlib.Path, cite: list[pathlib.Path] | None = None,
          capstone: bool | None = None) -> list[str]:
    fails: list[str] = []
    served = track_dir / "brief" / "index.html"
    if not served.exists():
        return [f"{served} missing"]
    page = served.read_text()
    if (track_dir / SOURCE_NAME).exists():
        src = (track_dir / SOURCE_NAME).read_text()
        if re.search(r"<img\b[^>]*\b(width|height)=", src):
            fails.append("page.html sets an image width or height: the build sizes figures (SVG_SCALE)")
        if re.search(r"<svg\b", src):
            fails.append("page.html has an inline <svg>: put it in a file and use <figure><img>")
        if re.search(r"\sstyle=", src):
            fails.append("page.html has a style attribute: styling lives in page.css")
        if render(track_dir) != page:
            fails.append(f"brief/index.html is stale: run page.py build {track_dir}")
    else:
        fails.append(f"no {SOURCE_NAME} source beside brief/")
    if (track_dir / "brief" / "slides.md").exists():
        fails.append("brief/slides.md still present (the Brief is a page)")
    fails += check_html(page, is_capstone(track_dir) if capstone is None else capstone)
    if cite:
        o = _Outline()
        o.feed(page)
        heads = {s["h2"] for s in o.sections}
        for title in citations(cite):
            if title not in heads:
                fails.append(f'citation "Brief, {title!r}" matches no section title')
    return fails


# ── Convert a deck (slides.md) to a draft page source ────────────────────────

def _parse_slides(source: str) -> list[dict]:
    slides = []
    for block in re.split(r"^---$", source, flags=re.M):
        block = block.strip()
        if not block:
            continue
        fm: dict = {}
        for m in re.finditer(r"<!--(.*?)-->", block, re.S):
            for line in m.group(1).splitlines():
                kv = line.strip().split(":", 1)
                if len(kv) == 2 and kv[0].strip().isidentifier():
                    fm[kv[0].strip()] = kv[1].strip()
        markers = set(re.findall(r"<!--\s*(problem|rule)\s*-->", block))
        body = re.sub(r"<!--.*?-->", "", block, flags=re.S).strip()
        slides.append({"layout": fm.get("layout", "concept"), "markers": markers, "body": body})
    return slides


def _clean(body: str) -> str:
    s = body
    s = re.sub(r'<div class="terminal-block"[^>]*>\n?(.*?)\n?\s*</div>', lambda m: "<pre>" + m.group(1).rstrip() + "</pre>", s, flags=re.S)
    s = re.sub(r'<span style="color:\s*var\(--yellow\);?">', '<span class="hl">', s)
    s = re.sub(r'<span style="color:\s*var\(--(?:green|teal)\);?">', '<span class="right">', s)
    s = re.sub(r'<span style="color:\s*var\(--(?:red|orange|pink)\);?">', '<span class="wrong">', s)
    s = re.sub(r'<div class="col-[a-z]+"[^>]*>|</div>\s*(?=<div class="col-|$)', "", s)
    s = re.sub(r'<(h2|p) class="slide-[a-z]+"[^>]*>', r"<\1>", s)
    s = re.sub(r'<p class="rule-caption"[^>]*>', '<p class="rule-line">', s)
    s = re.sub(r'<table class="[^"]*">', "<table>", s)
    s = re.sub(r'<div style="[^"]*">', '<div class="note">', s)
    s = re.sub(r'\s+style="[^"]*"', "", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _heading_first(s: str) -> tuple[str, str]:
    m = re.search(r"<h2>(.*?)</h2>", s, re.S)
    if not m:
        return "", s
    return _text(m.group(1)), (s[:m.start()] + s[m.end():]).strip()


def _balance_divs(s: str) -> str:
    opened, closed = len(re.findall(r"<div\b", s)), s.count("</div>")
    while closed > opened and s.rstrip().endswith("</div>"):
        s = s.rstrip()[:-len("</div>")].rstrip(); closed -= 1
    return s + "\n</div>" * max(0, opened - closed)


def convert(slides_path: pathlib.Path) -> str:
    """A draft page source from a deck. Review it by hand: keep everything that serves the
    Build or Defend, cut only repetition, then check the sentence-case title and citations."""
    out: list[str] = [f"<!-- converted from {slides_path.name} by brief/page.py; edit by hand -->"]
    for sl in _parse_slides(slides_path.read_text()):
        layout, body = sl["layout"], sl["body"]
        if layout == "next":
            continue
        if layout == "title":
            code = re.search(r'<p class="track-code">(.*?)</p>', body, re.S)
            h1 = re.search(r"<h1[^>]*>(.*?)</h1>", body, re.S)
            sub = re.search(r'<p class="slide-subtitle">(.*?)</p>', body, re.S)
            code_t = _text(code.group(1)) if code else ""
            h1_t = _text(re.sub(r"<br\s*/?>", " ", h1.group(1))) if h1 else ""
            title = h1_t if not code_t or h1_t.startswith(code_t) else f"{code_t}: {h1_t}"
            out.append("<header>")
            if code_t:
                out.append(f'<p class="track-code">{code_t}</p>')
            out.append(f"<h1>{title}</h1>")
            if sub:
                out.append(f"<p>{sub.group(1).strip()}</p>")
            out.append('<p class="tip"><strong>Tip:</strong> Select <strong>Hide Instructions</strong> '
                       "in the top bar to give the Brief full width.</p>")
            out.append("</header>")
            continue
        heading, rest = _heading_first(_clean(body))
        if layout == "done":
            items = re.findall(r'<span class="big-number">(.*?)</span>\s*<span class="big-number-label">(.*?)</span>', rest, re.S)
            if items:
                tail = re.sub(r'<div class="done-row">.*</div>', "", rest, flags=re.S).strip()
                lis = "\n".join("<li><strong>" + _text(n) + "</strong> "
                                + _text(re.sub(r"<br\s*/?>", " ", lab)) + "</li>" for n, lab in items)
                rest = f"<ul>\n{lis}\n</ul>" + (f"\n{tail}" if tail else "")
            heading = "What done looks like"
            rest = rest.replace('<p class="rule-line">', "<p>")
        # A marked slide becomes the standard section only when its own title says so (or it has
        # none): a capstone's SLO slides use the rule layout but are not the Decision rule.
        if ((layout == "rule" or "rule" in sl["markers"])
                and (not heading or "rule" in heading.lower())):
            heading, sid = "Decision rule", "rule"
        elif ((layout == "problem" or "problem" in sl["markers"])
                and (not heading or "problem" in heading.lower())):
            heading, sid = "The problem", "problem"
        elif layout == "done":
            sid = "done"
        else:
            sid = None
        rest = _balance_divs(rest)
        open_tag = f'<section id="{sid}">' if sid else "<section>"
        out.append(f"{open_tag}\n<h2>{heading}</h2>\n{rest}\n</section>")
    return "\n\n".join(out) + "\n"


def convert_page(index_path: pathlib.Path) -> str:
    """A draft page source from an older hand-written page (M2's <div class="slide"> blocks).
    The block with the <h1> becomes the header, the closing "Select Check" block is dropped
    (the template supplies it), the rest become sections with the standard ids."""
    text = index_path.read_text()
    body = re.search(r"<body>(.*?)<div id=\"status\"", text, re.S)
    blocks = re.split(r'<div class="slide">', body.group(1) if body else text)[1:]
    out: list[str] = [f"<!-- converted from {index_path.name} by brief/page.py; edit by hand -->"]
    for b in blocks:
        b = re.sub(r"\s*</div>\s*$", "", b.strip())
        b = re.sub(r"\s*</div>\s*</div>\s*$", "", b)
        if "<h1" in b:
            out.append(f"<header>\n{b.strip()}\n</header>")
            continue
        heading, rest = _heading_first(b)
        if heading.startswith("Select Check"):
            continue
        sid = SECTION_IDS.get(heading)
        open_tag = f'<section id="{sid}">' if sid else "<section>"
        rest = re.sub(r'\s+style="[^"]*"', "", rest).strip()
        if heading == "Decision rule" and rest.startswith("<p>"):
            rest = '<p class="rule-line">' + rest[3:]
        out.append(f"{open_tag}\n<h2>{heading}</h2>\n{rest}\n</section>")
    return "\n\n".join(out) + "\n"


# ── CLI ───────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="ARA Brief page tool")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build"); b.add_argument("track_dir", type=pathlib.Path)
    c = sub.add_parser("check"); c.add_argument("track_dir", type=pathlib.Path)
    c.add_argument("--cite", nargs="*", type=pathlib.Path, default=[])
    c.add_argument("--capstone", action="store_true", default=None)
    v = sub.add_parser("convert"); v.add_argument("slides", type=pathlib.Path, help="slides.md or an older index.html")
    v.add_argument("-o", "--out", type=pathlib.Path)
    a = ap.parse_args(argv)
    if a.cmd == "build":
        out = build(a.track_dir)
        print(f"Written: {out}")
        fails = check(a.track_dir)
    elif a.cmd == "check":
        fails = check(a.track_dir, a.cite, a.capstone)
    else:
        text = convert_page(a.slides) if a.slides.suffix == ".html" else convert(a.slides)
        if a.out:
            a.out.write_text(text)
            print(f"Draft written: {a.out}. Edit it, then: page.py build {a.out.parent}")
        else:
            sys.stdout.write(text)
        return 0
    for f in fails:
        print(f"  FAIL: {f}")
    print("  OK" if not fails else f"  {len(fails)} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
