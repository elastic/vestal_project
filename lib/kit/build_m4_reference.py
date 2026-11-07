#!/usr/bin/env python3
"""
build_m4_reference.py - assemble M4's reference question set (21 section 10) from the M4 dev sets.

Authoring tool; nothing in a sandbox runs it. M4 owes M5 and M6 "the fixed question sets M4's
BEHAVIOR checks use, with expected routes". The held-out sets stay private (vestal_project is
public), so the reference set is their public dev twins, graded the same way, plus 4.4's fixed
statute question, which 4.4 asks in its assignment. 25 draws on it for the 5.2 no-regression set
and the 5.3 example test set; M6 uses it as the pre-degradation reference.

Each entry keeps the M4 case schema (id, kind, input, expected, forbid), so ara_behavior.run_case
runs it unchanged against ara-m4-end, and adds source (dev file and case id). @aml becomes the 4.C
reference specialist. A question that reads a page names the expected page as 25 section 8.2's pool
does (url and title line), not as a literal: the url is compared normalised (4.4 norm_url).

Usage:
  python3 lib/kit/build_m4_reference.py [--assets <vestal_project root>] [--check]
--check exits 1 when the committed file differs from a fresh build.
"""
import argparse
import json
import pathlib
import sys

OUT = "data/dev-sets/m5/m4-reference.json"
SETS = [  # (set name, dev file under data/dev-sets/m4), in M4 track order
    ("4-1-b1", "4-1-agent-builder-tools/4-1-b1.json"),
    ("4-1-b2", "4-1-agent-builder-tools/4-1-b2.json"),
    ("4-2-b2", "4-2-skills-automation-multi-agent/4-2-b2.json"),
    ("4-2-b3", "4-2-skills-automation-multi-agent/4-2-b3.json"),
    ("4-c-dev", "4-c-allocation-and-safety/4-c-dev.json"),
]
AML_ID = "cortex-aml-specialist"  # 4.C reference (_solve4c.py AML_ID)
SPECIALISTS = {AML_ID: "aml", "cortex-securities-irregularities": "securities"}
# What ara-m4-end holds (25 section 8.3 item 1: the 4.4 reference end state): Tina's tools, her
# securities specialist and its tools. The 4.C AML desk is not in it, so a case that needs a tool or
# agent outside this set has no route in M5 and is left out (listed in the output's _doc).
END_REACH = {"cortex.policy_search", "cortex.structuring_deposits", "cortex.open_case", "cortex.escalate",
             "cortex.file_sar", "cortex.read_page", "run_subagent", "cortex-securities-irregularities",
             "cortex.securities_layering", "cortex.wash_trading", "cortex.unexplained_wealth"}

# 4.4 Build 1's fixed question (thresholds.json build1, extension; assignment step 5). The check
# passes a run that calls cortex.read_page on the pinned page; Tina first looks up the account.
PAGE = ("https://raw.githubusercontent.com/elastic/vestal_project/4caa7d19ff9c1682a8b7ca6dd44229b7cb6548b3/"
        "ara-m4-pages/doj-crm-structuring-laundering.md")
STATUTE = {
    "id": "4-4-b1-01", "kind": "extension", "source": "4-4 thresholds.json build1.question",
    "input": "Which US Code section governs the pattern on account 1981?",
    "expected": [{"tool_id": "cortex.structuring_deposits", "params": {"account_id": "1981"}},
                 {"tool_id": "cortex.read_page"}],
    "page": {"url": PAGE,
             "title_line": "# U.S. Department of Justice, Criminal Resource Manual: structuring and money laundering"},
}


def kind_of(case: dict) -> str:
    """The desk that answers: the delegated specialist, policy, or the coordinator (Tina herself)."""
    for c in case["expected"]:
        if c["tool_id"] == "run_subagent":
            return SPECIALISTS[c["params"]["agent_id"]]
    if [c["tool_id"] for c in case["expected"]] == ["cortex.policy_search"]:
        return "policy"
    return "coordinator"


def resolve(value):
    if isinstance(value, dict):
        return {k: resolve(v) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v) for v in value]
    return AML_ID if value == "@aml" else value


def reachable(case: dict) -> bool:
    return all(e["tool_id"] in END_REACH and (e.get("params") or {}).get("agent_id", "run_subagent") in END_REACH
               and e.get("agent_id", "run_subagent") in END_REACH for e in case["expected"])


def build(assets: pathlib.Path) -> dict:
    cases, left_out = [], []
    for name, rel in SETS:
        for i, c in enumerate(json.loads((assets / "data/dev-sets/m4" / rel).read_text())["cases"], 1):
            c = resolve(c)
            if not reachable(c):
                left_out.append(f"{name}:{c['id']}")
                continue
            entry = {"id": f"{name}-{i:02d}", "kind": kind_of(c), "source": f"{name}:{c['id']}",
                     "input": c["input"], "expected": c["expected"]}
            if c.get("forbid"):
                entry["forbid"] = c["forbid"]
            cases.append(entry)
    cases.append(STATUTE)
    return {
        "_doc": ("M4 reference question set (21 section 10), built by lib/kit/build_m4_reference.py from the M4 dev "
                 "sets plus 4.4's fixed statute question; do not edit by hand. Each case is in the M4 case schema "
                 "and runs against ara-m4-end with ara_behavior.run_case. kind is the desk that answers. A case "
                 "with page expects cortex.read_page on that page (url compared normalised). Left out: the "
                 "4.C AML-desk cases, whose tools ara-m4-end (the 4.4 reference end, 25 section 8.3) does not hold."),
        "version": "v1",
        "left_out": left_out,
        "cases": cases,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--assets", default=str(pathlib.Path(__file__).resolve().parents[2]))
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    assets = pathlib.Path(a.assets)
    text = json.dumps(build(assets), indent=2) + "\n"
    out = assets / OUT
    if a.check:
        same = out.exists() and out.read_text() == text
        print(f"{OUT}: {'current' if same else 'STALE, rebuild'}")
        return 0 if same else 1
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    print(f"wrote {OUT}: {len(json.loads(text)['cases'])} cases")
    return 0


if __name__ == "__main__":
    sys.exit(main())
