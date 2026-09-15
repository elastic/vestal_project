<!-- layout: title
track: 3.1
minutes: 8 -->

<p class="track-code">Lab 3.1</p>
<h1 class="slide-title">Select and justify<br>a RAG architecture</h1>
<p class="slide-subtitle"><strong>Tina</strong> is Cortex Bank and Trust's compliance assistant. One question against a 40,000-token SAR narrative wastes 99.5 percent of her context. You measure where that breaks, then make her choose a strategy per query.</p>
<div style="margin-top:auto;padding:10px 16px;background:rgba(255,255,255,0.12);border-radius:8px;border:1px solid rgba(255,255,255,0.25);font-size:13px;display:flex;align-items:center;gap:10px;max-width:420px;">
  <span style="font-size:18px;">&#8592;</span>
  <span><strong>Tip:</strong> Select <strong>Hide Instructions</strong> in the top bar to give the Brief full width.</span>
</div>

---

<!-- layout: problem -->

<div class="col-left">
  <div class="terminal-block">
Q: which account originated the structuring pattern?

sar-2024-0417   retrieved whole        40,218 tokens
  sec 1  Filing institution ........... 1,240
  sec 2  Subject identification ....... 2,980
  sec 3  Account history ............. 11,470
  sec 4  Transaction detail .......... 13,806
  sec 5  Related parties .............. 4,102
  sec 6  Prior filings ................ 2,820
  sec 7  Analyst notes ................ 2,493
<span style="color:var(--yellow);">  sec 8  Key finding ..................... 187  &lt;== the answer</span>
  sec 9  Attachments .................. 1,120

signal in context:  187 / 40,218  =  <span class="wrong">0.5%</span>
  </div>
</div>
<div class="col-right">
  <h2 class="slide-heading">The problem</h2>
  <p class="slide-body">One question. <strong>40,218 tokens</strong> sent. <strong>187</strong> of them hold the answer. Tina pays for the other 99.5 percent, and section 8 falls out of context before she reads it.</p>
  <p class="slide-body">You reproduce this in Build 1, across five narrative lengths.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div class="terminal-block">
naive
  query -> search -> top 5 passages -> answer
  decisions: none

advanced
  query -> read intent -> filter + search -> rerank
        -> top 5 passages -> answer
  decisions: <span style="color:var(--yellow);">+ which metadata clause</span>

agentic
  query -> think -> search -> think -> search -> answer
                      |_______ loop, up to 3 calls
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
"did the gold section reach the model"
whole-document retrieval, top 3 narratives

prec
1.0 | *--*
    |     \
.75 |......\................. <span class="wrong">floor</span>
    |       *
0.6 |        \
    |          *--*
0.4 |
    +-+--+--+--+--+
     1k 3k 8k 20k 40k   tokens per narrative

<span class="label">illustration only; your curve is your own</span>
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">The haystack problem</h2>
  <p class="slide-body">Retrieval quality is not a property of your retriever alone. It is a property of your retriever and your document length. A whole-document retriever that works at 1k has retrieved a haystack at 40k.</p>
  <p class="slide-body">Build 1 plots this curve on your corpus, in five length buckets.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div class="terminal-block">
       precision, falls        tokens sent, rises
  1k   ###############  0.95   ##  1,900
  3k   ##############   0.90   ####  5,700
  8k   ###########      0.68   ######  15,200
 20k   ########         0.48   ##########  38,400
 40k   ######           0.38   ##############  74,100
                   :               :
              0.75 floor      8,000 budget (seeded)

<span class="label">illustration only; both scales are relative</span>
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">Tokens are the other axis</h2>
  <p class="slide-body">Precision falls. Token cost rises. Neither depends on which model you call. Your <strong>break bucket</strong> is the smallest bucket that fails both tests, precision under the floor and tokens over the budget.</p>
  <p class="slide-body">Your budget is seeded. A different budget can move the break bucket.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div class="terminal-block">
Q: which account originated the structuring pattern?

WHOLE DOCUMENTS           PASSAGES
top 3 narratives          top 5 sections
-----------------------   ------------------------
0417   40,218 tok         0417 sec 8  finding  187
0390   21,044 tok         0417 sec 4  accounts 512
0356    8,901 tok         0390 sec 7  pattern  468
                          0356 sec 2  subject  441
                          0417 sec 6  priors   502
-----------------------   ------------------------
70,163 tokens sent        2,110 tokens sent
gold section <span class="wrong">LOST</span>         gold section <span style="color:var(--yellow);">RANK 1</span>
context truncated         top hit
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">Passages, not documents</h2>
  <p class="slide-body">Same question, same corpus, same retriever. Only the unit of retrieval changed. Retrieving a document bets that the whole document is relevant. Retrieving a section makes that bet one section at a time.</p>
  <p class="slide-body">Precision up. Tokens down 97 percent.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div class="terminal-block">
RAW REPORT                PRE-COMPUTED FACT RECORD
inv-2024-0083             inv-2024-0083
-----------------------   -------------------------
9 sections of prose       { "summary":          ...
4,860 tokens                "key_entities":     [..]
every question re-reads     "amounts":          [..]
all of it                   "dates":            [..]
                            "answers_questions":[..]
                            "topics":           [..] }
-----------------------   -------------------------
8 questions, top 3        8 questions, top 3
38,900 tokens             780 tokens      <span style="color:var(--yellow);">-98%</span>
precision 0.62            precision 0.84  <span style="color:var(--yellow);">+0.22</span>
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">Query the extraction, not the report</h2>
  <p class="slide-body">The extraction runs once, offline. Every question after that reads structured facts instead of prose. Precision rises, tokens fall.</p>
  <p class="slide-body"><strong>Knowledge Indicators</strong> is the product form that builds these records from your corpus.</p>
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

features the harness extracts:
  has_filter_intent     "tier 3 sanctions cases"
  asks_specific_figure  "what amount was wired"
  needs_multiple_docs   "which two reports share.."
  mentions_case_id      "case CB-2024-0417"

your routing order:
  needs_multiple_docs      ->  agentic
  has_filter_intent or id  ->  advanced
  otherwise                ->  naive
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">The strategy router</h2>
  <p class="slide-body">The harness extracts the features. You write the function that maps them to a strategy.</p>
  <p class="slide-body">Order matters. Test for a second hop before you test for filters, or an investigation query that also names a case type routes <code>advanced</code> and stops after one search.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div class="terminal-block">
Q  "tier 3 sanctions cases filed this quarter"
   routed   naive        should be   advanced
   got      5 structuring memos mentioning sanctions
   answer   <span class="wrong">WRONG</span>        tokens      2,410

Q  "which two reports share the beneficiary?"
   routed   advanced     should be   agentic
   got      one search, 5 passages, one report
   answer   <span class="wrong">INCOMPLETE</span>   second report never retrieved
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">Where Tina picks wrong</h2>
  <p class="slide-body">Under-routing costs accuracy. On the labelled dev set a wrong strategy drops answer accuracy by <strong>40 points</strong>.</p>
  <p class="slide-body">Over-routing costs tokens. A single-hop policy lookup sent through the agentic loop spends <strong>3x</strong> the tokens for the same answer.</p>
  <p class="slide-body">You watch both happen in Build 2.</p>
</div>

---

<!-- layout: rule -->
<!-- rule -->

<h2 class="slide-heading">Decision rule</h2>
<table class="rule-table">
  <tr><th>Characteristic</th><th>Pattern</th><th>Reason</th></tr>
  <tr><td>Single-hop lookup, one document</td><td>naive</td><td>No filter, no second hop</td></tr>
  <tr><td>Query names type, tier, or date</td><td>advanced</td><td>Metadata clause cuts contamination</td></tr>
  <tr><td>Facts from two or more documents</td><td>agentic</td><td>Hop two depends on hop one</td></tr>
</table>
<p class="rule-caption">agentic is never right for a single-hop lookup. naive is never right where a filter is named.</p>

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
    <span class="big-number">+0.15</span>
    <span class="big-number-label">fact-index precision<br>tokens 60% lower</span>
  </div>
</div>
<p class="rule-caption" style="color:var(--dark-grey);">Your per-bucket numbers must land within 0.10 precision and 15 percent tokens of the check's.</p>

---

<!-- layout: next -->

<h2 class="slide-heading">Select Check, then open Build 1</h2>
<p style="opacity:0.8;font-size:18px;">Environment status:</p>
<div class="status-indicator">
  <div class="status-dot"></div>
  <span class="status-text">Provisioning, check back in a moment</span>
</div>
<p style="font-size:15px;opacity:0.75;max-width:52ch;text-align:center;">The indicator turns green when provisioning finishes. Select Check at any time and it reports which step is still running.</p>
