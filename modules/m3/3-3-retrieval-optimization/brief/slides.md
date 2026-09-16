<!-- layout: title
track: 3.3
minutes: 8 -->

<p class="track-code">Lab 3.3</p>
<h1 class="slide-title">Optimize retrieval<br>inputs for precision</h1>
<p class="slide-subtitle"><strong>Tina</strong> gets Cortex Bank and Trust's 120 case memos. The five case types share vocabulary, so half of what she retrieves is the wrong type. You fix that in the mapping, the filter, and the context.</p>
<div style="margin-top:auto;padding:10px 16px;background:rgba(255,255,255,0.12);border-radius:8px;border:1px solid rgba(255,255,255,0.25);font-size:13px;display:flex;align-items:center;gap:10px;max-width:420px;">
  <span style="font-size:18px;">&#8592;</span>
  <span><strong>Tip:</strong> Select <strong>Hide Instructions</strong> in the top bar to give the Brief full width.</span>
</div>

---

<!-- layout: problem -->

<div class="col-left">
  <div class="terminal-block">
Q: structuring cases, cash held below the reporting threshold

rank  case_id                   case_type     score
 1    case-structuring-004      structuring    0.71
 2    <span class="wrong">case-wire-fraud-001       wire_fraud</span>     0.69
 3    <span class="wrong">case-wire-fraud-013       wire_fraud</span>     0.68
 4    case-structuring-011      structuring    0.66
 5    <span class="wrong">case-wire-fraud-005       wire_fraud</span>     0.64

  why: every wire_fraud memo above contains the phrase
       "sequential same-day deposits across multiple
        branches" and "CTR avoidance"

precision@5:  2 / 5  =  <span class="wrong">0.40</span>
  </div>
</div>
<div class="col-right">
  <h2 class="slide-heading">The problem</h2>
  <p class="slide-body">Three of the top five files are the wrong case type. Not because retrieval failed, but because those memos really do discuss structuring. The text cannot tell them apart. The metadata can.</p>
  <p class="slide-body">You reproduce this in Build 2, then remove it.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div class="terminal-block">
one value, three ways to index it

"wire_fraud"
   as <span style="color:var(--yellow);">text</span>            analyzed into [wire, fraud]
                      match  yes    filter  no
                      count  no     sort    no

   as <span style="color:var(--yellow);">keyword</span>         stored whole
                      match  yes    filter  <span style="color:var(--teal);">yes</span>
                      count  <span style="color:var(--teal);">yes</span>    sort    <span style="color:var(--teal);">yes</span>

   as <span style="color:var(--yellow);">semantic_text</span>   embedded as a vector
                      meaning  yes  filter  no

"2024-03-07"
   as text            "2024" and "03" and "07"
   as <span style="color:var(--yellow);">date</span>            a point on a line, ranges work
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">The mapping decides first</h2>
  <p class="slide-body">Every retrieval option you have later was granted or refused when the field was mapped. A type is not a formatting choice.</p>
  <p class="slide-body">You cannot filter your way out of an analyzed field, and re-indexing 120 memos to fix it costs more than reading this slide.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div class="terminal-block">
the same body, indexed twice

  memo body
      |
      +---> <span style="color:var(--yellow);">body_text</span>   (text)
      |         inverted index, BM25
      |         finds "CTR avoidance" exactly
      |
      +---> <span style="color:var(--yellow);">body</span>        (semantic_text)
                vectors, nearest neighbour
                finds "kept deposits under the limit"

  hybrid retrieval fuses the two ranked lists

  one filter clause has to narrow <span class="wrong">both</span> halves
  or the unfiltered half leaks contamination back in
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">The twin field</h2>
  <p class="slide-body">Exact phrases and paraphrases are different retrieval problems. Indexing the body twice buys both, at the cost of one extra field.</p>
  <p class="slide-body">Fusion is where filters get forgotten. A clause on one half is worse than none, because the number looks almost right.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div class="terminal-block">
is it a facet?

  case_type      keyword, 5 values        <span style="color:var(--teal);">facet</span>
  risk_tier      keyword, 3 values        <span style="color:var(--teal);">facet</span>
  filing_date    date                     <span style="color:var(--teal);">facet (range)</span>
  title          text, free               <span class="wrong">not a facet</span>
  body           semantic_text            <span class="wrong">not a facet</span>

the test, in order:
  1  can a term clause select it exactly
  2  does an aggregation return one bucket per value
  3  is the value stable when the sentence is reworded

  a field of prose fails all three, however
  informative it reads
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">Facets</h2>
  <p class="slide-body">A facet is a field you can select on exactly. Free text is never a facet.</p>
  <p class="slide-body">Getting it wrong is expensive in one direction only: a match on the body keeps every memo that mentions the value, so precision stays where it started while the query looks filtered.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div class="terminal-block">
120 memos, built to overlap

  structuring          24     each memo also carries one
  wire_fraud           24     other case type's vocabulary
  sanctions            24
  kyc_gap              24     x 3 risk tiers
  elder_exploitation   24     x filing dates over 3 years

unfiltered precision@10, typed query

  relevant by type      24 / 120
  lexical and semantic signal lifts it
  measured baseline     <span class="wrong">~0.50</span>

filtered to the named type

  candidate set         24 documents
  every hit in scope    <span style="color:var(--teal);">~1.00</span>
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">Contamination</h2>
  <p class="slide-body">The overlap is deliberate and it is what real case files look like: a wire fraud investigation explains the structuring it found.</p>
  <p class="slide-body">Half your results being right is the baseline you measure, not the one you defend.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div class="terminal-block">
the harness reads the intent, you build the clauses

intent
  {"case_type":  "sanctions",
   "risk_tier":  ["medium", "high"],
   "date_from":  "2024-01-01",
   "date_to":    null}

your clauses
  [{"term":  {"case_type": "sanctions"}},
   {"terms": {"risk_tier": ["medium","high"]}},
   {"range": {"filing_date": {"gte": "2024-01-01"}}}]

  a key set to null gets <span class="wrong">no clause</span>
  one value and a list of values are different clauses
  a window with one end set is still a range
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">Filters from intent</h2>
  <p class="slide-body">Reading the intent is solved. Turning it into clauses is yours, and the empty intent is the case that breaks naive implementations.</p>
  <p class="slide-body">Filters narrow the candidate set. They do not rank.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div class="terminal-block">
precision@10 = relevant in the top 10 / 10

  unfiltered   R . R . . R . . R .     0.40
  filtered     R R R R R R R R R R     1.00

what a miss looks like after filtering

  intent    {"risk_tier": ["high"], "case_type": null}
  clauses   [{"term": {"case_type": null}}]
  result    <span class="wrong">0 documents</span>, precision 0.00

  the clause was built for a constraint
  the query never made
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">Reading a miss</h2>
  <p class="slide-body">After filtering, a miss is almost never a ranking problem. It is a clause built for a constraint that was not there, or a constraint that was there and got no clause.</p>
  <p class="slide-body">Print the clauses beside the intent and the pattern shows up in three queries at once.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div class="terminal-block">
a budget is a hard ceiling on the packed context

  budget            3,000 tokens
  retrieved         12 memos x ~420  =  5,040

  pack everything
    sent            5,040 tokens
    what arrives    the first 3,000, cut mid-memo
    the cut memo    a figure with no subject
    Tina's answer   <span class="wrong">confident and wrong</span>

  pack to fit
    sent            2,870 tokens
    what arrives    7 whole memos
    what is lost    5 memos you chose to drop
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">Context budgets</h2>
  <p class="slide-body">Overrunning a budget is not a slightly larger bill. It is a truncated prompt, and the truncation lands wherever the text happened to end.</p>
  <p class="slide-body">Two budgets are seeded for your sandbox. The smaller one is a real constraint.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div class="terminal-block">
<span style="color:var(--yellow);">SET A  many short results</span>     <span style="color:var(--yellow);">SET B  few long results</span>
12 memos x ~420 tokens       3 sections x ~1,300 tokens
relevant end to end          one relevant span each

rerank_top_n                 rerank_top_n
  score, take whole            score, take whole
  7 memos fit                  2 sections fit
  gold ranked high             gold span in section 3
  retention <span style="color:var(--teal);">high</span>              retention <span class="wrong">at risk</span>

summarize_first              summarize_first
  compress 12 to 225 each      compress 3 to 800 each
  all 12 fit                   all 3 fit
  short memos lose detail      the span survives
  retention <span class="wrong">at risk</span>            retention <span style="color:var(--teal);">high</span>
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">Two shapes, two strategies</h2>
  <p class="slide-body">Neither strategy is better. Each one matches a shape of result set, and the budget decides how sharply.</p>
  <p class="slide-body">Build 3 runs all eight combinations so the answer is measured on your corpus, not assumed.</p>
</div>

---

<!-- layout: rule -->
<!-- rule -->

<h2 class="slide-heading">Decision rules</h2>
<table class="rule-table">
  <tr><th>Question</th><th>Answer</th><th>Because</th></tr>
  <tr><td>Which field is the facet</td><td>The coded field, as keyword</td><td>A term clause selects it exactly</td></tr>
  <tr><td>Many short results</td><td>rerank_top_n</td><td>Order decides what survives</td></tr>
  <tr><td>Few long results</td><td>summarize_first</td><td>Compression keeps a span per document</td></tr>
  <tr><td>What moved precision</td><td>The clause you recorded</td><td>The mapping fingerprint did not change</td></tr>
</table>
<p class="rule-caption">Free text is never a facet. A frozen mapping rules out re-indexing.</p>

---

<!-- layout: done -->

<h2 class="slide-heading" style="color:var(--white);">What done looks like</h2>
<div class="done-row">
  <div class="done-item">
    <span class="big-number">120</span>
    <span class="big-number-label">memos mapped and loaded<br>5 case type buckets</span>
  </div>
  <div class="done-item">
    <span class="big-number">0.80</span>
    <span class="big-number-label">filtered precision at 10<br>on 20 held-out queries</span>
  </div>
  <div class="done-item">
    <span class="big-number">8</span>
    <span class="big-number-label">packing combinations run<br>no budget overrun</span>
  </div>
</div>
<p class="rule-caption" style="color:var(--dark-grey);">The mapping fingerprint from Build 1 has to still match when Build 2 is graded.</p>

---

<!-- layout: next -->

<h2 class="slide-heading">Select Check, then open Build 1</h2>
<p style="opacity:0.8;font-size:18px;">Environment status:</p>
<div class="status-indicator">
  <div class="status-dot"></div>
  <span class="status-text">Provisioning, check back in a moment</span>
</div>
<p style="font-size:15px;opacity:0.75;max-width:52ch;text-align:center;">The indicator turns green when provisioning finishes. Select Check at any time and it reports which step is still running.</p>
