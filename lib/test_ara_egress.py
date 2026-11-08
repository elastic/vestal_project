"""Offline tests for ara_egress.py: guard structure over the P2 guard forms (Phase 0 r2), the look-alike
pool, and leftover reach on an agent."""
from __future__ import annotations

import pathlib
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import ara_egress as E  # noqa: E402

PREFIX = "https://raw.githubusercontent.com/elastic/vestal_project/4caa7d19/ara-m4-pages/"
BASE = """version: "1"
name: cortex-read-page
inputs:
  - name: url
    type: string
steps:
{steps}
"""
HTTP = """    type: http
    connector-id: cortex-jina-reader
    with:
      method: GET
      path: "/{{ inputs.url }}"
"""


def doc(steps: str) -> dict:
    return yaml.safe_load(BASE.format(steps=steps))


def test_guarded_http_in_the_true_branch():
    d = doc("  - name: guard\n    type: if\n    condition: 'inputs.url: https\\://raw.githubusercontent.com/x*'\n    steps:\n"
            "      - name: read\n" + HTTP.replace("    ", "        ", 1).replace("\n    ", "\n        "))
    s = E.guard_shape(d)
    assert s["http"] == ["read"] and not s["unguarded"] and not s["other_target"] and s["guard"]


def test_http_after_or_beside_the_guard_is_unguarded():
    after = doc("  - name: guard\n    type: if\n    condition: 'inputs.url: x*'\n    steps: []\n  - name: read\n" + HTTP)
    assert E.guard_shape(after)["unguarded"] == ["read"]
    in_else = doc("  - name: guard\n    type: if\n    condition: 'inputs.url: x*'\n    steps: []\n    else:\n"
                  "      - name: read\n" + HTTP.replace("\n    ", "\n        ").replace("    type", "        type", 1))
    assert E.guard_shape(in_else)["unguarded"] == ["read"]
    other_cond = doc("  - name: guard\n    type: if\n    condition: 'true'\n    steps:\n      - name: read\n"
                     + HTTP.replace("\n    ", "\n        ").replace("    type", "        type", 1))
    assert E.guard_shape(other_cond)["unguarded"] == ["read"]


def test_target_from_another_value_is_flagged():
    d = doc("  - name: read\n    type: http\n    connector-id: c\n    with:\n      path: \"/{{ steps.x.output }}{{ inputs.url }}\"\n")
    assert E.guard_shape(d)["other_target"] == ["read"]


def test_look_alike_pool_has_every_form_and_none_starts_with_the_prefix():
    pool = E.look_alikes(PREFIX, "cortex-drop.example", "44-19385-6", "someone-else")
    assert {"host_suffix", "prefix_in_query", "other_owner", "other_path", "kql_quote_or"} <= set(pool)
    assert not any(u.startswith(PREFIX) for u in pool.values())
    assert pool["other_path"].startswith("https://raw.githubusercontent.com/elastic/vestal_project/")
    assert '" or url:*' in pool["kql_quote_or"]


def test_leftovers_and_transient_errors():
    assert E.leftovers({"configuration": {"tools": []}}) == []
    got = E.leftovers({"configuration": {"connector_ids": ["abc"],
                                         "approvals": {"auto_approved_apis": {"elasticsearch": ["indices.*"], "kibana": []}}}})
    assert len(got) == 2 and "indices.*" in got[1]
    assert E.leftovers({"configuration": {"approvals": {"auto_approved_apis": {"elasticsearch": []}}}}) == []
    assert E.transient("Request failed with status code 429") and E.transient("ETIMEDOUT timeout")
    assert not E.transient("Not Found")
