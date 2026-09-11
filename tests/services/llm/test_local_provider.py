"""Tests for local-server model discovery and the deprecated call shims."""

from __future__ import annotations

from collections.abc import Callable
from types import TracebackType

from _pytest.monkeypatch import MonkeyPatch
import pytest

from deeptutor.services.llm import local_provider


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
    def __init__(self, route: Callable[[str], _FakeResponse]) -> None:
        self._route = route
        self.urls: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    def get(self, url: str, **_kwargs: object) -> _FakeResponse:
        self.urls.append(url)
        return self._route(url)


def _install(monkeypatch: MonkeyPatch, route: Callable[[str], _FakeResponse]) -> _FakeSession:
    session = _FakeSession(route)
    monkeypatch.setattr(local_provider.aiohttp, "ClientSession", lambda *a, **kw: session)
    return session


@pytest.mark.asyncio
async def test_ollama_models_come_from_api_tags(monkeypatch: MonkeyPatch) -> None:
    session = _install(
        monkeypatch,
        lambda url: (
            _FakeResponse(200, {"models": [{"name": "llama3"}, {"name": "qwen"}]})
            if url.endswith("/api/tags")
            else _FakeResponse(404, {})
        ),
    )

    models = await local_provider.fetch_models("http://localhost:11434/v1")

    assert models == ["llama3", "qwen"]
    assert session.urls == ["http://localhost:11434/api/tags"]


@pytest.mark.asyncio
async def test_openai_compatible_models_come_from_models_endpoint(
    monkeypatch: MonkeyPatch,
) -> None:
    session = _install(
        monkeypatch,
        lambda url: _FakeResponse(200, {"data": [{"id": "local-a"}, {"id": "local-b"}]}),
    )

    models = await local_provider.fetch_models("http://localhost:1234/v1")

    assert models == ["local-a", "local-b"]
    assert session.urls == ["http://localhost:1234/v1/models"]


@pytest.mark.asyncio
async def test_stream_shim_forwards_to_factory(monkeypatch: MonkeyPatch) -> None:
    from deeptutor.services.llm import factory

    async def fake_stream(prompt: str, **kwargs: object):
        yield f"{prompt}:{kwargs['model']}"

    monkeypatch.setattr(factory, "stream", fake_stream)
    with pytest.warns(DeprecationWarning):
        chunks = [
            chunk
            async for chunk in local_provider.stream(
                "hello", model="local-test", base_url="http://localhost:8000/v1"
            )
        ]

    assert chunks == ["hello:local-test"]
