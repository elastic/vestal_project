"""Unit tests for ara_mcp_client.py (4.3): key ids, tool results, transcripts. Offline."""
from __future__ import annotations

import base64
import json
import os
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ara_mcp_client as M  # noqa: E402


def entry(kind: str, content) -> str:
    return json.dumps({"type": kind, "version": "2.1.296", "cwd": "/home/elastic/cortex-desk",
                       "message": {"role": kind, "content": content}})


class TestKeys(unittest.TestCase):
    def test_api_key_id(self):
        enc = base64.b64encode(b"abc123:secret").decode()
        self.assertEqual(M.api_key_id(f"ApiKey {enc}"), "abc123")
        self.assertEqual(M.api_key_id(f"ApiKey {enc.rstrip('=')}"), "abc123")
        self.assertIsNone(M.api_key_id(f"Bearer {enc}"))
        self.assertIsNone(M.api_key_id("ApiKey not-base64!"))
        self.assertIsNone(M.api_key_id(""))

    def test_underscore(self):
        self.assertEqual(M.underscore("cortex.open_case"), "cortex_open_case")


class TestResults(unittest.TestCase):
    def wrap(self, payload: dict) -> dict:
        return {"content": [{"type": "text", "text": json.dumps(payload)}]}

    def test_ok(self):
        self.assertIsNone(M.result_failed(self.wrap({"results": [{"type": "esql_results", "data": {}}]})))

    def test_is_error(self):
        self.assertTrue(M.result_failed({"isError": True, "content": []}))

    def test_workflow_failed_in_payload(self):
        # probe-43 M5: the result is not isError; the execution status says failed
        r = self.wrap({"results": [{"type": "other", "data": {"execution": {"status": "failed"}}}]})
        self.assertEqual(M.result_failed(r), "the workflow run failed")

    def test_error_result(self):
        self.assertTrue(M.result_failed(self.wrap({"results": [{"type": "error", "data": {}}]})))

    def test_mcp_error_is_outage(self):
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
        from ara_grade import is_outage
        self.assertTrue(is_outage(M.MCPError("tools/list: URLError")))
        self.assertTrue(is_outage(M.MCPError("tools/list: HTTP 502", 502)))


class TestTranscripts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = pathlib.Path(self.tmp.name)
        self.proj = self.home / ".claude" / "projects" / "-home-elastic-cortex-desk"
        self.proj.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name: str, lines: list[str]) -> pathlib.Path:
        p = self.proj / name
        p.write_text("\n".join(lines) + "\n")
        return p

    def test_repeated_ids_pair_in_order(self):
        # probe-43 r4: every tool_use id through the gateway was toolu_bdrk_0
        tu = lambda name, inp: entry("assistant", [{"type": "tool_use", "id": "toolu_bdrk_0", "name": name, "input": inp}])
        tr = lambda err: entry("user", [{"type": "tool_result", "tool_use_id": "toolu_bdrk_0", "is_error": err, "content": "x"}])
        p = self.write("s1.jsonl", [
            entry("user", "Find the layering candidates and open cases."),
            tu("mcp__cortex__cortex_securities_layering", {"lookback_days": 10}), tr(None),
            tu("mcp__cortex__cortex_open_case", {"account_id": "1594"}), tr(True),
            tu("Bash", {"command": "curl -X POST $ES_URL/cortex-fraud-cases/_doc"}), tr(None),
            "not json"])
        t = M.transcript_calls(p)
        self.assertEqual(t["version"], "2.1.296")
        self.assertEqual(t["user_turns"], 1)
        kinds = [(c["kind"], c["tool"], c["ok"]) for c in t["calls"]]
        self.assertEqual(kinds, [("mcp", "cortex_securities_layering", True), ("mcp", "cortex_open_case", False),
                                 ("shell", "Bash", True)])
        self.assertEqual(t["calls"][0]["server"], "cortex")

    def test_symlink_refused(self):
        real = self.write("real.jsonl", [entry("user", "hi")])
        link = self.proj / "link.jsonl"
        os.symlink(real, link)
        self.assertEqual([p.name for p in M.transcripts(str(self.home))], ["real.jsonl"])
        self.assertEqual(M.transcript_calls(link)["calls"], [])

    def test_since(self):
        p = self.write("old.jsonl", [entry("user", "hi")])
        os.utime(p, (1000, 1000))
        self.assertEqual(M.transcripts(str(self.home), since=2000), [])

    def test_read_learner_json(self):
        p = self.home / "x.json"
        p.write_text('{"a": 1}')
        self.assertEqual(M.read_learner_json(p), {"a": 1})
        link = self.home / "y.json"
        os.symlink(p, link)
        self.assertIsNone(M.read_learner_json(link))
        self.assertIsNone(M.read_learner_json(self.home / "missing.json"))


if __name__ == "__main__":
    unittest.main()
