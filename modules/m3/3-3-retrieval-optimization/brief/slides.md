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
<!-- problem -->

<div class="col-left">
  <div class="terminal-block">
Q: Among the investigations into large
   outbound transfers that were
   unexpectedly diverted, what was the
   specific amount involved in the
   Lanternhill Machinery Enterprises LLC
   incident?
intent: {"case_type": "wire_fraud",
         "risk_tier": null,
         "date_from": null,
         "date_to": null}
 1 case-wire-fraud-008 wire_fraud in gold
 2 <span class="wrong">case-sanctions-024  sanctions  WRONG</span>
 3 case-wire-fraud-020 wire_fraud in gold
 4 <span class="wrong">case-sanctions-001  sanctions  WRONG</span>
 5 <span class="wrong">case-sanctions-007  sanctions  WRONG</span>
unfiltered precision@10 for this query:
  <span class="wrong">0.20</span>
  </div>
</div>
<div class="col-right">
  <h2 class="slide-heading">The problem</h2>
  <p class="slide-body">The cause: the query that produced this ranks on text alone.</p>
  <div class="terminal-block">
hybrid RRF
  match body_text
  match body (semantic)
filter  <span class="wrong">none</span>
  </div>
  <p class="slide-body">The intent names wire_fraud. Sanctions memos discuss diverted transfers too, so the text cannot tell them apart. The metadata can. You reproduce this in Build 2, then remove it.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div class="terminal-block">
one value, three ways to index it

"wire_fraud"
  as <span style="color:var(--yellow);">text</span>           analyzed into
                    [wire, fraud]
                    match  yes    filter  no
                    count  no     sort    no

  as <span style="color:var(--yellow);">keyword</span>        stored whole
                    match  yes    filter  <span style="color:var(--teal);">yes</span>
                    count  <span style="color:var(--teal);">yes</span>    sort    <span style="color:var(--teal);">yes</span>

  as <span style="color:var(--yellow);">semantic_text</span>  embedded as a vector
                    meaning  yes  filter  no

"2024-03-07"
  as text           "2024" and "03" and "07"
  as <span style="color:var(--yellow);">date</span>           a point on a line,
                    ranges work
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
    |       inverted index, BM25
    |       finds "CTR avoidance" exactly
    |
    +---> <span style="color:var(--yellow);">body</span>        (semantic_text)
            vectors, nearest neighbour
            finds
            "kept deposits under the limit"

  hybrid retrieval fuses the two ranked lists

  one filter clause has to narrow <span class="wrong">both</span> halves
  or the unfiltered half leaks contamination
  back in
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

  case_type    keyword, 5 values  <span style="color:var(--teal);">facet</span>
  risk_tier    keyword, 3 values  <span style="color:var(--teal);">facet</span>
  filing_date  date               <span style="color:var(--teal);">facet
                                  (range)</span>
  title        text, free         <span class="wrong">not a facet</span>
  body         semantic_text      <span class="wrong">not a facet</span>

the test, in order:
  1  can a term clause select it exactly
  2  does an aggregation return one bucket
     per value
  3  is the value stable when the sentence
     is reworded

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

  structuring          24  each memo also
  wire_fraud           24  carries one other
  sanctions            24  case type's
  kyc_gap              24  vocabulary
  elder_exploitation   24
                           x 3 risk tiers
                           x filing dates
                             over 3 years

precision@10, held-out queries
(case type, risk tier, date window, combined)

  unfiltered hybrid     <span class="wrong">0.515</span>
  reference filters     <span style="color:var(--teal);">1.000</span>
  one clause per constraint
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
the harness reads the intent,
you build the clauses

intent
  {"case_type":  "sanctions",
   "risk_tier":  ["medium", "high"],
   "date_from":  "2024-01-01",
   "date_to":    null}

your clauses
  [{"term":  {"case_type": "sanctions"}},
   {"terms": {"risk_tier":
               ["medium","high"]}},
   {"range": {"filing_date":
               {"gte": "2024-01-01"}}}]

  a key set to null gets <span class="wrong">no clause</span>
  one value and a list of values are
    different clauses
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

  intent    {"risk_tier": ["high"],
             "case_type": null}
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
a budget is a hard ceiling
on the packed context

  budget          4,000 tokens
                  (the smaller one on
                  some seeds)
  set B retrieved 5 passages
                  3,860 + 1,151 + 1,374
                  + 1,144 + 1,067
                  =  8,596 tokens

  pack everything
    sent          <span class="wrong">8,596 tokens, 4,596 over</span>
    what arrives  the text up to the cut,
                  mid-passage
    the check     fails the overrun

  pack to fit, in rank order
    measure each passage before adding it
    skip one that does not fit
    sent          at most 4,000 tokens
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">Context budgets</h2>
  <p class="slide-body">Overrunning a budget is not a slightly larger bill. It is a truncated prompt, and the truncation lands wherever the text happened to end.</p>
  <p class="slide-body">Your sandbox has two seeded budgets: either 3,000 and 8,000 tokens, or 4,000 and 12,000. constraint.json has yours. On set B the smaller budget always binds; the larger sometimes does. The diagram uses 4,000.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div class="terminal-block">
<span style="color:var(--yellow);">SET A  short memos</span>     <span style="color:var(--yellow);">SET B  long passages</span>
3 memos, about 400     5 passages, 1,067 to
tokens                 3,860
1,182 tokens in all    8,596 tokens in all
fits either budget     overruns 3,000, 4,000
whole                  and 8,000

rerank_top_n           rerank_top_n
  score, take whole      score, take whole
  until the budget       until the budget
  is full                is full

summarize_first        summarize_first
  compress each,         compress each,
  then pack              then pack
  all fit                all fit, detail
                         can drop
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">Two shapes, two strategies</h2>
  <p class="slide-body">The shape of the result set decides how much each strategy has to give up. A set that fits the budget whole loses nothing to either.</p>
  <p class="slide-body">Build 3 runs all eight combinations so the answer is measured on your corpus, not assumed.</p>
</div>

---

<!-- layout: rule -->
<!-- rule -->

<h2 class="slide-heading">Decision rules</h2>
<table class="rule-table">
  <tr><th>Question</th><th>When</th><th>Answer</th></tr>
  <tr><td>Q1</td><td>A clause selects the field exactly, one bucket per value</td><td>That field, as keyword. Never free text</td></tr>
  <tr><td>Q2</td><td>Set B retention values at the smaller budget differ by under 0.05</td><td>Tie</td></tr>
  <tr><td>Q2</td><td>Otherwise</td><td>The higher strategy</td></tr>
  <tr><td>Q3</td><td>Mapping fingerprint held through Build 2</td><td>The filter clauses your run recorded</td></tr>
</table>

---

<!-- layout: done -->

<h2 class="slide-heading" style="color:var(--white);">What done looks like</h2>
<div class="done-row">
  <div class="done-item">
    <span class="big-number">5</span>
    <span class="big-number-label">case type buckets<br>from your mapping</span>
  </div>
  <div class="done-item">
    <span class="big-number">0.80</span>
    <span class="big-number-label">filtered precision at 10<br>on held-out queries</span>
  </div>
  <div class="done-item">
    <span class="big-number">0.80</span>
    <span class="big-number-label">gold retention on held-out questions<br>no budget overrun</span>
  </div>
</div>
<p class="rule-caption" style="color:var(--dark-grey);">Tina also has to quote the gold figure from your packed context in 3 of the 4 sampled answers. The mapping fingerprint from Build 1 has to still match when Build 2 is graded.</p>

---

<!-- layout: next -->

<h2 class="slide-heading">Select Check, then open Build 1</h2>
<p style="opacity:0.8;font-size:18px;">Environment status:</p>
<div class="status-indicator">
  <div class="status-dot"></div>
  <span class="status-text">Provisioning, check back in a moment</span>
</div>
<p style="font-size:15px;opacity:0.75;max-width:52ch;text-align:center;">The indicator turns green when provisioning finishes. Select Check at any time and it reports which step is still running.</p>
