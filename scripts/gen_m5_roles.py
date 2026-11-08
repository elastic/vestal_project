"""gen_m5_roles.py - the M5 reference roles carried from 5.2 on (25 sections 1 and 8.4).

5.1's reference roles (Build 2's reference: one index block per restricted index, DLS on both corpus
indices, first-line FLS hiding the three subject fields), extended for 5.2: both read
cortex-case-correspondence with the same DLS as cortex-cases, and cortex-intake with no DLS or FLS
(5.2 Build 3 adds what the PII scenario requires).

    python3 scripts/gen_m5_roles.py   # writes data/ara-m5/roles/reference-5-2.json
"""
from __future__ import annotations

import copy
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
ACCESS = ROOT / "modules/m5/5-1-access-control/access"
CORPUS = ("cortex-cases", "cortex-sar-narratives")
READ = ["read", "view_index_metadata"]
ROLES = {
    "cortex-analyst-l1": {"sees": {"risk_tier": ["low", "medium"]}, "hides": ["subject_name", "subject_account", "subject_tin"]},
    "cortex-investigator": {"sees": {"case_type": ["structuring", "wire_fraud", "sanctions"]}, "hides": []},
}


def role(name: str) -> dict:
    spec = ROLES[name]
    rd = copy.deepcopy(json.loads((ACCESS / f"{name}.base.json").read_text())["role"])
    dls = json.dumps({"terms": spec["sees"]})
    out = []
    for ix in rd["indices"]:
        hit = [n for n in ix["names"] if n in CORPUS]
        if not hit:
            out.append(ix)
            continue
        for n in hit:
            b = dict(ix, names=[n], query=dls)
            if spec["hides"]:
                b["field_security"] = {"grant": ["*"], "except": list(spec["hides"])}
            out.append(b)
    out.append({"names": ["cortex-case-correspondence"], "privileges": READ, "query": dls})
    out.append({"names": ["cortex-intake"], "privileges": READ})
    rd["indices"] = out
    return rd


if __name__ == "__main__":
    doc = {"_doc": __doc__.split("\n\n")[1].replace("\n", " "), **{n: role(n) for n in ROLES}}
    p = ROOT / "data/ara-m5/roles/reference-5-2.json"
    p.write_text(json.dumps(doc, indent=1) + "\n")
    print(f"wrote {p}")
