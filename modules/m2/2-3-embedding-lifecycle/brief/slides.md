<!-- layout: title
track: 2.3
minutes: 8 -->

<p class="track-code">Lab 2.3</p>
<h1 class="slide-title">Embedding<br>lifecycle</h1>
<p class="slide-subtitle">A new embedding model is ready for <strong>Tina</strong>. You benchmark it, move the live alias to it without a failed search, raise recall for the queries it still misses, and defend whether it stays.</p>
<div style="margin-top:auto;padding:10px 16px;background:rgba(255,255,255,0.12);border-radius:8px;border:1px solid rgba(255,255,255,0.25);font-size:13px;display:flex;align-items:center;gap:10px;max-width:420px;">
  <span style="font-size:18px;">&#8592;</span>
  <span><strong>Tip:</strong> Select <strong>Hide Instructions</strong> in the top bar to give the Brief full width.</span>
</div>

---

<!-- layout: problem -->
<!-- problem -->

<div class="col-left">
  <div class="terminal-block">
Q: money moved around to hide where it came from

Tina today (cortex-corpus)
 1  <span class="wrong">sar-109</span>
 2  <span class="wrong">sar-105</span>
 3  <span class="wrong">sar-116</span>
 4  <span class="wrong">sar-110</span>
    sar-103, the case that answers it: not retrieved

"Based on the documents provided, several cases
describe money being moved around to hide its
origin: Loan Layering [sar-109] ..."
  </div>
</div>
<div class="col-right">
  <h2 class="slide-heading">The problem</h2>
  <p class="slide-body">The cause: the analyst's words are not the case's words.</p>
  <div class="terminal-block">
sar-103   shell company layering
          and ownership obfuscation
query     <span class="wrong">none of those words</span>
  </div>
  <p class="slide-body">Tina answers confidently from four other cases. A new embedding model might close the gap, or a rewrite of the query might. Build 1 and Build 3 measure each.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div class="terminal-block">
cortex-corpus             current model
cortex-corpus-candidate   candidate model
                          same documents

benchmark   labelled queries, every doc type
            nDCG@5 and p95 on both indices

gain        candidate nDCG@5 - current
            0.02 or less is noise
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">Benchmark before you switch</h2>
  <p class="slide-body">A newer model is not automatically a better one for your corpus. Score both indices on the same labelled queries.</p>
  <p class="slide-body">A set that skips a document type cannot show a regression there.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div class="terminal-block">
POST _aliases
{ "actions": [
  { "remove": { "index": "cortex-corpus",
                "alias": "cortex-corpus-live" } },
  { "add":    { "index": "cortex-corpus-candidate",
                "alias": "cortex-corpus-live" } }
] }
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">One request, no gap</h2>
  <p class="slide-body">Tina queries <code>cortex-corpus-live</code>, never an index name. Remove and add in one <code>_aliases</code> request, and no search sees the alias pointing nowhere.</p>
  <p class="slide-body">A probe searches the alias throughout and records every failure. Keep the old index: it is your rollback.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div class="terminal-block">
# cortex-generation
es.inference.inference(
    inference_id="cortex-generation",
    task_type="completion",
    body={"input": prompt},
)["completion"][0]["result"]

# llm_client()
from tina.client import llm_client, model_fast
llm_client().chat.completions.create(
    model=model_fast(),
    messages=[{"role": "user", "content": prompt}],
).choices[0].message.content
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">Fix recall at query time</h2>
  <p class="slide-body">Re-embedding is not the only fix. <code>rewrite()</code> changes what Tina searches with, and the index stays as it is. HyDE asks a model for the passage that would answer the query, then searches with that passage.</p>
  <p class="slide-body">A model call costs time on every query. A static synonym list costs upkeep.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div class="terminal-block">
Build 1   benchmark the candidate
          nDCG@5 and p95, both indices

Build 2   cut over without downtime
          one _aliases request

Build 3   raise recall query-side
          rewrite() on keyword misses

Defend    keep or roll back,
          from your own numbers
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">In this track</h2>
  <p class="slide-body">The Defend reads the gain and latency the Build 1 check measured, and how your rewrite recovered recall in Build 3.</p>
</div>

---

<!-- layout: rule -->
<!-- rule -->

<h2 class="slide-heading">Decision rule</h2>
<table class="rule-table">
  <tr><th>Gain over current</th><th>Candidate p95</th><th>Call</th></tr>
  <tr><td>More than 0.02</td><td>Within budget</td><td>Keep the cutover</td></tr>
  <tr><td>0.02 or less</td><td>Within budget</td><td>Roll back: no real gain</td></tr>
  <tr><td>More than 0.02</td><td>Over budget</td><td>Roll back: too slow</td></tr>
  <tr><td>0.02 or less</td><td>Over budget</td><td>Roll back: both</td></tr>
</table>
<p class="rule-caption">A gain of 0.02 or less, including a negative one, is noise.</p>

---

<!-- layout: done -->

<h2 class="slide-heading" style="color:var(--white);">What done looks like</h2>
<div class="done-row">
  <div class="done-item">
    <span class="big-number">12</span>
    <span class="big-number-label">labelled benchmark queries<br>policy, sar and wire-fraud</span>
  </div>
  <div class="done-item">
    <span class="big-number">0</span>
    <span class="big-number-label">failed or empty searches<br>in at least 20 probe samples</span>
  </div>
  <div class="done-item">
    <span class="big-number">8 of 13</span>
    <span class="big-number-label">held-out keyword misses<br>in the first 5 after rewrite()</span>
  </div>
  <div class="done-item">
    <span class="big-number">35 s</span>
    <span class="big-number-label">for all 13 rewrite() calls<br>index left unchanged</span>
  </div>
</div>
<p class="rule-caption" style="color:var(--dark-grey);">The Defend uses the 0.02 noise band and a 300 or 500 ms p95 budget.</p>

---

<!-- layout: next -->

<h2 class="slide-heading">Select Check, then open Build 1</h2>
<p style="opacity:0.8;font-size:18px;">Environment status:</p>
<div class="status-indicator">
  <div class="status-dot"></div>
  <span class="status-text">Provisioning, check back in a moment</span>
</div>
<p style="font-size:15px;opacity:0.75;max-width:52ch;text-align:center;">The indicator turns green when provisioning finishes. Select Check at any time and it reports which step is still running.</p>
