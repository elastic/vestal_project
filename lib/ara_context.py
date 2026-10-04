"""Context-sufficiency scoring for ARA chunking labs (adapted from the alt-track ara21/scoring.py).

A question names its source document and the verbatim strings a complete answer needs.
What counts is what Tina receives: the top 5 chunks her retriever returns for the question.
A question passes when one chunk from the source document holds every required string.
Classes: procedure (timelines, numbered action lists) and policy (multi-fact paragraphs).
Budget: the top 5 must fit Tina's 4,000-token context (tokens = words x 1.3).
The evaluator and the check use this same module.
"""
BUDGET = 4000

def norm(s): return " ".join(s.split())
def tokens(t): return int(len(t.split()) * 1.3)

def score(q, top):
    """top: [{"doc_id", "text"}, ...] in retrieval order."""
    rel = set(q["relevant_ids"]); req = [norm(r) for r in q["required_strings"]]
    mine = [norm(c["text"]) for c in top if c["doc_id"] in rel]
    return {"query_id": q["query_id"], "class": q["class"],
            "ok": any(all(r in b for r in req) for b in mine),
            "tokens": sum(tokens(c["text"]) for c in top)}

def whole_in_index(es, index, q):
    """True when some chunk of the source document, anywhere in the index, holds the whole answer.
    Tells a split answer (False) from an answer chunk that retrieval missed (True)."""
    from elasticsearch import BadRequestError, NotFoundError
    req = [norm(r) for r in q["required_strings"]]
    try:  # a terms query needs doc_id as keyword
        hits = es.search(index=index, size=1000, body={"query": {"terms": {"doc_id": q["relevant_ids"]}},
                                                        "_source": ["body_text"]})["hits"]["hits"]
    except (BadRequestError, NotFoundError):
        # The index rejects the query (doc_id not keyword) or is missing: the learner's state.
        # This returns False, which callers count as split. Any other error (no connection,
        # timeout, 429, 5xx) is raised, so a check can retry it and never counts an outage as a miss.
        return False
    return any(all(r in norm(h["_source"].get("body_text", "")) for r in req) for h in hits)

def summarize(results, budget=BUDGET):
    """Per-class pass counts, and how many questions sent Tina more than budget tokens.
    Checks pass budget from thresholds.json, so the graded number has one source."""
    out = {}
    for cls in sorted({r["class"] for r in results}):
        rs = [r for r in results if r["class"] == cls]
        out[cls] = {"n": sum(r["ok"] for r in rs), "of": len(rs)}
    out["over_budget"] = sum(r["tokens"] > budget for r in results)
    return out
