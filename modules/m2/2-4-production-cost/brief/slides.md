<!-- layout: title
track: 2.4
minutes: 8 -->

<p class="track-code">Lab 2.4</p>
<h1 class="slide-title">Production<br>cost</h1>
<p class="slide-subtitle">Every question <strong>Tina</strong> answers costs a generation call. You query the transaction log with ES|QL, cut repeat calls with a semantic cache, route lookups to a cheaper model, and defend the savings from your own numbers.</p>
<div style="margin-top:auto;padding:10px 16px;background:rgba(255,255,255,0.12);border-radius:8px;border:1px solid rgba(255,255,255,0.25);font-size:13px;display:flex;align-items:center;gap:10px;max-width:420px;">
  <span style="font-size:18px;">&#8592;</span>
  <span><strong>Tip:</strong> Select <strong>Hide Instructions</strong> in the top bar to give the Brief full width.</span>
</div>

---

<!-- layout: problem -->
<!-- problem -->

<div class="col-left">
  <div class="terminal-block">
Tina today, no cache

generation call 2477 ms
  How long must Cortex Bank keep
  customer identification records?

generation call 2205 ms
  What is the retention period for
  CIP records at Cortex Bank?

"Based on the provided documents, the
retention period for CIP (Customer
Identification Program) records at
Cortex Bank and Trust varies ..."
  </div>
</div>
<div class="col-right">
  <h2 class="slide-heading">The problem</h2>
  <p class="slide-body">Two paraphrases of one question, each a full generation call.</p>
  <p class="slide-body">Every call is billed. Analysts ask the same things in different words, and most of their questions are one-fact lookups a cheaper model could answer.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div class="terminal-block">
hit         a paraphrase of a cached question
            serve the cached answer, no call

near-miss   same domain, different question
            must miss and generate

single-hop  one fact, one clause: fast tier
multi-part  several sub-questions:
            strong tier
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">Key concepts</h2>
  <p class="slide-body"><strong>Semantic cache:</strong> match a new question to a stored one by embedding similarity, and serve the stored answer above a threshold.</p>
  <p class="slide-body"><strong>Threshold:</strong> too low and near-misses hit with the wrong answer; too high and paraphrases miss.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div class="terminal-block">
FROM cortex-transactions
| WHERE amount > ?threshold
    AND country == ?country
| WHERE DATE_DIFF("day", @timestamp,
                  NOW()) <= ?days

?days is a whole number: compare it
with a day count, not a time span
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">Parameters, not literals</h2>
  <p class="slide-body"><code>cortex-transactions</code> holds 2,000 transactions from the last 90 days. The check runs your three queries with its own parameters and compares the rows with a reference query.</p>
  <p class="slide-body">A value typed into the query only works for the values you tried.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div class="terminal-block">
Build 1   ES|QL over the transaction log
          filter, aggregation, weekly bucket

Build 2   semantic cache
          cache_lookup, cache_store,
          THRESHOLD

Build 3   route by complexity
          pick_tier(query): fast or strong

Defend    savings and routing,
          from your own numbers
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">In this track</h2>
  <p class="slide-body">Each Build check runs your code on queries it holds out. The Defend reads the hit rate the cache check measured and the fast-tier answer accuracy the router check measured.</p>
</div>

---

<!-- layout: rule -->
<!-- rule -->

<h2 class="slide-heading">Decision rule</h2>
<table class="rule-table">
  <tr><th>When</th><th>Then</th></tr>
  <tr><td>A query paraphrases one already answered</td><td>Serve the cached answer; no generation call</td></tr>
  <tr><td>Same domain, different question (a near-miss)</td><td>Miss and generate</td></tr>
  <tr><td>Fast-tier answer accuracy is 0.8 or higher</td><td>Route single-hop lookups to the fast tier</td></tr>
  <tr><td>Below 0.8, or nothing sent fast</td><td>Route nothing to the fast tier</td></tr>
  <tr><td>Always</td><td>Multi-part analysis goes to the strong tier</td></tr>
</table>
<p class="rule-caption">Rows are independent. Savings = <code>floor(daily volume × hit rate × cost per call in cents / 100)</code></p>

---

<!-- layout: done -->

<h2 class="slide-heading" style="color:var(--white);">What done looks like</h2>
<div class="done-row">
  <div class="done-item">
    <span class="big-number">3</span>
    <span class="big-number-label">ES|QL queries return the<br>reference rows, sums within 0.1%</span>
  </div>
  <div class="done-item">
    <span class="big-number">2 of 12</span>
    <span class="big-number-label">cache outcomes wrong at most<br>0 near-misses served</span>
  </div>
  <div class="done-item">
    <span class="big-number">10 of 12</span>
    <span class="big-number-label">held-out queries routed<br>to their tier, at least</span>
  </div>
  <div class="done-item">
    <span class="big-number">$1</span>
    <span class="big-number-label">Q1 tolerance<br>at your hit rate</span>
  </div>
</div>
<p class="rule-caption" style="color:var(--dark-grey);">Also: one document per miss, the env model per tier, a live fast-tier call. Q2 and Q3: fast-tier accuracy, 0.8.</p>

---

<!-- layout: next -->

<h2 class="slide-heading">Select Check, then open Build 1</h2>
<p style="opacity:0.8;font-size:18px;">Environment status:</p>
<div class="status-indicator">
  <div class="status-dot"></div>
  <span class="status-text">Provisioning, check back in a moment</span>
</div>
<p style="font-size:15px;opacity:0.75;max-width:52ch;text-align:center;">The indicator turns green when provisioning finishes. Select Check at any time and it reports which step is still running.</p>
