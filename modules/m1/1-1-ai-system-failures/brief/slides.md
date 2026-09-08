<!-- layout: title -->

<p class="track-code">Lab 1.1</p>
<h1 class="slide-title">Tina answered three compliance questions this morning.<br>All three were wrong in different ways.</h1>
<p class="slide-subtitle"><strong>Tina</strong> is Cortex Bank's AI compliance assistant. In this track you diagnose her failures and repair the system prompt that caused them.</p>
<div style="margin-top:auto;padding:10px 16px;background:rgba(255,255,255,0.12);border-radius:8px;border:1px solid rgba(255,255,255,0.25);font-size:13px;display:flex;align-items:center;gap:10px;max-width:420px;">
  <span style="font-size:18px;">&#8592;</span>
  <span><strong>Tip:</strong> Select <strong>Hide Instructions</strong> in the top bar to give the Brief full width.</span>
</div>

---

<!-- layout: problem -->

<div class="col-left">
  <div class="terminal-block">
User: What is Cortex Bank's CTR threshold?

Tina: The CTR threshold is <span class="wrong">$5,000</span> for cash
      transactions. A $9,500 deposit
      would be reportable.
  </div>
</div>
<div class="col-right">
  <h2 class="slide-heading">The problem</h2>
  <p class="slide-body">Tina answered confidently. The threshold is <strong>$10,000</strong> from policy-003. Cortex files reports on the wrong transactions if this ships.</p>
  <p class="slide-body">This is one of three failures you will diagnose today.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <img src="../../../../brief/img/library/llm.svg" alt="LLM: generates text" style="max-width:100px;"> &nbsp;&nbsp;
  <img src="../../../../brief/img/library/embedding-model.svg" alt="Embedding model: positions text in a vector space" style="max-width:100px;"> &nbsp;&nbsp;
  <img src="../../../../brief/img/library/reranker.svg" alt="Reranker: orders candidate documents" style="max-width:100px;">
</div>
<div class="col-text">
  <h2 class="slide-heading">Three model types, three jobs</h2>
  <p class="slide-body"><strong>LLM</strong> generates text. <strong>Embedding model</strong> positions text in a vector space. <strong>Reranker</strong> scores and orders candidate documents. Each type has one job. Giving it the wrong job produces a distinct failure pattern.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div class="terminal-block" style="font-size:13px;">
User: What is the CTR threshold?

Response from embedding endpoint:
[0.023, -0.451, 0.887, 0.112,
 -0.334, 0.556, 0.091, ...]
(768 floats — not an answer)
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">When the wrong model gets the job</h2>
  <p class="slide-body">Ask an embedding model to "answer" a question and it returns a vector. The UI may show nothing, or raw numbers. No error — just the wrong output type for the task.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div class="terminal-block" style="font-size:13px;">
Tina: The threshold is <span class="wrong">$5,000</span>.
      A $9,500 deposit is reportable.

policy-003 (actual text):
"Currency Transaction Reports are
 required for cash transactions
 exceeding $10,000..."
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">Hallucination is confident</h2>
  <p class="slide-body">The $5,000 answer has no signal that it is wrong. Same format, same confidence, wrong value. The only way to catch it is to compare against the authoritative source.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div class="terminal-block" style="font-size:13px;">
{
  "answer": "SAR filing deadline: <span class="wrong">45 days</span>",
  "policy_id": "policy-011",
  "confidence": "high"
}

policy-011 (actual):
"SARs must be filed within
 30 calendar days..."
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">Schema-valid is not correct</h2>
  <p class="slide-body">The output has the right shape — JSON with all required fields. But the value is wrong: 45 days, not 30. Schema validation passes. Semantic validation catches it. This sets up track 1.2.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <img src="../../../../brief/img/library/prompt-anatomy.svg" alt="System prompt anatomy: four regions — role, output schema, constraints, grounding instruction" style="max-width:100%;max-height:300px;">
</div>
<div class="col-text">
  <h2 class="slide-heading">Anatomy of a system prompt</h2>
  <p class="slide-body">A well-structured prompt has four regions: <strong>Role</strong> (who Tina is), <strong>Schema</strong> (required output format), <strong>Constraints</strong> (rules to follow), <strong>Grounding instruction</strong> (cite retrieved text). Remove any one and Tina's behavior changes.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div class="terminal-block" style="font-size:13px;">
# Ablation: remove each element, re-run 6 questions
# Record how many stay grounded.

Element removed    | Grounded
role               | ? / 6
schema             | ? / 6
constraints        | ? / 6
grounding          | ? / 6   ← your results will differ
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">How you will prove a fix</h2>
  <p class="slide-body">The check runs your prompt against 6 held-out questions, then re-runs with each prompt element removed. The element whose removal drops the grounded count most is the decisive one. Your ablation results decide the Defend answer.</p>
</div>

---

<!-- layout: rule -->
<!-- rule -->

<h2 class="slide-heading">Decision rule</h2>
<table class="rule-table">
  <tr><th>Prompt element removed</th><th>Grounded pass rate drops most</th><th>Therefore</th></tr>
  <tr>
    <td>Element A</td><td>&#x2193; biggest drop</td><td>Element A was decisive</td>
  </tr>
  <tr>
    <td>Element B</td><td>&#x2193; smaller drop</td><td>Element B was not decisive</td>
  </tr>
  <tr>
    <td>Element C or D</td><td>&#x2193; smallest drop</td><td>Those were not decisive</td>
  </tr>
</table>
<p class="rule-caption">Which element is "A" depends on which one your prompt was missing. Your ablation results answer it — not general knowledge.</p>

---

<!-- layout: done -->

<h2 class="slide-heading" style="color:var(--white);">What done looks like</h2>
<div class="done-row">
  <div class="done-item">
    <span class="big-number">3</span>
    <span class="big-number-label">diagnoses recorded<br>all endpoints invoked (Build 1)</span>
  </div>
  <div class="done-item">
    <span class="big-number">5<span style="font-size:0.5em;">/6</span></span>
    <span class="big-number-label">grounded responses<br>all 6 schema-valid (Build 2)</span>
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
