"""
test_ara_capstone.py — tests for the 3.C harness's outage classification.

No LLM calls, no ES connection.
Run with: python -m pytest lib/test_ara_capstone.py -v
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import ara_capstone as H  # noqa: E402


class _Status(Exception):
    def __init__(self, status: int):
        super().__init__(f"HTTP {status}")
        self.status_code = status


def test_message_text_never_decides():
    assert not H.is_remote_error(ValueError("connection id missing; timeout; 503; unauthorized"))
    assert not H.is_remote_error(KeyError("rate limit"))


def test_harness_failure_is_an_outage():
    assert H.is_remote_error(H.RemoteUnavailable("search endpoint unreachable"))


def test_http_status():
    for status in (401, 403, 408, 429, 500, 502, 503, 504):
        assert H.is_remote_error(_Status(status)), status
    for status in (400, 404, 409, 422):
        assert not H.is_remote_error(_Status(status)), status


def test_failed_connection_is_an_outage_and_a_bare_timeout_is_not():
    assert H.is_remote_error(ConnectionRefusedError())
    assert H.is_remote_error(ConnectionResetError())
    assert not H.is_remote_error(TimeoutError("timed out"))


def test_wrapped_outage_stays_an_outage():
    try:
        try:
            raise H.RemoteUnavailable("rerank endpoint unreachable")
        except H.RemoteUnavailable as exc:
            raise ValueError("attribution failed") from exc
    except ValueError as wrapped:
        assert H.is_remote_error(wrapped)


def test_elasticsearch_errors():
    try:
        import elastic_transport as et
        import elasticsearch as es
    except ImportError:
        return
    assert H.is_remote_error(et.ConnectionError("refused"))
    assert not H.is_remote_error(et.ConnectionTimeout("slow"))

    def meta(status):
        return et.ApiResponseMeta(status=status, http_version="1.1", headers=et.HttpHeaders(),
                                  duration=0.0, node=None)
    assert H.is_remote_error(es.ApiError("unavailable", meta=meta(503), body={}))
    assert not H.is_remote_error(es.BadRequestError("bad body", meta=meta(400), body={}))


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
