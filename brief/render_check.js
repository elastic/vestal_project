// render_check.js - render built Brief pages in Chromium and fail on layout defects
// (Brief review, 2026-10-09). Run before every assets tag.
//
//   node brief/render_check.js [--shots DIR] modules/m1/*/brief/index.html
//
// Checks at 1280, 900 and 600 px wide:
//   - the brand fonts (Inter, Space Grotesk, Space Mono) load;
//   - every figure image renders at its built size, or shrinks to fit, never wider or stretched,
//     and its smallest text renders at 12 px or more;
//   - no word breaks across lines inside a table cell or a code chip;
//   - no horizontal scroll on the page or inside a table cell;
//   - pre blocks scroll sideways only at 600 px (reported, not failed, below 900).
// --shots DIR also writes a full-page PNG per page and width.
// Needs Playwright: `npm i -g playwright` (or set PLAYWRIGHT_PATH to the module).
const path = require('path');
const fs = require('fs');

function loadPlaywright() {
  for (const p of [process.env.PLAYWRIGHT_PATH, 'playwright', '/opt/homebrew/lib/node_modules/playwright',
                   '/usr/local/lib/node_modules/playwright']) {
    if (!p) continue;
    try { return require(p); } catch (e) { /* next */ }
  }
  throw new Error('Playwright not found: npm i -g playwright, or set PLAYWRIGHT_PATH');
}

const WIDTHS = [1280, 900, 600];
const FAMILIES = ['Inter', 'Space Grotesk', 'Space Mono'];

async function inspect(page) {
  return page.evaluate((FAMILIES) => {
    const out = { fails: [], notes: [] };
    const loaded = new Set([...document.fonts].filter(f => f.status === 'loaded').map(f => f.family.replace(/"/g, '')));
    for (const f of FAMILIES) if (!loaded.has(f)) out.fails.push(`font ${f} not loaded`);

    if (document.documentElement.scrollWidth > window.innerWidth)
      out.fails.push(`page scrolls sideways (${document.documentElement.scrollWidth} > ${window.innerWidth})`);

    for (const img of document.querySelectorAll('img')) {
      const fig = img.closest('figure');
      const built = parseInt(img.getAttribute('width') || '0', 10);
      const w = img.getBoundingClientRect().width - 24;          // minus the panel padding
      const room = fig ? fig.clientWidth - 24 : 0;
      const want = Math.min(built, room);
      if (!fig) out.fails.push(`image outside a figure: ${img.alt.slice(0, 40)}`);
      else if (!built) out.fails.push(`image has no built width: ${img.alt.slice(0, 40)}`);
      else if (Math.abs(w - want) > 1.5) out.fails.push(`image ${img.alt.slice(0, 40)} renders ${Math.round(w)} px, rule says ${Math.round(want)}`);
      const builtH = parseInt(img.getAttribute('height') || '0', 10);
      const h = img.getBoundingClientRect().height - 24;
      if (built && builtH && Math.abs(h - w * builtH / built) > 1.5)
        out.fails.push(`image ${img.alt.slice(0, 40)} is stretched: ${Math.round(w)}x${Math.round(h)}, built ${built}x${builtH}`);
      // Smallest SVG text as rendered: font-size in viewBox units x rendered width / viewBox width.
      if (img.src.startsWith('data:image/svg+xml;base64,')) {
        const svg = atob(img.src.split(',')[1]);
        const vb = svg.match(/viewBox="\s*[-\d.]+[\s,]+[-\d.]+[\s,]+([\d.]+)/);
        const sizes = [...svg.matchAll(/font-size(?:="|:\s*)([\d.]+)/g)].map(m => parseFloat(m[1]));
        if (vb && sizes.length) {
          const px = Math.min(...sizes) * w / parseFloat(vb[1]);
          if (px < 12 - 0.05) out.fails.push(`image ${img.alt.slice(0, 40)} text renders at ${px.toFixed(1)} px (minimum 12)`);
        }
      }
    }

    // A word whose characters sit on more than one line was split.
    const splitWords = (el, label) => {
      const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
      for (let n = walker.nextNode(); n; n = walker.nextNode()) {
        for (const m of n.textContent.matchAll(/\S+/g)) {
          if (label !== 'code' && m[0].includes('-')) continue;      // a hyphen is a fair break in prose
          const r = document.createRange();
          r.setStart(n, m.index); r.setEnd(n, m.index + m[0].length);
          const tops = new Set([...r.getClientRects()].map(x => Math.round(x.top)));
          if (tops.size > 1) out.fails.push(`${label} word split across lines: "${m[0].slice(0, 40)}"`);
        }
      }
    };
    for (const el of document.querySelectorAll('th, td')) splitWords(el, el.tagName.toLowerCase());
    for (const el of document.querySelectorAll('p code, li code, td code')) splitWords(el, 'code');

    for (const td of document.querySelectorAll('th, td'))
      if (td.scrollWidth > td.clientWidth + 1) out.fails.push(`table cell overflows: "${td.textContent.trim().slice(0, 40)}"`);
    for (const pre of document.querySelectorAll('pre'))
      if (pre.scrollWidth > pre.clientWidth + 1)
        (window.innerWidth >= 900 ? out.fails : out.notes).push(`pre scrolls sideways: "${pre.textContent.trim().slice(0, 40)}"`);
    return out;
  }, FAMILIES);
}

(async () => {
  const args = process.argv.slice(2);
  let shots = null;
  if (args[0] === '--shots') { shots = args[1]; args.splice(0, 2); fs.mkdirSync(shots, { recursive: true }); }
  if (!args.length) { console.error('usage: node brief/render_check.js [--shots DIR] <index.html>...'); process.exit(2); }
  const { chromium } = loadPlaywright();
  const browser = await chromium.launch();
  let failed = 0;
  for (const file of args) {
    const track = path.basename(path.dirname(path.dirname(path.resolve(file))));
    for (const w of WIDTHS) {
      const page = await browser.newPage({ viewport: { width: w, height: 1000 } });
      await page.goto('file://' + path.resolve(file));
      await page.evaluate(() => document.fonts.ready);
      const r = await inspect(page);
      for (const f of [...new Set(r.fails)]) { console.log(`FAIL ${track} @${w}: ${f}`); failed++; }
      for (const n of [...new Set(r.notes)]) console.log(`note ${track} @${w}: ${n}`);
      if (shots) await page.screenshot({ path: `${shots}/${track}-${w}.png`, fullPage: true });
      await page.close();
    }
  }
  await browser.close();
  console.log(failed ? `${failed} failure(s)` : 'OK');
  process.exit(failed ? 1 : 0);
})();
