"""Dispatcher tests for ``fetch_url_as_markdown``'s pluggable backend.

Every remote provider is a stub registered through monkeypatched
``get_fetch_provider``; every local HTTP client is a stub factory. No
test performs network I/O or uses real credentials.
"""

from __future__ import annotations

from typing import Any

import pytest

from deeptutor.services.fetch.base import FetchProviderError
from deeptutor.tools.web_fetch import FetchOutcome, fetch_url_as_markdown

_ALLOW_ALL = lambda host: False  # noqa: E731 — single-use stub
_ALLOW_ALL.__doc__ = "Treat every host as public; the response is pinned by a stub."


# ---------------------------------------------------------------------------
# Local-path stubs (same shape as tests/tools/test_web_fetch.py)
# ---------------------------------------------------------------------------


class _StubLocalResponse:
    def __init__(self, body: bytes = b"<html><title>L</title><body><p>local</p></body></html>"):
        self._body = body
        self.status_code = 200
        self.url = "https://example.com/p"
        self.headers = {"content-type": "text/html; charset=utf-8"}

    async def aiter_bytes(self):
        yield self._body


class _StubLocalClient:
    def __init__(self, response: _StubLocalResponse) -> None:
        self._response = response
        self.requests: list[tuple[str, str, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def stream(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        outer = self

        class _Ctx:
            async def __aenter__(self):
                return outer._response

            async def __aexit__(self, *exc):
                return False

        return _Ctx()


# ---------------------------------------------------------------------------
# Remote-provider stub
# ---------------------------------------------------------------------------


class _StubRemoteProvider:
    """Records calls; returns ``outcome`` or raises ``error``."""

    name = "stub-remote"
    description = ""

    def __init__(self, outcome: FetchOutcome | None = None, error: Exception | None = None):
        self.outcome = outcome
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def fetch(self, url: str, **kwargs: Any) -> FetchOutcome:
        self.calls.append({"url": url, **kwargs})
        if self.error is not None:
            raise self.error
        assert self.outcome is not None
        return self.outcome


def _mount_provider(monkeypatch, provider: _StubRemoteProvider) -> None:
    def _fake_get(name: str, **_kwargs: Any) -> _StubRemoteProvider:
        assert name == "deepseek"
        return provider

    monkeypatch.setattr("deeptutor.services.fetch.get_fetch_provider", _fake_get)


@pytest.fixture(autouse=True)
def _clean_backend_env(monkeypatch):
    monkeypatch.delenv("DEEPTUTOR_FETCH_BACKEND", raising=False)


# ---------------------------------------------------------------------------
# SSRF gate: always in front of any remote backend
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_remote_backend_never_sees_a_private_host(monkeypatch) -> None:
    provider = _StubRemoteProvider(
        outcome=FetchOutcome(ok=True, markdown="should not happen", url="http://127.0.0.1/x")
    )
    _mount_provider(monkeypatch, provider)

    outcome = await fetch_url_as_markdown("http://127.0.0.1/x", backend="deepseek")

    assert outcome.ok is False
    assert "Refusing to fetch private/loopback host" in outcome.error
    assert provider.calls == []  # gated before the backend is contacted


@pytest.mark.asyncio
async def test_remote_backend_blocked_for_private_hostname_via_dns(monkeypatch) -> None:
    provider = _StubRemoteProvider()
    _mount_provider(monkeypatch, provider)

    outcome = await fetch_url_as_markdown(
        "https://intranet.internal/x", backend="deepseek", host_validator=lambda host: True
    )

    assert outcome.ok is False
    assert provider.calls == []


# ---------------------------------------------------------------------------
# Dispatch + fallback semantics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_remote_success_uses_backend_markdown_and_requested_url(monkeypatch) -> None:
    provider = _StubRemoteProvider(
        outcome=FetchOutcome(ok=True, markdown="# Page\n\nbody", url="", title="Page")
    )
    _mount_provider(monkeypatch, provider)

    outcome = await fetch_url_as_markdown(
        "https://example.com/js-heavy",
        backend="deepseek",
        host_validator=_ALLOW_ALL,
    )

    assert outcome.ok is True
    assert outcome.markdown == "# Page\n\nbody"
    assert outcome.title == "Page"
    assert outcome.url == "https://example.com/js-heavy"
    assert provider.calls[0]["max_chars"] == 50_000


@pytest.mark.asyncio
async def test_remote_markdown_is_truncated_to_max_chars(monkeypatch) -> None:
    provider = _StubRemoteProvider(
        outcome=FetchOutcome(ok=True, markdown="a" * 5_000, url="", title="")
    )
    _mount_provider(monkeypatch, provider)

    outcome = await fetch_url_as_markdown(
        "https://example.com/big", max_chars=200, backend="deepseek", host_validator=_ALLOW_ALL
    )

    assert outcome.ok is True
    assert outcome.truncated is True
    assert outcome.markdown.endswith("…[truncated]")
    assert len(outcome.markdown) <= 220


@pytest.mark.asyncio
async def test_retryable_backend_error_falls_back_to_local_extraction(monkeypatch) -> None:
    provider = _StubRemoteProvider(
        error=FetchProviderError("HTTP 429 from DeepSeek Fetch.", retryable=True)
    )
    _mount_provider(monkeypatch, provider)
    local_client = _StubLocalClient(_StubLocalResponse())

    outcome = await fetch_url_as_markdown(
        "https://example.com/p",
        backend="deepseek",
        host_validator=_ALLOW_ALL,
        client_factory=lambda **_kwargs: local_client,
    )

    assert outcome.ok is True
    assert "local" in outcome.markdown
    assert provider.calls  # remote was tried first
    assert local_client.requests  # local served the fallback


@pytest.mark.asyncio
async def test_backend_network_gap_without_key_falls_back_to_local(monkeypatch) -> None:
    provider = _StubRemoteProvider(
        error=FetchProviderError("DeepSeek Fetch selected but no API key", retryable=True)
    )
    _mount_provider(monkeypatch, provider)
    local_client = _StubLocalClient(_StubLocalResponse())

    outcome = await fetch_url_as_markdown(
        "https://example.com/p",
        backend="deepseek",
        host_validator=_ALLOW_ALL,
        client_factory=lambda **_kwargs: local_client,
    )

    assert outcome.ok is True


@pytest.mark.asyncio
async def test_hard_backend_error_does_not_fall_back_to_local(monkeypatch) -> None:
    provider = _StubRemoteProvider(
        error=FetchProviderError("refuses this request shape", retryable=False)
    )
    _mount_provider(monkeypatch, provider)
    local_client = _StubLocalClient(_StubLocalResponse())

    outcome = await fetch_url_as_markdown(
        "https://example.com/p",
        backend="deepseek",
        host_validator=_ALLOW_ALL,
        client_factory=lambda **_kwargs: local_client,
    )

    assert outcome.ok is False
    assert "refuses this request shape" in outcome.error
    assert local_client.requests == []


@pytest.mark.asyncio
async def test_backend_hard_http_outcome_is_returned_as_is(monkeypatch) -> None:
    provider = _StubRemoteProvider(
        outcome=FetchOutcome(
            ok=False,
            url="https://example.com/p",
            error="HTTP 404 from DeepSeek Fetch for https://example.com/p.",
        )
    )
    _mount_provider(monkeypatch, provider)
    local_client = _StubLocalClient(_StubLocalResponse())

    outcome = await fetch_url_as_markdown(
        "https://example.com/p",
        backend="deepseek",
        host_validator=_ALLOW_ALL,
        client_factory=lambda **_kwargs: local_client,
    )

    assert outcome.ok is False
    assert "404" in outcome.error
    assert local_client.requests == []


@pytest.mark.asyncio
async def test_backend_empty_markdown_is_a_hard_failure(monkeypatch) -> None:
    provider = _StubRemoteProvider(outcome=FetchOutcome(ok=True, markdown="   ", url="", title="t"))
    _mount_provider(monkeypatch, provider)
    local_client = _StubLocalClient(_StubLocalResponse())

    outcome = await fetch_url_as_markdown(
        "https://example.com/p",
        backend="deepseek",
        host_validator=_ALLOW_ALL,
        client_factory=lambda **_kwargs: local_client,
    )

    assert outcome.ok is False
    assert "no content" in outcome.error
    assert local_client.requests == []


@pytest.mark.asyncio
async def test_crashing_backend_adapter_falls_back_to_local(monkeypatch) -> None:
    provider = _StubRemoteProvider(error=RuntimeError("adapter bug"))
    _mount_provider(monkeypatch, provider)
    local_client = _StubLocalClient(_StubLocalResponse())

    outcome = await fetch_url_as_markdown(
        "https://example.com/p",
        backend="deepseek",
        host_validator=_ALLOW_ALL,
        client_factory=lambda **_kwargs: local_client,
    )

    assert outcome.ok is True
    assert "local" in outcome.markdown


@pytest.mark.asyncio
async def test_unknown_explicit_backend_is_a_hard_error(monkeypatch) -> None:
    outcome = await fetch_url_as_markdown("https://example.com/p", backend="tarball")

    assert outcome.ok is False
    assert "Unknown fetch backend" in outcome.error
    assert "local" in outcome.error and "deepseek" in outcome.error


# ---------------------------------------------------------------------------
# Default resolution: None follows env; explicit local always wins
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_backend_none_uses_the_deployed_default(monkeypatch) -> None:
    provider = _StubRemoteProvider(
        outcome=FetchOutcome(ok=True, markdown="via default", url="", title="")
    )
    _mount_provider(monkeypatch, provider)
    monkeypatch.setenv("DEEPTUTOR_FETCH_BACKEND", "deepseek")

    outcome = await fetch_url_as_markdown("https://example.com/p", host_validator=_ALLOW_ALL)

    assert outcome.ok is True
    assert outcome.markdown == "via default"
    assert provider.calls


@pytest.mark.asyncio
async def test_explicit_local_overrides_a_remote_default(monkeypatch) -> None:
    provider = _StubRemoteProvider(error=AssertionError("remote backend must not be contacted"))
    _mount_provider(monkeypatch, provider)
    monkeypatch.setenv("DEEPTUTOR_FETCH_BACKEND", "deepseek")
    local_client = _StubLocalClient(_StubLocalResponse())

    outcome = await fetch_url_as_markdown(
        "https://example.com/p",
        backend="local",
        host_validator=_ALLOW_ALL,
        client_factory=lambda **_kwargs: local_client,
    )

    assert outcome.ok is True
    assert "local" in outcome.markdown
    assert provider.calls == []


@pytest.mark.asyncio
async def test_invalid_env_default_keeps_the_local_path(monkeypatch) -> None:
    provider = _StubRemoteProvider(error=AssertionError("remote backend must not be contacted"))
    _mount_provider(monkeypatch, provider)
    monkeypatch.setenv("DEEPTUTOR_FETCH_BACKEND", "tarball")
    local_client = _StubLocalClient(_StubLocalResponse())

    outcome = await fetch_url_as_markdown(
        "https://example.com/p", host_validator=_ALLOW_ALL, client_factory=lambda **_k: local_client
    )

    assert outcome.ok is True
    assert provider.calls == []
