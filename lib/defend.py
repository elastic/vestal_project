#!/usr/bin/env python3
"""
defend.py — interactive Defend helper for ARA tracks.

The learner runs: python3 /opt/ara/lib/defend.py

It reads questions.json from /home/elastic/defend/questions.json,
shows each question with options and the learner's own measured numbers
from /opt/ara/results/, validates the selection, writes decision.json,
and prints "Decision recorded. Select Check."

It never says whether the answer is right. The truth table lives only
in the check script.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys

QUESTIONS_FILE = pathlib.Path("/home/elastic/defend/questions.json")
RESULTS_DIR = pathlib.Path("/opt/ara/results")
DECISION_FILE = pathlib.Path("/home/elastic/decision.json")


def load_questions() -> list[dict]:
    if not QUESTIONS_FILE.exists():
        print(f"ERROR: questions file not found at {QUESTIONS_FILE}", file=sys.stderr)
        sys.exit(1)
    return json.loads(QUESTIONS_FILE.read_text())


def load_results() -> dict:
    """Merge all results files into a flat dict of metric_name -> value."""
    combined: dict = {}
    if RESULTS_DIR.exists():
        for p in sorted(RESULTS_DIR.glob("*.json")):
            try:
                data = json.loads(p.read_text())
                if "metrics" in data:
                    combined.update(data["metrics"])
                if "constraints" in data:
                    combined.update({f"constraint.{k}": v for k, v in data["constraints"].items()})
            except Exception:
                pass
    return combined


def ask_question(q: dict, results: dict, idx: int, total: int) -> tuple[str, str]:
    """Present one question; return (choice_key, reason_key)."""
    print()
    print(f"Question {idx}/{total}")
    print("=" * 60)
    print(q["question"])
    print()

    # Show relevant measured numbers if specified
    if "show_metrics" in q:
        for metric in q["show_metrics"]:
            val = results.get(metric)
            if val is not None:
                label = metric.replace("_", " ").replace(".", " ")
                print(f"  Your {label}: {val}")
        print()

    # Choice options
    choices: list[dict] = q.get("choices", [])
    if not choices:
        print("ERROR: no choices in this question", file=sys.stderr)
        sys.exit(1)
    print("Choose one:")
    for i, c in enumerate(choices, 1):
        print(f"  {i}. {c['label']}")
    while True:
        raw = input("Your choice (number): ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(choices):
            chosen_choice = choices[int(raw) - 1]
            break
        print(f"  Enter a number between 1 and {len(choices)}.")

    # Reason options
    reasons: list[dict] = q.get("reasons", [])
    if not reasons:
        # No reason required for this question
        return chosen_choice["key"], ""

    print()
    print("Choose the reason:")
    for i, r in enumerate(reasons, 1):
        print(f"  {i}. {r['label']}")
    while True:
        raw = input("Your reason (number): ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(reasons):
            chosen_reason = reasons[int(raw) - 1]
            break
        print(f"  Enter a number between 1 and {len(reasons)}.")

    return chosen_choice["key"], chosen_reason["key"]


def main() -> None:
    questions = load_questions()
    results = load_results()

    print()
    print("Defend — your measurements, your call")
    print("=" * 60)
    print("Answer based on what you measured in this track.")
    print("Your numbers are shown next to each question.")
    print("Another learner's answer may be wrong for you.")

    answers: list[dict] = []
    for i, q in enumerate(questions, 1):
        choice_key, reason_key = ask_question(q, results, i, len(questions))
        entry: dict = {"question_id": q["id"], "choice": choice_key}
        if reason_key:
            entry["reason"] = reason_key
        answers.append(entry)

    decision = {"answers": answers}
    DECISION_FILE.parent.mkdir(parents=True, exist_ok=True)
    DECISION_FILE.write_text(json.dumps(decision, indent=2))

    print()
    print("Decision recorded.")
    print("Select Check in the sidebar to continue.")


if __name__ == "__main__":
    main()
