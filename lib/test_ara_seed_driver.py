"""The seeder driver: baseline first, apply, change log, degraded measurement; revert on failure; no double seeding."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ara_degrade_live as DL  # noqa: E402
import ara_seed_driver as S  # noqa: E402
from test_ara_degrade_live import AT, MANUAL, MAPPING, Fake  # noqa: E402


class ES:
    def __init__(self, labels):
        self.labels, self.docs, self.order = set(labels), [], []

    def has_label(self, label): return label in self.labels
    def index_docs(self, index, docs): self.order.append(("log", index)); self.docs += docs


def test_seed_order_and_summary():
    es, c = ES({"m6-baseline"}), Fake()
    order = []
    es.index_docs = lambda i, d: order.append("log") or None
    plan = DL.plan_l1(MANUAL, AT, "s1")
    out = S.seed(plan, c, es, lambda label: order.append(f"measure:{label}"))
    assert order == ["log", "measure:m6-degraded"] and len(c.calls) == 2 and out["layer"] == "L1"   # the load and the count of what it loaded
    assert out["cause_change_id"] in out["change_ids"] and len(out["change_ids"]) == 2


def test_no_baseline_means_nothing_is_applied():
    c = Fake()
    try:
        S.seed(DL.plan_l1(MANUAL, AT), c, ES(set()), lambda l: None)
        raise AssertionError("expected SeedError")
    except S.SeedError as e:
        assert "m6-baseline has not been measured" in str(e)
    assert c.calls == []


def test_second_seed_is_refused():
    try:
        S.seed(DL.plan_l1(MANUAL, AT), Fake(), ES({"m6-baseline", "m6-degraded"}), lambda l: None)
        raise AssertionError("expected SeedError")
    except S.SeedError as e:
        assert "already" in str(e)


def test_failure_reverts_and_measures_nothing():
    plan = DL.plan_l2(MANUAL, MAPPING, "old", "new", AT, "s1")
    c, measured = Fake(fail_at="-v2/_bulk"), []
    es = ES({"m6-baseline"})
    try:
        S.seed(plan, c, es, measured.append)
        raise AssertionError("expected SeedError")
    except S.SeedError as e:
        assert "reverted" in str(e)
    assert measured == [] and es.docs == []
    assert ("PUT", "/cortex-policies") in c.calls  # the revert recreated the original


def test_unseed_runs_the_revert_and_c2_differs_from_l2():
    c = Fake()
    S.unseed(DL.plan_l1(MANUAL, AT), c)
    assert c.calls and c.calls[0][0] == "POST" and "_delete_by_query" in c.calls[0][1]
    l2, c2 = DL.plan_l2(MANUAL, MAPPING, "old", "new", AT, "s1"), DL.plan_c2(MANUAL, MAPPING, "old", "new", AT, "s1")
    assert c2["layer"] == "C2" and len(c2["v2"]) < len(l2["v2"]) and "re-index moved" in c2["change_log"][0]["after"]
    assert sorted(c2["v1"] + c2["v2"]) == sorted(m["chunk_id"] for m in MANUAL) and c2["key"]["type"] == "embedding_staleness"
