<!-- layout: title
track: 2.2
minutes: 8 -->

<p class="track-code">Lab 2.2</p>
<h1 class="slide-title">Tune retrieval<br>quality</h1>
<p class="slide-subtitle"><strong>Tina</strong> searches Cortex Bank's compliance documents by meaning alone, and analysts also ask for cases by number. You measure four retrievers, size the vector index to a memory budget, and defend which retriever ships.</p>
<div style="margin-top:auto;padding:10px 16px;background:rgba(255,255,255,0.12);border-radius:8px;border:1px solid rgba(255,255,255,0.25);font-size:13px;display:flex;align-items:center;gap:10px;max-width:420px;">
  <span style="font-size:18px;">&#8592;</span>
  <span><strong>Tip:</strong> Select <strong>Hide Instructions</strong> in the top bar to give the Brief full width.</span>
</div>

---

<!-- layout: problem -->
<!-- problem -->

<div class="col-left">
  <div class="terminal-block">
Q: WF-2026-0803A
   (from wire-fraud-202's case
    number, MTB-WF-2026-0803A)

by meaning (Tina today)   168 ms
 1  <span class="wrong">wire-fraud-204</span>
 2  <span class="wrong">wire-fraud-207</span>
 3  wire-fraud-202   the case asked for
 4  <span class="wrong">sar-111</span>

by exact words             54 ms
 1  wire-fraud-202
  </div>
</div>
<div class="col-right">
  <h2 class="slide-heading">The problem</h2>
  <p class="slide-body">The cause: Tina's only retriever searches by meaning.</p>
  <div class="terminal-block">
dense template
  match body   (semantic_text)
lexical leg  <span class="wrong">none</span>
  </div>
  <p class="slide-body">A case number has no meaning to embed, so two cases that read alike rank above the one asked for. Exact words find it first, in a third of the time. You run this search yourself at the start of Build 1.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div class="terminal-block">
template      searches       pays

bm25          body_text,     one query
              exact tokens
dense         body, by       one query
              meaning        + an embedding
hybrid        both, fused    both queries
              with RRF
hybrid_rerank hybrid, then   both queries
              a reranker     + a model call
              re-scores the
              top results
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">Four strategies</h2>
  <p class="slide-body">Exact words win on identifiers. Meaning wins on questions in the analyst's words. Hybrid hedges between the two; it can trail the stronger leg on your corpus. A reranker reads question and passage together, so it separates two rules that differ by one detail.</p>
  <p class="slide-body">Every stage adds latency. Measure each on your corpus before you pay for it.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div class="terminal-block">
nDCG@5   how well the top 5 are ordered
         over every question
         1.0 = the relevant documents first

MRR      1 / rank of the case asked for
         over the identifier questions
         rank 1 -> 1.0   rank 2 -> 0.5
         not in the top 5 -> 0

p50      median latency over the questions
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">Three numbers</h2>
  <p class="slide-body">nDCG@5 rewards a good ranking overall. MRR asks one thing: is the case the analyst named at the top?</p>
  <p class="slide-body">An identifier lookup that lands second scores half. The check measures all three on held-out questions you never see: identifiers, conceptual questions and fine distinctions between near-identical rules.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div class="terminal-block">
bbq_hnsw memory, per vector
  quantized vector   dims / 8 + 14 bytes
                     1024 dims -> 142 bytes
  HNSW graph         4 x m bytes

production: 12,000,000 vectors
  m = 16 (default)   (142 + 64) x 12M
                     = 2,472,000,000 bytes
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">Memory per vector</h2>
  <p class="slide-body">A larger <code>m</code> gives each vector more graph links. Recall improves, and every one of the 12 million vectors pays for it.</p>
  <p class="slide-body">Your sandbox has a seeded memory budget. Build 2 asks for the largest <code>m</code> that fits it, from this formula in the Elastic docs.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div class="terminal-block">
Build 1   retriever bench
          four templates, measured on
          held-out questions

Build 2   tune the vector index
          bbq_hnsw at the largest m
          that fits your budget

Defend    which retriever ships,
          from your own numbers
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">In this track</h2>
  <p class="slide-body">Each step feeds the next. The Defend sets a latency budget from your Build 1 latencies and asks about the graph memory your Build 2 choice adds.</p>
</div>

---

<!-- layout: rule -->
<!-- rule -->

<h2 class="slide-heading">Decision rule</h2>
<table class="rule-table">
  <tr><th>Decision</th><th>Rule</th></tr>
  <tr><td>Default retriever</td><td>The highest nDCG@5 among templates whose p50 fits the budget</td></tr>
  <tr><td>Exact lookups</td><td>The template with the highest identifier MRR</td></tr>
  <tr><td>Graph memory</td><td>4 &times; <code>m</code> bytes per vector, times the vector count</td></tr>
</table>
<p class="rule-caption">Your own measurements decide each row.</p>

---

<!-- layout: done -->

<h2 class="slide-heading" style="color:var(--white);">What done looks like</h2>
<div class="done-row">
  <div class="done-item">
    <span class="big-number">0.90</span>
    <span class="big-number-label">bm25 identifier MRR<br>graded</span>
  </div>
  <div class="done-item">
    <span class="big-number">0.75</span>
    <span class="big-number-label">hybrid_rerank nDCG@5<br>target, reported only</span>
  </div>
  <div class="done-item">
    <span class="big-number">100</span>
    <span class="big-number-label">minimum ef_construction<br>at the largest m that fits</span>
  </div>
  <div class="done-item">
    <span class="big-number">0.03</span>
    <span class="big-number-label">largest nDCG@5 change<br>after tuning</span>
  </div>
</div>
<p class="rule-caption" style="color:var(--dark-grey);">Every template must also return documents for every question and reach nDCG@5 0.4. The check measures on held-out questions, so its numbers can differ from the notebook's.</p>

---

<!-- layout: next -->

<h2 class="slide-heading">Select Check, then open Build 1</h2>
<p style="opacity:0.8;font-size:18px;">Environment status:</p>
<div class="status-indicator">
  <div class="status-dot"></div>
  <span class="status-text">Provisioning, check back in a moment</span>
</div>
<p style="font-size:15px;opacity:0.75;max-width:52ch;text-align:center;">The indicator turns green when provisioning finishes. Select Check at any time and it reports which step is still running.</p>
