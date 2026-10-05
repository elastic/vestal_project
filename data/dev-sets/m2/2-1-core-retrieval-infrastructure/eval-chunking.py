"""Dev-set evaluator for Build 1: run this after every re-index.

Usage:
  /home/elastic/.venv/bin/python /home/elastic/dev-sets/eval-chunking.py

It first looks for each dev structured unit (a complete timeline or list, stored in
dev-structured-units.json) whole in one chunk of its document, with the check's rule:
whitespace normalised, markdown marker characters * _ ` # | removed from both sides.
Then it asks Tina's retriever each dev question through cortex-corpus-live, exactly as she
would, and scores what comes back with the same rules the check uses (ara_context):
a question passes when one chunk from its source document, among the top 5, holds the
whole answer. The check runs a separate held-out set of the same kinds, so its numbers
can differ from these in either direction.
"""
import json, os, pathlib, re, sys, time
sys.path.insert(0, "/opt/ara/lib")

env = pathlib.Path("/home/elastic/env")
if env.exists():
    for line in env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from elasticsearch import Elasticsearch
from ara_context import score, summarize, tokens, whole_in_index
from tina.rag import load_retriever

T = json.loads(pathlib.Path("/opt/ara/thresholds.json").read_text())["build1"]
QS = json.loads((pathlib.Path(__file__).parent / "dev-questions.json").read_text())
UNITS = json.loads((pathlib.Path(__file__).parent / "dev-structured-units.json").read_text())
MARKS = re.compile(r"[*_`#|]")

def unit_norm(text):
    # same rule as the check: whitespace normalised, markdown marker characters removed
    return " ".join(MARKS.sub("", text).split())

es = Elasticsearch(os.environ["ES_URL"], api_key=os.environ["ES_API_KEY"], request_timeout=60)
t0 = time.time()

if not es.indices.exists_alias(name="cortex-corpus-live"):
    sys.exit("cortex-corpus-live does not exist yet. Create the alias, then run this again.")

# chunk sizes, over every chunk
sizes = []
resp = es.search(index="cortex-corpus-live", scroll="2m", size=1000,
                 body={"query": {"match_all": {}}, "_source": ["body_text"]})
while resp["hits"]["hits"]:
    sizes += [tokens(h["_source"].get("body_text", "")) for h in resp["hits"]["hits"] if h["_source"].get("body_text")]
    resp = es.scroll(scroll_id=resp["_scroll_id"], scroll="2m")
sizes.sort()
if not sizes:
    sys.exit("The index has no chunks with body_text yet.")
n = len(sizes)
median, p95, mx = sizes[n // 2], sizes[min(n - 1, -(-95 * n // 100) - 1)], sizes[-1]
ok = lambda b: "PASS" if b else "FAIL"
print(f"Chunks: {n}   median {median} tokens [{ok(median <= T['median_tokens_max'])}, target <= {T['median_tokens_max']}]"
      f"   p95 {p95}   max {mx} [{ok(mx <= T['max_tokens_max'])}, target <= {T['max_tokens_max']}]")
print("Note the p95. The Defend asks you to spend it.\n")

# structured units: is each one whole in one chunk of its document?
kept = 0
for u in UNITS:
    hits = es.search(index="cortex-corpus-live", size=1000,
                     body={"query": {"term": {"doc_id": u["doc_id"]}}, "_source": ["body_text"]})["hits"]["hits"]
    whole = any(unit_norm(u["text"]) in unit_norm(h["_source"].get("body_text", "")) for h in hits)
    kept += whole
    print(f"  {ok(whole)}  {u['unit_id']:7s} {u['kind']:9s} {u['doc_id']} ({u['tokens']} tokens): "
          f"{'kept whole in one chunk' if whole else 'split across chunks'}")
print()

retriever = load_retriever(None)
results = []
for q in QS:
    body = json.loads(json.dumps(retriever).replace("{query_text}", json.dumps(q["query_text"])[1:-1]))
    hits = es.search(index="cortex-corpus-live", body=body, size=5)["hits"]["hits"]
    top = [{"doc_id": h["_source"].get("doc_id", ""), "text": h["_source"].get("body_text", "")} for h in hits]
    r = score(q, top)
    results.append(r)
    if r["ok"]:
        why = "one chunk holds the whole answer"
    elif not whole_in_index(es, "cortex-corpus-live", q):
        why = "split: no chunk in your index holds the whole answer"
    else:
        why = "retrieval miss: a chunk holds the whole answer, but it was not in the top 5"
    print(f"  {ok(r['ok'])}  {q['query_id']:7s} {q['class']:9s} {why}")
    print(f"        {q['query_text']}")

s = summarize(results, budget=T["budget_tokens"])
print()
# Units and each class pass on the dev set at the same rate the check requires on the held-out set.
U = T["units"]
print(f"{ok(kept * U['of'] >= U['min_whole'] * len(UNITS))}  units     dev {kept}/{len(UNITS)} kept whole"
      f"   (the check needs at least {U['min_whole']} of {U['of']} held-out)")
for cls in ("procedure", "policy"):
    c = s.get(cls, {"n": 0, "of": 0})
    need = T["context"][cls]
    passed = c["of"] > 0 and c["n"] * need["of"] >= need["min_pass"] * c["of"]
    print(f"{ok(passed)}  {cls:9s} dev {c['n']}/{c['of']}   (the check needs at least {need['min_pass']} of {need['of']} held-out)")
print(f"{ok(s['over_budget'] <= T['over_budget_max'])}  budget    {s['over_budget']} question(s) over Tina's {T['budget_tokens']}-token context in the top 5")
print("\nA retrieval miss is not a split. "
      "Chunking can still help it, but it does not have to pass for the class to pass.")
print(f"\nDone in {time.time() - t0:.1f} s. If anything above fails, adjust chunk(doc), re-index, and run this again.")
