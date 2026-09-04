<!-- layout: title -->
<section class="slide" data-layout="title">
  <p class="track-code">Lab 1.3</p>
  <h1 class="slide-title">Four versions of Tina.<br>Each one fails at exactly one thing.</h1>
  <p class="slide-subtitle">Build Tina from a bare completion to a ReAct agent on Elasticsearch.</p>
</section>

---

<!-- layout: problem -->
<section class="slide" data-layout="problem">
  <div class="col-left">
    <div class="terminal-block">
User: What is Cortex Bank's CTR threshold,
      and is a $9,500 cash deposit reportable?

Tina: The Currency Transaction Report (CTR)
      threshold is typically $5,000 for cash
      deposits. A $9,500 deposit would
      <span class="wrong">likely be reportable</span> depending on
      your institution's policies.
    </div>
  </div>
  <div class="col-right">
    <h2 class="slide-heading">The problem</h2>
    <p class="slide-body">Tina answered confidently. She has no source. The threshold is <strong>$10,000</strong> from policy-003, and she gave the wrong number. Cortex files reports on the wrong transactions.</p>
    <p class="slide-body">You will see this yourself in Build 1, stage 1.</p>
  </div>
</section>

---

<!-- layout: concept -->
<section class="slide" data-layout="concept">
  <div class="col-diagram">
    <img src="../img/tier-axes.svg" alt="Four tier axes: cost per 1,000 requests, latency p50, capability on the task, deployment constraints such as residency" style="max-width:100%;max-height:340px;">
  </div>
  <div class="col-text">
    <h2 class="slide-heading">What a tier is</h2>
    <p class="slide-body">Four axes matter for Cortex: <strong>cost</strong> per 1,000 requests, <strong>latency</strong> p50, <strong>capability</strong> on the task, and <strong>deployment constraints</strong> such as data residency.</p>
    <p class="slide-body">A benchmark on the wrong axis picks the wrong tier.</p>
  </div>
</section>

---

<!-- layout: concept -->
<section class="slide" data-layout="concept">
  <div class="col-diagram">
    <img src="../img/tier-constraints.svg" alt="Three Cortex constraints: data residency rules out one region, cost ceiling rules out the expensive tier, accuracy floor rules out the cheap tier" style="max-width:100%;max-height:340px;">
  </div>
  <div class="col-text">
    <h2 class="slide-heading">Choose by constraint, not by benchmark</h2>
    <p class="slide-body">Cortex has three possible constraints: a <strong>data-residency</strong> rule that forbids one model region, a <strong>cost ceiling</strong> per 1,000 requests, and an <strong>accuracy floor</strong> on structured output.</p>
    <p class="slide-body">Each constraint rules out a different tier. You will be given one. Measure both, then decide.</p>
  </div>
</section>

---

<!-- layout: concept -->
<section class="slide" data-layout="concept">
  <div class="col-diagram">
    <img src="../../../../brief/img/library/stage-1.svg" alt="Stage 1: User sends a message, the LLM generates an answer directly with no retrieval" style="max-width:100%;max-height:300px;">
  </div>
  <div class="col-text">
    <h2 class="slide-heading">Stage 1: bare completion</h2>
    <p class="slide-body">User &rarr; LLM &rarr; answer. No source consulted. The model generates from training data, which may be stale, wrong, or hallucinated.</p>
    <p class="slide-body">Gap: <strong>no source</strong>.</p>
  </div>
</section>

---

<!-- layout: concept -->
<section class="slide" data-layout="concept">
  <div class="col-diagram">
    <img src="../../../../brief/img/library/stage-2.svg" alt="Stage 2: the cortex-policies index is retrieved before the LLM call and injected into the prompt as context" style="max-width:100%;max-height:300px;">
  </div>
  <div class="col-text">
    <h2 class="slide-heading">Stage 2: context injection</h2>
    <p class="slide-body">Retrieve the top-3 chunks from <code>cortex-policies</code> before the call. Inject them into the prompt. The model can now cite sources.</p>
    <p class="slide-body">Gap: the model can only read what <strong>you pre-loaded</strong>. It cannot request different documents mid-answer.</p>
  </div>
</section>

---

<!-- layout: concept -->
<section class="slide" data-layout="concept">
  <div class="col-diagram">
    <img src="../../../../brief/img/library/stage-3.svg" alt="Stage 3: the LLM can call a search_policies tool during the conversation; finish_reason tool_calls triggers the dispatch" style="max-width:100%;max-height:300px;">
  </div>
  <div class="col-text">
    <h2 class="slide-heading">Stage 3: tool calling</h2>
    <p class="slide-body">Register <code>search_policies(query)</code> as a tool. The model calls it on demand. <code>finish_reason: tool_calls</code> triggers your dispatch; the result comes back as a <code>role: tool</code> message.</p>
    <p class="slide-body">Gap: <strong>one shot</strong>. A two-hop question needs two searches; the model cannot yet loop.</p>
  </div>
</section>

---

<!-- layout: concept -->
<section class="slide" data-layout="concept">
  <div class="col-diagram">
    <img src="../../../../brief/img/library/stage-4.svg" alt="Stage 4: a loop arrow connects the answer back to the LLM, creating the ReAct loop where the model can reason and call tools multiple times" style="max-width:100%;max-height:300px;">
  </div>
  <div class="col-text">
    <h2 class="slide-heading">Stage 4: ReAct loop</h2>
    <p class="slide-body">Handle <code>tool_calls</code>, append each tool result, continue until <code>finish_reason: stop</code>. The model can now reason, search again, and synthesize across multiple tool calls.</p>
    <p class="slide-body">Gap: none for two-hop compliance questions. This is the target architecture.</p>
  </div>
</section>

---

<!-- layout: concept -->
<section class="slide" data-layout="concept">
  <div class="col-diagram">
    <div class="terminal-block" style="font-size:13px;max-height:320px;overflow:auto;">
<span class="label"># assistant message</span>
{"role": "assistant",
 "tool_calls": [{
   "id": "call_abc",
   "type": "function",
   "function": {
     "name": "search_policies",
     "arguments": "{\"query\": \"CTR threshold cash deposit\"}"
 }}]}

<span class="label"># your code runs search_policies(query=...)</span>
<span class="label"># then appends:</span>
{"role": "tool",
 "tool_call_id": "call_abc",
 "content": "[{\"policy_id\": \"policy-003\", ...}]"}
    </div>
  </div>
  <div class="col-text">
    <h2 class="slide-heading">The tool-call protocol</h2>
    <p class="slide-body">Four messages: <strong>assistant</strong> with <code>tool_calls</code>, your code dispatches, a <strong>tool</strong> message with the result, then the model continues. You implement the dispatch loop.</p>
  </div>
</section>

---

<!-- layout: concept -->
<section class="slide" data-layout="concept">
  <div class="col-diagram">
    <div class="terminal-block" style="font-size:13px;max-height:280px;">
<span class="label"># search_policies tool schema</span>
{
  "name": "search_policies",
  "description": "Search Cortex Bank AML policies",
  "parameters": {
    "type": "object",
    "properties": {
      "query": {"type": "string"}
    },
    "required": ["query"]
  }
}

<span class="label"># Elasticsearch query it runs</span>
{"query": {"semantic": {
  "field": "body_semantic",
  "query": "CTR threshold cash deposit"
}}}
    </div>
  </div>
  <div class="col-text">
    <h2 class="slide-heading">Your tool is a search</h2>
    <p class="slide-body"><code>search_policies(query)</code> runs a semantic search over <code>cortex-policies</code>. You write the schema and the dispatch. The harness in <code>/opt/ara/lib/tina/</code> handles the rest.</p>
  </div>
</section>

---

<!-- layout: concept -->
<section class="slide" data-layout="concept">
  <div class="col-diagram">
    <table class="rule-table" style="font-size:16px;">
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
</section>

---

<!-- layout: rule -->
<!-- rule -->
<section class="slide" data-layout="rule">
  <h2 class="slide-heading">Decision rule</h2>
  <table class="rule-table">
    <tr>
      <th>Tier selection</th>
      <th>Stage gap</th>
    </tr>
    <tr class="correct">
      <td>Satisfies constraint <em>and</em> accuracy floor</td>
      <td>Read from your trace; match the stage description</td>
    </tr>
    <tr>
      <td>Both satisfy: choose the one meeting the floor</td>
      <td>S1: no source &bull; S2: cannot re-query &bull; S3: one shot</td>
    </tr>
  </table>
  <p class="rule-caption">Defend grades against your own measurements, not a fixed key.</p>
</section>

---

<!-- layout: done -->
<section class="slide" data-layout="done">
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
  <p style="color:rgba(255,255,255,0.7);margin-top:var(--s-5);font-size:18px;">Build 1 measures tiers. Build 2 records all four stages. Defend uses both.</p>
</section>

---

<!-- layout: next -->
<section class="slide" data-layout="next">
  <h2 class="slide-heading">Select Check, then open Build 1</h2>
  <p style="opacity:0.8;font-size:18px;">Environment status:</p>
  <div class="status-indicator">
    <div class="status-dot"></div>
    <span class="status-text">Provisioning — check back in a moment</span>
  </div>
</section>
