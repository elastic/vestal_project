"""Capture the Brief's problem section for Lab 3.1 from a live run (spec 18 section 1.2).

Runs in a provisioned 3.1 sandbox against the start state: one 40k-bucket dev question,
retrieved whole (top 3 narratives) and as passages (top 5 sections), with the token cost of
each and where the gold section landed. Prints the block that becomes problem.txt.

Run as root after provisioning (the ch02 solve does):
  /opt/ara/venv/bin/python3 /opt/ara/src/modules/m3/3-1-rag-architecture-selection/capture_problem.py
Reads only the learner-visible dev set and the indices. Writes nothing.
"""
import json
import os
import pathlib
import sys

sys.path.insert(0, "/opt/ara/lib")
from elasticsearch import Elasticsearch

QUERY_ID = "dev-3-1-33"
DEV = pathlib.Path("/home/elastic/dev-sets/dev-queries-sar.json")

es = Elasticsearch(os.environ["ES_URL"], api_key=os.environ["ES_API_KEY"], request_timeout=60)
q = next(x for x in json.loads(DEV.read_text()) if x["query_id"] == QUERY_ID)
gold_doc = q["relevant_doc_ids"][0]
gold_sec = q["relevant_passage_ids"][0]


def search(index, size, fields):
    body = {"query": {"match": {"body": q["query_text"]}}, "size": size, "_source": fields}
    return es.search(index=index, body=body)["hits"]["hits"]


whole = search("cortex-sar-narratives", 3, ["doc_id", "token_count"])
passages = search("cortex-sar-passages", 5, ["section_id", "narrative_id", "section_title", "token_count"])
gold = es.search(index="cortex-sar-passages",
                 body={"query": {"term": {"section_id": gold_sec}}, "size": 1,
                       "_source": ["section_title", "token_count"]})["hits"]["hits"][0]["_source"]

lines = [f"Q: {q['query_text']}", "", "WHOLE NARRATIVES, top 3"]
whole_tokens = 0
for i, h in enumerate(whole, 1):
    s = h["_source"]
    whole_tokens += s.get("token_count", 0)
    mark = "   <== holds the answer" if s["doc_id"] == gold_doc else ""
    lines.append(f"  {i}. {s['doc_id']}  {s.get('token_count', 0):>7,} tokens{mark}")
share = 100 * gold["token_count"] / max(whole_tokens, 1)
lines += [f"  sent {whole_tokens:,} tokens; the answer is section '{gold['section_title']}', "
          f"{gold['token_count']} tokens = {share:.1f}%", "", "PASSAGES, top 5"]
passage_tokens = 0
for i, h in enumerate(passages, 1):
    s = h["_source"]
    passage_tokens += s.get("token_count", 0)
    mark = "   <== the answer" if s["section_id"] == gold_sec else ""
    lines.append(f"  {i}. {s['narrative_id']} {s['section_title'][:34]:34s} {s.get('token_count', 0):>5,}{mark}")
lines.append(f"  sent {passage_tokens:,} tokens")
for line in lines:
    print("PROBLEM " + line)
