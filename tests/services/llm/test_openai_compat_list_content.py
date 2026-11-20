"""Providers such as Mistral reasoning models send ``content`` as a list of blocks."""

from __future__ import annotations

from types import SimpleNamespace

from deeptutor.services.llm.provider_core.openai_compat_provider import OpenAICompatProvider

THINKING = {"type": "thinking", "thinking": [{"type": "text", "text": "hmm"}]}


def _chunk(content, finish_reason=None):
    delta = SimpleNamespace(content=content, tool_calls=None)
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=delta, finish_reason=finish_reason)],
        usage=None,
    )


def test_parse_chunks_joins_text_blocks_and_skips_thinking_blocks() -> None:
    response = OpenAICompatProvider._parse_chunks(
        [
            _chunk([THINKING]),
            _chunk([{"type": "text", "text": "Hello"}]),
            _chunk([SimpleNamespace(type="text", text=", world")]),
            _chunk("!", finish_reason="stop"),
        ]
    )

    assert response.content == "Hello, world!"


def test_parse_non_streaming_message_with_list_content() -> None:
    message = SimpleNamespace(
        content=[THINKING, {"type": "text", "text": "Answer"}], tool_calls=None
    )
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason="stop")], usage=None
    )

    assert OpenAICompatProvider()._parse(response).content == "Answer"
