#!/usr/bin/env python3
"""
defend.py — interactive Defend helper for ARA tracks.

The learner runs: python3 /opt/ara/lib/defend.py

Reads questions.json from /home/elastic/defend/questions.json, shows each
question with computed options and the learner's measured numbers from
/opt/ara/results/, validates the selection, writes decision.json to
/home/elastic/defend/decision.json, and prints "Decision recorded. Select Check."

It never says whether the answer is right. The truth table lives only in the
private check script.

Supports two questions.json shapes for backward compatibility:
  New: {"questions": [...], "display_rules": {...}, ...}
  Old: [{"id": ..., "question": ..., "choices": [...], "reasons": [...]}, ...]
"""

from __future__ import annotations

import hashlib
import json
import random
import math
import os
import pathlib
import sys

QUESTIONS_FILE = pathlib.Path("/home/elastic/defend/questions.json")
VARIANT_FILE   = pathlib.Path("/home/elastic/defend/variant.json")
RESULTS_DIR    = pathlib.Path("/opt/ara/results")
DECISION_FILE  = pathlib.Path("/home/elastic/defend/decision.json")


# ── Results and env loading ───────────────────────────────────────────────────

def load_results() -> dict:
    combined: dict = {}
    if RESULTS_DIR.exists():
        for p in sorted(RESULTS_DIR.glob("*.json")):
            try:
                data = json.loads(p.read_text())
                if "metrics" in data:
                    for k, v in data["metrics"].items():
                        combined[k] = v
            except Exception:
                pass
    return combined


def load_env() -> dict:
    env = {}
    # the learner runs this as elastic; solves import it as root, which reads only /opt/ara/env (T20)
    env_path = pathlib.Path("/opt/ara/env" if os.geteuid() == 0 else "/home/elastic/env")
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def shuffle_seed() -> int:
    """Per-sandbox seed for choice order (G4). seed_mod has only 2-3 values, so it would give
    every learner one of 2-3 orders. Grading is by value, so order never affects the grade."""
    for src in ("/etc/machine-id",):
        try:
            mid = pathlib.Path(src).read_text().strip()
        except Exception:
            continue
        if mid:  # an empty machine-id (common in images) would give every sandbox one order
            return int(hashlib.md5(mid.encode()).hexdigest(), 16)
    import socket
    return int(hashlib.md5(socket.gethostname().encode()).hexdigest(), 16)


def seed_from_variant() -> int:
    if VARIANT_FILE.exists():
        try:
            return int(json.loads(VARIANT_FILE.read_text()).get("seed_mod", 0))
        except Exception:
            pass
    # Instruqt sets INSTRUQT_PARTICIPANT_ID and _SANDBOX_ID; INSTRUQT_SANDBOX_ID is never set.
    sid = os.environ.get("INSTRUQT_PARTICIPANT_ID") or os.environ.get("_SANDBOX_ID") or "default"
    return int(hashlib.md5(sid.encode()).hexdigest(), 16) % 3


def _lookup(results: dict, key: str):
    """Return a result value by flat key, or by dotted path into nested result
    dicts (for example fast.field_accuracy). None when absent."""
    if key in results:
        return results[key]
    cur = results
    for part in key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _metric_label(key: str) -> str:
    return key.replace(".", " ").replace("_", " ")


# ── Formula evaluation ────────────────────────────────────────────────────────

def _eval_formula(formula: str, results: dict, env: dict) -> int | float | str | None:
    """Evaluate a formula string against results + env vars.

    Supported forms:
      floor(4000 / p95_tokens)        — arithmetic with floor/max
      pinned_model_id                  — direct results key lookup
      env:ARA_EMBED_ID                 — env var lookup
    Only floor() and max() are allowed as functions.
    """
    formula = formula.strip()
    if formula.startswith("env:"):
        return env.get(formula[4:])

    # Merge results + env as namespace
    ns = {k: v for k, v in results.items()}
    ns.update({f"env_{k}": v for k, v in env.items()})
    ns["floor"] = lambda x: int(math.floor(x))
    ns["max"] = max

    # Simple direct-variable check (no arithmetic operators)
    if formula in results:
        return results[formula]

    try:
        return eval(formula, {"__builtins__": {}}, ns)
    except Exception:
        return None


def render_choices(choices: list[dict], results: dict, env: dict, seed: int) -> list[dict]:
    """Expand computed choices; drop collisions; optionally shuffle by seed."""
    rendered = []
    seen_labels: set = set()
    for c in choices:
        if "computed" not in c:
            rendered.append({"key": c["key"], "label": c["label"], "value": c["label"]})
            continue
        comp = c["computed"]
        val = _eval_formula(comp["formula"], results, env)
        if val is None:
            # fallback formula
            if "fallback_formula" in comp:
                val = _eval_formula(comp["fallback_formula"], results, env)
        if val is None:
            continue
        label = c["label"].replace("{result}", str(val))
        if label in seen_labels:
            continue
        seen_labels.add(label)
        rendered.append({"key": c["key"], "label": label, "value": val})

    return rendered


# ── Question loading and rendering ─────────────────────────────────────────────

def load_questions_new(raw: dict, results: dict, env: dict, seed: int) -> list[dict]:
    """Parse new-format questions.json."""
    qs = []
    for q in raw.get("questions", []):
        text = q["text"]

        # Render seeded variant text
        if q.get("seed_variant"):
            variants = q.get("variants", [])
            v = variants[seed % max(1, len(variants))] if variants else {}
            text = text.replace("{variant_text}", v.get("variant_text", ""))

        # Show context from results
        context_keys = q.get("context_from_results") or []
        context_lines = []
        for k in context_keys:
            val = _lookup(results, k)
            if val is not None:
                context_lines.append(f"  Your {_metric_label(k)}: {val}")

        choices = render_choices(q.get("choices", []), results, env, seed)
        # 18 S5: choices shuffle by the sandbox seed so the right one has no fixed position;
        # reasons are never shuffled.
        if q.get("shuffle") == "seed":
            choices = list(choices)
            random.Random(shuffle_seed() + int(hashlib.md5(q["id"].encode()).hexdigest(), 16) % 1000).shuffle(choices)
        reasons = q.get("reasons", [])

        qs.append({
            "id": q["id"],
            "text": text,
            "context_lines": context_lines,
            "choices": choices,
            "reasons": reasons,
        })
    return qs


def load_questions_old(raw: list, results: dict) -> list[dict]:
    """Parse old-format questions.json (bare array)."""
    qs = []
    for q in raw:
        context_lines = []
        for metric in q.get("show_metrics", []):
            val = _lookup(results, metric)
            if val is not None:
                context_lines.append(f"  Your {_metric_label(metric)}: {val}")
        choices = [{"key": c["key"], "label": c["label"], "value": c["label"]}
                   for c in q.get("choices", [])]
        qs.append({
            "id": q.get("id", str(len(qs))),
            "text": q.get("question", q.get("text", "")),
            "context_lines": context_lines,
            "choices": choices,
            "reasons": q.get("reasons", []),
        })
    return qs


def load_all(results: dict, env: dict, seed: int) -> list[dict]:
    if not QUESTIONS_FILE.exists():
        print(f"ERROR: questions file not found at {QUESTIONS_FILE}", file=sys.stderr)
        sys.exit(1)
    raw = json.loads(QUESTIONS_FILE.read_text())
    if isinstance(raw, list):
        return load_questions_old(raw, results)
    return load_questions_new(raw, results, env, seed)


# ── Interactive prompt ─────────────────────────────────────────────────────────

def ask_question(q: dict, idx: int, total: int) -> tuple[str, str | int | float, str]:
    """Return (choice_key, choice_value, reason_key)."""
    print()
    print(f"Question {idx} of {total}")
    print("=" * 60)
    print(q["text"])
    if q["context_lines"]:
        print()
        for line in q["context_lines"]:
            print(line)

    choices = q["choices"]
    if not choices:
        print("ERROR: no choices available for this question.", file=sys.stderr)
        sys.exit(1)

    print()
    print("Choose one:")
    for i, c in enumerate(choices, 1):
        print(f"  {i}. {c['label']}")

    while True:
        raw = input("Your choice (number): ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(choices):
            chosen_choice = choices[int(raw) - 1]
            break
        print(f"  Enter a number between 1 and {len(choices)}.")

    reasons = q["reasons"]
    if not reasons:
        return chosen_choice["key"], chosen_choice["value"], ""

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

    return chosen_choice["key"], chosen_choice["value"], chosen_reason["key"]


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    results = load_results()
    env = load_env()
    seed = seed_from_variant()
    questions = load_all(results, env, seed)

    print()
    print("Defend: your measurements, your call")
    print("=" * 60)
    print("Answer based on what you measured in this track.")
    if any(q["context_lines"] for q in questions):
        print("Your numbers are shown next to each question.")
    print("Another learner's answer may be wrong for you.")

    decision: dict = {}
    for i, q in enumerate(questions, 1):
        choice_key, choice_value, reason_key = ask_question(q, i, len(questions))
        entry: dict = {"choice": choice_key, "choice_value": choice_value}
        if reason_key:
            entry["reason"] = reason_key
        decision[q["id"]] = entry
        decision.setdefault("answers", []).append({"question_id": q["id"], **entry})

    DECISION_FILE.parent.mkdir(parents=True, exist_ok=True)
    DECISION_FILE.write_text(json.dumps(decision, indent=2))

    print()
    print("Decision recorded.")
    print("Select Check in the sidebar to continue.")


if __name__ == "__main__":
    main()
