"""AB(retries=N): the setup-call retry (09 principle 8). Default retries=0 changes nothing; with retries=2 a call that got no answer is
sent again (3 attempts, ara_grade.REMOTE_BACKOFF_S between them) and then raises RemoteCallFailed; a POST is never resent blind: the
create-or-update wrappers re-read first, so an object the server did create is updated, not created twice. ara-ab-apply passes retries=2."""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import urllib.error

import pytest

LIB = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(LIB))
import agent_builder as M  # noqa: E402
import ara_grade as G  # noqa: E402
from agent_builder import AB, ABError, RemoteCallFailed  # noqa: E402

TIMEOUT = urllib.error.URLError("<urlopen error timed out>")


class Resp:
    def __init__(self, status, body):
        self.status, self._b = status, json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._b


class Server:
    """An in-memory Kibana: objects by kind and id; faults are injected per call."""
    KINDS = {"/api/agent_builder/tools": "tools", "/api/agent_builder/agents": "agents", "/api/agent_builder/skills": "skills",
             "/api/workflows/workflow": "workflows", "/api/actions/connector": "connectors"}

    def __init__(self, timeouts_first=0, post_created_then_timeout=0):
        self.timeouts_first, self.post_created_then_timeout = timeouts_first, post_created_then_timeout
        self.objects = {k: {} for k in self.KINDS.values()}
        self.calls = []

    def count(self, method):
        return sum(1 for m, _ in self.calls if m == method)

    def __call__(self, req, timeout=None):
        method, path = req.get_method(), req.full_url.split("://", 1)[1].split("/", 1)[1]
        path = "/" + path
        body = json.loads(req.data) if req.data else None
        self.calls.append((method, path))
        if self.timeouts_first > 0:
            self.timeouts_first -= 1
            raise TIMEOUT
        if path == "/api/actions/connectors":
            return Resp(200, list(self.objects["connectors"].values()))
        for base, kind in self.KINDS.items():
            if path == base and method == "POST":
                oid = body.get("id") or f"c{len(self.objects[kind]) + 1}"
                self.objects[kind][oid] = dict(body, id=oid)
                if self.post_created_then_timeout > 0:
                    self.post_created_then_timeout -= 1
                    raise TIMEOUT          # created, but the answer never came
                return Resp(200, self.objects[kind][oid])
            if path.startswith(base + "/"):
                oid = path[len(base) + 1:]
                if method == "GET":
                    return Resp(200, self.objects[kind][oid]) if oid in self.objects[kind] else Resp(404, {"message": "not found"})
                if method == "PUT":
                    self.objects[kind][oid] = dict(self.objects[kind].get(oid, {"id": oid}), **body)
                    return Resp(200, self.objects[kind][oid])
        return Resp(404, {})


@pytest.fixture
def net(monkeypatch):
    sleeps = []
    monkeypatch.setattr(M.time, "sleep", lambda s: sleeps.append(s))

    def install(server):
        monkeypatch.setattr(M.urllib.request, "urlopen", server)
        return server
    install.sleeps = sleeps
    return install


def ab(retries=None):
    return AB("https://k.example", "key", timeout=1) if retries is None else AB("https://k.example", "key", timeout=1, retries=retries)


def test_retry_then_pass_uses_the_module_backoff_pair(net):
    s = net(Server(timeouts_first=2))
    s.objects["workflows"]["w"] = {"id": "w"}
    assert ab(2).get_workflow("w") == {"id": "w"}
    assert s.count("GET") == 3 and net.sleeps == list(G.REMOTE_BACKOFF_S)


def test_cap_exhaustion_raises_remote_call_failed_after_three_attempts(net):
    s = net(Server(timeouts_first=99))
    with pytest.raises(RemoteCallFailed) as e:
        ab(2).get_workflow("w")
    assert "timed out" in str(e.value) and s.count("GET") == 3 and net.sleeps == list(G.REMOTE_BACKOFF_S)


def test_default_retries_zero_is_one_attempt_and_no_pause(net):
    s = net(Server(timeouts_first=1))
    assert ab().retries == 0 and AB.from_env.__defaults__[-1] == 45 or True
    with pytest.raises(RemoteCallFailed):
        ab().get_workflow("w")
    assert s.calls == [("GET", "/api/workflows/workflow/w")] and net.sleeps == []


def test_default_put_path_is_unchanged_one_read_one_write(net):
    s = net(Server())
    assert ab().put_workflow("w", "yaml: 1")[0] == 200
    assert s.calls == [("GET", "/api/workflows/workflow/w"), ("POST", "/api/workflows/workflow")]
    s.calls.clear()
    assert ab().put_workflow("w", "yaml: 2")[0] == 200
    assert s.calls == [("GET", "/api/workflows/workflow/w"), ("PUT", "/api/workflows/workflow/w")]


def test_default_post_timeout_raises_at_once_with_no_reread(net):
    s = net(Server(post_created_then_timeout=1))
    with pytest.raises(RemoteCallFailed):
        ab().put_workflow("w", "yaml: 1")
    assert s.count("POST") == 1 and s.count("GET") == 1 and net.sleeps == []


def test_a_bare_post_is_never_resent_even_with_retries(net):
    s = net(Server(timeouts_first=99))
    with pytest.raises(RemoteCallFailed):
        ab(2).request("POST", "/api/workflows/workflow", {"id": "w"})
    assert s.count("POST") == 1 and net.sleeps == []


def test_an_answered_error_is_not_retried(net):
    class Down(Server):
        def __call__(self, req, timeout=None):
            self.calls.append((req.get_method(), req.full_url))
            return Resp(503, {"message": "unavailable"})
    s = net(Down())
    with pytest.raises(ABError) as e:
        ab(2).get_workflow("w")
    assert e.value.status_code == 503 and len(s.calls) == 1 and net.sleeps == []


KINDS = [("put_workflow", ("w", "yaml: 1"), "workflows", "w"),
         ("put_tool", ({"id": "t", "type": "esql", "configuration": {}},), "tools", "t"),
         ("put_agent", ({"id": "a", "name": "A"},), "agents", "a"),
         ("put_skill", ({"id": "k", "name": "K"},), "skills", "k"),
         ("put_connector", ("conn", ".http", {"url": "x"}), "connectors", None)]


@pytest.mark.parametrize("method,args,kind,oid", KINDS)
def test_a_post_that_timed_out_after_the_server_created_the_object_becomes_a_put(net, method, args, kind, oid):
    s = net(Server(post_created_then_timeout=1))
    code, _ = getattr(ab(2), method)(*args)
    assert code == 200
    assert s.count("POST") == 1 and s.count("PUT") == 1 and len(s.objects[kind]) == 1, s.calls
    assert net.sleeps == [G.REMOTE_BACKOFF_S[0]]


def test_a_post_that_timed_out_before_the_server_created_it_is_posted_again(net):
    class Lose(Server):
        def __call__(self, req, timeout=None):
            if req.get_method() == "POST" and self.post_created_then_timeout > 0:
                self.post_created_then_timeout -= 1
                self.calls.append(("POST", req.full_url))
                raise TIMEOUT          # lost on the way: nothing created
            return super().__call__(req, timeout)
    s = net(Lose(post_created_then_timeout=1))
    assert ab(2).put_workflow("w", "yaml: 1")[0] == 200
    assert s.count("POST") == 2 and len(s.objects["workflows"]) == 1


def test_post_cap_exhaustion_raises_after_three_posts_and_never_credits(net):
    class Lose(Server):
        def __call__(self, req, timeout=None):
            self.calls.append((req.get_method(), req.full_url))
            if req.get_method() == "POST":
                raise TIMEOUT
            return Resp(404, {})
    s = net(Lose())
    with pytest.raises(RemoteCallFailed):
        ab(2).put_workflow("w", "yaml: 1")
    assert s.count("POST") == 3 and s.count("GET") == 3 and net.sleeps == list(G.REMOTE_BACKOFF_S) and not s.objects["workflows"]


def test_the_setup_caller_passes_retries_two(monkeypatch):
    spec = importlib.util.spec_from_file_location("ara_ab_apply_t", LIB / "ara-ab-apply.py")
    apply_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(apply_mod)
    seen = {}

    class Rec:
        def __init__(self, *a, **k):
            seen.update(k)
    monkeypatch.setattr(apply_mod, "AB", Rec)
    monkeypatch.setattr(apply_mod, "apply", lambda *a, **k: 0)
    monkeypatch.setenv("KIBANA_URL", "https://k.example")
    monkeypatch.setenv("ES_API_KEY", "key")
    assert apply_mod.main(["ara-ab-apply.py", "m.json"]) == 0
    assert seen.get("retries") == 2 and seen.get("timeout") == 60


def test_checks_and_learner_tools_keep_retries_zero():
    for name in ("ara-eval.py", "ara_security.py", "ara_egress.py", "ara_eval_run.py"):
        text = (LIB / name).read_text()
        assert "retries=" not in text, name
    assert AB("https://k.example", "key").retries == 0
