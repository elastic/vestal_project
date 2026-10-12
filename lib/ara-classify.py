#!/usr/bin/env python3
"""ara-classify.py - record a class, a reason and a control for every action Tina can take (4.4 Build 2).

    python3 /opt/ara/lib/ara-classify.py

Reads Tina's live configuration as tina-runtime (ARA_TINA_RUNTIME_KEY and KIBANA_URL from ~/env) and
lists every custom tool she holds. For each, asks for the class, the reason and the control from closed lists, then writes
~/cortex-desk/action-classes.json. It never says whether an answer is right: Check does that, from
the tool definitions and the Brief's decision rule. Run it again after you change Tina's tools.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from agent_builder import AB  # noqa: E402
from ara_actions import CLASSES, CONTROLS, REASONS, agent_tool_ids  # noqa: E402
from record import collect  # noqa: E402

OUT = pathlib.Path.home() / "cortex-desk" / "action-classes.json"


def items(ab: AB) -> list[str]:
    agent = ab.get_agent("tina-compliance")
    if agent is None:
        sys.exit("Tina (tina-compliance) was not found. Has provisioning finished?")
    return sorted({t for t in agent_tool_ids(agent) if not t.startswith("platform.") and not t.startswith(".")})


def main() -> int:
    for var in ("KIBANA_URL", "ARA_TINA_RUNTIME_KEY"):
        if not os.environ.get(var):
            sys.exit(f"{var} is not set. Open a new Terminal tab, or run: set -a; . ~/env; set +a")
    ab = AB(os.environ["KIBANA_URL"], os.environ["ARA_TINA_RUNTIME_KEY"], timeout=30)
    ids = items(ab)
    print("Tina can take these actions:")
    for i in ids:
        print(f"  - {i}")
    print("\nFor each one: its class, the reason from its definition, and the control its class requires.")
    schema = []
    for i in ids:
        schema += [{"key": f"{i}|class", "label": f"{i}: class", "options": CLASSES},
                   {"key": f"{i}|reason", "label": f"{i}: reason", "options": list(REASONS)},
                   {"key": f"{i}|control", "label": f"{i}: control", "options": sorted(set(CONTROLS.values()))}]
    flat = collect(schema)
    record = {i: {f: flat[f"{i}|{f}"] for f in ("class", "reason", "control")} for i in ids}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(record, indent=2))
    print(f"\nSaved to {OUT}. Select Check to grade it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
