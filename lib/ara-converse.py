#!/usr/bin/env python3
"""ara-converse.py - send one turn to Tina and print what she did (22 section 1, 4.3 Build 1).

    python3 /opt/ara/lib/ara-converse.py --conversation <id> "your turn"   # continue a conversation
    python3 /opt/ara/lib/ara-converse.py "your turn"                       # a fresh conversation

Runs as tina-runtime with the pinned connector, the identity the checks use. Prints the conversation
id, the route Tina took (her custom tools in call order with their parameters), the platform's
internal steps, and the start of her answer. Prints no verdict.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from agent_builder import AB, ABError, internal_calls, route_record  # noqa: E402
from ara_behavior import route_text  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--conversation", help="continue this conversation id")
    ap.add_argument("--agent", default="tina-compliance")
    ap.add_argument("text")
    a = ap.parse_args()
    for var in ("KIBANA_URL", "ARA_TINA_RUNTIME_KEY", "ARA_AB_CONNECTOR_ID"):
        if not os.environ.get(var):
            print(f"{var} is not set. Open a new Terminal tab, or run: set -a; . ~/env; set +a")
            return 2
    tina = AB(os.environ["KIBANA_URL"], os.environ["ARA_TINA_RUNTIME_KEY"], os.environ["ARA_AB_CONNECTOR_ID"], timeout=150)
    print(f"Sending to {a.agent} {'in conversation ' + a.conversation if a.conversation else 'as a new conversation'} ...")
    try:
        resp = tina.converse(a.agent, a.text, conversation_id=a.conversation)
    except ABError as e:
        print(f"Kibana did not answer ({e}). Wait a moment and run it again.")
        return 1
    except ValueError as e:
        print(f"Kibana refused the turn: {e}")
        return 1
    route = route_record(resp)
    print(f"conversation_id: {resp.get('conversation_id')}")
    print(f"route:           {route_text(route) if route else 'no Cortex tool called'}")
    internal = internal_calls(resp)
    if internal:
        print(f"internal steps:  {', '.join(internal)}")
    msg = str(((resp.get("response") or {}).get("message")) or "").strip()
    print("answer:")
    print("  " + (msg[:600] + (" ..." if len(msg) > 600 else "")).replace("\n", "\n  "))
    return 0


if __name__ == "__main__":
    sys.exit(main())
