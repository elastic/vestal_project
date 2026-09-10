---
track: "2.1"
title: "Configure core retrieval infrastructure"
minutes: 7
---

# Lab 2.1
Configure core retrieval infrastructure

*Tina cannot answer Cortex's compliance questions yet. The documents are raw text. The retrieval ceiling is determined by what you build here.*

---
layout: problem

# The problem

Tina was asked: "What does the risk-scoring deadline schedule say about Tier 5 accounts?"

```
Error: No semantic index found. cortex-corpus does not exist.
```

Every question Tina answers from here on depends on the corpus you index in this track.

---

# Chunking sets the ceiling

A retrieval system can only return what fits in a chunk. A table split mid-row means Tina answers with half a rule.

Three strategies, one corpus, different tradeoffs:

| Strategy | Keeps intact | Breaks |
|---|---|---|
| Fixed | Easy to implement | Tables, numbered steps |
| Heading-aware | Section text | Tables spanning a section |
| Unit-preserving | Any unit you define | Needs explicit boundaries |

---

# `semantic_text` and the twin field

`body` as `semantic_text` on the embedding model: indexed into a dense vector at write time.

`body_text` as `text`: the raw text, for BM25 matching.

A `match` query on `body` is a semantic search. BM25 needs `body_text`.

**Tina's retriever uses both.** You need both fields.

---

# The alias is the indirection layer

```
cortex-corpus-live  →  cortex-corpus
```

Track 2.2 swaps to `cortex-corpus-tuned` behind this alias.  
Track 2.3 cuts over to a candidate embedding model.  
Tina never changes her query target.

---

# Pin the model: `cortex-generation`

The platform provides a dot-prefixed completion endpoint. Dot-prefixed names rotate when Elastic updates.

`cortex-generation` is your pinned copy. It calls the same model, but its name does not change.

Tina's generation path stays stable.

---
layout: rule

# Decision rule

<!-- rule -->

| New document type | Chunking rule |
|---|---|
| Numbered procedure manuals (40+ pages) | Unit-preserving — numbered steps must stay intact |
| One-paragraph alert notes | Whole-document — too short to split |
| Fee schedules (tables) | Unit-preserving — table rows must stay intact |

---

# What done looks like

- Median chunk: at most **512 tokens**
- Semantic units: **5 of 5** intact in single chunks
- precision@5 on held-out queries: at least **0.80**
- `cortex-corpus-live` resolves to `cortex-corpus`
- `cortex-generation` exists, pinned to the platform model

---
layout: next

# Select Check

The indicator turns green when your environment is ready.

When it does, open Build 1 and start chunking.
