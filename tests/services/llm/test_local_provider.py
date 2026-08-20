"""Tests for the local LLM provider."""

from __future__ import annotations

import json
from types import TracebackType

from _pytest.monkeypatch import MonkeyPatch
import pytest

from deeptutor.services.llm import local_provider


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


class _FakeStreamResponse:
    status = 200

    def __init__(self, lines: list[bytes]) -> None:
        self.content = _AsyncIterator(lines)

    async def __aenter__(self):
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None


class _FakeSession:
    def __init__(self, response: _FakeStreamResponse) -> None:
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

    def post(self, _url: str, **_kwargs: object) -> _FakeStreamResponse:
        return self._response


def _json_line(content: str) -> bytes:
    payload = {"choices": [{"delta": {"content": content}}]}
    return json.dumps(payload).encode() + b"\n"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("chunks", "expected"),
    [
        (["before <think>hidden</think>after"], "before after"),
        (["before <think>hidden</thi", "nk>after"], "before after"),
        (["before <think>hidden"], "before "),
    ],
)
async def test_non_sse_stream_filters_thinking_blocks(
    monkeypatch: MonkeyPatch,
    chunks: list[str],
    expected: str,
) -> None:
    """Non-SSE JSON streams should never expose model reasoning tags."""
    fake_response = _FakeStreamResponse([_json_line(chunk) for chunk in chunks])
    monkeypatch.setattr(
        local_provider.aiohttp,
        "ClientSession",
        lambda *args, **kwargs: _FakeSession(fake_response),
    )

    visible = [
        chunk
        async for chunk in local_provider.stream(
            prompt="hello",
            model="local-test",
            base_url="http://localhost:8000/v1",
        )
    ]

    assert "".join(visible) == expected


@pytest.mark.asyncio
async def test_sse_stream_uses_the_same_thinking_filter(
    monkeypatch: MonkeyPatch,
) -> None:
    """The shared parser should preserve the existing SSE filtering behavior."""
    lines = [
        b'data: {"choices": [{"delta": {"content": "before <think>hidden"}}]}\n',
        b'data: {"choices": [{"delta": {"content": "</think>after"}}]}\n',
        b"data: [DONE]\n",
    ]
    fake_response = _FakeStreamResponse(lines)
    monkeypatch.setattr(
        local_provider.aiohttp,
        "ClientSession",
        lambda *args, **kwargs: _FakeSession(fake_response),
    )

    visible = [
        chunk
        async for chunk in local_provider.stream(
            prompt="hello",
            model="local-test",
            base_url="http://localhost:8000/v1",
        )
    ]

    assert "".join(visible) == "before after"
