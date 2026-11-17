import json
import pathlib
import tempfile
import unittest
from datetime import datetime, timezone

import ara_degrade as D
import ara_setup6_steps as S

NOW = datetime(2026, 11, 12, 9, 0, tzinfo=timezone.utc)


class Fake:
    def __init__(self):
        self.calls, self.bulks, self.cmds, self.labels = [], [], [], set()

    def es(self, m, p, b):
        self.calls.append((m, p))
        if p.endswith("/_count"):
            lab = b["query"]["term"]["run_label"]
            return 200, {"count": 1 if lab in self.labels else 0}
        return 200, {}

    def nd(self, m, p, t):
        self.bulks.append((p, t))
        return 200, {"errors": False, "items": []}

    def run(self, argv):
        self.cmds.append(argv)
        if len(argv) > 4 and argv[3] == "--label":
            self.labels.add(argv[4])
        return 0


def steps(track="6-4", assets=None, root=None, f=None):
    f = f or Fake()
    d = pathlib.Path(root or tempfile.mkdtemp())
    return S.Steps6(f.es, f.nd, f.run, NOW, "p1", d, pathlib.Path(assets or tempfile.mkdtemp()), pathlib.Path("/opt/ara/lib"), track), f, d


def put_set(a, d, items, cats, name="canary-v1", folder="canary"):
    """A public set (no categories) in the assets and its root-only key (categories) under the sandbox root."""
    (a / f"data/ara-m6/{folder}").mkdir(parents=True, exist_ok=True)
    (a / f"data/ara-m6/{folder}/{name}.json").write_text(json.dumps(items))
    (d / "opt/ara/heldout").mkdir(parents=True, exist_ok=True)
    (d / f"opt/ara/heldout/{name}-key.json").write_text(json.dumps({"questions": {}, "categories": cats}))


class T(unittest.TestCase):
    def test_history_load_writes_runs_and_a_root_only_key(self):
        s, f, d = steps()
        s.history_load(1)
        n = sum(t.count('"index"') for _, t in f.bulks)
        self.assertEqual(n, 90)
        k = d / "opt/ara/heldout/6-4/history-key.json"
        self.assertEqual(oct(k.stat().st_mode & 0o777), "0o600")
        self.assertEqual(len(json.loads(k.read_text())), 3)

    def test_capstone_history_is_healthy_with_no_log(self):
        s, f, d = steps("6-c")
        s.history_load(1, last_night_degraded=True)
        s.change_log()
        self.assertEqual(json.loads((d / "opt/ara/heldout/6-c/history-key.json").read_text()), [])
        self.assertTrue(all("cortex-change-log" not in t for _, t in f.bulks))

    def test_change_log_writes_cause_and_decoys(self):
        s, f, _ = steps()
        s.history_load(1)
        s.change_log()
        t = f.bulks[-1][1]
        self.assertIn('"_index": "cortex-change-log"', t)
        self.assertGreaterEqual(t.count('"index"'), 6)

    def test_healthy_history_has_no_degradation(self):
        h = D.history("p1", NOW, healthy=True)
        self.assertEqual((h["change_log"], h["key"]), ([], []))
        self.assertGreater(min(r["routing_accuracy_overall"] for r in h["records"]), 75)

    def test_baseline_measures_once_and_is_idempotent(self):
        a = pathlib.Path(tempfile.mkdtemp())
        s, f, d = steps(assets=a)
        put_set(a, d, [{"question_id": "q-1"}], {"q-1": "straightforward"})
        s.workdir = tempfile.mkdtemp()
        (d / "home/elastic/cortex-eval").mkdir(parents=True)
        (d / "home/elastic/cortex-eval/pool.json").write_text(json.dumps({"questions": [{"id": "q-1", "type": "policy", "input": "x", "relevant_ids": ["a"]}]}))
        s.baseline("m6-baseline")
        s.baseline("m6-baseline")
        self.assertEqual([c[2] for c in f.cmds], ["run", "rank-eval"])
        self.assertEqual(json.loads((pathlib.Path(s.workdir) / "canary-v1.json").read_text()), [{"question_id": "q-1", "category": "straightforward"}])

    def test_missing_data_names_the_path(self):
        s, _, _ = steps()
        with self.assertRaises(S.DataMissing) as e:
            s.testset("canary-v1")
        self.assertIn("data/ara-m6/canary/canary-v1.json", str(e.exception))

    def test_testset_ids_are_stable(self):
        a = pathlib.Path(tempfile.mkdtemp())
        s, f, d = steps(assets=a)
        put_set(a, d, [{"question_id": "q1", "input": "x"}], {"q1": "ambiguous"})
        s.testset("canary-v1")
        self.assertIn('"_id": "canary-v1:q1"', f.bulks[0][1])
        self.assertIn('"category": "ambiguous"', f.bulks[0][1])

    def test_a_set_that_the_root_key_cannot_categorise_ends_the_step(self):
        items = [{"question_id": "q1"}, {"question_id": "q2"}]
        for cats, why in (({"q1": "ambiguous"}, "no category"), ({"q1": "ambiguous", "q2": "nonsense"}, "outside"),
                          ({"q1": "ambiguous", "q2": "ambiguous", "q3": "ambiguous"}, "not in the set"), ({}, "no categories")):
            a = pathlib.Path(tempfile.mkdtemp())
            s, f, d = steps(assets=a)
            put_set(a, d, items, cats)
            with self.assertRaises(S.DataMissing, msg=why):
                s.testset("canary-v1")
            self.assertEqual(f.bulks, [], why)   # nothing is loaded when the key cannot categorise
        # a label in the public file is never used: an entry with its own category ends the step even when the key agrees
        a = pathlib.Path(tempfile.mkdtemp())
        s, f, d = steps(assets=a)
        put_set(a, d, [{"question_id": "q1", "category": "ambiguous"}], {"q1": "ambiguous"})
        with self.assertRaises(S.DataMissing):
            s.testset("canary-v1")
        # no key file at all
        a = pathlib.Path(tempfile.mkdtemp())
        s, f, d = steps(assets=a)
        put_set(a, d, [{"question_id": "q1"}], {"q1": "ambiguous"})
        (d / "opt/ara/heldout/canary-v1-key.json").unlink()
        with self.assertRaises(S.DataMissing) as e:
            s.testset("canary-v1")
        self.assertIn("canary-v1-key.json", str(e.exception))

    def test_search_template_uses_the_text_twin(self):
        s, f, _ = steps()
        s.search_template("cortex-policy-lexical")
        self.assertEqual(f.calls[-1], ("PUT", "/_scripts/cortex-policy-lexical"))
        self.assertIn("body_text", json.dumps(S.LEXICAL_TEMPLATE))

    def test_seed_refuses_an_unmeasured_baseline(self):
        s, f, _ = steps()
        a = s.assets
        (a / "data/ara-m6/seed").mkdir(parents=True)
        (a / "data/ara-m6/seed/manual-chunks.json").write_text("[]")
        s.client = object()
        with self.assertRaises(Exception):
            s.seed("L1")


class SeedPlans(unittest.TestCase):
    def test_l1_and_c1_load_their_extra_field_without_mapping_it(self):
        """6.4 L1 (`audience`) and 6.C C1 (`status`): the seed asks for a clean mapping, so deleting the chunks leaves no field behind; L2/C2 are plain."""
        import ara_degrade_live as DL
        seen = {}
        real = (DL.plan_l1, DL.plan_c1)

        class Stop(Exception):
            pass

        def spy(name):
            def f(*a, **k):
                seen[name] = k
                raise Stop()
            return f
        for layer, name in (("L1", "plan_l1"), ("C1", "plan_c1")):
            s, f, _ = steps()
            (s.assets / "data/ara-m6/seed").mkdir(parents=True)
            (s.assets / "data/ara-m6/seed/manual-chunks.json").write_text(json.dumps([{"chunk_id": "policy-001-s1", "body": "b", "body_text": "b", "title": "t"}]))
            s.client = object()
            try:
                setattr(DL, name, spy(name))
                with self.assertRaises(Stop):
                    s.seed(layer)
            finally:
                DL.plan_l1, DL.plan_c1 = real
        self.assertEqual(seen["plan_l1"].get("clean_mapping"), True)
        # plan_c1 sets clean_mapping inside the plan itself (ara_degrade_live), so the seed passes nothing extra there
        real_plan = DL.plan_c1([{"chunk_id": "policy-001-s1", "body": "b", "title": "t"}], "2026-01-01T00:00:00.000Z", "s")
        self.assertEqual(real_plan["apply"][0]["body"], {"dynamic": False})


class LiveCapture(unittest.TestCase):
    """The seeder reads the manual chunks, the policy mapping and the second endpoint from the project (the data files do not exist)."""

    def _fake(self):
        f = Fake()
        mapping = {"cortex-policies": {"mappings": {"properties": {"body": {"type": "semantic_text", "inference_id": ".jina-embeddings-v5-text-small"}, "body_text": {"type": "text"}, "_inference_fields": {"type": "_inference_fields"}}, "_inference_fields": {"x": 1}}}}
        hits = [{"_id": "policy-002-s6", "_source": {"doc_id": "policy-002-s6", "doc_type": "policy", "body": "b", "body_text": "b", "title": "KYC", "_inference_fields": None}},
                {"_id": "policy-001-s1", "_source": {"doc_id": "policy-001-s1", "doc_type": "policy", "body": "a", "body_text": "a", "title": "Structuring"}}]

        def es(m, p, b):
            f.calls.append((m, p))
            if p == "/cortex-policies/_search":
                return 200, {"hits": {"hits": hits}}
            if p == "/cortex-policies/_mapping":
                return 200, mapping
            if p == "/_inference":
                return 200, {"endpoints": [{"inference_id": ".jina-embeddings-v5-text-small", "task_type": "text_embedding"},
                                           {"inference_id": ".elser-2", "task_type": "sparse_embedding"},
                                           {"inference_id": ".multilingual-e5-small-elasticsearch", "task_type": "text_embedding"}]}
            return 200, {}
        return f, es

    def test_manual_chunks_are_captured_sorted_and_written_under_the_assets(self):
        f, es = self._fake()
        s, _, _ = steps()
        s.es = es
        docs = s._manual_chunks()
        self.assertEqual([d["chunk_id"] for d in docs], ["policy-001-s1", "policy-002-s6"])
        self.assertEqual(json.loads((s.assets / "data/ara-m6/seed/manual-chunks.json").read_text()), docs)
        self.assertTrue(all("_inference_fields" not in d for d in docs))   # a re-bulk of the read-back field is refused

    def test_the_new_endpoint_is_another_dense_one_e5_first(self):
        f, es = self._fake()
        s, _, _ = steps()
        s.es = es
        mapping, old = s._policy_mapping()
        self.assertEqual(old, ".jina-embeddings-v5-text-small")
        self.assertEqual(s._other_dense_endpoint(old), ".multilingual-e5-small-elasticsearch")
        self.assertIn("mappings", mapping)
        self.assertNotIn("_inference_fields", json.dumps(mapping))

    def test_no_second_dense_endpoint_is_an_error(self):
        f, es = self._fake()
        s, _, _ = steps()
        s.es = lambda m, p, b: (200, {"endpoints": [{"inference_id": "x", "task_type": "text_embedding"}]}) if p == "/_inference" else es(m, p, b)
        with self.assertRaises(RuntimeError):
            s._other_dense_endpoint("x")


class Warm(unittest.TestCase):
    def test_the_new_endpoint_is_searched_until_it_answers(self):
        s, f, _ = steps()
        codes = iter([503, 503, 200])
        s.es = lambda m, p, b: (next(codes), {})
        sleeps = []
        real_sleep = S.time.sleep   # S.time is the time module itself: restore what was there, or every later test in the process runs without sleeping
        S.time.sleep = lambda n: sleeps.append(n)
        try:
            s._warm_new_endpoint({"layer": "L2"})
        finally:
            S.time.sleep = real_sleep
        self.assertEqual(len(sleeps), 2)

    def test_other_layers_do_not_wait(self):
        s, f, _ = steps()
        s.es = lambda m, p, b: (_ for _ in ()).throw(AssertionError("no search expected"))
        s._warm_new_endpoint({"layer": "L1"})


if __name__ == "__main__":
    unittest.main()


class Files(unittest.TestCase):
    def test_files_install_data_and_schemas_for_the_track(self):
        a = pathlib.Path(tempfile.mkdtemp())
        (a / "data/ara-m6/files/6-1").mkdir(parents=True)
        (a / "data/ara-m6/files/6-1/card.md").write_text("generic")
        (a / "data/ara-m6/files/6-1/card.md.B").write_text("variant B")
        s, f, d = steps("6-1", assets=a)
        s.files(["card.md"], "B")
        t = d / "home/elastic/cortex-traces"
        self.assertEqual((t / "card.md").read_text(), "variant B")
        self.assertEqual({p.name for p in t.glob("*-schema.json")}, {"read-schema.json", "defect-schema.json", "gap-schema.json"})

    def test_schema_options_are_the_graders_vocabulary(self):
        import ara_m6_schemas as M
        import ara_tracepack as TP
        r = {x["key"]: x for x in M.schemas("6-1")["read-schema.json"]}
        self.assertEqual(tuple(r["failure_class"]["options"]), TP.FAILURE_CLASSES)
        self.assertEqual(r["costly_input_tokens"]["type"], "integer")
        w = M.schemas("6-4")["window1-schema.json"]
        self.assertEqual([x["key"] for x in w], ["change_point_date", "type", "signal"])
        self.assertEqual(sorted(M.schemas("6-3")["patterns-schema.json"][0]["options"]), ["ad_hoc", "per_response", "scheduled"])

    def test_every_schema_is_accepted_by_the_recorder(self):
        import record as R
        import ara_m6_schemas as M
        for t in ("6-1", "6-3", "6-4", "6-c"):
            for name, spec in M.schemas(t).items():
                for fld in spec:
                    self.assertTrue(fld["key"] and fld["label"], name)
                    self.assertIn(fld.get("type", "text"), R.TYPES, name)


class More(unittest.TestCase):
    def test_ticket_needs_the_pack_and_fills_conversation_and_time(self):
        a = pathlib.Path(tempfile.mkdtemp())
        (a / "data/ara-m6/files/6-1").mkdir(parents=True)
        (a / "data/ara-m6/files/6-1/ticket.md").write_text("Conversation {conversation_id} at {at}: {words}")
        s, f, d = steps("6-1", assets=a)
        with self.assertRaises(S.DataMissing):
            s.files(["ticket.md"], "A")
        s.ticket = {"conversation_id": "c-1", "at": "2026-11-12 03:10", "words": "gave up"}
        s.files(["ticket.md"], "A")
        self.assertEqual((d / "home/elastic/cortex-traces/ticket.md").read_text(), "Conversation c-1 at 2026-11-12 03:10: gave up")

    def test_policy_files_write_words_examples_and_a_root_only_key(self):
        s, f, d = steps("6-2")
        s.policy_files(1)
        self.assertIn("Cortex change policy", (d / "home/elastic/cortex-loop/change-policy.md").read_text())
        self.assertEqual(len(list((d / "home/elastic/cortex-loop/proposal-examples").glob("*.json"))), 3)
        k = d / "opt/ara/heldout/6-2/gate-key.json"
        self.assertEqual(json.loads(k.read_text())["target_scope"], "overall")
        self.assertEqual(oct(k.stat().st_mode & 0o777), "0o600")
        self.assertEqual(oct((d / "opt/ara/heldout").stat().st_mode & 0o777), "0o700")

    def test_capstone_gate_json_carries_the_incident_block(self):
        a = pathlib.Path(tempfile.mkdtemp())
        s, f, d = steps("6-c", assets=a)
        s.files(["gate.json"], 2)
        g = json.loads((d / "home/elastic/cortex-loop/gate.json").read_text())   # beside the change policy, where ara-loop.py reads it
        self.assertIn("incident", g)
        self.assertFalse((d / "home/elastic/cortex-history/gate.json").exists())

    def test_defect_applies_the_private_overlay_query_and_keeps_the_rest(self):
        class AB:
            def __init__(self):
                self.put = None

            def get_tool(self, i):
                return {"id": i, "type": "esql", "description": "d", "readonly": False, "schema": {}, "configuration": {"query": "FROM x", "params": {"a": 1}}}

            def put_tool(self, t):
                self.put = t
                return 200, {}
        s, f, d = steps("6-1")
        s.ab = AB()
        with self.assertRaises(S.DataMissing):
            s.defect("C")
        (d / "opt/ara/heldout/6-1").mkdir(parents=True)
        (d / "opt/ara/heldout/6-1/defect.C.json").write_text(json.dumps({"clause": "amount_unit_mismatch", "query": "FROM y"}))
        s.defect("C")
        t = s.ab.put
        self.assertTrue((d / "opt/ara/heldout/6-1/tool-start.json").exists())
        self.assertEqual(t["configuration"]["query"], "FROM y")
        self.assertEqual(t["configuration"]["params"], {"a": 1})
        self.assertNotIn("schema", t)

    def test_heldout_checks_the_embedded_files_and_records_the_variant(self):
        s, f, d = steps("6-1")
        with self.assertRaises(S.DataMissing):
            s.heldout(["structuring.json", "gap.json"], "B")
        h = d / "opt/ara/heldout/6-1"
        h.mkdir(parents=True)
        for n in ("structuring.json", "gap.B.json"):
            (h / n).write_text("{}")
        s.heldout(["structuring.json", "gap.json"], "B")
        self.assertEqual(json.loads((h / "variant.json").read_text())["gap_file"], "gap.B.json")

    def test_exceptions_index_is_loaded_in_every_variant(self):
        a = pathlib.Path(__file__).resolve().parent.parent
        s, f, d = steps("6-1", assets=a)
        s.exceptions()
        self.assertEqual(sum(t.count('"index"') for _, t in f.bulks), 12)

    def test_fresh_round_runs_the_runtime_identity_script_not_the_admin_key(self):
        s, f, d = steps("6-1")
        s.fresh_round()
        self.assertTrue(f.cmds[0][1].endswith("ara-converse.py"))


class VariantRecord(unittest.TestCase):
    def test_merges(self):
        root = pathlib.Path(tempfile.mkdtemp())
        st, _, _ = steps("6-2", root=root)
        st.variant_record(seed_mod=7, ops="O2")
        st.variant_record(variant="A")
        v = json.loads((root / "opt/ara/heldout/6-2/variant.json").read_text())
        self.assertEqual(v, {"seed_mod": 7, "ops": "O2", "variant": "A"})


class StartSnapshot(unittest.TestCase):
    def test_writes_snapshot_and_state(self):
        class AB:
            def get_agent(self, i): return {"id": i, "configuration": {"tools": [{"tool_ids": ["t1"]}]}}
            def get_tool(self, i): return {"id": i, "type": "esql"}
            def get_skill(self, i): return None
            def get_workflow(self, i): return None
            def plugins(self): return []
        st, _, root = steps("6-3")
        st.ab = AB()
        st.start_snapshot()
        held = root / "opt/ara/heldout/6-3"
        state = json.loads((held / "start-state.json").read_text())
        self.assertEqual(set(state), {"tina-compliance", "cortex-securities-irregularities", "t1"})
        self.assertIn("fingerprints", json.loads((held / "start-snapshot.json").read_text()))


class BaselineAgg(unittest.TestCase):
    def test_writes_aggregates(self):
        st, f, root = steps("6-4")
        rec = {"question_id": "q1", "category": "escalation", "expected_route": ["x"], "route_correct": True, "tool_call_count": 2, "input_tokens": 100,
               "cached_input_tokens": 0, "output_tokens": 10, "retrieval": {"ndcg_at_5": 0.8}}
        st.es = lambda m, p, b=None: (200, {"hits": {"hits": [{"_source": rec}]}})
        st.baseline_agg()
        d = json.loads((root / "opt/ara/heldout/6-4/baseline-agg.json").read_text())
        self.assertEqual(d["routing_accuracy_overall"], 100.0)
        self.assertEqual(d["ndcg_at_5"], 0.8)
