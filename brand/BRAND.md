# Elastic Brand Reference for ARA Decks

Read this before writing any `slides.md` or hand-authoring a deck.

---

## 1. Palette

| Token | Hex | Role |
|---|---|---|
| `--elastic-blue` | `#0B64DD` | Primary surface, emphasis, title backgrounds |
| `--white` | `#FFFFFF` | Most backgrounds, type on blue |
| `--light-teal` | `#48EFCF` | Single accent: correct answer, ready indicator, highlight |
| `--light-poppy` | `#FF957D` | Warnings, wrong-answer highlight |
| `--pink` | `#F04E98` | Categorical distinction in diagrams (use sparingly) |
| `--yellow` | `#FEC514` | Categorical distinction in diagrams (use sparingly) |
| `--midnight` | `#153385` | Depth, data surfaces |
| `--developer-blue` | `#101C3F` | Outlines, code frames, borders only |

**Proportion rule: 20/20/15/11/10/4.** Elastic Blue and white carry the slide. Light Teal points at the one thing that matters. Developer Blue is outline-only.

**Never use hex values that are not in tokens.css.** `build.py --check` fails on any unlisted hex.

---

## 2. Typography

| Role | Family | Weight |
|---|---|---|
| Slide titles and headlines | Space Grotesk | 700 |
| Body text, lists, captions | Inter | 400 |
| Inline emphasis | Inter | 600 |
| Numbers, code, track codes | Space Mono | 400 or 700 |

- Line heights: headline 1.14, body 1.55
- One weight per role per slide. No mixing weights.
- Body text at least 20 px at 1280 px viewport width.
- No Mier B anywhere: limited display license, not for this use.

**Numbers are the biggest type on a slide when the numbers are the point.**

---

## 3. Logos

Use only the 13 official SVG variants in `brand/logos/`.

| Background | Variant |
|---|---|
| Elastic Blue (dark) | `elastic-horizontal-white.svg` or `elastic-horizontal-color-reverse.svg` |
| White (light) | `elastic-horizontal-color.svg` |
| Small corner use | `elastic-glyph-white.svg` (on blue) or `elastic-glyph-color.svg` (on white) |

- Never recolor a logo.
- Never place a logo on a busy diagram.
- Minimum clear space: equal to the glyph height on all sides.

---

## 4. Diagram primitives

Use the shared SVG library in `brief/img/library/`. Same shapes, same colors, every deck.

| Element | Shape | Color |
|---|---|---|
| LLM | Rounded rect | Elastic Blue fill, white glyph |
| Embedding model | Rounded rect | Midnight fill, vector glyph |
| Reranker | Rounded rect | Midnight fill, ordered-bars glyph |
| Index | Cylinder | White fill, Developer Blue outline |
| Tool | Hexagon | Light Teal fill |
| Agent | Circle with loop | Elastic Blue + Developer Blue loop |
| User/Analyst | Figure outline | Developer Blue stroke |
| Arrows | Strokes | Developer Blue, `draw`-animatable |

---

## 5. Voice

- Second person, present tense. "You build" not "The learner builds."
- Sentence case. No title case in body text.
- No em-dashes. Use a comma, a colon, or a new sentence.
- No emoji.
- No marketing copy ("powerful," "seamless," "unlock").
- Cortex Bank and Trust context on every scenario slide.

---

## 6. Do and do not

**Do:**
- Put numbers in Space Mono and make them large when the numbers are the point.
- Use Light Teal for the one thing that matters per slide.
- Show a real or realistic failed output on the Problem slide.
- Keep body text under 60 words per slide.
- Use progressive reveal (`class="step"`) to build diagrams frame by frame.

**Do not:**
- Use any hex not in tokens.css.
- Use Mier B.
- Load any resource from the network at runtime.
- Auto-advance slides.
- Convey information by color alone (accessibility).
- Reference external URLs anywhere in the deck.
- Use any name other than Cortex Bank and Trust in scenario slides.
