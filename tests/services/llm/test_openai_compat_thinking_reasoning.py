"""Mistral reasoning models send thinking as typed ``content`` blocks (#2791).

#2795 stopped the crash by extracting text blocks and skipping thinking.
These tests pin the follow-up: ``{"type": "thinking"}`` blocks surface as
reasoning -- the same channel ``reasoning_content`` uses on other providers --
on the non-streaming parse, the chunk aggregation and the live stream callback.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from deeptutor.services.llm.provider_core.openai_compat_provider import OpenAICompatProvider
from deeptutor.services.provider_registry import find_by_name


def _thinking(*texts: str) -> dict:
    return {
        "type": "thinking",
        "thinking": [{"type": "text", "text": text} for text in texts],
        "closed": True,
    }


def _chunk(content, finish_reason=None):
    delta = SimpleNamespace(content=content, tool_calls=None)
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=delta, finish_reason=finish_reason)],
        usage=None,
    )


def _response(message):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason="stop")], usage=None
    )


def test_parse_chunks_maps_thinking_blocks_to_reasoning() -> None:
    response = OpenAICompatProvider._parse_chunks(
        [
            _chunk([_thinking("hmm")]),
            _chunk([_thinking(" more")]),
            _chunk([{"type": "text", "text": "Hello"}]),
            _chunk("!", finish_reason="stop"),
        ]
    )

    assert response.content == "Hello!"
    assert response.reasoning_content == "hmm more"


def test_parse_chunks_thinking_only_turn_has_reasoning_and_no_content() -> None:
    response = OpenAICompatProvider._parse_chunks(
        [_chunk([_thinking("hmm")], finish_reason="stop")]
    )

    assert response.content is None
    assert response.reasoning_content == "hmm"


def test_parse_chunks_keeps_explicit_reasoning_field_in_arrival_order() -> None:
    delta = SimpleNamespace(content=None, tool_calls=None, reasoning_content="explicit")
    explicit = SimpleNamespace(
        choices=[SimpleNamespace(delta=delta, finish_reason=None)], usage=None
    )
    response = OpenAICompatProvider._parse_chunks(
        [explicit, _chunk([_thinking("hmm")]), _chunk("ok", finish_reason="stop")]
    )

    assert response.content == "ok"
    assert response.reasoning_content == "explicithmm"


def test_parse_non_streaming_maps_thinking_to_reasoning() -> None:
    message = SimpleNamespace(
        content=[_thinking("hmm"), {"type": "text", "text": "Answer"}], tool_calls=None
    )

    parsed = OpenAICompatProvider()._parse(_response(message))

    assert parsed.content == "Answer"
    assert parsed.reasoning_content == "hmm"


def test_parse_non_streaming_prefers_explicit_reasoning_field() -> None:
    message = SimpleNamespace(
        content=[_thinking("hmm"), {"type": "text", "text": "Answer"}],
        tool_calls=None,
        reasoning_content="explicit",
    )

    parsed = OpenAICompatProvider()._parse(_response(message))

    assert parsed.content == "Answer"
    assert parsed.reasoning_content == "explicit"


class _FakeStream:
    def __init__(self, chunks) -> None:
        self._chunks = list(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)

    async def close(self) -> None:
        pass


@pytest.mark.asyncio
async def test_live_stream_reports_thinking_as_reasoning(monkeypatch) -> None:
    provider = OpenAICompatProvider(
        api_key="test-key",
        api_base="https://api.mistral.ai/v1",
        default_model="mistral-large-4",
        spec=find_by_name("custom"),
        provider_name="custom",
        wire_api="chat_completions",
    )
    stream = _FakeStream(
        [
            _chunk([_thinking("hmm")]),
            _chunk([{"type": "text", "text": "Hello"}]),
            _chunk("!", finish_reason="stop"),
        ]
    )

    async def fake_create(_fn, _kwargs):
        return stream

    monkeypatch.setattr(provider, "_create_with_key_rotation", fake_create)

    reasoning: list[str] = []
    content: list[str] = []

    async def on_reasoning(text: str) -> None:
        reasoning.append(text)

    async def on_content(text: str) -> None:
        content.append(text)

    result = await provider.chat_stream(
        messages=[{"role": "user", "content": "hi"}],
        on_content_delta=on_content,
        on_reasoning_delta=on_reasoning,
    )

    assert reasoning == ["hmm"]
    assert content == ["Hello", "!"]
    assert result.content == "Hello!"
    assert result.reasoning_content == "hmm"
