<!-- layout: title -->

<p class="track-code">Lab 1.4</p>
<h1 class="slide-title">Turn three: "Is that reportable?"<br>Tina has no idea what "that" is.</h1>
<p class="slide-subtitle"><strong>Tina</strong> is Cortex Bank's AI compliance assistant. Model calls have no memory. You give her one: implement the MemoryStore, then defend the harness posture that fits Cortex's constraints.</p>
<div style="margin-top:auto;padding:10px 16px;background:rgba(255,255,255,0.12);border-radius:8px;border:1px solid rgba(255,255,255,0.25);font-size:13px;display:flex;align-items:center;gap:10px;max-width:420px;">
  <span style="font-size:18px;">&#8592;</span>
  <span><strong>Tip:</strong> Select <strong>Hide Instructions</strong> in the top bar to give the Brief full width.</span>
</div>

---

<!-- layout: problem -->

<div class="col-left">
  <div class="terminal-block">
Turn 1, Analyst: I'm reviewing Elias Vance,
  account 4492. He made 10 daily withdrawals
  of $9,500 each over two weeks.

Turn 2, Analyst: Are his wire transfers
  consistent with that pattern?

  Tina: I see several wire transfers in the
  account. They appear routine.

Turn 3, Analyst: Is <span class="wrong">that</span> reportable?

  Tina: I'm sorry, could you clarify
  what you mean by "that"?
  </div>
</div>
<div class="col-right">
  <h2 class="slide-heading">The problem</h2>
  <p class="slide-body">Tina forgot the customer by turn three. Every LLM call starts fresh. The context window held the conversation, but the model processed each turn independently. Cortex analysts cannot re-introduce context every turn.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <img src="../../../../brief/img/library/agent.svg" alt="A harness wraps the model: memory, tool dispatch, control flow, and tracing surround the LLM box" style="max-width:100%;max-height:320px;">
</div>
<div class="col-text">
  <h2 class="slide-heading">What a harness adds</h2>
  <p class="slide-body">The model is one box. A harness wraps it with <strong>memory</strong> (state that persists), <strong>tool dispatch</strong> (calling Elasticsearch), <strong>control flow</strong> (loops, branches), and <strong>tracing</strong> (audit). None of this lives in the model call itself.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <table class="rule-table" style="font-size:15px;">
    <tr><th>Memory type</th><th>Lives where</th><th>Survives</th></tr>
    <tr><td>Context window</td><td>This API call</td><td>One call</td></tr>
    <tr><td>Working memory</td><td>This conversation</td><td>This session</td></tr>
    <tr><td>Persistent memory</td><td>External store</td><td>Across sessions</td></tr>
  </table>
</div>
<div class="col-text">
  <h2 class="slide-heading">Three memory scopes</h2>
  <p class="slide-body">"That account" in turn three needs <strong>working memory</strong>: it must survive across the conversation but not necessarily across sessions. The right scope avoids over-storing (full persistent) and under-storing (context-only).</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div class="terminal-block" style="font-size:13px;line-height:1.7;">
<span class="label"># cortex-tina-memory mapping</span>
{
  "mappings": {
    "properties": {
      "turn":     {"type": "integer"},
      "entities": {"type": "text"},
      "summary":  {"type": "text"}
    }
  }
}

<span class="label"># remember: index one doc per turn</span>
<span class="label"># recall:   search on entities + summary</span>
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">Your memory store is an index</h2>
  <p class="slide-body"><code>cortex-tina-memory</code> is a small Elasticsearch index. <strong>Remember</strong> indexes a document per turn. <strong>Recall</strong> searches it by entity or topic. Stays on the same stack as <code>cortex-policies</code>.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <table class="rule-table" style="font-size:14px;">
    <tr><th>Posture</th><th>Control flow</th><th>Cortex use</th></tr>
    <tr><td>Sequential</td><td>Ordered steps</td><td>Compliance audit trail</td></tr>
    <tr><td>Graph</td><td>Branch on results</td><td>Risk-tiered escalation</td></tr>
    <tr><td>Event-driven</td><td>React to triggers</td><td>Wire alert on arrival</td></tr>
  </table>
</div>
<div class="col-text">
  <h2 class="slide-heading">Three harness postures</h2>
  <p class="slide-body"><strong>Sequential</strong> runs fixed steps in order: auditable, predictable. <strong>Graph</strong> branches based on what each step returns: flexible, harder to trace. <strong>Event-driven</strong> reacts to external signals: responsive, requires durable queues.</p>
</div>

---

<!-- layout: rule -->
<!-- rule -->

<h2 class="slide-heading">Decision rule</h2>
<table class="rule-table">
  <tr><th>Constraint</th><th>Correct posture</th><th>Why</th></tr>
  <tr class="correct">
    <td>Strict step order with audit trail</td>
    <td>Sequential</td>
    <td>Fixed sequence, each step logged</td>
  </tr>
  <tr>
    <td>Branch on tool results</td>
    <td>Graph</td>
    <td>Conditional paths require branch nodes</td>
  </tr>
  <tr>
    <td>React to incoming events</td>
    <td>Event-driven</td>
    <td>External trigger drives execution</td>
  </tr>
</table>
<p class="rule-caption">You will be given one constraint. The Defend grades your posture choice against it.</p>

---

<!-- layout: done -->

<h2 class="slide-heading" style="color:var(--white);">What done looks like</h2>
<div class="done-row">
  <div class="done-item">
    <span class="big-number">3</span>
    <span class="big-number-label">turns resolved<br>at temperature 0</span>
  </div>
  <div class="done-item">
    <span class="big-number">3</span>
    <span class="big-number-label">documents in<br>cortex-tina-memory</span>
  </div>
  <div class="done-item">
    <span class="big-number">1</span>
    <span class="big-number-label">posture choice<br>with matching reason</span>
  </div>
</div>

---

<!-- layout: next -->

<h2 class="slide-heading">Select Next, then open Build 1</h2>
<p style="opacity:0.8;font-size:18px;">Environment status:</p>
<div class="status-indicator">
  <div class="status-dot"></div>
  <span class="status-text">Provisioning - check back in a moment</span>
</div>
