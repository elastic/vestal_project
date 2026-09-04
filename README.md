# Elastic Agentic Retrieval Architect — Public Assets

Learner-facing assets for the [Elastic Agentic Retrieval Architect](SYLLABUS.md)
certification training. Notebooks, Brief decks, shared libraries, the Cortex Bank
corpus, and evaluation data sets. Everything here is what a learner may see,
reuse, and adapt.

> **What lives elsewhere.** Track configuration, setup/check/solve scripts, held-out
> evaluation sets, and graders stay in the private Instruqt track repository. Those
> files never appear here.

---

## Repository layout

```
brand/                  Elastic brand tokens, self-hosted fonts, logos, BRAND.md
brief/template/         Shared deck template, runtime, and build script
brief/img/library/      Shared SVG diagram primitives (reused across all decks)
lib/
  tina/                 The reference Tina harness (LLM client, ES client, ReAct loop)
  ara_metrics.py        Shared metrics: precision@k, nDCG, latency, token counts
  defend.py             Interactive Defend helper
  record.py             Generic interactive recorder for small learner configs
data/
  cortex-corpus/        The 44 synthetic Cortex Bank and Trust documents + manifest
  dev-sets/<m>/<track>/ Development evaluation sets learners iterate on
modules/
  m1/                   Module 1: AI and LLM Foundations
    1-1-ai-system-failures/
    1-2-reasoning-and-retrieval/
    1-3-model-tier-and-agent-stack/
    1-4-harness-and-memory/
    1-c-tina-v0/
  m2/ ...
SYLLABUS.md             The publishable learning-path syllabus
```

---

## Using outside Instruqt

All notebooks and library code read from environment variables only.
Set these in your shell before opening a notebook:

```bash
export LLM_PROXY_URL="<your LiteLLM proxy URL>"
export LLM_APIKEY="<your key>"
export ARA_MODEL_FAST="gpt-4o-mini"
export ARA_MODEL_STRONG="claude-sonnet-5"
export ES_URL="<your Elasticsearch URL>"
export ES_API_KEY="<your API key>"
export ARA_INFERENCE_COMPLETION_ID="<your _inference endpoint id>"
```

No Instruqt-specific paths or credentials appear in any notebook.

---

## License

Apache 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).

Elastic logos and trademarks are not covered by the Apache license and are
governed by [Elastic's trademark guidelines](https://www.elastic.co/legal/trademarks).

Fonts in `brand/fonts/` are distributed under the SIL Open Font License 1.1.

The Cortex Bank and Trust corpus in `data/cortex-corpus/` is synthetic and
fictional.

---

*Elastic Agentic Retrieval Architect is a Beta program. Track listings,
module details, and seat times are subject to change.*
