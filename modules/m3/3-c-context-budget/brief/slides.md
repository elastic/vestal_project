<!-- layout: title
track: 3.C
minutes: 5 -->

<p class="track-code">Capstone 3.C</p>
<h1 class="slide-title">Meet the<br>context budget</h1>
<p class="slide-subtitle">Cortex Bank and Trust's compliance desk puts about twenty questions an hour to <strong>Tina</strong>. Every answer is read by an analyst who acts on it.</p>
<div style="margin-top:auto;padding:10px 16px;background:rgba(255,255,255,0.12);border-radius:8px;border:1px solid rgba(255,255,255,0.25);font-size:13px;display:flex;align-items:center;gap:10px;max-width:420px;">
  <span style="font-size:18px;">&#8592;</span>
  <span><strong>Tip:</strong> Select <strong>Hide Instructions</strong> in the top bar to give the Brief full width.</span>
</div>

---

<!-- layout: problem -->
<!-- problem -->

<div class="col-left">
  <div class="terminal-block">
$ submit.py --limit 2     # the start state, unchanged

  precision@10            <span class="wrong">0.417</span>   (target 0.80 on the held-out set)
    policy              0.400
    case                <span class="wrong">0.150</span>
    sar                 0.700
  peak context            <span class="wrong">9909 tokens</span>   (budget 6000, ceiling per question)
  over budget             <span class="wrong">5 question(s)</span>   (target zero)
  unsupported claims      <span class="wrong">8</span>   (target at most 1)
  </div>
</div>
<div class="col-right">
  <h2 class="slide-heading">The problem</h2>
  <div class="terminal-block">
# pipeline.py, as it ships
route:  H.ALL_INDEXES, semantic, size 10
filter: none
PACK_STRATEGY = "naive"
attribute, guard: return nothing
  </div>
  <p class="slide-body">Tina's own dev run, before any change. One search across all three indices, every result packed whole, no claim tied to a passage.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div class="terminal-block">
where the questions come from

  policy library     requirements, thresholds
  case files         facts from one case
  SAR narratives     findings buried in long reports

  some ask for something on file
  some ask for something that is not
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">Three sources, one desk</h2>
  <p class="slide-body">The questions mix all three sources. Some of them the corpus cannot answer, and the desk cannot tell which before it asks.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div class="terminal-block">
an invented figure     analyst acts on it      <span class="wrong">costly</span>
a declined answer      analyst looks it up     cheap
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">What a wrong answer costs</h2>
  <p class="slide-body">A figure Tina invented costs more than an answer she declined to give. A question the corpus cannot answer has to be held back, with no figure in the response.</p>
</div>

---

<!-- layout: rule -->

<h2 class="slide-heading">The SLO: retrieval and context</h2>
<table class="rule-table">
  <tr><th>Target</th><th>Value</th></tr>
  <tr><td>Precision@10 on 17 answerable questions</td><td>at least 0.80</td></tr>
  <tr><td>Context per question</td><td>at most your budget, every question</td></tr>
  <tr><td>The store</td><td><code>cortex-cases</code> mapping unchanged</td></tr>
</table>
<p class="rule-caption">Your budget is 6,000 or 9,000 tokens, seeded per sandbox.</p>

---

<!-- layout: rule -->

<h2 class="slide-heading">The SLO: answers</h2>
<table class="rule-table">
  <tr><th>Target</th><th>Value</th></tr>
  <tr><td>Exact figure in the answer</td><td>at least 14 of 17</td></tr>
  <tr><td>Claims with no passage behind them</td><td>at most 1</td></tr>
  <tr><td>3 unanswerable questions</td><td>all held back, zero figures</td></tr>
</table>
<p class="rule-caption">The unanswerable row has no tolerance.</p>

---

<!-- layout: rule -->
<!-- rule -->

<h2 class="slide-heading">Decision rule</h2>
<table class="rule-table">
  <tr><th>Question</th><th>Read</th><th>The answer</th></tr>
  <tr><td>Q1: lever that moved precision most</td><td><code>lever deltas (precision)</code></td><td>Largest delta; packing, attribution and guardrails count as one. None clears 0.005: no lever</td></tr>
  <tr><td>Q2: class with the most context</td><td>averages under <code>peak context</code></td><td>Largest average. All three within 5%: no class</td></tr>
</table>
<p class="rule-caption">Your own measurements decide each row.</p>

---

<!-- layout: done -->

<h2 class="slide-heading" style="color:var(--white);">What done looks like</h2>
<div class="done-row">
  <div class="done-item">
    <span class="big-number">0.80</span>
    <span class="big-number-label">precision@10 on<br>17 answerable questions</span>
  </div>
  <div class="done-item">
    <span class="big-number">14/17</span>
    <span class="big-number-label">answers with<br>the exact figure</span>
  </div>
  <div class="done-item">
    <span class="big-number">0</span>
    <span class="big-number-label">invented figures on<br>unanswerable questions</span>
  </div>
</div>
<p class="rule-caption" style="color:var(--dark-grey);">No index over 1.5 times the largest one built. Then you defend which levers you pulled, from your own measurements.</p>

---

<!-- layout: next -->

<h2 class="slide-heading">Select Check, then open the Build</h2>
<p style="opacity:0.8;font-size:18px;">Environment status:</p>
<div class="status-indicator">
  <div class="status-dot"></div>
  <span class="status-text">Provisioning, check back in a moment</span>
</div>
<p style="font-size:15px;opacity:0.75;max-width:52ch;text-align:center;">The indicator turns green when provisioning finishes, usually in under 10 minutes. Select Check at any time and it reports which step is still running.</p>
