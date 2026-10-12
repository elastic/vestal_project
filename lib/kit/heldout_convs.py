#!/usr/bin/env python3
"""Solve gate for 09 section 7 rule 1: no held-out question is in the learner's conversation list.

    python3 /opt/ara/src/lib/kit/heldout_convs.py /opt/ara/heldout/02-b1-questions.json [...]

Root-only test tool. Lists the conversations of the admin user (the user the learner's Kibana tab
signs in as, and the user tina-runtime belongs to), reads each one's first message, and fails if any
equals a held-out input from the given files (each {"cases": [{"input": ...}]}). Prints PF-OK or
PF-FAIL with the count; never prints a held-out text.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, "/opt/ara/lib")
from agent_builder import AB  # noqa: E402


def norm(text) -> str:
    return " ".join(str(text or "").lower().split())


def main(paths: list[str]) -> int:
    wanted = set()
    for p in paths:
        wanted |= {norm(c.get("input")) for c in json.load(open(p)).get("cases") or [] if c.get("input")}
    ab = AB(os.environ["KIBANA_URL"], os.environ["ES_API_KEY"], timeout=60)
    items = ab.conversations()
    found = 0
    for item in items:
        conv = ab.conversation(item.get("id")) or {}
        rounds = [r for r in conv.get("rounds") or [] if isinstance(r, dict)]
        first = (rounds[0].get("input") if rounds else None) or {}
        text = first.get("message") if isinstance(first, dict) else first
        if norm(text) in wanted:
            found += 1
    if found:
        print(f"PF-FAIL heldout_convs: {found} of {len(items)} conversations in the admin user's list open with a "
              "held-out question")
        return 1
    print(f"PF-OK heldout_convs: none of the {len(items)} conversations in the admin user's list opens with one of "
          f"the {len(wanted)} held-out questions")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
