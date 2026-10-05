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
import math
import os
import pathlib
import re
import sys
import random

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
    env_path = pathlib.Path("/home/elastic/env")
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


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


def _formula_keys(choices: list[dict]) -> list[str]:
    """Result keys the computed choices read, to name what a skipped challenge left missing."""
    keys: list[str] = []
    for c in choices:
        comp = c.get("computed") or {}
        for f in (comp.get("formula"), comp.get("fallback_formula")):
            if not f or f.strip().startswith("env:"):
                continue
            for name in re.findall(r"[A-Za-z_][A-Za-z0-9_.]*", f):
                if name not in ("floor", "max") and not name.startswith("env_") and name not in keys:
                    keys.append(name)
    return keys


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
        # every choice is computed from results a skipped challenge never wrote
        missing = [] if choices else [k for k in _formula_keys(q.get("choices", []))
                                      if _lookup(results, k) is None]
        
        # Apply seeded shuffle if requested
        if q.get("shuffle") == "seed" and seed is not None:
            shuffled_choices = list(choices)
            random.Random(seed).shuffle(shuffled_choices)
            choices = shuffled_choices
        
        reasons = q.get("reasons", [])
        
        # Apply seeded shuffle to reasons if requested
        if q.get("shuffle") == "seed" and seed is not None and reasons:
            shuffled_reasons = list(reasons)
            random.Random(seed).shuffle(shuffled_reasons)
            reasons = shuffled_reasons

        qs.append({
            "id": q["id"],
            "text": text,
            "context_lines": context_lines,
            "choices": choices,
            "reasons": reasons,
            "missing": missing,
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
    if any(q.get("seed_variant") for q in raw.get("questions", [])):
        require_variant()
    return load_questions_new(raw, results, env, seed)


def require_variant() -> None:
    """A seeded question must use the variant the Defend setup recorded, the one the check
    grades against. Never reseed: a recomputed seed can show another variant's question."""
    try:
        int(json.loads(VARIANT_FILE.read_text())["seed_mod"])
    except Exception:
        print("This track's setup did not record your variant, so the questions can't be shown. "
              "Stop the track and start it again.")
        sys.exit(1)


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


FEEDBACK_CMD = ["sudo", "-n", "/opt/ara/checks/defend-feedback"]


def feedback() -> bool | None:
    """Spec 18 section 1.8: grade the recorded decision with the Defend check's own code (run as
    root through one sudoers entry) and print what Check would show. True on a pass (the rule
    behind each answer, next to your numbers), False on a fail (the check's message for the first
    inconsistent question, never why). None when the step is unavailable: Check still grades."""
    import subprocess
    try:
        p = subprocess.run(FEEDBACK_CMD, capture_output=True, text=True, timeout=60,
                           stdin=subprocess.DEVNULL)
    except Exception:
        return None
    if p.returncode not in (0, 10) or not p.stdout.strip():
        return None
    print()
    if p.returncode == 0:
        print("Your answers are consistent with your measurements:")
    print(p.stdout.rstrip())
    return p.returncode == 0


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    results = load_results()
    env = load_env()
    seed = seed_from_variant()
    questions = load_all(results, env, seed)

    print()
    print("Defend — your measurements, your call")
    print("=" * 60)
    print("Answer based on what you measured in this track.")
    print("Your numbers are shown next to each question.")
    print("Another learner's answer may be wrong for you.")

    # A skipped Build leaves no results, so a question built from them has no choices.
    # Say so first, record the rest, and let Check name the challenge (C5-4).
    skipped = [i for i, q in enumerate(questions, 1) if not q["choices"]]
    if skipped:
        print()
        print("A challenge was skipped, so some of your results are missing.")
        for i in skipped:
            q = questions[i - 1]
            names = ", ".join(_metric_label(k) for k in q.get("missing") or []) or "results from an earlier challenge"
            print(f"  Question {i} can't be shown: it needs your {names}.")
        if len(skipped) < len(questions):
            print("Answer the other questions. Check then names the challenge to complete.")

    decision: dict = {}
    for i, q in enumerate(questions, 1):
        if not q["choices"]:
            decision[q["id"]] = {"skipped": True}
            continue
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
    passed = feedback()
    print()
    if passed is False:
        print("Run python3 /opt/ara/lib/defend.py again to change your answers, then select Check.")
    else:
        print("Select Check in the sidebar to continue.")


if __name__ == "__main__":
    main()
