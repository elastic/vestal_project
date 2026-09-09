<!-- layout: title -->

<p class="track-code">Self-Improving Agents</p>
<h1 class="slide-title">Diagnose. Fix. Measure.<br>Without touching the code.</h1>
<p class="slide-subtitle">Your inherited IT Helpdesk Agent is escalating everything. 90 minutes. OTel traces. One evaluator agent. Find out why, fix it, and prove it worked.</p>
<div style="margin-top:auto;padding:10px 16px;background:rgba(255,255,255,0.12);border-radius:8px;border:1px solid rgba(255,255,255,0.25);font-size:13px;display:flex;align-items:center;gap:10px;max-width:420px;">
  <span style="font-size:18px;">&#8592;</span>
  <span><strong>Tip:</strong> Select <strong>Hide Instructions</strong> in the top bar to give these slides full width.</span>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div style="width:100%;max-width:430px;border:1.5px solid var(--developer-blue);border-radius:12px;overflow:hidden;box-shadow:var(--shadow-md);">
    <div style="background:var(--developer-blue);color:var(--white);padding:10px 16px;font-family:var(--font-code);font-size:12px;letter-spacing:0.08em;">IT SERVICE DESK</div>
    <div style="padding:14px 16px;font-family:var(--font-code);font-size:13px;color:var(--ink);">
      <div style="display:flex;justify-content:space-between;padding:3px 0;"><span>ticket</span><strong style="color:var(--elastic-blue);">INC-20847</strong></div>
      <div style="display:flex;justify-content:space-between;padding:3px 0;"><span>priority</span><strong style="color:var(--light-poppy);">HIGH</strong></div>
      <div style="display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px solid var(--medium-grey);margin-bottom:10px;"><span>owner</span><strong>you</strong></div>
      <div style="font-size:12px;line-height:1.7;color:var(--ink);">escalation queue up 3x<br>4&ndash;6 turns per conversation<br>30 days of traces on disk</div>
    </div>
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">Your persona</h2>
  <p class="slide-body">You're an <strong>Agent Ops engineer</strong> at Nexus Corp. You didn't build the IT Helpdesk Agent&mdash;you inherited it. Today you own its ticket.</p>
</div>

---

<!-- layout: problem -->

<div class="col-left">
  <div class="terminal-block">
Employee: I can't connect to VPN from home.
          AnyConnect says certificate error.

IT Agent: What device and OS are you using?
Employee: Mac laptop.
IT Agent: Are you in the office or remote?
Employee: Remote.
IT Agent: What were you doing when this happened?
Employee: Just opened AnyConnect and tried to connect.
IT Agent: What have you already tried?
Employee: Nothing yet.
IT Agent: Thank you. I'll escalate this
          to a human IT agent.

<span class="label">tools called</span>
escalate-to-human   ok
create-ticket       ok
<span class="wrong">it-kb-search        never called</span>
  </div>
</div>
<div class="col-right">
  <h2 class="slide-heading">The complaint</h2>
  <p class="slide-body">Four clarifying questions, then escalation. The knowledge base had the VPN answer the whole time&mdash;the agent never looked. This conversation is in the trace data, and there are 30 days of it.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div style="width:100%;max-width:430px;display:flex;flex-direction:column;align-items:stretch;">
    <div style="border:1.5px solid var(--elastic-blue);border-radius:10px;padding:12px 16px;background:rgba(11,100,221,0.06);">
      <div style="font-family:var(--font-code);font-size:12px;letter-spacing:0.06em;color:var(--elastic-blue);font-weight:700;">IT HELPDESK AGENT</div>
      <div style="font-size:12px;color:var(--ink);margin-top:5px;line-height:1.6;">Live in production. Naive prompt.<br>KB search, escalate, create ticket.</div>
    </div>
    <div style="display:flex;align-items:center;gap:10px;padding:6px 0 6px 26px;">
      <div style="display:flex;flex-direction:column;align-items:center;">
        <div style="width:2px;height:26px;background:var(--medium-grey);"></div>
        <div style="width:0;height:0;border-left:5px solid transparent;border-right:5px solid transparent;border-top:8px solid var(--medium-grey);"></div>
      </div>
      <div style="font-family:var(--font-code);font-size:11px;color:var(--dark-grey);letter-spacing:0.06em;">OTel spans</div>
    </div>
    <div style="border:1.5px solid var(--logo-teal);border-radius:10px;padding:12px 16px;background:rgba(2,188,183,0.07);">
      <div style="font-family:var(--font-code);font-size:12px;letter-spacing:0.06em;color:var(--logo-teal);font-weight:700;">EVALUATOR AGENT</div>
      <div style="font-size:12px;color:var(--ink);margin-top:5px;line-height:1.6;">Reads 30 days of spans.<br>Diagnoses. Proposes. Applies.</div>
    </div>
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">Two agents, one sandbox</h2>
  <p class="slide-body">One is the patient. One is the doctor. Both live in Agent Builder. You talk to the evaluator in plain English; it reads the patient's traces.</p>
</div>

---

<!-- layout: problem -->

<div class="col-left">
  <div class="terminal-block">
<span class="label">span tree - one conversation</span>

agent.run                        12.4s
|- chat.completion                2.1s
|    turn 1  "what device and OS?"
|- chat.completion                1.8s
|    turn 2  "office or remote?"
|- chat.completion                2.0s
|    turn 3  "what were you doing?"
|- chat.completion                1.9s
|    turn 4  "what have you tried?"
|- tool.escalate-to-human          .3s
`- tool.create-ticket              .4s

<span class="label">attributes on every span</span>
gen_ai.conversation.id
gen_ai.agent.name
gen_ai.tool.name
workshop.topic = vpn
  </div>
</div>
<div class="col-right">
  <h2 class="slide-heading">What a trace records</h2>
  <p class="slide-body">Agent Builder emits OpenTelemetry spans on its own: every turn, every tool call, every escalation, with timings and token counts. Nobody instrumented this agent. The evidence was already there.</p>
</div>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div style="width:100%;max-width:400px;display:flex;flex-direction:column;gap:6px;">
    <div style="display:flex;align-items:center;gap:12px;padding:8px 14px;border-left:3px solid var(--elastic-blue);background:rgba(11,100,221,0.05);border-radius:0 6px 6px 0;"><span style="font-family:var(--font-code);font-size:12px;color:var(--dark-grey);">01</span><span style="font-weight:600;font-size:14px;">Trace</span></div>
    <div style="display:flex;align-items:center;gap:12px;padding:8px 14px;border-left:3px solid var(--elastic-blue);background:rgba(11,100,221,0.05);border-radius:0 6px 6px 0;"><span style="font-family:var(--font-code);font-size:12px;color:var(--dark-grey);">02</span><span style="font-weight:600;font-size:14px;">Diagnose</span></div>
    <div style="display:flex;align-items:center;gap:12px;padding:8px 14px;border-left:3px solid var(--elastic-blue);background:rgba(11,100,221,0.05);border-radius:0 6px 6px 0;"><span style="font-family:var(--font-code);font-size:12px;color:var(--dark-grey);">03</span><span style="font-weight:600;font-size:14px;">Propose</span></div>
    <div style="display:flex;align-items:center;gap:12px;padding:10px 14px;border-left:3px solid var(--light-poppy);background:rgba(255,149,125,0.16);border-radius:0 6px 6px 0;"><span style="font-family:var(--font-code);font-size:12px;color:var(--ink);">04</span><span style="font-weight:700;font-size:14px;">Approve</span><span style="font-family:var(--font-code);font-size:11px;color:var(--ink);margin-left:auto;">you</span></div>
    <div style="display:flex;align-items:center;gap:12px;padding:8px 14px;border-left:3px solid var(--elastic-blue);background:rgba(11,100,221,0.05);border-radius:0 6px 6px 0;"><span style="font-family:var(--font-code);font-size:12px;color:var(--dark-grey);">05</span><span style="font-weight:600;font-size:14px;">Apply</span></div>
    <div style="display:flex;align-items:center;gap:12px;padding:8px 14px;border-left:3px solid var(--elastic-blue);background:rgba(11,100,221,0.05);border-radius:0 6px 6px 0;"><span style="font-family:var(--font-code);font-size:12px;color:var(--dark-grey);">06</span><span style="font-weight:600;font-size:14px;">Measure</span></div>
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">The evaluation loop</h2>
  <p class="slide-body">Six steps. You own exactly one. The evaluator traces, diagnoses, proposes, applies through Elastic Workflows, and measures. Step 04 is the human gate.</p>
</div>

---

<!-- layout: rule -->
<!-- rule -->

<h2 class="slide-heading">The rule</h2>
<p class="slide-body" style="max-width:560px;margin:0 auto;text-align:center;">You diagnose from <strong>data</strong>, not intuition. You <strong>approve</strong> the fix&mdash;you don't write it. The machine <strong>applies</strong> it and measures the result. That is agent operations in production.</p>

---

<!-- layout: concept -->

<div class="col-diagram">
  <div style="width:100%;max-width:420px;display:flex;flex-direction:column;gap:8px;">
    <div style="display:flex;gap:14px;align-items:baseline;padding-bottom:8px;border-bottom:1px solid var(--medium-grey);"><span style="font-family:var(--font-code);font-size:11px;color:var(--elastic-blue);letter-spacing:0.06em;min-width:52px;">LAB 1</span><span style="font-size:14px;">Inspect the agent, run a baseline</span></div>
    <div style="display:flex;gap:14px;align-items:baseline;padding-bottom:8px;border-bottom:1px solid var(--medium-grey);"><span style="font-family:var(--font-code);font-size:11px;color:var(--elastic-blue);letter-spacing:0.06em;min-width:52px;">LAB 2</span><span style="font-size:14px;">Interrogate 30 days of traces</span></div>
    <div style="display:flex;gap:14px;align-items:baseline;padding-bottom:8px;border-bottom:1px solid var(--medium-grey);"><span style="font-family:var(--font-code);font-size:11px;color:var(--elastic-blue);letter-spacing:0.06em;min-width:52px;">LAB 3</span><span style="font-size:14px;">Approve a fix, watch it apply</span></div>
    <div style="display:flex;gap:14px;align-items:baseline;padding-bottom:8px;border-bottom:1px solid var(--medium-grey);"><span style="font-family:var(--font-code);font-size:11px;color:var(--elastic-blue);letter-spacing:0.06em;min-width:52px;">LAB 4</span><span style="font-size:14px;">Regression set, honest numbers</span></div>
    <div style="display:flex;gap:14px;align-items:baseline;"><span style="font-family:var(--font-code);font-size:11px;color:var(--logo-teal);letter-spacing:0.06em;min-width:52px;">BONUS</span><span style="font-size:14px;">The agent grows a capability</span></div>
  </div>
</div>
<div class="col-text">
  <h2 class="slide-heading">What you'll do</h2>
  <p class="slide-body">Four labs and a bonus chapter. You never hand-edit a config.</p>
</div>

---

<!-- layout: next -->

<h2 class="slide-heading">Lab 1: The Ticket</h2>
<p class="slide-body">You have a ticket. Let's start there.</p>
