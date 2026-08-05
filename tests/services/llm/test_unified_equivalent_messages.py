"""Equivalent internal message semantics across the three protocols.

The same provider-neutral conversation must convert to each provider's wire
shape without losing the semantic system/user/assistant/tool conversation, and
tool-call/tool-result identity must survive the round trip.
"""

from __future__ import annotations

from deeptutor.services.llm.provider_core.unified import (
    build_anthropic_request,
    build_chat_completions_request,
    build_responses_request,
    parse_anthropic_response,
    parse_chat_completions_response,
    parse_responses_response,
)
from deeptutor.services.llm.provider_core.unified.common import normalize_messages
from deeptutor.services.llm.provider_core.unified.types import UnifiedRequest

from . import unified_fixtures as fx

MODEL = "gpt-5.6"


def _request() -> UnifiedRequest:
    return UnifiedRequest(
        messages=normalize_messages(fx.LEGACY_MESSAGES),
        tools=[
            {
                "name": "get_weather",
                "description": "Get the weather",
                "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
            }
        ],
        model=MODEL,
        max_tokens=256,
        temperature=0.0,
    )


class TestSemanticEquivalence:
    def test_system_survives_every_protocol(self) -> None:
        chat = build_chat_completions_request(_request())
        responses = build_responses_request(_request())
        anthropic = build_anthropic_request(_request())

        chat_system = next(m for m in chat["messages"] if m["role"] == "system")
        assert chat_system["content"] == "You are a helpful assistant."
        assert responses["instructions"] == "You are a helpful assistant."
        assert anthropic["system"] == "You are a helpful assistant."

    def test_user_text_survives_every_protocol(self) -> None:
        chat = build_chat_completions_request(_request())
        responses = build_responses_request(_request())
        anthropic = build_anthropic_request(_request())

        chat_user = next(m for m in chat["messages"] if m["role"] == "user")
        assert chat_user["content"] == "What is the weather in Paris?"
        responses_user = next(item for item in responses["input"] if item.get("type") == "message")
        assert responses_user["content"][0]["text"] == "What is the weather in Paris?"
        anthropic_user = next(m for m in anthropic["messages"] if m["role"] == "user")
        text_block = next(b for b in anthropic_user["content"] if b.get("type") == "text")
        assert text_block["text"] == "What is the weather in Paris?"

    def test_tool_call_and_result_identity_round_trips(self) -> None:
        # Outbound: every protocol must carry the same assistant tool call id
        # and bind the tool result to that same id.
        chat = build_chat_completions_request(_request())
        responses = build_responses_request(_request())
        anthropic = build_anthropic_request(_request())

        chat_assistant = next(m for m in chat["messages"] if m["role"] == "assistant")
        assert chat_assistant["tool_calls"][0]["id"] == "call_1"
        chat_tool = next(m for m in chat["messages"] if m["role"] == "tool")
        assert chat_tool["tool_call_id"] == "call_1"

        fc = next(item for item in responses["input"] if item["type"] == "function_call")
        fco = next(item for item in responses["input"] if item["type"] == "function_call_output")
        assert fc["call_id"] == "call_1"
        assert fco["call_id"] == "call_1"

        anthropic_assistant = next(m for m in anthropic["messages"] if m["role"] == "assistant")
        tool_use = next(b for b in anthropic_assistant["content"] if b["type"] == "tool_use")
        anthropic_user = [m for m in anthropic["messages"] if m["role"] == "user"][-1]
        tool_result = next(b for b in anthropic_user["content"] if b.get("type") == "tool_result")
        assert tool_use["id"] == "call_1"
        assert tool_result["tool_use_id"] == "call_1"

    def test_equivalent_inbound_semantics(self) -> None:
        """Feeding each protocol's tool fixture back yields the same tool call."""
        chat = parse_chat_completions_response(fx.CHAT_COMPLETIONS_TOOL)
        responses = parse_responses_response(fx.RESPONSES_TOOL)
        anthropic = parse_anthropic_response(fx.ANTHROPIC_TOOL)

        # The same function was called by the model in every protocol.
        assert [tc.name for tc in chat.tool_calls] == ["get_weather", "get_time"]
        assert [tc.name for tc in responses.tool_calls] == ["get_weather", "get_time"]
        assert [tc.name for tc in anthropic.tool_calls] == ["get_weather"]
        assert (
            chat.tool_calls[0].arguments == responses.tool_calls[0].arguments == {"city": "Paris"}
        )

    def test_equivalent_text_semantics(self) -> None:
        chat = parse_chat_completions_response(fx.CHAT_COMPLETIONS_TEXT)
        responses = parse_responses_response(fx.RESPONSES_TEXT)
        anthropic = parse_anthropic_response(fx.ANTHROPIC_TEXT)

        assert chat.content == responses.content == anthropic.content == "Hello there!"
        assert chat.finish_status == responses.finish_status == anthropic.finish_status == "stop"
        assert (
            chat.usage.prompt_tokens
            == responses.usage.prompt_tokens
            == anthropic.usage.prompt_tokens
            == 10
        )
