#!/usr/bin/env python3
"""
record.py — generic interactive recorder for small learner configs.

Replaces one-off record_deployment.py, record_decision.py, etc.

Usage (from a notebook or assignment):
  python3 /opt/ara/lib/record.py <config_path> <schema_path>

config_path:  where to write the JSON result (e.g. /home/elastic/config.json)
schema_path:  a JSON file describing the fields to collect:
  [
    {"key": "deploy", "label": "Deploy decision", "options": ["current", "candidate"]},
    {"key": "reason", "label": "Reason",          "options": ["latency_over_budget", "relevance_gain"]}
  ]

Validates input against the options list. Writes a JSON file. Prints a confirmation.
Does not print whether the selection is correct.
"""

from __future__ import annotations

import json
import pathlib
import sys


def collect(schema: list[dict]) -> dict:
    result: dict = {}
    for field in schema:
        key = field["key"]
        label = field["label"]
        options: list[str] = field.get("options", [])

        print()
        print(label)
        if options:
            for i, opt in enumerate(options, 1):
                print(f"  {i}. {opt}")
            while True:
                raw = input("  Choice (number): ").strip()
                if raw.isdigit() and 1 <= int(raw) <= len(options):
                    result[key] = options[int(raw) - 1]
                    break
                print(f"  Please enter a number between 1 and {len(options)}.")
        else:
            val = input("  Value: ").strip()
            result[key] = val
    return result


def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: record.py <output.json> <schema.json>", file=sys.stderr)
        sys.exit(1)

    output_path = pathlib.Path(sys.argv[1])
    schema_path = pathlib.Path(sys.argv[2])

    if not schema_path.exists():
        print(f"Schema file not found: {schema_path}", file=sys.stderr)
        sys.exit(1)

    schema = json.loads(schema_path.read_text())
    print()
    print("Record your decision")
    print("=" * 40)

    data = collect(schema)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, indent=2))
    print()
    print(f"Saved to {output_path}")
    print("Select Check in the sidebar to continue.")


if __name__ == "__main__":
    main()
