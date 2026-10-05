"""lark-oapi sync calls must reuse connections instead of reconnecting per call."""

from __future__ import annotations

import threading

import pytest

from deeptutor.partners.channels import lark_http


@pytest.fixture(autouse=True)
def _restore_transport():
    """Leave the SDK transport as we found it after each test."""
    lark_oapi_transport = pytest.importorskip("lark_oapi.core.http.transport")
    original = lark_oapi_transport.requests
    original_installed = lark_http._INSTALLED
    yield
    lark_oapi_transport.requests = original
    lark_http._INSTALLED = original_installed


def test_install_routes_the_sdk_transport_through_the_shim() -> None:
    lark_oapi_transport = pytest.importorskip("lark_oapi.core.http.transport")
    lark_http._INSTALLED = False

    assert lark_http.install_keep_alive() is True

    shim = lark_oapi_transport.requests
    assert isinstance(shim, lark_http._KeepAliveRequests)
    # Idempotent: a second call keeps the same shim (and its warm sessions).
    assert lark_http.install_keep_alive() is True
    assert lark_oapi_transport.requests is shim
    # Non-request attributes still resolve against the real requests module.
    import requests

    assert shim.exceptions is requests.exceptions


def test_shim_reuses_one_session_per_thread(monkeypatch) -> None:
    pytest.importorskip("lark_oapi")
    calls: list[tuple[str, str]] = []

    class FakeSession:
        def request(self, method: str, url: str, **kwargs: object) -> str:
            calls.append((method, url))
            return "response"

    sessions: list[FakeSession] = []

    def fake_session() -> FakeSession:
        session = FakeSession()
        sessions.append(session)
        return session

    monkeypatch.setattr(lark_http.requests, "Session", fake_session)
    monkeypatch.setattr(lark_http._SESSIONS, "session", None, raising=False)

    shim = lark_http._KeepAliveRequests()
    assert shim.request("POST", "https://open.feishu.cn/a") == "response"
    assert shim.request("POST", "https://open.feishu.cn/b") == "response"

    assert calls == [
        ("POST", "https://open.feishu.cn/a"),
        ("POST", "https://open.feishu.cn/b"),
    ]
    main_session = lark_http._session()
    assert len(sessions) == 1, "one keep-alive session per thread"
    assert sessions[0] is main_session

    seen: list[object] = []

    def worker() -> None:
        seen.append(lark_http._session())

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()

    assert len(seen) == 1, "the worker thread builds its own session"
    assert seen[0] is not main_session
