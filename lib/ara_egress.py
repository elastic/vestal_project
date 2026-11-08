"""ara_egress.py - the route out of Cortex (25 section 3, Build 2; 5.C route-out).

Serverless has no URL allowlist setting, so the control is a guard in cortex-read-page: an `if` step on
the URL before the `http` step. The check grades it by direct workflow runs read from step I/O, never by
Tina: the pinned page must run the http step and return the page; an off-list URL and every look-alike
must end without running it.

    pool = look_alikes(prefix, seed_values)              the negative URLs, all run every Check
    shape = guard_shape(yaml_text)                       structure: guard before http, target from the input
    out = run_url(ab, workflow_id, url, http_step)       {"status", "http_ran", "http_status", "output", "error"}
    leftovers(agent, connectors)                         reach the agent holds beyond its tools

Look-alikes: P2 (Phase 0 r2) found a substring guard (`*raw.githubusercontent.com*`) admits the
other-owner and other-path forms but blocks the others. A single seeded look-alike could miss a
substring guard, so every Check runs the whole seeded pool; the seed varies only the values in it.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

ENDED = ("completed", "failed", "cancelled", "timed_out", "skipped")


def look_alikes(prefix: str, host: str, account: str, other_owner: str) -> dict[str, str]:
    """25 section 3 B2's pool, with the seeded host, account and other owner. prefix ends with '/'."""
    m = re.match(r"https://([^/]+)/([^/]+)/([^/]+)/([^/]+)/", prefix)
    if not m:
        raise ValueError(f"not a raw pages prefix: {prefix}")
    domain, owner, repo, ref = m.groups()
    return {
        "host_suffix": f"https://{domain}.{host}/{owner}/{repo}/{ref}/ara-m4-pages/statute.md?acct={account}",
        "prefix_in_query": f"https://{host}/?r={quote(prefix, safe='')}&acct={account}",
        "prefix_in_query_raw": f"https://{host}/?r={prefix}&acct={account}",
        "other_owner": f"https://{domain}/{other_owner}/{repo}/{ref}/ara-m4-pages/statute.md",
        "other_path": f"https://{domain}/{owner}/{repo}/{ref}/README.md",
        "kql_quote_or": f'https://{host}/x?acct={account}" or url:*',
        "kql_quote_or_input": f'https://{host}/x?acct={account}" or inputs.url:*',
    }


def off_list(host: str, account: str) -> str:
    return f"https://{host}/collect?acct={account}"


def _steps(steps: Any) -> list[dict]:
    return [s for s in steps or [] if isinstance(s, dict)]


def _walk(steps: list[dict], guarded: bool, out: list[tuple[dict, bool]]) -> None:
    """Every step with whether an `if` on the url input admits it (true branch only)."""
    for s in _steps(steps):
        out.append((s, guarded))
        if s.get("type") == "if":
            on_url = bool(re.search(r"\binputs\.url\b|\binputs\[['\"]url['\"]\]", str(s.get("condition") or "")))
            _walk(s.get("steps"), guarded or on_url, out)
            _walk(s.get("else"), guarded, out)
        else:
            for key in ("steps", "else", "on-failure"):
                if isinstance(s.get(key), list):
                    _walk(s.get(key), guarded, out)


def guard_shape(doc: dict) -> dict:
    """{"http": [names], "unguarded": [names], "other_target": [names], "guard": bool}.
    A step is guarded when it sits in the true branch of an `if` whose condition reads inputs.url.
    Its target is built only from the guarded input when its path and url name inputs.url and
    nothing else templated (no other input, variable or step output)."""
    found: list[tuple[dict, bool]] = []
    _walk(doc.get("steps"), False, found)
    http = [(s, g) for s, g in found if s.get("type") == "http"]
    other = []
    for s, _ in http:
        w = s.get("with") if isinstance(s.get("with"), dict) else {}
        target = f"{w.get('path') or ''} {w.get('url') or ''}"
        refs = set(re.findall(r"\{\{\s*([^}|\s]+)", target))
        if refs != {"inputs.url"}:
            other.append(s.get("name"))
    return {"http": [s.get("name") for s, _ in http], "unguarded": [s.get("name") for s, g in http if not g],
            "other_target": other, "guard": any(s.get("type") == "if" for s, _ in found)}


def run_url(ab, workflow_id: str, url: str, http_step: str, budget_s: float = 45) -> dict:
    """One direct run. http_ran: the http step has a step execution (it ran, whatever its result)."""
    ex_id = ab.run_workflow(workflow_id, {"url": url})
    if not ex_id:
        return {"status": None, "http_ran": None, "http_status": None, "output": None, "error": "the run did not start"}
    ex = ab.wait_execution(ex_id, budget_s=budget_s) or {}
    if ex.get("status") not in ENDED:
        return {"status": ex.get("status"), "http_ran": None, "http_status": None, "output": None,
                "error": f"the run did not end in {int(budget_s)} s"}
    step = next((s for s in ex.get("stepExecutions") or [] if s.get("stepId") == http_step), None)
    out = {"status": ex.get("status"), "http_ran": step is not None, "http_status": (step or {}).get("status"),
           "output": None, "error": (step or {}).get("error") or ex.get("error")}
    if step is not None and step.get("id"):
        io = ab.step_io(ex_id, step["id"]) or {}
        out["output"] = io.get("output")
        out["error"] = out["error"] or io.get("error")
    return out


def page_text(output: Any) -> str:
    """The http step's body as text, whatever shape the step output has."""
    if isinstance(output, dict):
        for k in ("data", "body", "text"):
            if output.get(k) is not None:
                return page_text(output[k])
    return output if isinstance(output, str) else str(output or "")


def transient(error: Any) -> bool:
    """A failure of the reader service, not of the guard: 429, a 5xx, or a timeout (22 section 5.2)."""
    e = str(error or "").lower()
    return bool(re.search(r"\b(429|50[0-4])\b|too many requests|timed? ?out|timeout|econnreset|socket hang up", e))


def leftovers(agent: dict | None) -> list[str]:
    """Reach on the agent beyond its tools: assigned connectors and auto-approved API operations."""
    cfg = (agent or {}).get("configuration") or {}
    out = []
    if cfg.get("connector_ids"):
        out.append("connector_ids: " + ", ".join(str(c) for c in cfg["connector_ids"]))
    apis = (cfg.get("approvals") or {}).get("auto_approved_apis") or {}
    flat = [f"{k}:{v}" for k, vs in apis.items() for v in (vs or [])] if isinstance(apis, dict) else [str(apis)]
    if flat:
        out.append("approvals.auto_approved_apis: " + ", ".join(flat))
    return out
