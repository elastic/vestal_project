#!/usr/bin/env python3
"""
build.py  — ARA Brief deck builder
Usage:
  python3 brief/build.py <slides.md>              Build index.html beside the source file
  python3 brief/build.py <slides.md> --check      Validate only; exit 1 on failure
  python3 brief/build.py <path/to/brief/> --check Check all slides.md files found recursively
"""

import argparse, base64, json, pathlib, re, sys, html, textwrap
from typing import Optional

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
TEMPLATE_DIR = REPO_ROOT / "brief" / "template"
BRAND_DIR = REPO_ROOT / "brand"

# Colors that build.py --check accepts (must match tokens.css :root definitions)
ALLOWED_HEX = {
    "#0b64dd", "#48efcf", "#ff957d", "#f04e98", "#fec514",
    "#153385", "#101c3f", "#1c1e23", "#343741", "#ffffff",
    "#f5f7fa", "#dce2ea", "#abb4c4",
    "#02bcb7", "#9adc30",  # logo cluster
    # Illustration palette
    "#0a52b3", "#1893ff", "#45a8ff", "#128d91",
    "#e55940", "#fa744e", "#dd0a73", "#f990c6",
    "#ffad18", "#ffdf56",
}
ALLOWED_FONT_FAMILIES = {"space grotesk", "inter", "space mono", "arial", "sans-serif", "monospace", "ui-monospace"}

# Slide layouts declared in the markdown front-matter
LAYOUTS = {"title", "problem", "concept", "rule", "done", "next"}


# ── Markdown → HTML (minimal; real decks use the HTML slide classes directly) ──

def md_to_html(text: str) -> str:
    """Very small markdown subset: bold, code, br, paragraphs."""
    text = html.escape(text)
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'`(.+?)`', r'<code>\1</code>', text)
    text = re.sub(r'\n\n+', '</p><p>', text)
    return text


# ── Slide parsing ──

def parse_slides(source: str) -> list[dict]:
    """Split on --- and extract per-slide front-matter + body."""
    blocks = re.split(r'^---$', source, flags=re.MULTILINE)
    slides = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        fm: dict = {}
        body: str = block
        if block.startswith('<!--'):
            # extract HTML comment front-matter block
            m = re.match(r'<!--\s*(.*?)\s*-->(.*)', block, re.DOTALL)
            if m:
                for line in m.group(1).splitlines():
                    kv = line.strip().split(':', 1)
                    if len(kv) == 2:
                        fm[kv[0].strip()] = kv[1].strip()
                body = m.group(2).strip()
        slides.append({'fm': fm, 'body': body, 'raw': block})
    return slides


# ── Inline assets ──

def inline_css(path: pathlib.Path, visited: Optional[set] = None) -> str:
    """Read CSS, recursively resolve @import url(...) relative to the file."""
    if visited is None:
        visited = set()
    if path in visited:
        return ''
    visited.add(path)
    text = path.read_text()
    def replace_import(m: re.Match) -> str:
        rel = m.group(1).strip("'\"")
        if rel.startswith('http'):
            return ''  # strip external imports
        target = (path.parent / rel).resolve()
        return inline_css(target, visited)
    text = re.sub(r'@import\s+url\(([^)]+)\)\s*;', replace_import, text)
    # Rewrite relative font paths to data URIs
    def replace_font(m: re.Match) -> str:
        rel = m.group(1).strip("'\"")
        font_path = (path.parent / rel).resolve()
        if not font_path.exists():
            return m.group(0)
        data = base64.b64encode(font_path.read_bytes()).decode()
        fmt = 'woff2' if rel.endswith('.woff2') else 'truetype'
        return f'url("data:font/{fmt};base64,{data}")'
    text = re.sub(r"url\(([^)]+\.woff2|[^)]+\.ttf)\)", replace_font, text)
    return text


def inline_svg(path: pathlib.Path) -> str:
    if path.exists():
        return path.read_text()
    return f'<!-- missing: {path.name} -->'


# ── Build ──

def inline_svg_images(html_body: str, base_path: pathlib.Path) -> str:
    """Replace <img src="*.svg"> with inline data URIs, resolving relative to base_path."""
    def replace_svg_src(m: re.Match) -> str:
        before = m.group(1)
        src = m.group(2)
        after = m.group(3)
        if src.startswith('data:') or src.startswith('http'):
            return m.group(0)
        svg_path = (base_path / src).resolve()
        if not svg_path.exists() or not svg_path.suffix == '.svg':
            return m.group(0)
        data = base64.b64encode(svg_path.read_bytes()).decode()
        return f'{before}data:image/svg+xml;base64,{data}{after}'
    # Match src="...svg" in img tags
    return re.sub(r'(<img[^>]+src=")([^"]+\.svg)("[^>]*>)', replace_svg_src, html_body)


def build(source_path: pathlib.Path) -> str:
    """Render slides.md → self-contained HTML string."""
    source = source_path.read_text()
    slides_data = parse_slides(source)
    slides_dir = source_path.parent  # for resolving relative image paths

    template = (TEMPLATE_DIR / "deck.html").read_text()

    # Inline CSS (tokens + deck.css)
    deck_css_text = inline_css(TEMPLATE_DIR / "deck.css")
    deck_js_text = (TEMPLATE_DIR / "deck.js").read_text()
    poller_js_text = (TEMPLATE_DIR / "status-poller.js").read_text()

    # Inline logo SVG (used on title slide)
    logo_svg = inline_svg(BRAND_DIR / "logos" / "elastic-glyph-white.svg")

    # Build slide HTML
    slides_html = []
    for i, slide in enumerate(slides_data):
        layout = slide['fm'].get('layout', 'concept')
        rule_marker = '<!-- rule -->' if '<!-- rule -->' in slide['raw'] else ''
        # Inline any SVG <img> references to make index.html self-contained
        body = inline_svg_images(slide['body'], slides_dir)
        slide_html = (
            f'<section class="slide" data-layout="{html.escape(layout)}" '
            f'data-index="{i}">'
            f'{rule_marker}'
            f'{body}'
            f'\n<img class="elastic-logo" alt="Elastic" '
            f'src="data:image/svg+xml;base64,'
            f'{base64.b64encode(logo_svg.encode()).decode()}"/>'
            f'</section>'
        )
        slides_html.append(slide_html)

    slides_block = '\n'.join(slides_html)

    # Extract title from first slide
    title_match = re.search(r'<[hH][123][^>]*>([^<]+)', slides_block)
    deck_title = title_match.group(1).strip() if title_match else 'ARA Brief'

    # Assemble self-contained HTML
    html_out = template
    html_out = html_out.replace('<!-- DECK_TITLE -->', html.escape(deck_title))
    html_out = html_out.replace('<!-- SLIDES_PLACEHOLDER -->', slides_block)
    html_out = html_out.replace('<link rel="stylesheet" href="../../brand/tokens.css">', '')
    html_out = html_out.replace('<link rel="stylesheet" href="deck.css">', f'<style>{deck_css_text}</style>')
    html_out = html_out.replace('<script src="deck.js"></script>', f'<script>{deck_js_text}</script>')
    html_out = html_out.replace('<script src="status-poller.js"></script>', f'<script>{poller_js_text}</script>')

    return html_out


# ── Check ──

def check(source_path: pathlib.Path) -> list[str]:
    """Validate slides.md. Returns list of failure strings."""
    failures = []
    source = source_path.read_text()
    slides_data = parse_slides(source)
    n = len(slides_data)

    if n < 8:
        failures.append(f"Too few slides: {n} (minimum 8)")
    if n > 15:
        failures.append(f"Too many slides: {n} (maximum 15)")

    has_rule = any('<!-- rule -->' in s['raw'] or s['fm'].get('rule') for s in slides_data)
    if not has_rule:
        failures.append("Missing decision-rule slide (mark it with <!-- rule --> in the slide body or rule: true in front-matter)")

    for i, slide in enumerate(slides_data, 1):
        # Strip code/terminal blocks before counting body-text words
        body_no_code = re.sub(
            r'<(?:pre|code|div[^>]*terminal-block[^>]*)>.*?</(?:pre|code|div)>',
            '', slide['body'], flags=re.DOTALL
        )
        words = len(re.sub(r'<[^>]+>', '', body_no_code).split())
        if words > 60:
            failures.append(f"Slide {i}: body text exceeds 60 words ({words} words)")

    # Check for external URLs
    external_urls = re.findall(r'https?://(?!fonts\.gstatic\.com)', source)
    if external_urls:
        failures.append(f"External URLs found (not allowed): {external_urls[:3]}")

    # Check for disallowed hex colors in the body
    hex_colors = re.findall(r'#[0-9a-fA-F]{6}', source)
    bad_hex = [h for h in hex_colors if h.lower() not in ALLOWED_HEX]
    if bad_hex:
        failures.append(f"Hex colors not in brand tokens: {list(set(bad_hex))}")

    # Check for layouts
    for i, slide in enumerate(slides_data, 1):
        layout = slide['fm'].get('layout', 'concept')
        if layout not in LAYOUTS:
            failures.append(f"Slide {i}: unknown layout '{layout}'")

    return failures


# ── CLI ──

def main():
    parser = argparse.ArgumentParser(description="ARA Brief deck builder")
    parser.add_argument("target", help="slides.md file or directory to scan")
    parser.add_argument("--check", action="store_true", help="Validate only; do not write output")
    args = parser.parse_args()

    target = pathlib.Path(args.target)

    sources = []
    if target.is_dir():
        sources = list(target.rglob("slides.md"))
    elif target.is_file():
        sources = [target]
    else:
        print(f"ERROR: {target} not found", file=sys.stderr)
        sys.exit(1)

    if not sources:
        print("No slides.md files found.", file=sys.stderr)
        sys.exit(1)

    all_ok = True
    for src in sources:
        print(f"{'Checking' if args.check else 'Building'}: {src}")
        failures = check(src)
        if failures:
            all_ok = False
            for f in failures:
                print(f"  FAIL: {f}")
        else:
            print("  OK")
            if not args.check:
                out = src.parent / "index.html"
                html_content = build(src)
                out.write_text(html_content)
                print(f"  Written: {out} ({len(html_content):,} bytes)")

    if not all_ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
