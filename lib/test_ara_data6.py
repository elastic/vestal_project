import datetime as dt
import gzip
import json
import pathlib

import ara_defects6 as D
import ara_gap6 as G
import ara_loop as L
import ara_policy6 as P

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCS = [json.loads(x) for x in gzip.open(ROOT / "data/ara-m4-fraud/cortex-wire-transfers.ndjson.gz", "rt")]
PLANTED = json.loads((ROOT / "data/ara-m4-fraud/planted.json").read_text())["cortex-wire-transfers"]
NOW = max(D._t(d["@timestamp"]) for d in DOCS) + dt.timedelta(days=1)


def test_card_lists_three_buildable_and_two_named_only():
    t = G.card_md()
    for c in G.CARDS.values():
        assert c["tool_id"] in t and c["key_column"] in t
    assert all(d in t for d in G.DECOYS) and "cortex.sanctions" not in t


def test_gate_keys_are_distinct_complete_and_accepted_by_the_loop():
    keys = [P.gate_key(v) for v in P.VARIANTS]
    assert all(set(P.FIELDS) == set(k) for k in keys) and len({json.dumps(k, sort_keys=True) for k in keys}) == 3
    assert all(set(P.GATES[v]["incident"]) == {"recovery_tolerance_points", "recovery_tolerance_ndcg"} for v in P.VARIANTS)
    assert L._limit(keys[0]["cost_limit_pct"]) == 15.0


def test_policy_text_states_every_number_and_has_no_dash():
    for v in P.VARIANTS:
        t = P.policy_text(v, True)
        for f in ("min_gain_points", "min_gain_pct", "category_drop_limit_points", "tool_call_limit_pct", "cost_limit_pct"):
            assert f"{P.GATES[v][f]:g}" in t
        assert "—" not in t and f'{P.GATES[v]["incident"]["recovery_tolerance_ndcg"]:g}' in t
    assert "Incident rule" not in P.policy_text("G1")


def test_public_question_sets_carry_no_category():
    """The category of each M6 question comes from the root-only key (ara_setcat); a label in the public file is never read."""
    import ara_setcat as SC
    for rel in ("data/ara-m6/gate/gate-v1.1.json", "data/ara-m6/canary/canary-v1.json"):
        items = json.loads((ROOT / rel).read_text())
        assert items and SC.check_public(items) == [], rel
        assert all(set(q) <= {"question_id", "type", "kind", "input"} for q in items), rel
