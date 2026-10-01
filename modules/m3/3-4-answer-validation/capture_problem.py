"""Capture the Brief's problem slide for Lab 3.4 from a live run (spec 18 section 1.2).

Runs in a provisioned 3.4 sandbox against the start state: the shipped guardrails notebook's
harness cell, with all three hooks empty, over the fifteen dev queries. For each query it
prints what retrieval returned, what Tina delivered, the figures in it, and the claims the
reference attributor could not ground. The problem slide's failure is picked from this output.

Run as elastic after provisioning, with the track env (the ch03 solve did this for the capture):
  /home/elastic/.venv/bin/python3 /opt/ara/src/modules/m3/3-4-answer-validation/capture_problem.py
Reads only the learner-visible notebook and dev set. Writes nothing.
"""
import json

nb = json.load(open("/home/elastic/notebooks/lab-3-4-guardrails.ipynb"))
g = {"__name__": "__main__"}
exec(compile("".join(nb["cells"][1]["source"]), "<harness>", "exec"), g)
for q in g["DEV"]:
    passages = g["SURVEY"][q["query_id"]]["passages"]
    answer = g["ask"](q["query_text"], passages)
    claims = g["split_claims"](answer)
    attr = g["reference_attribution"](claims, passages)
    rec = {"id": q["query_id"], "cls": q["query_class"], "q": q["query_text"],
           "gold": q.get("gold_literal", ""),
           "retrieved": [(p["passage_id"], p["source_type"], round(p["score"], 3)) for p in passages],
           "answer": answer, "figures": g["figures_in"](answer),
           "unsupported": [a["claim"] for a in attr if a["passage_id"] == "UNSUPPORTED"]}
    s = json.dumps(rec)
    for i in range(0, len(s), 900):
        print("PROBLEMCAP " + ("" if i == 0 else "+ ") + s[i:i + 900])
