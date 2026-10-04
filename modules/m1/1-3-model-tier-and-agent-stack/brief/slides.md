<!-- layout: title -->

<p class="track-code">Lab 1.3</p>
<h1 class="slide-title">Four versions of Tina.<br>Each one fails at exactly one thing.</h1>
<p class="slide-subtitle"><strong>Tina</strong> is Cortex Bank's AI compliance assistant, the system you build across this module. This track starts from zero: bare LLM call, context from Elasticsearch, a search tool, a ReAct loop.</p>
<div style="margin-top:auto;padding:10px 16px;background:rgba(255,255,255,0.12);border-radius:8px;border:1px solid rgba(255,255,255,0.25);font-size:13px;display:flex;align-items:center;gap:10px;max-width:420px;">
  <span style="font-size:18px;">&#8592;</span>
  <span><strong>Tip:</strong> Select <strong>Hide Instructions</strong> in the top bar to give the Brief full width.</span>
</div>

---

<!-- layout: problem -->

<div class="col-left">
  <div class="terminal-block">
User: What is Cortex Bank's internal
      threshold for filing a Suspicious
      Activity Report when the suspect is
      known, and is a $4,000 suspicious
      transfer by a known customer
      reportable?

Tina: Cortex Bank's internal threshold
      for filing a Suspicious Activity
      Report (SAR) when the suspect is
      known is <span class="wrong">$5,000</span>. A single $4,000
      suspicious transfer by a known
      customer would generally <span class="wrong">not</span> meet
      the monetary ...
  </div>
</div>
<div class="col-right">
  <h2 class="slide-heading">The problem</h2>
  <p class="slide-body">Tina answered confidently from her training: $5,000 is the federal figure. She consulted no source. Cortex's own threshold is <strong>$3,500</strong>, in policy-003, so this $4,000 transfer must be reported. Cortex would miss the filing.</p>
  <p class="slide-body">You will see this yourself in Build 2, stage 1.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <img src="img/tier-axes.svg" alt="Four tier axes: cost per 1,000 requests, latency p50, capability on task, deployment constraints" style="max-width:100%;max-height:340px;">
</div>
<div class="col-text">
  <h2 class="slide-heading">What a tier is</h2>
  <p class="slide-body">Four axes: <strong>cost</strong> per 1,000 requests, <strong>latency</strong> p50, <strong>capability</strong> on your task, and <strong>deployment constraints</strong> such as data residency or a limit on completion tokens per reply. A benchmark on the wrong axis picks the wrong tier.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <img src="img/tier-constraints.svg" alt="Three Cortex constraints: data residency, a cost ceiling and a completion-token ceiling. Each sandbox gets one." style="max-width:100%;max-height:340px;">
</div>
<div class="col-text">
  <h2 class="slide-heading">Choose by constraint, not by benchmark</h2>
  <p class="slide-body">Cortex has three possible constraints: a <strong>data-residency</strong> rule, a <strong>cost ceiling</strong> per 1,000 requests, and a <strong>completion-token ceiling</strong> on completion tokens per reply. You will be given one. Residency is a rule; the ceilings are decided by what you measure. Completion tokens include any reasoning a model does before it answers.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <img src="../../../../brief/img/library/stage-1.svg" alt="Stage 1: User sends a message; LLM generates an answer with no retrieval" style="max-width:100%;max-height:280px;">
</div>
<div class="col-text">
  <h2 class="slide-heading">Stage 1: bare completion</h2>
  <p class="slide-body">User &rarr; LLM &rarr; answer. No source consulted. The model generates from training weights. Gap: <strong>no source</strong>.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <img src="../../../../brief/img/library/stage-2.svg" alt="Stage 2: the cortex-policies index is retrieved before the LLM call and injected into the prompt" style="max-width:100%;max-height:280px;">
</div>
<div class="col-text">
  <h2 class="slide-heading">Stage 2: context injection</h2>
  <p class="slide-body">Retrieve top-3 chunks from <code>cortex-policies</code>, inject into the prompt. The model can cite sources. Gap: it can only read what <strong>you pre-loaded</strong>. It cannot request different documents mid-answer.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <img src="../../../../brief/img/library/stage-3.svg" alt="Stage 3: the LLM calls a search_policies tool during the conversation on demand" style="max-width:100%;max-height:280px;">
</div>
<div class="col-text">
  <h2 class="slide-heading">Stage 3: tool calling</h2>
  <p class="slide-body">Register <code>search_policies(query)</code>. The model calls it on demand. <code>finish_reason: tool_calls</code> triggers your dispatch; the result returns as a <code>role: tool</code> message. Gap: <strong>one shot</strong>. A two-hop question needs two searches.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <img src="../../../../brief/img/library/stage-4.svg" alt="Stage 4: a loop arrow connects answer back to LLM, enabling multiple tool calls" style="max-width:100%;max-height:280px;">
</div>
<div class="col-text">
  <h2 class="slide-heading">Stage 4: ReAct loop</h2>
  <p class="slide-body">Handle <code>tool_calls</code>, append each result, continue until <code>finish_reason: stop</code>. The model reasons, searches again, and synthesizes across multiple calls. This is the target architecture.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div class="terminal-block" style="padding:var(--s-4);">
<span class="label"># assistant message</span>
{"role": "assistant",
 "tool_calls": [{"id": "call_abc",
   "function": {"name": "search_policies",
     "arguments":
"{\"query\": \"SAR threshold known suspect\"}"
   }}]}

<span class="label"># your dispatch returns:</span>
{"role": "tool", "tool_call_id": "call_abc",
 "content":
   "[{\"policy_id\": \"policy-003\", ...}]"}
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">The tool-call protocol</h2>
  <p class="slide-body">Four messages: <strong>assistant</strong> with <code>tool_calls</code>, your code dispatches, a <strong>tool</strong> message with the result, the model continues. You implement the dispatch loop.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div class="terminal-block">
<span class="label"># tool schema</span>
{"name": "search_policies",
 "description": "Search Cortex AML policies",
 "parameters": {"type": "object",
   "properties": {
     "query": {"type": "string"}},
   "required": ["query"]}}

<span class="label"># Elasticsearch query it runs</span>
{"query": {"match": {
  "body_semantic":
    "SAR threshold known suspect"}}}
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">Your tool is a search</h2>
  <p class="slide-body"><code>search_policies(query)</code> runs semantic search over <code>cortex-policies</code>. You write the schema and the dispatch. The harness in <code>/opt/ara/lib/tina/</code> handles the LLM loop.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <table class="rule-table" style="font-size:15px;">
    <tr><th>Stage</th><th>What it cannot do</th></tr>
    <tr><td>1: bare completion</td><td>No source consulted</td></tr>
    <tr><td>2: context injection</td><td>Cannot choose documents mid-answer</td></tr>
    <tr><td>3: tool calling</td><td>Cannot loop; one shot only</td></tr>
    <tr><td>4: ReAct loop</td><td>(target; no gap for this task)</td></tr>
  </table>
</div>
<div class="col-text">
  <h2 class="slide-heading">What each stage cannot do</h2>
  <p class="slide-body">The Defend asks which gap applied at each stage. Your recorded trace confirms it.</p>
</div>

---

<!-- layout: rule -->
<!-- rule -->

<h2 class="slide-heading">Decision rule</h2>
<table class="rule-table">
  <tr><th>Your constraint</th><th>Choose</th></tr>
  <tr><td>Data residency</td><td>Strong tier: fast has no EU region</td></tr>
  <tr><td>Cost ceiling $0.40 per 1,000</td><td>Under the ceiling; if both or neither, cheaper</td></tr>
  <tr><td>Completion-token ceiling 200 per reply</td><td>Under the ceiling; if both, cheaper; if neither, fewer tokens</td></tr>
  <tr><td>Stage gaps</td><td>What the stage before could not do, per your traces</td></tr>
</table>
<p class="rule-caption">Your own measurements decide each row.</p>

---

<!-- layout: done -->

<h2 class="slide-heading" style="color:var(--white);">What done looks like</h2>
<div class="done-row">
  <div class="done-item">
    <span class="big-number">5</span>
    <span class="big-number-label">runs per tier<br>(Build 1)</span>
  </div>
  <div class="done-item">
    <span class="big-number">2</span>
    <span class="big-number-label">tool calls in stage 4<br>both gold values returned</span>
  </div>
  <div class="done-item">
    <span class="big-number">4</span>
    <span class="big-number-label">stage traces<br>grounded from stage 2</span>
  </div>
</div>

---

<!-- layout: next -->

<h2 class="slide-heading">Select Check, then open Build 1</h2>
<p style="opacity:0.8;font-size:18px;">Environment status:</p>
<div class="status-indicator">
  <div class="status-dot"></div>
  <span class="status-text">Provisioning - check back in a moment</span>
</div>
