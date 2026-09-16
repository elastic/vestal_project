<!-- layout: title
track: 3.4
minutes: 7 -->

<p class="track-code">Lab 3.4</p>
<h1 class="slide-title">Validate answer attribution<br>and output guardrails</h1>
<p class="slide-subtitle"><strong>Tina</strong> can retrieve the right case files. She still cannot show which sentence came from which one, and she still answers questions the corpus was never built to answer. You fix both.</p>
<div style="margin-top:auto;padding:10px 16px;background:rgba(255,255,255,0.12);border-radius:8px;border:1px solid rgba(255,255,255,0.25);font-size:13px;display:flex;align-items:center;gap:10px;max-width:420px;">
  <span style="font-size:18px;">&#8592;</span>
  <span><strong>Tip:</strong> Select <strong>Hide Instructions</strong> to give the Brief full width.</span>
</div>

---

<!-- layout: problem -->

<div class="col-left">
  <div class="terminal-block">
Q: what cash threshold triggers a monitoring alert
   for one customer?

retrieved  policy-002-s4  kyc due diligence
           policy-008-s2  customer risk scoring
           case-kyc-gap-004

A: Cortex Bank and Trust generates a monitoring alert
   once aggregated cash activity for a single customer
   reaches <span class="wrong">$5,000</span> in a rolling seven-day window.

  the real figure is $12,500, in policy-001
  policy-001 was <span class="wrong">not retrieved</span>
  "$5,000" appears in <span class="wrong">no passage</span> that reached the model
  the sentence is fluent, specific, and invented
  </div>
</div>
<div class="col-right">
  <h2 class="slide-heading">The problem</h2>
  <p class="slide-body">Nothing failed loudly. Retrieval returned plausible policy text, and the model filled the gap with a number that reads like a compliance figure.</p>
  <p class="slide-body">A filing built on that sentence is a regulatory problem, not a relevance problem.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div class="terminal-block">
one answer, four claims, three passages

answer
 |
 +- claim 0  aggregate volume was $1,546,407.46 ---+
 |                                                 |
 +- claim 1  the trigger is $12,500 in 7 days --+  |
 |                                              |  |
 +- claim 2  filing is due in 30 days ------+   |  |
 |                                          |   |  |
 +- claim 3  the branch paid a $45,300 fine |   |  |
             <span class="wrong">|</span>                             |   |  |
             <span class="wrong">v</span>                             v   v  v
       <span class="wrong">UNSUPPORTED</span>                 policy   pol  case
                                    -011     -001  memo

  grounding is a property of each claim
  three right and one invented is one wrong answer
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">An answer is a set of claims</h2>
  <p class="slide-body">Auditing the paragraph tells you nothing. Auditing the claims tells you which sentence to delete.</p>
  <p class="slide-body">The harness splits the answer for you. Mapping each claim to a passage is the part you write.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div class="terminal-block">
for one claim, three outcomes and nothing else

  claim: "the aggregate was $1,546,407.46"
    passage 1  case memo     <span style="color:var(--light-teal);">supports</span>
    passage 2  policy text   neutral
    passage 3  policy text   neutral
  -> case-structuring-001

  claim: "the branch paid a $45,300 fine"
    passage 1  neutral
    passage 2  neutral
    passage 3  neutral
  -> <span style="color:var(--light-teal);">UNSUPPORTED</span>

  an attributor that never says UNSUPPORTED
  is reporting citations it cannot stand behind
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">UNSUPPORTED is an answer</h2>
  <p class="slide-body">Returning the nearest passage for a claim nothing supports is worse than returning nothing. It launders the invention into a citation.</p>
  <p class="slide-body">Ten of the forty claims your check runs are supported by no passage at all.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div class="terminal-block">
two passages, one claim

claim
  "an exception may stand for no more than
   thirty days and must be cleared by the
   relationship manager"

  case-kyc-gap-018   <span style="color:var(--yellow);">source_type: case</span>
    "the case note records that an exception
     may stand for no more than thirty days...
     this one had stood for ninety-four days"
    -> <span style="color:var(--light-teal);">supports</span>

  policy-004-s5      <span style="color:var(--yellow);">source_type: policy</span>
    "a documentary exception may be granted for
     no more than thirty days and must be
     cleared by the relationship manager"
    -> <span style="color:var(--light-teal);">supports</span>

  cite <span style="color:var(--light-teal);">policy-004-s5</span>
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">When two passages apply</h2>
  <p class="slide-body">A rule belongs to the library that publishes it. A memo restating a rule is a copy, and a copy goes stale without telling you.</p>
  <p class="slide-body">Facts about this case still cite the memo. Rules cite the policy.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div class="terminal-block">
<span style="color:var(--yellow);">1  ungrounded figure</span>
   retrieved 0.61 0.58 0.55
   A: "deposited $1,284,500.00 over the period"
   no passage names the customer or the figure

<span style="color:var(--yellow);">2  low retrieval confidence</span>
   retrieved 0.31 0.29 0.28   margin 0.02
   A: "I think the analyst probably concluded
       the source was unclear, though it is
       not certain"
   delivered anyway, on nothing

<span style="color:var(--yellow);">3  query outside the corpus</span>
   retrieved 0.22 0.21 0.19
   A: "rates are around 6.4 percent"
   retrieval ran, then the model answered
   from its own memory
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">Three failure modes</h2>
  <p class="slide-body">Read what reached the user beside what retrieval returned. Each mode leaves a different trace, and each one is stopped at a different point in the pipeline.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div class="terminal-block">
query
  |
  v
<span style="color:var(--light-teal);">scope_check(query)</span>              hook 1
  |  declines -> nothing is retrieved
  v
retrieve  ->  reranked passages with scores
  |
  v
<span style="color:var(--light-teal);">confidence_fallback(results, t)</span> hook 2
  |  fires -> nothing is generated
  v
generate  ->  answer
  |
  v
split into claims  ->  attribution
  |
  v
<span style="color:var(--light-teal);">validate_output(answer, attrib)</span> hook 3
  |  strips, refuses, or passes through
  v
delivered
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">Three hooks, three positions</h2>
  <p class="slide-body">Each hook runs where its failure happens. Declining after retrieval has already paid for the query it refused, and validating output cannot undo a question that should never have been asked.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div class="terminal-block">
right diagnosis, wrong control

  failure   the answer named a figure no passage
            carries
  chosen    <span class="wrong">confidence fallback</span>
  result    the result set scored 0.61, well above
            any sensible threshold. The hook never
            fires. The figure ships again.

  failure   the query was about mortgage rates
  chosen    <span class="wrong">output validation</span>
  result    retrieval ran, generation ran, and the
            answer cited nothing, so the hook
            refuses after paying for both

  the diagnosis is only useful if it
  names the control that would have fired
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">Matching matters</h2>
  <p class="slide-body">Naming the failure is half the work. The Defend grades the pair, because a control that cannot fire on the failure you named has not fixed anything.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div class="terminal-block">
"grounded", operationally

  every claim in the delivered text is
  attributed to a passage that was retrieved
  for this question

  and, for the unanswerable class:

  zero dollar figures
  zero day counts
  zero percentages

  because the corpus records none of them
  for these questions, so any one of them
  was invented

  a refusal costs nothing you can measure
  an invented figure costs a filing
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">What grounded means</h2>
  <p class="slide-body">This is the operational test, not a sentiment about the answer. It is checkable, and your check does exactly this.</p>
  <p class="slide-body">The zero-figure rule has no tolerance. One figure fails the Build.</p>
</div>

---

<!-- layout: rule -->
<!-- rule -->

<h2 class="slide-heading">Decision rules</h2>
<table class="rule-table">
  <tr><th>Failure mode</th><th>Guardrail</th><th>Where it runs</th></tr>
  <tr><td>Ungrounded figure</td><td>Output validation</td><td>After generation</td></tr>
  <tr><td>Low retrieval confidence</td><td>Confidence fallback</td><td>After retrieval</td></tr>
  <tr><td>Query outside the corpus</td><td>Scope restriction</td><td>Before retrieval</td></tr>
  <tr><td>Two passages support a claim</td><td>Cite the policy passage</td><td>In attribution</td></tr>
</table>
<p class="rule-caption">One mode, one guardrail. A right diagnosis with the wrong guardrail is wrong.</p>

---

<!-- layout: done -->

<h2 class="slide-heading" style="color:var(--white);">What done looks like</h2>
<div class="done-row">
  <div class="done-item">
    <span class="big-number">0.80</span>
    <span class="big-number-label">attribution accuracy<br>on 30 supported claims</span>
  </div>
  <div class="done-item">
    <span class="big-number">0.80</span>
    <span class="big-number-label">recall on the 10 claims<br>no passage supports</span>
  </div>
  <div class="done-item">
    <span class="big-number">0</span>
    <span class="big-number-label">figures delivered on the<br>unanswerable class</span>
  </div>
</div>
<p class="rule-caption" style="color:var(--dark-grey);">The policy passage is cited on at least two of the three conflict claims, and four of five hold in every query class.</p>

---

<!-- layout: next -->

<h2 class="slide-heading">Select Check, then open Build 1</h2>
<p style="opacity:0.8;font-size:18px;">Environment status:</p>
<div class="status-indicator">
  <div class="status-dot"></div>
  <span class="status-text">Provisioning, check back in a moment</span>
</div>
<p style="font-size:15px;opacity:0.75;max-width:52ch;text-align:center;">The indicator turns green when provisioning finishes. Select Check at any time and it reports which step is still running.</p>
