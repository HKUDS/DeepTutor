"""Tests for cloud provider helpers."""

from __future__ import annotations

import importlib
from types import TracebackType

from _pytest.monkeypatch import MonkeyPatch
import pytest

from src.services.llm.exceptions import LLMAPIError

cloud_provider = importlib.import_module("src.services.llm.cloud_provider")


class _AsyncIterator:
    def __init__(self, items: list[bytes]) -> None:
        self._items = items
        self._index = 0

    def __aiter__(self):
        return self

    async def __anext__(self) -> bytes:
        if self._index >= len(self._items):
            raise StopAsyncIteration
        item = self._items[self._index]
        self._index += 1
        return item


class _FakeResponse:
    def __init__(self, status: int, json_data: dict[str, object]) -> None:
        self.status = status
        self._json_data = json_data
        self.content = _AsyncIterator([])

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

    async def text(self) -> str:
        return ""


class _FakeStreamResponse(_FakeResponse):
    def __init__(self, status: int, lines: list[bytes]) -> None:
        super().__init__(status, {})
        self.content = _AsyncIterator(lines)


class _FakeSession:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    def post(self, _url: str, **_kwargs: object) -> _FakeResponse:
        return self._response

    def get(self, _url: str, **_kwargs: object) -> _FakeResponse:
        return self._response


@pytest.mark.asyncio
async def test_cloud_complete_fallback(monkeypatch: MonkeyPatch) -> None:
    """Fallback path should parse JSON content from aiohttp responses."""
    fake_response = _FakeResponse(
        200,
        {
            "choices": [
                {"message": {"content": "ok"}},
            ]
        },
    )

    async def _no_cache(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(cloud_provider, "_get_openai_complete_if_cache", lambda: _no_cache)
    monkeypatch.setattr(
        cloud_provider.aiohttp,
        "ClientSession",
        lambda *args, **kwargs: _FakeSession(fake_response),
    )

    result = await cloud_provider.complete(
        prompt="hello",
        model="gpt-test",
        api_key="",
        base_url="https://api.openai.com/v1",
        binding="openai",
    )

    assert result == "ok"


@pytest.mark.asyncio
async def test_cloud_stream_yields_chunks(monkeypatch: MonkeyPatch) -> None:
    """Streaming should yield delta content from SSE lines."""
    lines = [
        b'data: {"choices": [{"delta": {"content": "hi"}}]}\n\n',
        b"data: [DONE]\n\n",
    ]
    fake_response = _FakeStreamResponse(200, lines)

    monkeypatch.setattr(
        cloud_provider.aiohttp,
        "ClientSession",
        lambda *args, **kwargs: _FakeSession(fake_response),
    )

    chunks = []
    async for chunk in cloud_provider.stream(
        prompt="hello",
        model="gpt-test",
        api_key="",
        base_url="https://api.openai.com/v1",
        binding="openai",
    ):
        chunks.append(chunk)

    assert "".join(chunks) == "hi"


@pytest.mark.asyncio
async def test_cloud_complete_error(monkeypatch: MonkeyPatch) -> None:
    """Non-200 responses should raise LLMAPIError."""
    response = _FakeResponse(500, {})

    async def _no_cache(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(cloud_provider, "_get_openai_complete_if_cache", lambda: _no_cache)
    monkeypatch.setattr(
        cloud_provider.aiohttp,
        "ClientSession",
        lambda *args, **kwargs: _FakeSession(response),
    )

    with pytest.raises(LLMAPIError):
        await cloud_provider.complete(
            prompt="hello",
            model="gpt-test",
            api_key="",
            base_url="https://api.openai.com/v1",
            binding="openai",
        )


@pytest.mark.asyncio
async def test_cloud_complete_cached(monkeypatch: MonkeyPatch) -> None:
    """Cache hit should return cached content without fallback calls."""

    async def _cached(*_args: object, **_kwargs: object) -> str:
        return "cached"

    monkeypatch.setattr(cloud_provider, "_get_openai_complete_if_cache", lambda: _cached)

    result = await cloud_provider.complete(
        prompt="hello",
        model="gpt-test",
        api_key="",
        base_url="https://api.openai.com/v1",
        binding="openai",
    )

    assert result == "cached"


def test_cloud_helpers(monkeypatch: MonkeyPatch) -> None:
    """Helper coercion and SSL connector paths should behave as expected."""
    assert cloud_provider._coerce_float(True, 0.5) == 0.5
    assert cloud_provider._coerce_float(2, 0.5) == 2.0
    assert cloud_provider._coerce_int(True, None) is None
    assert cloud_provider._coerce_int(3, None) == 3

    monkeypatch.delenv("DISABLE_SSL_VERIFY", raising=False)
    assert cloud_provider._get_aiohttp_connector() is None

    class _FakeConnector:
        pass

    monkeypatch.setenv("DISABLE_SSL_VERIFY", "1")
    monkeypatch.setitem(cloud_provider.__dict__, "_ssl_warning_logged", False)
    monkeypatch.setattr(cloud_provider.aiohttp, "TCPConnector", lambda **_kw: _FakeConnector())
    connector = cloud_provider._get_aiohttp_connector()
    assert connector is not None


@pytest.mark.asyncio
async def test_cloud_fetch_models(monkeypatch: MonkeyPatch) -> None:
    """Fetch models should parse model lists from the response."""
    response = _FakeResponse(200, {"data": [{"id": "m1"}, {"id": "m2"}]})
    monkeypatch.setattr(
        cloud_provider.aiohttp,
        "ClientSession",
        lambda *args, **kwargs: _FakeSession(response),
    )

    models = await cloud_provider.fetch_models("https://api.openai.com/v1")

    assert models == ["m1", "m2"]
