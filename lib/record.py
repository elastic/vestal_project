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

A field without options is a free field; its optional "type" is one of text (default), span_id, integer, date
(e.g. {"key": "failing_span_id", "label": "Failing span", "type": "span_id"}); the value is validated and
re-prompted, and an integer is written as a JSON number.

Validates input against the options list. Writes a JSON file. Prints a confirmation.
Does not print whether the selection is correct.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys
from datetime import date

TYPES = ("text", "span_id", "integer", "date")


def parse_value(kind: str, raw: str):
    """Validate and normalise a free-field value by its type. Raises ValueError with a message the learner can
    act on (it never says whether the value is the right one).
      text      any string (default)
      span_id   16 hex characters (an OpenTelemetry span id), lower-cased
      integer   whole number; commas and underscores are allowed as separators; stored as an int
      date      YYYY-MM-DD, a real calendar date; stored as that string
    """
    raw = raw.strip()
    if kind == "text":
        return raw
    if kind == "span_id":
        if not re.fullmatch(r"[0-9a-fA-F]{16}", raw):
            raise ValueError("A span id is 16 hex characters.")
        return raw.lower()
    if kind == "integer":
        cleaned = raw.replace(",", "").replace("_", "")
        if not re.fullmatch(r"-?\d+", cleaned):
            raise ValueError("Enter a whole number.")
        return int(cleaned)
    if kind == "date":
        try:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
                raise ValueError
            return date.fromisoformat(raw).isoformat()
        except ValueError:
            raise ValueError("Enter a date as YYYY-MM-DD.") from None
    raise ValueError(f"unknown field type {kind!r}")


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
            kind = field.get("type", "text")
            if kind not in TYPES:
                raise ValueError(f"field {key}: unknown type {kind!r}")
            while True:
                try:
                    result[key] = parse_value(kind, input("  Value: "))
                    break
                except ValueError as e:
                    print(f"  {e}")
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
