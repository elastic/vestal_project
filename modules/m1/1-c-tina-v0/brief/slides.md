<!-- layout: title -->

<p class="track-code">Capstone 1.C</p>
<h1 class="slide-title">Build Tina v0.<br>Then show which question earned the fast tier.</h1>
<p class="slide-subtitle"><strong>Tina</strong> is Cortex Bank's AI compliance assistant. This capstone puts Labs 1.1 to 1.4 together: a search tool, a ReAct loop, citations, and a routing call between two model tiers.</p>
<div style="margin-top:auto;padding:10px 16px;background:rgba(255,255,255,0.12);border-radius:8px;border:1px solid rgba(255,255,255,0.25);font-size:13px;display:flex;align-items:center;gap:10px;max-width:420px;">
  <span style="font-size:18px;">&#8592;</span>
  <span><strong>Tip:</strong> Select <strong>Hide Instructions</strong> in the top bar to give the Brief full width.</span>
</div>

---

<!-- layout: problem -->
<!-- problem -->

<div class="col-left">
  <div class="terminal-block">
User: What aggregated cash amount within
      a seven-day window triggers a
      structuring alert at Cortex Bank,
      and what fuzzy-match threshold does
      sanctions screening use for
      cross-border SWIFT messages?

Tina: ...triggers a structuring alert
      when aggregated cash transactions
      within a seven-day window reach
      **$7,500 USD**... we utilize a
      fuzzy-match threshold of **85%**.

<span class="label"># tools registered: 0   tool calls: 0</span>
<span class="label"># policy-001: $12,500   policy-006: 72 percent</span>
  </div>
</div>
<div class="col-right">
  <h2 class="slide-heading">The problem</h2>
  <p class="slide-body">Today Tina has no tools. Asked a held-out question on the fast tier, she answered with confidence and got both figures wrong. Neither came from a Cortex policy.</p>
</div>

---

<!-- layout: concept -->

<div class="col-text">
  <h2 class="slide-heading">The scenario</h2>
  <p class="slide-body">Analysts will ask Tina questions that each need two facts from <strong>two different policies</strong> in <code>cortex-policies</code>. The harness has a tool registry and a ReAct loop. The notebook's starter <code>search_policies</code> runs the search; you decide what it gives the model. Cortex pays for every token, and an analyst must see which policy each fact came from.</p>
</div>

---

<!-- layout: concept -->

<div class="col-text">
  <h2 class="slide-heading">Three runs per question</h2>
  <p class="slide-body">The same agent can answer a question correctly once and miss it the next time. <code>submit.py</code> runs each question <strong>3 times</strong> on the tier <code>choose_model</code> gives it. The check grades each question on a majority, <strong>2 of 3 runs</strong>, and reports how many runs were correct.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <table class="rule-table" style="font-size:15px;">
    <tr><th>Criterion</th><th>Target</th></tr>
    <tr><td>Questions with both correct values</td><td>3 of 3</td></tr>
    <tr><td>Questions citing each fact's policy, from retrieved chunks only</td><td>3 of 3</td></tr>
    <tr><td>Tool calls per run</td><td>at most 4</td></tr>
    <tr><td>Questions on the fast tier</td><td>at least 1</td></tr>
    <tr><td>Tokens per pass</td><td>under 9,000</td></tr>
    <tr><td>Tokens per pass (reported, not graded)</td><td>target 5,000</td></tr>
  </table>
</div>
<div class="col-text">
  <h2 class="slide-heading">The SLO</h2>
  <p class="slide-body">Graded rows count on 2 of a question's 3 runs. The target is reported only.</p>
</div>

---

<!-- layout: rule -->
<!-- rule -->

<h2 class="slide-heading">Decision rule</h2>
<p class="slide-body">Trust a question to the fast tier only if it was correct in every run there. Passing on 2 of 3 meets the grade, not the bar for trust, and tokens are a cost, not evidence. Keep those correct every time; move any that missed to the strong tier.</p>
<p class="rule-caption">Your own runs decide the answer.</p>

---

<!-- layout: done -->

<h2 class="slide-heading" style="color:var(--white);">What done looks like</h2>
<div class="done-row">
  <div class="done-item">
    <span class="big-number">3</span>
    <span class="big-number-label">questions correct<br>on 2 of 3 runs each</span>
  </div>
  <div class="done-item">
    <span class="big-number">1</span>
    <span class="big-number-label">question at least<br>on the fast tier</span>
  </div>
  <div class="done-item">
    <span class="big-number">9,000</span>
    <span class="big-number-label">tokens per pass,<br>under this ceiling</span>
  </div>
</div>

---

<!-- layout: next -->

<h2 class="slide-heading">Select Check, then open Build and Defend</h2>
<p style="opacity:0.8;font-size:18px;">Provisioning takes about 5 to 10 minutes. Environment status:</p>
<div class="status-indicator">
  <div class="status-dot"></div>
  <span class="status-text">Provisioning - check back in a moment</span>
</div>
