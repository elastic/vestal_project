# Elastic Agentic Retrieval Architect

## Learning Path Syllabus

**Status:** Draft v1.0, 2026-09-04. Publishable once Jeff approves wording. Beta program: modules release individually through late 2026; the certification exam follows in beta at year end. Features marked *preview* are taught in the training and excluded from the exam until they reach general availability.

---

### The one-sentence version

You will design, build, secure, measure, and keep improving a production AI assistant whose retrieval layer is Elasticsearch, using any LLM, and you will prove it in a live environment.

### Who this is for

Working AI and ML engineers, solution architects, and platform engineers who have already shipped an LLM feature and hit the wall: retrieval quality, cost, hallucination, security, or "it worked in the demo." You should be comfortable with Python, HTTP APIs, and JSON, and you should have used Elasticsearch or a comparable search engine at least once. You do not need to be an Elasticsearch administrator.

This is not an introduction to AI. If you need to learn what an embedding is, start with the Associate path and come back.

### What you will build

One system, end to end. Across six modules you build **Tina**, the compliance and fraud analyst assistant for **Cortex Bank and Trust**, a fictional institution with a real-sized corpus: an anti-money-laundering policy manual, suspicious activity report narratives, wire-fraud investigation files, a risk-scoring reference, and transaction data. Every module adds a layer to Tina. Every lab measures whether the layer worked. You leave with an architecture you built and can defend, not a folder of notebooks you ran.

### How the training works

Every track follows the same shape:

- **Brief.** A short visual briefing on the scenario, the constraint Tina is about to hit, and what "done" looks like. Five to eight minutes.
- **Build.** You produce something with real latitude: a mapping, a retrieval configuration, a workflow, an agent definition, a security role, a test set. The check measures what your artifact does, not what you say about it.
- **Defend.** You make the call an architect would make, and you justify it with your own measured numbers. Right answer with the wrong reason is a miss.

Each track runs 35 to 45 minutes and stands alone. Take one in a lunch break, come back tomorrow for the next. Each module closes with an **Architect's Challenge**: a 45-minute, spec-only problem with no hints, graded the way the exam is graded.

### Why Elastic, and why this cert exists

Every major AI certification on the market is a multiple-choice exam about a vendor's model or platform. None of them test retrieval engineering, retrieval-layer security, RAG evaluation, or agent observability as hands-on skills, and the leading LLM-vendor architect cert explicitly excludes embedding models and vector databases from scope. That is exactly where production AI systems succeed or fail. This path covers that ground with live infrastructure and measured outcomes, in the tradition of Elastic's existing hands-on engineer certifications.

---

## The path at a glance

| Module | Title | What you add to Tina | Tracks | Seat time | Exam domain |
|---|---|---|---|---|---|
| 1 | AI and LLM Foundations | Her first working agent, grounded in Elasticsearch | 4 + capstone | ~3 h | D1, 5% |
| 2 | Search and Retrieval Engineering | The retrieval layer, tuned and measured | 4 + capstone | ~3.5 h | D2, 20% |
| 3 | RAG Architecture and Context Design | The context pipeline: what reaches the model and why | 4 + capstone | ~3.5 h | D3, 20% |
| 4 | Building Agentic Systems | Tina rebuilt on Agent Builder, exposed over MCP, driven by a coding agent | 5 + capstone | ~4 h | D4, 25% |
| 5 | Production AI: Security and Evaluation | Tina hardened and measured before she ships | 4 + capstone | ~3.5 h | D5, 15% |
| 6 | Agent Observability and Self-Improvement | Tina in production, watched, and improving herself | 4 + capstone | ~3 h | D6, 15% |

Total: roughly 20 to 22 hours of hands-on work. Exam domain weights are proposed and subject to confirmation by the certification team.

---

## Module 1: AI and LLM Foundations

**Why it matters.** Most production failures are not model failures. They are the wrong model type for the task, an ungrounded prompt, a schema that validates but lies, or an agent loop that never needed to exist. This module teaches you to diagnose those before you build, then builds Tina's first working agent the right way.

| Track | What you build | What you defend |
|---|---|---|
| 1.1 Diagnose Tina's failures | Run Tina's three model types (LLM, embedding, reranker) on Cortex tasks; analyze her broken responses; repair a system prompt and verify the fix | Which failure mode explains each broken response, and which prompt element caused it |
| 1.2 Structured output and retrieval versus fine-tuning | Diagnose a reasoning trace; build a schema-validated response that is also semantically correct; build Tina's first retrieval pipeline over Cortex policy documents; update the source and re-query | When schema validity is not enough, and why retrieval beats fine-tuning when the source changes |
| 1.3 Build Tina: from completion to ReAct on Elasticsearch | Choose a model tier under a data-residency constraint with measured cost and latency; then build Tina in four stages: bare completion, context injected from the Cortex policy index, an Elasticsearch search tool, a ReAct loop that answers a multi-step compliance question | What each stage could not do, evidenced by what it actually returned on a Cortex question |
| 1.4 Harness and memory | Wire a memory store so Tina carries state across turns; evaluate a harness choice against Cortex's constraints | Which memory scope and harness fit a stated operating constraint |
| 1.C Architect's Challenge | Tina v0: a ReAct agent over the Cortex policy index that answers three held-out compliance questions correctly with cited sources, under a stated token budget | |

## Module 2: Search and Retrieval Engineering

**Why it matters.** Retrieval quality is the ceiling on everything downstream. This is the module no other certification teaches: chunking, hybrid search, reranking, vector index economics, embedding lifecycle, and how to measure whether any of it worked.

| Track | What you build | What you defend |
|---|---|---|
| 2.1 Configure core retrieval infrastructure | Chunk and index the Cortex corpus with `semantic_text` and Jina embeddings; configure an LLM inference endpoint | A chunking strategy, evidenced by what it did to a structured table that naive chunking destroys |
| 2.2 Tune retrieval quality | Compare BM25, dense, hybrid, and reranked retrieval on Cortex queries; tune HNSW and BBQ quantization; measure precision@k, recall@k, and nDCG | A ship or no-ship call between two configurations using your own metrics |
| 2.3 Embedding lifecycle | Build a representative test set and benchmark a candidate embedding model; migrate models with zero failed queries during cutover; raise recall query-side with HyDE and rewriting without re-indexing | Deploy or hold, from your measured relevance and latency against a hard budget |
| 2.4 Production cost | Write parameterized ES\|QL over Cortex transactions; build a semantic cache verified at the Elasticsearch layer; implement a deterministic model router | Where caching pays and where routing to a smaller model is safe, from your hit rates and quality deltas |
| 2.C Architect's Challenge | Retrieval SLO: on 25 labeled Cortex queries, reach a stated nDCG@10 under a stated p95 latency within a stated index footprint, by any lever you choose. Then show Tina answers better. | |

## Module 3: RAG Architecture and Context Design

**Why it matters.** Getting the right document is half the problem. Getting the right 300 tokens of it in front of the model, with provenance, inside a budget, is the other half. This module covers RAG patterns, the haystack problem, pre-computed knowledge, metadata strategy, context packing, attribution, and guardrails.

| Track | What you build | What you defend |
|---|---|---|
| 3.1 RAG architecture selection | Analyze token cost against precision on Cortex SAR narratives to find where full-document retrieval breaks; run Tina as an agentic RAG system that picks a retrieval strategy per query and see where she picks wrong | Which RAG pattern fits each of three Cortex scenarios, and the reason |
| 3.2 Knowledge Indicator pipeline *(preview)* | Author the extraction schema and agent prompt for a Workflow that pre-computes structured facts from wire-fraud investigation reports into an AI Index; design routing profiles across Cortex indices | Whether pre-computation pays for a given corpus, from your measured cost and precision deltas |
| 3.3 Retrieval optimization | Ingest Cortex documents with the right mappings; apply metadata filters on case type and risk tier to hit a precision target; choose a context-packing strategy per scenario | Reranking-to-top-N or summarize-first, and why, for two concrete context budgets |
| 3.4 Answer validation | Implement claim-level attribution across retrieved passages; diagnose three guardrail failures and apply the matching control | Which guardrail addresses which failure mode, consistently |
| 3.C Architect's Challenge | Token budget: answer 20 held-out Cortex compliance questions at a stated precision, with every claim attributed, inside a stated context budget per query | |

## Module 4: Building Agentic Systems

**Why it matters.** An agent is tools plus judgment plus boundaries. This module rebuilds Tina on Elastic Agent Builder and covers the decisions that separate a demo agent from a production one: tool design, skill composition, multi-agent allocation, conversational state, interoperability over MCP, and action safety.

| Track | What you build | What you defend |
|---|---|---|
| 4.1 Agent Builder fundamentals and core tools | Tina on Agent Builder with parameterized ES\|QL tools and a Workflow tool over Cortex transaction and case data | When a tool should be ES\|QL and when it should be a Workflow |
| 4.2 Skills, automation, and multi-agent composition | Package tools into a skill with a playbook; write agent instructions that ground and escalate; build a coordinator plus specialists for fraud triage | Task allocation between agents, evidenced by routing traces |
| 4.3 Multi-turn state and query reformulation | Diagnose what a session reset drops; configure reformulation so follow-up questions retrieve correctly | Which context elements must persist and why |
| 4.4 Agents outside Kibana: MCP and coding agents | Learn how MCP works under the hood, expose Tina's tools through the Kibana-hosted MCP server, then connect a coding agent (Claude Code or the Elastic CLI) to it and complete a real task against Elasticsearch through Tina's tools | Which tools to expose over MCP, with what scopes, and what a coding agent should never be allowed to call |
| 4.5 Action safety and extension | Classify agent actions by risk; add a human approval gate to an irreversible Workflow *(preview)*; install a plugin and connector that fetch live external data | Which actions need a human, evidenced by the risk classification |
| 4.C Architect's Challenge | Multi-agent allocation and safety: given a fraud-triage scenario, build the coordinator, specialists, tools, and gates that route five held-out cases correctly and pause on the one that requires approval | |

## Module 5: Production AI: Security and Evaluation

**Why it matters.** Make it trustworthy before you ship. Retrieval-layer security and evaluation methodology are the two gates every production AI system passes or fails, and no other certification covers either hands-on.

| Track | What you build | What you defend |
|---|---|---|
| 5.1 Access control | Predict, then configure, document- and field-level security so each Cortex analyst role retrieves only what it is allowed to see through Tina | What a given API key and role can actually retrieve, before and after |
| 5.2 Adversarial threats and sensitive data | Run Tina against planted injection payloads in retrieved documents, classify what got through, mitigate, and re-run; restrict connector scope; select PII controls at ingest and retrieval | Which control at which layer, justified against the observed attack |
| 5.3 Build the evaluation harness | Build a test set that represents Cortex's real query distribution, including edge cases; implement a metrics pipeline for retrieval and RAG quality; compute Tina's baseline | Why the test set is representative, evidenced by its coverage |
| 5.4 Before-and-after measurement | Change one thing about Tina, run the harness before and after, and make the ship or no-ship call when quality and cost disagree | The gate decision from your own numbers |
| 5.C Architect's Challenge | Ship gate: given a proposed change and the M5 harness, secure the change, measure it, and produce a ship or no-ship decision that matches the measured result | |

## Module 6: Agent Observability and Self-Improvement

**Why it matters.** Keep it good after you ship. Elastic is the only platform where agent tracing, evaluation, and automated refinement run in the same place as the data. This module closes the loop.

| Track | What you build | What you defend |
|---|---|---|
| 6.1 Diagnose agent behavior from traces | Read Tina's per-step traces; find the failing step and the expensive step; tune a misfiring ES\|QL tool; identify a coverage gap and specify the missing tool | Root cause from trace evidence |
| 6.2 Close the self-improvement loop | Deploy an evaluator agent that reads traces and proposes improvements; run the refinement loop through the M5 evaluation gate | The risk of skipping the gate, evidenced by a before-and-after |
| 6.3 Schedule recurring agent runs | Configure cron and event triggers for Tina's scheduled work; choose the pattern per scenario | Ad hoc versus scheduled, and why |
| 6.4 Detect and respond to degradation | Diagnose drift, staleness, or behavior shift from metrics and traces; isolate the component; fix it; re-measure against the M5 baseline | The degradation type from the signal |
| 6.C Architect's Challenge | Simulated degradation: Tina's answer quality has dropped overnight. Find why, fix it, and prove the fix against baseline, within 45 minutes | |

---

## The certification exam

- **Format.** Live environment, human-proctored, practical-heavy. You work in a provisioned Elastic environment on tasks shaped like the Architect's Challenges, graded automatically against system state and measured outcomes. A shorter scenario-based multiple-choice section covers judgment that does not need a keyboard.
- **Domains.** Six, weighted as in the table above. Every scenario is set in the Cortex Bank world you trained in.
- **What makes it hard.** Nothing is scaffolded. Constraints conflict and you have to choose. You are graded on what your system does.
- **Preview features** are taught in the training and excluded from the exam until they reach general availability.
- **Beta.** Exam details, price, passing standard, and retake policy are set by the certification team and published before the beta exam opens.

---

## Prerequisites and environment

- Python, HTTP APIs, JSON. Comfortable in a terminal.
- Prior exposure to Elasticsearch or another search engine. Not administration.
- Everything runs in a browser-based lab environment. Nothing to install. Each lab provisions its own Elastic Cloud Serverless project and tears it down afterward.

---

*Elastic, Elasticsearch, and Kibana are trademarks of Elasticsearch B.V. Cortex Bank and Trust is fictional.*
