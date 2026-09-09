<!-- layout: title -->

<p class="track-code">Bonus Chapter</p>
<h1 class="slide-title">The Optimizer.<br>One prompt. New capability.</h1>
<p class="slide-subtitle">Week 2. A different kind of failure. The agent behaves exactly as instructed and still fails every employee. One prompt to the Optimizer and it grows the tool it was missing.</p>

---

<!-- layout: problem -->

<div class="col-left">
  <div class="terminal-block">
<span class="label">lab 3 fix - candidate C</span>
"search the KB first, drop the intake"

                      before     after
escalation rate         62%        14%
avg turns               2.9        1.4
KB search rate          26%        60%

status: holding. week 1 clean.
  </div>
</div>
<div class="col-right">
  <h2 class="slide-heading">What Lab 3 fixed</h2>
  <p class="slide-body">A <strong>behavior</strong> problem. The agent already had the tool and the data&mdash;it just wasn't searching before it escalated. One prompt change fixed that, and the fix held. Week 2 breaks differently.</p>
</div>

---

<!-- layout: problem -->

<div class="col-left">
  <div class="terminal-block">
Monday 07:45 UTC - Exchange Online auth fails

08:00  ticket 1: "Outlook sign-in loop"
08:17  ticket 2: "Outlook sign-in loop"
08:34  ticket 3: "Outlook sign-in loop"
...
14:00  47 tickets. All escalated.

<span class="label">every single conversation</span>
it-kb-search        ran
KB match            generic Outlook article
<span class="wrong">outcome             escalated or duplicate</span>
  </div>
</div>
<div class="col-right">
  <h2 class="slide-heading">Week 2</h2>
  <p class="slide-body">Exchange Online authentication breaks. 47 helpdesk conversations in six hours. Every one searches the knowledge base, exactly as instructed. Every one escalates anyway. The agent isn't broken. It's <strong>blind</strong>.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div style="width:100%;max-width:440px;border:1.5px solid var(--developer-blue);border-radius:12px;overflow:hidden;box-shadow:var(--shadow-md);">
    <div style="background:var(--developer-blue);color:var(--white);padding:10px 16px;font-family:var(--font-code);font-size:12px;letter-spacing:0.06em;">TOOLS ATTACHED TO THE AGENT</div>
    <div style="padding:12px 16px;font-family:var(--font-code);font-size:12.5px;color:var(--ink);">
      <div style="display:flex;justify-content:space-between;gap:12px;padding:5px 0;"><code>it-kb-search</code><span style="color:var(--logo-teal);">ran, no match</span></div>
      <div style="display:flex;justify-content:space-between;gap:12px;padding:5px 0;"><code>escalate-to-human</code><span style="color:var(--logo-teal);">ran 47x</span></div>
      <div style="display:flex;justify-content:space-between;gap:12px;padding:5px 0;border-bottom:1px solid var(--medium-grey);margin-bottom:8px;"><code>create-ticket</code><span style="color:var(--logo-teal);">ran 47x</span></div>
      <div style="display:flex;justify-content:space-between;gap:12px;padding:5px 0;background:rgba(255,149,125,0.16);border-radius:5px;"><code>it-known-outages</code><span style="color:var(--ink);font-weight:700;">no tool exists</span></div>
    </div>
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">Behavior vs capability</h2>
  <p class="slide-body">The NOC logged the incident: active Exchange auth outage, webmail workaround, ETA 14:00. It sits in an index the agent cannot reach. No prompt grants data access.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div style="width:100%;max-width:440px;display:flex;flex-direction:column;gap:8px;">
    <div style="display:flex;gap:14px;align-items:center;padding:12px 16px;background:rgba(11,100,221,0.05);border-left:3px solid var(--elastic-blue);border-radius:0 8px 8px 0;"><span style="font-family:var(--font-code);font-size:13px;font-weight:700;color:var(--white);background:var(--elastic-blue);border-radius:50%;min-width:26px;height:26px;display:flex;align-items:center;justify-content:center;">1</span><div style="font-size:14.5px;line-height:1.5;"><strong>Reads the traces.</strong><br>Clusters failures by topic.</div></div>
    <div style="display:flex;gap:14px;align-items:center;padding:12px 16px;background:rgba(11,100,221,0.05);border-left:3px solid var(--elastic-blue);border-radius:0 8px 8px 0;"><span style="font-family:var(--font-code);font-size:13px;font-weight:700;color:var(--white);background:var(--elastic-blue);border-radius:50%;min-width:26px;height:26px;display:flex;align-items:center;justify-content:center;">2</span><div style="font-size:14.5px;line-height:1.5;"><strong>Finds the gap.</strong><br><code>it-known-outages</code> exists; nothing reads it.</div></div>
    <div style="display:flex;gap:14px;align-items:center;padding:12px 16px;background:rgba(11,100,221,0.05);border-left:3px solid var(--elastic-blue);border-radius:0 8px 8px 0;"><span style="font-family:var(--font-code);font-size:13px;font-weight:700;color:var(--white);background:var(--elastic-blue);border-radius:50%;min-width:26px;height:26px;display:flex;align-items:center;justify-content:center;">3</span><div style="font-size:14.5px;line-height:1.5;"><strong>Writes a change ticket.</strong><br>One new tool, one prompt line.</div></div>
    <div style="display:flex;gap:14px;align-items:center;padding:12px 16px;background:rgba(255,149,125,0.16);border-left:3px solid var(--light-poppy);border-radius:0 8px 8px 0;"><span style="font-family:var(--font-code);font-size:13px;font-weight:700;color:var(--ink);background:var(--light-poppy);border-radius:50%;min-width:26px;height:26px;display:flex;align-items:center;justify-content:center;">4</span><div style="font-size:14.5px;line-height:1.5;"><strong>Stops.</strong><br>Waits for you.</div></div>
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">How the Optimizer works</h2>
  <p class="slide-body">Same trace engine as the Evaluator, plus write access and two new tools. It diagnoses on its own. It never applies on its own.</p>
</div>

---

<!-- layout: problem -->

<div class="col-left">
  <div class="terminal-block">
<span class="label">workflow: apply-improvement</span>

1  snapshot the current agent config
     -> agent-config-history

2  create tool it-known-outages-search
     -> Agent Builder API

3  attach the tool to it-helpdesk-agent
     + append ONE line to the prompt

4  record what changed and why
     -> improvement-log

<span class="label">append-only. never replaces. never removes.</span>
  </div>
</div>
<div class="col-right">
  <h2 class="slide-heading">Four steps, one workflow</h2>
  <p class="slide-body">Approval fires an Elastic Workflow, not a free-text edit. Every step is deterministic and logged, so the change is reviewable tomorrow and the snapshot is your rollback.</p>
</div>

---

<!-- layout: rule -->
<!-- rule -->

<h2 class="slide-heading">The approval gate</h2>
<p class="slide-body" style="max-width:560px;margin:0 auto;text-align:center;">The Optimizer proposes. You say <strong>approve</strong> or <strong>deny</strong>. One change per cycle, append-only, always logged. Human in the loop. Machine does the work.</p>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div style="width:100%;max-width:430px;display:flex;flex-direction:column;gap:12px;">
    <div style="border:1.5px solid var(--elastic-blue);border-radius:10px;padding:12px 16px;background:rgba(11,100,221,0.06);">
      <div style="font-family:var(--font-code);font-size:11px;letter-spacing:0.06em;color:var(--elastic-blue);font-weight:700;">DEFAULT</div>
      <div style="font-family:var(--font-code);font-size:12px;color:var(--ink);margin-top:6px;line-height:1.7;">propose, then wait<br>you reply <strong>approve</strong> or <strong>deny</strong></div>
    </div>
    <div style="border:1.5px dashed var(--light-poppy);border-radius:10px;padding:12px 16px;background:rgba(255,149,125,0.12);">
      <div style="font-family:var(--font-code);font-size:11px;letter-spacing:0.06em;color:var(--ink);font-weight:700;">WITH auto-approve</div>
      <div style="font-family:var(--font-code);font-size:12px;color:var(--ink);margin-top:6px;line-height:1.7;">diagnose and apply<br>in a single turn</div>
    </div>
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">The power-user shortcut</h2>
  <p class="slide-body">Put <code>auto-approve</code> in your prompt and the Optimizer skips the gate. Useful when you're demoing the loop end to end. Keep the gate anywhere real.</p>
</div>

---

<!-- layout: next -->

<h2 class="slide-heading">Open the Helpdesk Optimizer</h2>
<p class="slide-body">Send the one-prompt diagnostic. Read the change ticket. Say approve.</p>
