"""Tests for hosted-endpoint model discovery and the deprecated call shims."""

from __future__ import annotations

import importlib
from types import TracebackType

from _pytest.monkeypatch import MonkeyPatch
import pytest

cloud_provider = importlib.import_module("deeptutor.services.llm.cloud_provider")


class _FakeResponse:
    def __init__(self, status: int, json_data: object) -> None:
        self.status = status
        self._json_data = json_data

    async def __aenter__(self):
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    async def json(self):
        return self._json_data


class _FakeSession:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response
        self.requests: list[tuple[str, dict[str, str]]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    def get(self, url: str, **kwargs: object) -> _FakeResponse:
        self.requests.append((url, dict(kwargs.get("headers") or {})))  # type: ignore[arg-type]
        return self._response


def _install_session(monkeypatch: MonkeyPatch, response: _FakeResponse) -> _FakeSession:
    session = _FakeSession(response)
    monkeypatch.setattr(cloud_provider.aiohttp, "ClientSession", lambda *a, **kw: session)
    return session


@pytest.mark.asyncio
async def test_cloud_fetch_models(monkeypatch: MonkeyPatch) -> None:
    """Fetch models should parse model lists from the response."""
    session = _install_session(
        monkeypatch, _FakeResponse(200, {"data": [{"id": "m1"}, {"id": "m2"}]})
    )

    models = await cloud_provider.fetch_models("https://api.openai.com/v1", "sk-test")

    assert models == ["m1", "m2"]
    url, headers = session.requests[0]
    assert url == "https://api.openai.com/v1/models"
    assert headers["Authorization"] == "Bearer sk-test"
    assert "Content-Type" not in headers


@pytest.mark.asyncio
async def test_cloud_fetch_models_anthropic_format_uses_anthropic_headers(
    monkeypatch: MonkeyPatch,
) -> None:
    """A custom endpoint speaking Anthropic Messages is listed with x-api-key."""
    session = _install_session(monkeypatch, _FakeResponse(200, {"data": [{"id": "claude"}]}))

    models = await cloud_provider.fetch_models(
        "https://relay.example/anthropic", "ak", binding="custom", api_format="anthropic"
    )

    assert models == ["claude"]
    _, headers = session.requests[0]
    assert headers["x-api-key"] == "ak"
    assert "Authorization" not in headers


@pytest.mark.asyncio
async def test_cloud_fetch_models_non_200_returns_empty(monkeypatch: MonkeyPatch) -> None:
    _install_session(monkeypatch, _FakeResponse(401, {"error": "nope"}))

    assert await cloud_provider.fetch_models("https://api.openai.com/v1", "bad") == []


def test_ssl_connector(monkeypatch: MonkeyPatch) -> None:
    """The aiohttp connector only appears when TLS verification is disabled."""
    monkeypatch.delenv("DISABLE_SSL_VERIFY", raising=False)
    assert cloud_provider._get_aiohttp_connector() is None

    class _FakeConnector:
        pass

    monkeypatch.setenv("DISABLE_SSL_VERIFY", "1")
    monkeypatch.setitem(cloud_provider.__dict__, "_ssl_warning_logged", False)
    monkeypatch.setattr(cloud_provider.aiohttp, "TCPConnector", lambda **_kw: _FakeConnector())
    assert cloud_provider._get_aiohttp_connector() is not None


@pytest.mark.asyncio
async def test_complete_shim_forwards_to_factory(monkeypatch: MonkeyPatch) -> None:
    """The retired aiohttp path now forwards to the one real LLM entry point."""
    from deeptutor.services.llm import factory

    captured: dict[str, object] = {}

    async def fake_complete(prompt: str, **kwargs: object) -> str:
        captured["prompt"] = prompt
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr(factory, "complete", fake_complete)
    with pytest.warns(DeprecationWarning):
        result = await cloud_provider.complete("hello", model="gpt-test", binding="openai")

    assert result == "ok"
    assert captured == {"prompt": "hello", "model": "gpt-test", "binding": "openai"}
