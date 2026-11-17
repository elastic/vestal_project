"""ara_setcat.py - the categories of the M6 question sets (canary-v1, gate-v1.1) come from the root-only key, never from the public file.

The public set files hold question_id, type, kind and input. Each set's root-only key holds the golds under "questions" and the category of every
question under "categories". This module joins them and fails closed: a key without a category for every question, a category outside the list, a key
question missing from the set (or the reverse), or a public entry that carries a category of its own is an error. There is no fallback to a label
in the public file and no uncategorised entry.

    with_categories(items, key, what) -> items with "category" added   (setup, test-set files, the check-side pool)
    check_public(items, what)         -> problems: entries that carry a category (the lint)
    check_categorised(items, what)    -> problems in a finished test-set file (the learner-side guard)
Standard library only (the category list is read from ara_eval when it is importable).
"""
from __future__ import annotations

try:
    from ara_eval import CATEGORIES
except ImportError:   # pragma: no cover - the lib is always together in a sandbox
    CATEGORIES = ("straightforward", "ambiguous", "time_window_edge", "cross_domain", "adversarial", "out_of_scope")


class CategoryError(Exception):
    """The root-only key cannot categorise the set; the caller ends with no grade."""


def key_categories(key, what: str) -> dict:
    cats = key.get("categories") if isinstance(key, dict) else None
    if not isinstance(cats, dict) or not cats:
        raise CategoryError(f"{what}: the root-only key has no categories")
    return cats


def with_categories(items: list[dict], key, what: str = "the question set") -> list[dict]:
    """Every item gains its category from the key. Raises CategoryError on any gap or mismatch."""
    cats = key_categories(key, what)
    ids = [q.get("question_id") or q.get("id") for q in items]
    if len(set(ids)) != len(ids):
        raise CategoryError(f"{what}: a question id is listed twice")
    own = [i for q, i in zip(items, ids) if "category" in q]
    if own:
        raise CategoryError(f"{what}: {len(own)} entries carry a category of their own; categories come from the root-only key only")
    missing = [i for i in ids if i not in cats]
    if missing:
        raise CategoryError(f"{what}: {len(missing)} questions have no category in the root-only key")
    extra = [i for i in cats if i not in set(ids)]
    if extra:
        raise CategoryError(f"{what}: the root-only key categorises {len(extra)} questions that are not in the set")
    bad = [i for i in ids if cats[i] not in CATEGORIES]
    if bad:
        raise CategoryError(f"{what}: {len(bad)} questions have a category outside the list")
    return [dict(q, category=cats[i]) for q, i in zip(items, ids)]


def check_public(items: list[dict], what: str = "the public set") -> list[str]:
    return [f"{what}: {q.get('question_id') or q.get('id')} carries a category" for q in items if "category" in q]


def check_categorised(items: list[dict], what: str = "the test set") -> list[str]:
    """A finished test-set file: every agent-level entry needs a category from the list. Policy entries are retrieval questions and need one too
    (the retrieval table reports them by category)."""
    return [f"{what}: {q.get('question_id') or q.get('id')} has no valid category" for q in items if q.get("category") not in CATEGORIES]
