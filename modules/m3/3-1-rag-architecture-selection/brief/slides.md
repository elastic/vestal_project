<!-- layout: title
track: 3.1
minutes: 8 -->

<p class="track-code">Lab 3.1</p>
<h1 class="slide-title">Select and justify<br>a RAG architecture</h1>
<p class="slide-subtitle"><strong>Tina</strong> is Cortex Bank and Trust's compliance assistant. One question about a 37,000-token narrative sends her 111,330 tokens; 187 hold the answer. You measure where that breaks, then make her choose a strategy per query.</p>
<div style="margin-top:auto;padding:10px 16px;background:rgba(255,255,255,0.12);border-radius:8px;border:1px solid rgba(255,255,255,0.25);font-size:13px;display:flex;align-items:center;gap:10px;max-width:420px;">
  <span style="font-size:18px;">&#8592;</span>
  <span><strong>Tip:</strong> Select <strong>Hide Instructions</strong> in the top bar to give the Brief full width.</span>
</div>

---

<!-- layout: problem -->
<!-- problem -->

<div class="col-left">
  <div class="terminal-block">
Q: In the investigation of Emberline
   Marine Services Holdings Ltd., what
   was the total sum established as
   attributable to the undisclosed party?

WHOLE NARRATIVES, top 3
  1. sar-033   37,109 tokens  <span style="color:var(--yellow);">&lt;== holds
                              the answer</span>
  2. sar-040   37,115 tokens
  3. sar-039   37,106 tokens
  sent 111,330 tokens

the answer: section 'Key Finding',
            187 tokens
signal in context:  187 / 111,330  =  <span class="wrong">0.2%</span>
  </div>
</div>
<div class="col-right">
  <h2 class="slide-heading">The problem</h2>
  <p class="slide-body">Tina found the right narrative, first of three. She was sent <strong>111,330 tokens</strong> to answer a question that <strong>187</strong> of them answer.</p>
  <p class="slide-body">A live run against this lab's start state. You measure the same thing in Build 1, at five narrative lengths.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div class="terminal-block">
naive
  query -> search -> top 5 passages -> answer
  decisions: none

advanced
  query -> read intent -> filter + search
        -> rerank -> top 5 passages
        -> answer
  decisions: <span style="color:var(--yellow);">+ which metadata clause</span>

agentic
  query -> think -> search -> think -> search
        -> answer
                    |___ loop, up to 3 calls
  decisions: <span style="color:var(--yellow);">+ was one search enough</span>
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">Three patterns, three pipelines</h2>
  <p class="slide-body">Each pattern adds exactly one decision node. <strong>Naive</strong> decides nothing. <strong>Advanced</strong> decides which metadata clause applies. <strong>Agentic</strong> decides whether one search was enough.</p>
  <p class="slide-body">Decisions cost tokens and latency. Buy one only when the query needs it.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div class="terminal-block">
a bucket breaks on either gate

  precision   did the gold narrative reach
              the top 3?
              below 0.75        ->  <span class="wrong">broken</span>

  tokens      what the top 3 cost, per
              question
              over your budget  ->  <span class="wrong">broken</span>

  break bucket   the first bucket,
                 shortest first, that fails
                 either gate
                 none, if no bucket fails
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">The haystack problem</h2>
  <p class="slide-body">A whole-document retriever can find the right narrative and still fail. Every question pays for every token of every narrative it retrieves, and one section holds the answer.</p>
  <p class="slide-body">Build 1 measures both gates at five narrative lengths, from about 1,000 to about 40,000 tokens.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div class="terminal-block">
a question about a 1k narrative

  top 3 whole narratives
    = the 3 most similar narratives
      in the corpus
    = of any length

  one of them can be a 40k narrative
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">Tokens are the other axis</h2>
  <p class="slide-body">Top 3 means three narratives, not three short ones. Retrieval ranks by similarity, not by length, so what a question costs depends on what else in the corpus looks like it.</p>
  <p class="slide-body">Your token budget per question is seeded, in <code>/home/elastic/constraint.json</code>.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div class="terminal-block">
same question, same corpus, same retriever

WHOLE NARRATIVES, top 3
------------------------
sar-033   37,109
sar-040   37,115
sar-039   37,106
------------------------
111,330 tokens sent
answer in narrative 1

PASSAGES, top 5
------------------------------
sar-033 Key Finding        187 <span style="color:var(--yellow);">&lt;==</span>
sar-033 Due Diligence    1,217
sar-033 Related Parties  1,418
sar-033 Escalation       1,232
sar-033 Activity         1,073
------------------------------
5,127 tokens sent
answer is passage 1
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">Passages, not documents</h2>
  <p class="slide-body">Only the unit of retrieval changed. Retrieving a document bets that the whole document is relevant. Retrieving a section makes that bet one section at a time.</p>
  <p class="slide-body">The same answer, for 5 percent of the tokens.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div class="terminal-block">
RAW REPORT     PRE-COMPUTED FACT RECORD
FIU-WIRE-2413  FIU-WIRE-2413
-------------  ---------------------------
9 sections of  { "summary":          ...
prose            "key_entities":     [..]
4,902 tokens     "amounts":          [..]
every question   "dates":            [..]
re-reads all     "answers_questions":[..]
of it            "topics":           [..] }
-------------  ---------------------------
8 questions,   8 questions, top 3
top 3
tokens sent    a fraction      <span style="color:var(--yellow);">cheaper</span>
precision      measure it      <span style="color:var(--yellow);">?</span>
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">Query the extraction, not the report</h2>
  <p class="slide-body">The extraction runs once, offline. Questions then read facts, not prose, so tokens fall sharply. It pays if precision holds: within one question of raw reports.</p>
  <p class="slide-body"><strong>Knowledge Indicators</strong> builds these records from your corpus.</p>
  <div style="padding:10px 14px;background:rgba(254,197,20,0.15);border-left:3px solid var(--yellow);border-radius:6px;font-size:14px;line-height:1.5;">
    &#9888;&#65039; Knowledge Indicators are in preview. This lab uses an offline GA index to teach the same pattern.
  </div>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div class="terminal-block">
strategy_router(query, features)
  returns  naive | advanced | agentic

features on every query:
  has_filter_intent
    "high-risk sanctions cases"
  asks_for_figure
    "what amount was wired"
  multi_hop
    "opened the same day as FIU-WIRE-2421"
  has_case_id
    "case FIU-WIRE-2401"

one query can carry several.
your order decides which wins.
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">The strategy router</h2>
  <p class="slide-body">The harness extracts the features. You write the function that maps them to a strategy.</p>
  <p class="slide-body">Order matters when a query carries more than one feature. Tina's current router gets some of those wrong; the dev set shows which.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div class="terminal-block">
Q "high-risk sanctions cases this quarter"
  routed   naive        should be   advanced
  got      5 structuring memos mentioning
           sanctions
  answer   <span class="wrong">WRONG</span>

Q "how much was wired in the investigation
   opened the same day as FIU-WIRE-2421?"
  routed   advanced     should be   agentic
  got      one search, FIU-WIRE-2421 only
  answer   <span class="wrong">INCOMPLETE</span>   the date was in
                        the first report; no
                        second search
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">Where Tina picks wrong</h2>
  <p class="slide-body">Under-routing costs accuracy: the filter or the second hop never happens, and the answer is wrong or incomplete.</p>
  <p class="slide-body">Over-routing costs tokens and latency: a single-hop policy lookup sent through the agentic loop pays for searches it does not need.</p>
</div>

---

<!-- layout: rule -->
<!-- rule -->

<h2 class="slide-heading">Decision rule</h2>
<p class="rule-caption">Take the first row that applies.</p>
<table class="rule-table">
  <tr><th>Characteristic</th><th>Pattern</th><th>Reason</th></tr>
  <tr><td>Facts from two or more documents</td><td>agentic</td><td>Hop two depends on hop one</td></tr>
  <tr><td>Query names a case reference, case type, risk tier, or date</td><td>advanced</td><td>Metadata clause cuts contamination</td></tr>
  <tr><td>Query asks for a figure</td><td>advanced</td><td>Rerank puts the passage with the figure first</td></tr>
  <tr><td>Single-hop lookup, one document</td><td>naive</td><td>No filter, no second hop</td></tr>
</table>

---

<!-- layout: done -->

<h2 class="slide-heading" style="color:var(--white);">What done looks like</h2>
<div class="done-row">
  <div class="done-item">
    <span class="big-number">5</span>
    <span class="big-number-label">length buckets measured<br>break bucket named</span>
  </div>
  <div class="done-item">
    <span class="big-number">0.80</span>
    <span class="big-number-label">router accuracy on<br>15 held-out queries</span>
  </div>
  <div class="done-item">
    <span class="big-number">60%</span>
    <span class="big-number-label">fewer tokens from the fact index,<br>precision within one query</span>
  </div>
</div>
<p class="rule-caption" style="color:var(--dark-grey);">Your per-bucket numbers must land within 0.20 precision and 50 percent tokens of the check's, which measures on held-out questions.</p>

---

<!-- layout: next -->

<h2 class="slide-heading">Select Check, then open Build 1</h2>
<p style="opacity:0.8;font-size:18px;">Environment status:</p>
<div class="status-indicator">
  <div class="status-dot"></div>
  <span class="status-text">Provisioning, check back in a moment</span>
</div>
<p style="font-size:15px;opacity:0.75;max-width:52ch;text-align:center;">The indicator turns green when provisioning finishes. Select Check at any time and it reports which step is still running.</p>
