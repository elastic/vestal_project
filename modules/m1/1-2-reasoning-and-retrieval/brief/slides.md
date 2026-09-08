<!-- layout: title -->

<p class="track-code">Lab 1.2</p>
<h1 class="slide-title">Tina's eligibility decisions validate.<br>Some of them are wrong.</h1>
<p class="slide-subtitle"><strong>Tina</strong> is Cortex Bank's AI compliance assistant. Her decisions pass schema validation, but the compliance team found errors that the schema cannot catch. In this track you build a semantic validator and Tina's first retrieval pipeline.</p>

---

<!-- layout: problem -->

<div class="col-left">
  <div class="terminal-block">
Decision: {
  "subject": "Sandra Park",
  "threshold": <span class="wrong">5000</span>,
  "direction": "<span class="wrong">above</span>",
  "reportable": false
}

JSON Schema: <span style="color:var(--light-teal);">VALID</span>
Policy-003:  threshold=10000, direction="at or above"
  </div>
</div>
<div class="col-right">
  <h2 class="slide-heading">The problem</h2>
  <p class="slide-body">The decision is schema-valid. Both values are wrong. The CTR threshold is <strong>$10,000</strong>, not $5,000. The direction is <strong>"at or above"</strong>, not "above". Cortex files the wrong reports.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <table class="rule-table" style="font-size:15px;">
    <tr><th>A reasoning trace</th></tr>
    <tr><td>1. Retrieve policy-003 from index</td></tr>
    <tr><td>2. Parse threshold: $10,000</td></tr>
    <tr class="correct"><td>3. Compare: $9,500 <span class="wrong">above</span> $10,000 → false ✗</td></tr>
    <tr><td>4. Set reportable: false</td></tr>
    <tr><td>5. Return decision JSON</td></tr>
  </table>
</div>
<div class="col-text">
  <h2 class="slide-heading">A reasoning trace, step by step</h2>
  <p class="slide-body">Step 3 uses the wrong comparison operator. "Above" excludes the boundary. "At or above" includes it. The schema says nothing about which operator is correct.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <table class="rule-table" style="font-size:14px;">
    <tr><th>JSON Schema can assert</th><th>JSON Schema cannot assert</th></tr>
    <tr><td>threshold is a number</td><td>threshold matches the policy value</td></tr>
    <tr><td>direction is a string</td><td>direction uses the correct operator</td></tr>
    <tr><td>reportable is a boolean</td><td>reportable follows from the facts</td></tr>
    <tr><td>all required fields present</td><td>against what source?</td></tr>
  </table>
</div>
<div class="col-text">
  <h2 class="slide-heading">Schema checks shape; semantics check truth</h2>
  <p class="slide-body">Schema validation checks form, not facts. Semantic validity requires comparing the decision's claims against the authoritative source.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <img src="../../../../brief/img/library/index.svg" alt="cortex-policies Elasticsearch index" style="max-height:180px;max-width:180px;">
  <div style="text-align:center;font-family:var(--font-code);font-size:13px;margin-top:8px;color:var(--dark-grey);">cortex-policies</div>
  <div style="text-align:center;font-size:13px;margin-top:4px;color:var(--ink);">19 policy documents<br>+ risk-scoring reference</div>
</div>
<div class="col-text">
  <h2 class="slide-heading">The source is in Elasticsearch</h2>
  <p class="slide-body">Retrieve the governing rule from <code>cortex-policies</code> using a semantic search on <code>body_semantic</code>. Compare the decision's threshold and direction against the retrieved text. That is semantic validation.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div style="display:flex;flex-direction:column;gap:12px;padding:16px;">
    <div style="background:var(--light-teal);border-radius:8px;padding:12px;text-align:center;">
      <div style="font-family:var(--font-code);font-size:12px;color:var(--developer-blue);">Index update</div>
      <div style="font-family:var(--font-code);font-size:22px;font-weight:700;color:var(--developer-blue);">~1–3 s</div>
      <div style="font-size:12px;color:var(--developer-blue);">Next query sees new value</div>
    </div>
    <div style="font-size:13px;text-align:center;color:var(--dark-grey);">PUT /cortex-policies/_doc/policy-003 → refresh → search</div>
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">What retrieval changes</h2>
  <p class="slide-body">Update the document in Elasticsearch. The next retrieval sees the new value within seconds. The model's weights are untouched. No retraining pipeline required.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div style="display:flex;flex-direction:column;gap:12px;padding:16px;">
    <div style="background:var(--midnight);border-radius:8px;padding:12px;text-align:center;">
      <div style="font-family:var(--font-code);font-size:12px;color:rgba(255,255,255,0.6);">Training run</div>
      <div style="font-family:var(--font-code);font-size:22px;font-weight:700;color:var(--white);">Days +</div>
      <div style="font-size:12px;color:rgba(255,255,255,0.6);">Data pipeline + GPU time + eval</div>
    </div>
    <div style="font-size:13px;text-align:center;color:var(--dark-grey);">Collect data → train → evaluate → deploy</div>
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">What fine-tuning changes</h2>
  <p class="slide-body">Fine-tuning bakes updated knowledge into the model's weights. The data pipeline, training run, and evaluation cycle take days. Suitable when the update cadence is low and the propagation window is acceptable.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <table class="rule-table" style="font-size:14px;">
    <tr><th>Cadence</th><th>Approach</th></tr>
    <tr class="correct"><td>Weekly updates</td><td>Retrieval — propagates in seconds</td></tr>
    <tr><td>Annual updates</td><td>Depends on your measured latency</td></tr>
  </table>
  <p style="font-size:12px;color:var(--dark-grey);margin-top:8px;">Propagation time is the deciding variable.</p>
</div>
<div class="col-text">
  <h2 class="slide-heading">Propagation time is the deciding variable</h2>
  <p class="slide-body">Your sandbox has a seeded change cadence. Measure how fast your pipeline propagates a policy update, then decide whether retrieval keeps pace. You will be given one cadence.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div style="display:flex;flex-direction:column;gap:8px;padding:16px;font-size:13px;">
    <div style="display:flex;align-items:center;gap:8px;background:var(--light-grey);border-radius:6px;padding:8px 12px;">
      <span style="font-family:var(--font-code);color:var(--elastic-blue);">1.</span>
      <span>Semantic search: <code>body_semantic</code>, k=3</span>
    </div>
    <div style="text-align:center;color:var(--dark-grey);">↓</div>
    <div style="display:flex;align-items:center;gap:8px;background:var(--light-grey);border-radius:6px;padding:8px 12px;">
      <span style="font-family:var(--font-code);color:var(--elastic-blue);">2.</span>
      <span>Filter: <code>effective_date &lt;= now</code></span>
    </div>
    <div style="text-align:center;color:var(--dark-grey);">↓</div>
    <div style="display:flex;align-items:center;gap:8px;background:var(--light-grey);border-radius:6px;padding:8px 12px;">
      <span style="font-family:var(--font-code);color:var(--elastic-blue);">3.</span>
      <span>Inject top-3 context into prompt</span>
    </div>
    <div style="text-align:center;color:var(--dark-grey);">↓</div>
    <div style="display:flex;align-items:center;gap:8px;background:var(--light-grey);border-radius:6px;padding:8px 12px;">
      <span style="font-family:var(--font-code);color:var(--elastic-blue);">4.</span>
      <span>LLM answers with source</span>
    </div>
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">Building the pipeline</h2>
  <p class="slide-body">Four steps: semantic search, date filter, context injection, LLM call. You write the query in Build 2. The filter ensures Tina sees only current policy versions.</p>
</div>

---

<!-- layout: rule -->
<!-- rule -->

<h2 class="slide-heading">Decision rule</h2>
<table class="rule-table">
  <tr><th>Cadence</th><th>Propagation latency</th><th>Approach</th></tr>
  <tr class="correct"><td>Weekly</td><td>Any</td><td>Retrieval</td></tr>
  <tr><td>Annual</td><td>Under 60 s</td><td>Retrieval</td></tr>
  <tr><td>Annual</td><td>Over 60 s</td><td>Fine-tuning + retrieval</td></tr>
</table>
<p class="rule-caption">Your Defend answers derive from your seeded cadence and your measured propagation latency.</p>

---

<!-- layout: done -->

<h2 class="slide-heading" style="color:var(--white);">What done looks like</h2>
<div class="done-row">
  <div class="done-item">
    <span class="big-number">3/3</span>
    <span class="big-number-label">planted errors caught<br>0 false positives</span>
  </div>
  <div class="done-item">
    <span class="big-number">≥0.80</span>
    <span class="big-number-label">precision@3 on<br>5 held-out queries</span>
  </div>
  <div class="done-item">
    <span class="big-number">✓</span>
    <span class="big-number-label">updated threshold<br>visible after PUT</span>
  </div>
</div>

---

<!-- layout: next -->

<h2 class="slide-heading">Select Next, then open Build 1</h2>
<p style="opacity:0.8;font-size:18px;">Environment status:</p>
<div class="status-indicator">
  <div class="status-dot"></div>
  <span class="status-text">Provisioning — check back in a moment</span>
</div>
