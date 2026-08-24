"""Tests for the Responses bridge on the aiohttp cloud provider path."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from types import TracebackType
from typing import Any

import pytest

from deeptutor.services.llm import reset_llm_client
from deeptutor.services.llm import cloud_provider
import deeptutor.core.agentic.responses_bridge as bridge_module


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
    def __init__(
        self,
        status: int,
        *,
        json_data: dict[str, Any] | None = None,
        lines: list[bytes] | None = None,
        text: str = "",
    ) -> None:
        self.status = status
        self._json_data = json_data or {}
        self.content = _AsyncIterator(lines or [])
        self._text = text

    async def __aenter__(self):
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    async def json(self) -> dict[str, Any]:
        return self._json_data

    async def text(self) -> str:
        return self._text


class _RoutingSession:
    """Returns distinct fake responses per endpoint and counts posts."""

    def __init__(self, responses: dict[str, _FakeResponse]) -> None:
        self._responses = responses
        self.posts: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    def post(self, url: str, **_kwargs: object) -> _FakeResponse:
        self.posts.append(url)
        for suffix, response in self._responses.items():
            if url.endswith(suffix):
                return response
        raise AssertionError(f"unexpected post url: {url}")


def _responses_sse() -> list[bytes]:
    return [
        b'data: {"type": "response.output_text.delta", "delta": "Hello"}\n\n',
        b'data: {"type": "response.output_text.delta", "delta": " via responses"}\n\n',
        b'data: {"type": "response.completed", "response": {"status": "completed", "usage": {"input_tokens": 10, "output_tokens": 3, "total_tokens": 13, "input_tokens_details": {"cached_tokens": 8}}}}\n\n',
        b"data: [DONE]\n\n",
    ]


def _chat_sse(text: str) -> list[bytes]:
    return [
        f'data: {{"choices": [{{"delta": {{"content": "{text}"}}, "finish_reason": null}}]}}\n\n'.encode(),
        b'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}\n\n',
        b"data: [DONE]\n\n",
    ]


def _install(
    monkeypatch: pytest.MonkeyPatch, session: _RoutingSession
) -> None:
    monkeypatch.setattr(
        cloud_provider.aiohttp,
        "ClientSession",
        lambda *args, **kwargs: session,
    )


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[None, None]:
    monkeypatch.delenv(bridge_module.ENV_USE_RESPONSES_API, raising=False)
    bridge_module.reset_bridge_breaker()
    reset_llm_client()
    yield
    bridge_module.reset_bridge_breaker()
    reset_llm_client()


@pytest.mark.asyncio
async def test_stream_via_responses(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _RoutingSession({"/responses": _FakeStreamResponseLike(200, _responses_sse())})
    _install(monkeypatch, session)

    chunks = [
        chunk
        async for chunk in cloud_provider.stream(
            prompt="hello",
            model="gpt-test",
            api_key="k",
            base_url="https://relay.example/v1",
            binding="custom",
        )
    ]

    assert "".join(chunks) == "Hello via responses"
    assert [url for url in session.posts if url.endswith("/responses")]
    assert not [url for url in session.posts if url.endswith("/chat/completions")]


@pytest.mark.asyncio
async def test_stream_falls_back_on_responses_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _RoutingSession(
        {
            "/responses": _FakeStreamResponseLike(404, [], text="no /responses here"),
            "/chat/completions": _FakeStreamResponseLike(200, _chat_sse("fallback")),
        }
    )
    _install(monkeypatch, session)

    chunks = [
        chunk
        async for chunk in cloud_provider.stream(
            prompt="hello",
            model="gpt-test",
            api_key="k",
            base_url="https://relay.example/v1",
            binding="custom",
        )
    ]

    assert "".join(chunks) == "fallback"
    assert any(url.endswith("/responses") for url in session.posts)
    assert any(url.endswith("/chat/completions") for url in session.posts)


@pytest.mark.asyncio
async def test_breaker_blocks_probes_after_two_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _RoutingSession(
        {
            "/responses": _FakeStreamResponseLike(404, [], text="nope"),
            "/chat/completions": _FakeStreamResponseLike(200, _chat_sse("ok")),
        }
    )
    _install(monkeypatch, session)

    async def _one_turn() -> None:
        async for _ in cloud_provider.stream(
            prompt="hello",
            model="gpt-test",
            api_key="k",
            base_url="https://relay.example/v1",
            binding="custom",
        ):
            pass

    await _one_turn()
    await _one_turn()
    responses_posts = sum(
        1 for url in session.posts if url.endswith("/responses")
    )
    assert responses_posts == 2

    await _one_turn()
    responses_posts = sum(
        1 for url in session.posts if url.endswith("/responses")
    )
    assert responses_posts == 2  # breaker: no further probing


@pytest.mark.asyncio
async def test_complete_via_responses(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _RoutingSession(
        {
            "/responses": _FakeResponse(
                200,
                json_data={
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {"type": "output_text", "text": "complete ok"}
                            ],
                        }
                    ],
                    "usage": {"input_tokens": 5, "output_tokens": 2},
                },
            )
        }
    )
    _install(monkeypatch, session)

    result = await cloud_provider.complete(
        prompt="hello",
        model="gpt-test",
        api_key="k",
        base_url="https://relay.example/v1",
        binding="custom",
    )

    assert result == "complete ok"
    assert any(url.endswith("/responses") for url in session.posts)


class _FakeStreamResponseLike(_FakeResponse):
    """Stream-flavoured response (kept name short for the tables above)."""

    def __init__(self, status: int, lines: list[bytes], text: str = "") -> None:
        super().__init__(status, lines=lines, text=text)
