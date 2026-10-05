<!-- layout: title
track: 2.1
minutes: 7 -->

<p class="track-code">Lab 2.1</p>
<h1 class="slide-title">Configure core<br>retrieval infrastructure</h1>
<p class="slide-subtitle"><strong>Tina</strong> cannot answer Cortex Bank's compliance questions yet: the documents are raw text. You chunk and index them, pin the model she answers with, and defend the chunking rule for the next document type.</p>
<div style="margin-top:auto;padding:10px 16px;background:rgba(255,255,255,0.12);border-radius:8px;border:1px solid rgba(255,255,255,0.25);font-size:13px;display:flex;align-items:center;gap:10px;max-width:420px;">
  <span style="font-size:18px;">&#8592;</span>
  <span><strong>Tip:</strong> Select <strong>Hide Instructions</strong> in the top bar to give the Brief full width.</span>
</div>

---

<!-- layout: problem -->
<!-- problem -->

<div class="col-left">
  <div class="terminal-block">
Q: Under Cortex's risk-scoring reference,
   what transaction limit, review level
   and escalation SLA apply to Tier 5
   accounts?

Tina, through fixed 512-token chunks:
"I apologize, but I cannot provide a
complete answer to your question. [...]
- Daily Velocity Limit: <span class="wrong">The threshold
  text is cut off and does not provide
  the complete transaction limit</span>
- Review Level: <span class="wrong">Not specified in the
  provided excerpt</span>
- Escalation SLA: <span class="wrong">Not specified in
  the provided excerpt</span>"
  </div>
</div>
<div class="col-right">
  <h2 class="slide-heading">The problem</h2>
  <p class="slide-body">The chunk Tina retrieved ends in the middle of the Tier 5 row:</p>
  <div class="terminal-block">
| Tier 5: Medium-High Risk
| $2,500,001.00 to
  $10,000,000.00
| <span class="wrong">Maximum of</span>   &lt;- chunk ends
  </div>
  <p class="slide-body">The rest of the row (100 transactions a day, a Level 3 Senior Analyst review, an 8-hour SLA) sits in the next chunk, which ranked outside her top 5. The document holds the answer. The chunking cut it in half.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div class="terminal-block">
strategy          keeps whole  breaks

fixed windows     nothing by   tables,
                  design       numbered
                               steps,
                               timelines
split at headings section text a unit
                               longer than
                               its section
preserve units    any unit you needs
                  define       explicit
                               boundaries
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">Chunking sets the ceiling</h2>
  <p class="slide-body">Tina answers from the top 5 chunks her retriever returns. When an answer is split across two chunks, she gets part of it and answers anyway.</p>
  <p class="slide-body">No retriever or model downstream can put the halves back together. The chunks you build here set the ceiling for every later track.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div class="terminal-block">
cortex-corpus-live  ->  cortex-corpus

Tina queries the alias, never the index.
Track 2.3 moves the alias to a candidate
embedding without changing her code.
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">The alias is the indirection layer</h2>
  <p class="slide-body"><code>cortex-corpus-live</code> points at <code>cortex-corpus</code> now. Later tracks swap what sits behind it, and Tina never changes her query target.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div class="terminal-block">
Build 1   chunk and index the corpus
          cortex-corpus, behind the alias
          cortex-corpus-live

Build 2   pin Tina's generation endpoint
          cortex-generation, a named copy
          of the platform model

Defend    the chunking rule for a new
          document type, from your numbers
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">In this track</h2>
  <p class="slide-body">The Defend asks how many of your chunks fit Tina's 4,000-token budget, from your Build 1 measurements, and which model answers through your Build 2 endpoint.</p>
</div>

---

<!-- layout: rule -->
<!-- rule -->

<h2 class="slide-heading">Decision rule</h2>
<p class="rule-caption">Take the first row that applies.</p>
<table class="rule-table">
  <tr><th>When</th><th>Chunking rule</th></tr>
  <tr><td>The document is shorter than one chunk</td><td>One chunk per document</td></tr>
  <tr><td>A structured unit runs longer than one chunk</td><td>Preserve whole units</td></tr>
  <tr><td>Long prose with headings and no oversize unit</td><td>Split at headings</td></tr>
  <tr><td>Uniform prose with nothing structured to protect</td><td>Fixed 512-token windows</td></tr>
</table>

---

<!-- layout: done -->

<h2 class="slide-heading" style="color:var(--white);">What done looks like</h2>
<div class="done-row">
  <div class="done-item">
    <span class="big-number">512</span>
    <span class="big-number-label">median chunk<br>tokens, at most</span>
  </div>
  <div class="done-item">
    <span class="big-number">3 of 4</span>
    <span class="big-number-label">structured units<br>kept whole</span>
  </div>
  <div class="done-item">
    <span class="big-number">3 of 5</span>
    <span class="big-number-label">procedure answers whole<br>in one top-5 chunk</span>
  </div>
  <div class="done-item">
    <span class="big-number">4 of 6</span>
    <span class="big-number-label">policy answers,<br>same test</span>
  </div>
</div>
<p class="rule-caption" style="color:var(--dark-grey);">Also: largest chunk 2,048 tokens at most; no top 5 over 4,000 tokens; <code>cortex-corpus-live</code> resolves. Build 2: <code>cortex-generation</code> pinned, the latest 3 traces through it, 2 of 3 held-out answers right.</p>

---

<!-- layout: next -->

<h2 class="slide-heading">Select Check, then open Build 1</h2>
<p style="opacity:0.8;font-size:18px;">Environment status:</p>
<div class="status-indicator">
  <div class="status-dot"></div>
  <span class="status-text">Provisioning, check back in a moment</span>
</div>
<p style="font-size:15px;opacity:0.75;max-width:52ch;text-align:center;">The indicator turns green when provisioning finishes. Select Check at any time and it reports which step is still running.</p>
