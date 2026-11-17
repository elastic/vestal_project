"""ara_setup6_steps.py - the M6 setup steps that load data, seed and measure (28 sections 2 to 6, 29 section 3).

    Steps6(es, es_ndjson, run, now, participant, root, assets, lib, track, agent=...).handlers() -> {step name: callable}

ara-setup6.py merges these over the HTTP and file steps of ara_setup6.Setup6. `es` is (method, path, body) -> (code, body);
`es_ndjson` is (method, path, text) -> (code, body); `run(argv)` runs a subprocess as root and returns its exit code (the one place
a test replaces); `root` is the directory held-out files are written under (a sandbox's /). Held-out outputs go to
`<root>/opt/ara/heldout/<track>/` mode 0600 and never anywhere a learner reads. Nothing here enables a schedule or converses under
the admin credential: measuring goes through ara-eval.py with the sandbox's own harness settings.

A step whose data is not in the assets yet raises DataMissing with the path it looked for, so setup stops with a plain message
instead of a half-built sandbox. Standard library only.
"""
from __future__ import annotations

import json
import os
import pathlib
import time
from datetime import datetime, timedelta
from typing import Callable

import ara_degrade as D
import ara_history as H
import ara_defects6 as DF
import ara_degrade_live as DL
import ara_gap6 as GP
import ara_history as H
import ara_m6_schemas as MS
import ara_pack_cli as P
import ara_policy6 as PO
import ara_proposal_schema as PS
import ara_seed_driver as SD

RUNS = "cortex-eval-runs"
LOG = "cortex-change-log"
TESTSETS = "cortex-eval-testsets"
LEXICAL_TEMPLATE = {"script": {"lang": "mustache", "source": {
    "query": {"match": {"body_text": "{{query_string}}"}}, "size": "{{size}}"}}}


class DataMissing(RuntimeError):
    pass


class Steps6:
    def __init__(self, es: Callable, es_ndjson: Callable, run: Callable[[list[str]], int], now: datetime, participant: str,
                 root: pathlib.Path, assets: pathlib.Path, lib: pathlib.Path, track: str, agent: str = "tina-compliance",
                 client=None, workdir: str = "/root/m6", ab=None):
        self.es, self.nd, self.run, self.now, self.pid = es, es_ndjson, run, now, participant
        self.root, self.assets, self.lib, self.track, self.agent = root, assets, lib, track, agent
        self.client, self.workdir, self.ab = client, workdir, ab
        self.ticket: dict | None = None
        self.hist: dict | None = None
        self.plan: dict | None = None

    # ── helpers ──
    def _need(self, rel: str) -> pathlib.Path:
        p = self.assets / rel
        if not p.exists():
            raise DataMissing(f"{rel} is not in the assets yet (needs a live capture or authoring)")
        return p

    def _held(self, name: str, obj) -> None:
        """Root-only: the held-out tree is mode 0700 and each file 0600 (09 T20); nothing here is readable by the learner."""
        p = self.root / "opt/ara/heldout" / self.track / name
        p.parent.mkdir(parents=True, exist_ok=True)
        for d in (p.parent.parent, p.parent):
            d.chmod(0o700)
        p.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")
        p.chmod(0o600)

    def _snapshot_now(self):
        """The fraud snapshot's own clock: its newest event plus a day, which is the load time after the loader's uniform shift."""
        import gzip
        docs = [json.loads(x) for x in gzip.open(self._need("data/ara-m4-fraud/cortex-wire-transfers.ndjson.gz"), "rt")]
        return docs, max(DF._t(d["@timestamp"]) for d in docs) + timedelta(days=1)

    def _bulk(self, index: str, docs: list[dict], id_of: Callable[[dict], str]) -> None:
        for i in range(0, len(docs), 500):
            lines = []
            for d in docs[i:i + 500]:
                lines += [json.dumps({"index": {"_index": index, "_id": id_of(d)}}), json.dumps(d)]
            code, body = self.nd("POST", "/_bulk?refresh=wait_for", "\n".join(lines) + "\n")
            if code != 200 or (isinstance(body, dict) and body.get("errors")):
                raise RuntimeError(f"bulk into {index} refused (HTTP {code})")

    def _has_label(self, label: str) -> bool:
        code, body = self.es("POST", f"/{RUNS}/_count", {"query": {"term": {"run_label": label}}})
        return code == 200 and body.get("count", 0) > 0

    # ── steps ──
    def pack_load(self, pack: str, variant: str) -> None:
        d = self._need(f"data/ara-m6/traces/{pack}/manifest.json").parent
        manifest = json.loads((d / "manifest.json").read_text())
        key = json.loads((d / "key.json").read_text()) if (d / "key.json").exists() else None

        class _ES:
            request_ndjson = staticmethod(lambda m, p, t: self.nd(m, p, t))
        out = P.load(d, manifest, _ES, self.now, key, self.pid)
        if out["key"] is not None:
            self._held("week-key.json" if pack.startswith("W") else "key.json", out["key"])
        tk = d / "ticket.json"
        if tk.exists():
            t = json.loads(tk.read_text())
            cid = out["id_map"].get(t["conversation_id"], t["conversation_id"])
            self.ticket = {"conversation_id": cid, "at": self._conv_time(cid), "words": t.get("words", "Tina took about 40 seconds and then gave up.")}

    def _conv_time(self, conv_id: str) -> str:
        code, body = self.es("POST", f"/{P.SPAN_INDEX}/_search", {"size": 0, "query": {"term": {H.CONV: conv_id}},
                                                                    "aggs": {"first": {"min": {"field": "@timestamp"}}}})
        v = ((body or {}).get("aggregations") or {}).get("first", {}).get("value_as_string") if code == 200 else None
        if not v:
            raise RuntimeError("the ticket's round is not in the trace stream after the pack load")
        return v[:16].replace("T", " ")

    def _held_in(self, name: str) -> pathlib.Path:
        p = self.root / "opt/ara/heldout" / self.track / name
        if not p.exists():
            raise DataMissing(f"/opt/ara/heldout/{self.track}/{name} is not installed (the private track repo embeds it)")
        return p

    def defect(self, variant: str) -> None:
        """Apply the variant's defect: its query comes from the private overlay `defect.<variant>.json` ({clause, query}), installed root-only."""
        if self.ab is None:
            raise RuntimeError("defect needs the Agent Builder client")
        ov = json.loads(self._held_in(f"defect.{variant}.json").read_text())
        tool = self.ab.get_tool("cortex.structuring_deposits")
        if tool is None:
            raise RuntimeError("cortex.structuring_deposits is not in the start state")
        import ara_loop_cli as LC
        body = {k: v for k, v in tool.items() if k not in set(LC.SERVER_FIELDS) | set(LC.EXTRA_STRIP["tool"])}
        body.setdefault("configuration", {})["query"] = ov["query"]
        code, resp = self.ab.put_tool(body)
        if code >= 300:
            raise RuntimeError(f"the defective tool was refused (HTTP {code})")
        start = self.ab.get_tool("cortex.structuring_deposits")  # the learner's start state, for the check's "only the query changed" comparison
        self._held("tool-start.json", start or body)

    def exceptions(self) -> None:
        """cortex-policy-exceptions: loaded in every variant, so the index does not say which capability is the gap."""
        mapping = json.loads(self._need("data/ara-m6/mappings/cortex-policy-exceptions.json").read_text())
        self.es("DELETE", "/cortex-policy-exceptions?ignore_unavailable=true", None)
        code, _ = self.es("PUT", "/cortex-policy-exceptions", mapping)
        if code != 200:
            raise RuntimeError(f"cortex-policy-exceptions refused (HTTP {code})")
        self._bulk("cortex-policy-exceptions", GP.EXCEPTIONS, lambda e: e["exception_id"])

    def heldout(self, names: list[str], variant: str) -> None:
        """The 6.1 held-out files are embedded by the private track repo (never generated from public code): check each is installed,
        and record which variant this sandbox runs for the graders (`variant.json`)."""
        for n in names:
            self._held_in(n if n == "structuring.json" else n.replace(".json", f".{variant}.json"))
        if self.ab is not None:
            import ara_loop as L
            self._held("tina-start.json", {"tool_ids": sorted(L.tool_id_list(self.ab.get_agent(self.agent) or {}))})
        self.variant_record(variant=variant, gap_file=f"gap.{variant}.json", defect_file=f"defect.{variant}.json")

    def variant_record(self, **fields) -> None:
        """`variant.json` for the graders: the seed and every variant the plan picked (setup's `variant` step), merged with what other steps add."""
        p = self.root / "opt/ara/heldout" / self.track / "variant.json"
        try:
            cur = json.loads(p.read_text())
        except (OSError, ValueError):
            cur = {}
        self._held("variant.json", {**cur, **fields})

    def baseline_agg(self, label: str = "m6-baseline") -> None:
        """The trusted aggregates of the healthy baseline (ara_eval.aggregates over the label's records, plus the mean nDCG at 5 of the retrieval records), root-only,
        for the graders that compare a re-measure with it (6.2 gate and re-measure, 6.4 recovery, 6.C incident rule)."""
        import ara_eval as E
        code, body = self.es("POST", f"/{RUNS}/_search", {"size": 1000, "query": {"term": {"run_label": label}}})
        recs = [h["_source"] for h in body["hits"]["hits"]] if code == 200 else []
        if not recs:
            raise RuntimeError(f"no run records labelled {label}")
        try:
            card = json.loads((self.root / "opt/ara/thresholds.json").read_text()).get("rate_card")
        except (OSError, ValueError):
            card = None
        agg = E.aggregates(recs, card)
        vals = [r["retrieval"]["ndcg_at_5"] for r in recs if isinstance(r.get("retrieval"), dict) and r["retrieval"].get("ndcg_at_5") is not None]
        agg["ndcg_at_5"] = (sum(vals) / len(vals)) if vals else None
        self._held("baseline-agg.json", agg)

    def start_snapshot(self) -> None:
        """The reach as the learner is handed it, root-only: `start-snapshot.json` (ara_integrity.snapshot, for diff) and `start-state.json` (raw agent and
        tool definitions by id, the ledger replay's start in 6.2). Taken after the last seed step, so 'nothing else changed' means from this state."""
        if self.ab is None:
            raise RuntimeError("start_snapshot needs a live client")
        import ara_integrity as INTEG
        reach = INTEG.collect_reach(self.ab, [self.agent, "cortex-securities-irregularities"])
        self._held("start-snapshot.json", INTEG.snapshot(reach))
        self._held("start-state.json", {k.split("/", 1)[1]: v for k, v in reach.items() if k.startswith(("agent/", "tool/")) and v})

    def policy_files(self, variant, incident: bool = False) -> None:
        g = PO.VARIANTS[variant] if isinstance(variant, int) else variant
        dest = self.root / "home/elastic/cortex-loop"
        (dest / "proposal-examples").mkdir(parents=True, exist_ok=True)
        (dest / "change-policy.md").write_text(PO.policy_text(g, incident))
        for label, prop in PS.VALID.items():
            (dest / "proposal-examples" / f"valid-{label}.json").write_text(json.dumps(prop, indent=2) + "\n")
        self._held("gate-key.json", PO.gate_key(g, incident))
        self._chown(dest)

    def _chown(self, root_dir: pathlib.Path) -> None:
        try:
            import pwd
            u = pwd.getpwnam("elastic")
            for q in [root_dir, *root_dir.rglob("*")]:
                os.chown(q, u.pw_uid, u.pw_gid)
        except (KeyError, PermissionError, ImportError):
            pass

    def fresh_round(self) -> None:
        """One real Tina round after the trace settings are on, as the runtime identity (ara-converse.py reads ARA_TINA_RUNTIME_KEY), never the admin key."""
        rc = self.run(["python3", str(self.lib / "ara-converse.py"), "What does Cortex policy say about politically exposed persons?"])
        if rc != 0:
            raise RuntimeError(f"the fresh round exited {rc}")

    def history_load(self, variant, last_night_degraded: bool = False) -> None:
        night = {"C1": "retrieval_drift", "C2": "embedding_staleness", "C3": "behavior_shift"}.get(str(variant)) if last_night_degraded else None
        self.hist = D.history(self.pid, self.now, healthy=last_night_degraded, night_type=night)
        self._bulk(RUNS, self.hist["records"], lambda r: r["run_label"])
        self._held("history-key.json", self.hist["key"])

    def change_log(self) -> None:
        entries = (self.hist or {}).get("change_log") or []
        if entries:
            self._bulk(LOG, entries, lambda e: e["change_id"])

    def _set_file(self, version: str) -> pathlib.Path:
        """The public question file of a test set: the canary sets and the gate sets live in their own folders."""
        return self._need(f"data/ara-m6/{'gate' if version.startswith('gate-') else 'canary'}/{version}.json")

    def _set_items(self, version: str) -> list[dict]:
        """The set's questions with their categories from the root-only key. A key that cannot categorise every question ends the step (no label in the
        public file is ever used)."""
        import ara_setcat as SC
        items = json.loads(self._set_file(version).read_text())
        keyp = self.root / "opt/ara/heldout" / f"{version}-key.json"
        try:
            key = json.loads(keyp.read_text())
        except (OSError, ValueError):
            raise DataMissing(f"/opt/ara/heldout/{version}-key.json is not installed (the private track repo embeds it)") from None
        try:
            return SC.with_categories(items, key, version)
        except SC.CategoryError as e:
            raise DataMissing(str(e)) from None

    def testset(self, version: str) -> None:
        items = self._set_items(version)
        docs = [dict(q, testset_version=version) for q in items]
        self._bulk(TESTSETS, docs, lambda q: f"{version}:{q.get('question_id') or q['id']}")

    def search_template(self, id: str) -> None:
        code, body = self.es("PUT", f"/_scripts/{id}", LEXICAL_TEMPLATE)
        if code != 200:
            raise RuntimeError(f"search template {id} refused (HTTP {code})")

    def _measure(self, label: str, version: str = "canary-v1") -> None:
        """The harness over the gate set (M6's test copies: canary-v1 stands for v1.1 until that set is authored), then the retrieval measurement of its policy questions.
        The harness reads the set and the rank-eval artifact from files: written here from the assets and the pool file the learner is handed."""
        import ara_testset as TS
        wd = pathlib.Path(self.workdir)
        home = wd / "evalhome"
        home.mkdir(parents=True, exist_ok=True)
        ts = wd / f"{version}.json"
        ts.write_text(json.dumps(self._set_items(version)))
        pool = self.root / "home/elastic/cortex-eval/pool.json"
        if not pool.exists():
            raise RuntimeError("the learner pool file is missing: the 5.3 evaluation environment step writes it")
        (home / "pool.json").write_text(pool.read_text())
        (home / "testset.json").write_text(ts.read_text())
        import io
        TS.cmd_rank_eval(home, ["precision:k=5", "recall:k=5", "dcg:k=5,normalize=true"], io.StringIO())
        for argv in (["python3", str(self.lib / "ara-eval.py"), "run", "--label", label, "--testset", str(ts), "--agent", self.agent],
                     ["python3", str(self.lib / "ara-eval.py"), "rank-eval", "--label", label, "--testset", str(ts), "--rank-eval", str(home / "rank-eval.json")]):
            rc = self.run(argv)
            if rc != 0:
                raise RuntimeError(f"ara-eval.py {argv[2]} --label {label} exited {rc}")

    def baseline(self, label: str, testset: str = "canary-v1") -> None:
        if self._has_label(label):
            return
        self._measure(label, testset)

    def degraded(self, label: str, testset: str = "canary-v1") -> None:
        if not self._has_label(label):
            self._measure(label, testset)

    # live captures for the seeder: the same project every learner gets, so what is read here is what the fix has to put back
    def _manual_chunks(self) -> list[dict]:
        """The 89 manual policy chunks, {chunk_id (= the document id), body, body_text, doc_id, ...}. Read from the assets when the file is there; otherwise
        captured from `cortex-policies` before the seed and written under the assets (the graders read the ids from there)."""
        p = self.assets / "data/ara-m6/seed/manual-chunks.json"
        if p.exists():
            return json.loads(p.read_text())
        code, body = self.es("POST", "/cortex-policies/_search", {"size": 1000, "_source": {"excludes": ["_inference_fields"]}, "query": {"term": {"doc_type": "policy"}}})
        hits = (body or {}).get("hits", {}).get("hits", []) if code == 200 and isinstance(body, dict) else []
        if not hits:
            raise RuntimeError(f"the manual policy chunks could not be read from cortex-policies (HTTP {code}); seed needs them before it changes anything")
        docs = sorted(({"chunk_id": h["_id"], **{k: v for k, v in (h.get("_source") or {}).items() if k not in ("chunk_id", "_inference_fields")}} for h in hits), key=lambda d: d["chunk_id"])
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(docs))
        return docs

    def _policy_mapping(self) -> tuple[dict, str]:
        """({"mappings": ...} of cortex-policies, the endpoint its semantic_text field uses)."""
        code, body = self.es("GET", "/cortex-policies/_mapping", None)
        if code != 200 or not isinstance(body, dict) or not body:
            raise RuntimeError(f"the cortex-policies mapping could not be read (HTTP {code})")
        m = next(iter(body.values()))["mappings"]

        def strip(n):   # the read-back mapping lists the server's own `_inference_fields`; a new index built from it fails every bulk
            if isinstance(n, dict):
                n.pop("_inference_fields", None)
                for v in n.values():
                    strip(v)
        m = json.loads(json.dumps(m))
        strip(m)
        eps = []

        def walk(n):
            if isinstance(n, dict):
                if n.get("type") == "semantic_text":
                    eps.append(n.get("inference_id"))
                for v in n.values():
                    walk(v)
        walk(m)
        if not eps or not eps[0]:
            raise RuntimeError("cortex-policies has no semantic_text field with an inference endpoint")
        return {"mappings": m}, eps[0]

    def _other_dense_endpoint(self, old: str) -> str:
        """The new endpoint for L2/C2: another dense text-embedding endpoint than the one in use (probe r4: jina-v5-small and e5-small), e5-small first."""
        code, body = self.es("GET", "/_inference", None)
        eps = [e.get("inference_id") for e in ((body or {}).get("endpoints") or []) if isinstance(body, dict) and e.get("task_type") == "text_embedding"] if code == 200 else []
        eps = [e for e in eps if e and e != old]
        if not eps:
            raise RuntimeError("no second dense text_embedding endpoint is available for the staleness seed")
        return next((e for e in eps if "e5-small" in e), eps[0])

    def _warm_new_endpoint(self, plan: dict, wait_s: float = 420.0) -> None:
        """L2/C2: the new dense endpoint starts on first use, and a search over the mixed alias errors until it has (_rank_eval over the
        rrf template failed right after the seed, the same searches worked a few minutes later). Search the new index until it answers."""
        if plan.get("layer") not in ("L2", "C2"):
            return
        q = {"query": {"semantic": {"field": "body", "query": "warm up the new embedding endpoint"}}, "size": 1, "_source": False}
        end = time.monotonic() + wait_s
        while True:
            code, _ = self.es("POST", "/cortex-policies-v2/_search", q)
            if code == 200:
                return
            if time.monotonic() > end:
                raise RuntimeError(f"the new embedding endpoint did not answer a search within {int(wait_s)} s (last HTTP {code})")
            time.sleep(10)

    def seed(self, layer: str) -> None:
        if self.client is None:
            raise RuntimeError("seed needs a live client for the plan's operations")
        manual = self._manual_chunks()
        print("setup6: manual chunks", len(manual), "keys", sorted(manual[0]) if manual else None, "body type", type(manual[0].get("body")).__name__ if manual else None, flush=True)
        at = self.now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        if layer in ("L1", "C1"):
            plan = DL.plan_l1(manual, at, self.pid, clean_mapping=True) if layer == "L1" else DL.plan_c1(manual, at, self.pid)   # the FAQs' `audience` stays unmapped: mapped, it outlives the revert and the policy search returns no snippets
        elif layer in ("L2", "C2"):
            mapping, old = self._policy_mapping()
            new = self._other_dense_endpoint(old)
            plan = (DL.plan_l2 if layer == "L2" else DL.plan_c2)(manual, mapping, old, new, at, self.pid)
        elif layer == "L3":
            tool = self.ab.get_tool("cortex.escalate") if self.ab is not None else None
            if not tool:
                raise RuntimeError("cortex.escalate could not be read for the behaviour seed")
            plan = DL.plan_l3(tool, at, self.pid)
        elif layer == "C3":
            agent = self.ab.get_agent(self.agent) if self.ab is not None else None
            if not agent:
                raise RuntimeError("Tina could not be read for the instruction seed")
            plan = DL.plan_c3(agent, at, self.pid)
        else:
            raise DataMissing(f"unknown seed layer {layer}")

        class _E:
            has_label = staticmethod(self._has_label)
            index_docs = staticmethod(lambda idx, docs: self._bulk(idx, docs, lambda e: e["change_id"]))
        # The driver measures m6-degraded itself, so the plan's seed runs once and `degraded` finds the label.
        def measure(label):
            self._warm_new_endpoint(plan)
            self._measure(label, "gate-v1.1" if self.track == "6-c" else "canary-v1")
        out = SD.seed(plan, self.client, _E, measure)
        self.plan = plan
        self._held("seed-key.json", out)
        if self.track == "6-c":  # 07 section 3.4: the decoy key, for the capstone's Defend
            kind = next(e["kind"] for e in plan["change_log"] if not e["cause"])
            self._held("decoy-key.json", {"decoy": {"model_pin": "model_pin_no_model_change", "ingest": "intake_ingest"}.get(kind, kind)})

    def files(self, names: list[str], variant=None) -> None:
        """The learner's files for the track: each named file from data/ara-m6/files/<track>/ (a `<name>.<variant>` copy wins), plus the
        track's recorder schemas, under /home/elastic/<dir>/. Mode 0644; chown to `elastic` when setup runs as root."""
        dest = self.root / "home/elastic" / MS.DEST[self.track]
        dest.mkdir(parents=True, exist_ok=True)
        out = {}
        for n in names:
            v = self.assets / f"data/ara-m6/files/{self.track}/{n}.{variant}"
            if n == "gate.json" and self.track == "6-c":  # the capstone's reference gate, with its incident block (07 section 3.2), beside the change policy where ara-loop.py reads it
                loop = self.root / "home/elastic/cortex-loop"
                loop.mkdir(parents=True, exist_ok=True)
                (loop / n).write_text(json.dumps(PO.gate_key(PO.VARIANTS[variant], True), indent=2) + "\n")
                (loop / n).chmod(0o644)
                try:
                    import pwd
                    u = pwd.getpwnam("elastic")
                    os.chown(loop / n, u.pw_uid, u.pw_gid)
                except (KeyError, PermissionError, ImportError):
                    pass
                continue
            text = (v if variant is not None and v.exists() else self._need(f"data/ara-m6/files/{self.track}/{n}")).read_text()
            if n == "ticket.md":
                if self.ticket is None:
                    raise DataMissing("ticket.md needs the pack's ticket.json (a live capture): load the pack first")
                text = text.format(**self.ticket)
            out[n] = text
        for n, spec in MS.schemas(self.track).items():
            out[n] = json.dumps(spec, indent=2) + "\n"
        for n, text in out.items():
            (dest / n).write_text(text)
            (dest / n).chmod(0o644)
        try:
            import pwd
            u = pwd.getpwnam("elastic")
            for p in [dest, *dest.iterdir()]:
                os.chown(p, u.pw_uid, u.pw_gid)
        except (KeyError, PermissionError, ImportError):
            pass

    def patterns(self, week: int) -> None:
        """Install the week variant's live patterns in the objects Tina uses (ara_patterns6), before the baseline is measured, so the state the gate measures
        is the state the week recorded. The unattached tool is live in every week; its definition is the private `unattached-tool.json`."""
        if self.ab is None:
            raise RuntimeError("patterns needs the Agent Builder client")
        import ara_patterns6 as PT
        held = self.root / "opt/ara/heldout" / self.track
        for name in PT.LIVE[week]:
            PT.install(name, self.ab, self.assets, self.agent, held)
        if "oversized_result" in PT.LIVE[week]:
            PT.inflate_bodies(self.es)

    def proposals_seed(self, ids: list[str], week: int, policy: int) -> None:
        """The week's two named proposals in cortex-eval-proposals, written by 'last week's evaluator' from the week's patterns: one grounded, one a trap
        (which is which varies with the variant; the roles go in the root-only `proposal-roles.json`, never in the index)."""
        import ara_patterns6 as PT
        key = json.loads(self._held_in("week-key.json").read_text())
        base = ""
        if self.ab is not None:   # week 1's grounded fix carries the whole policy_search description, without the sentence that makes her search twice
            base = ((self.ab.get_tool("cortex.policy_search") or {}).get("description") or "").replace(PT.DOUBLE, "").strip()
        docs, roles = PT.review_proposals(week, policy, key, base)
        assert [d["proposal_id"] for d in docs] == list(ids), "the plan names other proposals than the module writes"
        stamp = (self.now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self._bulk("cortex-eval-proposals", [{**d, "created_at": stamp} for d in docs], lambda d: d["proposal_id"])
        self._held("proposal-roles.json", roles)

    def handlers(self) -> dict[str, Callable]:
        return {n: getattr(self, n) for n in ("pack_load", "history_load", "change_log", "testset", "search_template",
                                               "baseline", "degraded", "seed", "files", "defect", "heldout", "policy_files", "fresh_round", "exceptions", "start_snapshot", "baseline_agg", "patterns", "proposals_seed")} | {"variant": self.variant_record}
