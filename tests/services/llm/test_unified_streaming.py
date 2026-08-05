"""Streaming contract tests for the three LLM protocols.

Verifies normalized content/reasoning/tool-call deltas, final consolidation,
usage, and the stable error raised for malformed or incomplete tool-call
events.
"""

from __future__ import annotations

import pytest

from deeptutor.services.llm.provider_core.unified import (
    AnthropicStreamParser,
    ChatCompletionsStreamParser,
    ResponsesStreamParser,
)
from deeptutor.services.llm.provider_core.unified.types import UnifiedProtocolError

from . import unified_fixtures as fx


class TestChatCompletionsStream:
    def test_text_deltas_and_usage(self) -> None:
        parser = ChatCompletionsStreamParser()
        content = ""
        for chunk in fx.CHAT_COMPLETIONS_STREAM_TEXT:
            for event in parser.feed(chunk):
                if event.type == "content_delta":
                    content += event.delta
        unified = parser.final_response()
        assert content == "Hello"
        assert unified.content == "Hello"
        assert unified.finish_status == "stop"
        assert unified.usage.prompt_tokens == 10
        assert unified.model == "gpt-5.6"

    def test_fragmented_tool_arguments_are_joined(self) -> None:
        parser = ChatCompletionsStreamParser()
        for chunk in fx.CHAT_COMPLETIONS_STREAM_TOOL:
            parser.feed(chunk)
        unified = parser.final_response()
        assert len(unified.tool_calls) == 1
        assert unified.tool_calls[0].id == "call_1"
        assert unified.tool_calls[0].name == "get_weather"
        assert unified.tool_calls[0].arguments == {"city": "Paris"}
        assert unified.finish_status == "tool_calls"

    def test_malformed_tool_arguments_raise(self) -> None:
        parser = ChatCompletionsStreamParser()
        for chunk in fx.CHAT_COMPLETIONS_STREAM_BAD_ARGS:
            parser.feed(chunk)
        with pytest.raises(UnifiedProtocolError) as excinfo:
            parser.final_response()
        assert excinfo.value.code == "tool_call_invalid_arguments"

    def test_incomplete_tool_call_raises(self) -> None:
        parser = ChatCompletionsStreamParser()
        for chunk in fx.CHAT_COMPLETIONS_STREAM_INCOMPLETE:
            parser.feed(chunk)
        with pytest.raises(UnifiedProtocolError) as excinfo:
            parser.final_response()
        assert excinfo.value.code == "tool_call_incomplete"


class TestResponsesStream:
    def test_tool_call_and_text_deltas(self) -> None:
        parser = ResponsesStreamParser()
        content = ""
        tool_events = []
        for event in fx.RESPONSES_STREAM_TOOL:
            tool_events.extend(parser.feed(event))
        for event in tool_events:
            if event.type == "content_delta":
                content += event.delta
        unified = parser.final_response()
        assert content == "Hello"
        assert unified.content == "Hello"
        assert len(unified.tool_calls) == 1
        assert unified.tool_calls[0].id == "call_1|fc_1"
        assert unified.tool_calls[0].name == "get_weather"
        assert unified.tool_calls[0].arguments == {"city": "Paris"}
        assert unified.finish_status == "tool_calls"
        assert unified.usage.total_tokens == 14

    def test_incomplete_tool_call_raises(self) -> None:
        parser = ResponsesStreamParser()
        for event in fx.RESPONSES_STREAM_INCOMPLETE:
            parser.feed(event)
        with pytest.raises(UnifiedProtocolError) as excinfo:
            parser.final_response()
        assert excinfo.value.code == "tool_call_incomplete"

    def test_error_event_raises_stable_error(self) -> None:
        parser = ResponsesStreamParser()
        with pytest.raises(UnifiedProtocolError) as excinfo:
            parser.feed({"type": "error", "error": {"message": "upstream boom"}})
        assert excinfo.value.code == "provider_stream_error"


class TestAnthropicStream:
    def test_text_deltas(self) -> None:
        parser = AnthropicStreamParser()
        content = ""
        for event in fx.ANTHROPIC_STREAM_TEXT:
            for parsed in parser.feed(event):
                if parsed.type == "content_delta":
                    content += parsed.delta
        unified = parser.final_response()
        assert content == "Hello"
        assert unified.content == "Hello"
        assert unified.finish_status == "stop"
        assert unified.usage.prompt_tokens == 10
        assert unified.usage.completion_tokens == 2

    def test_thinking_deltas_and_signature(self) -> None:
        parser = AnthropicStreamParser()
        reasoning = ""
        for event in fx.ANTHROPIC_STREAM_THINKING:
            for parsed in parser.feed(event):
                if parsed.type == "reasoning_delta":
                    reasoning += parsed.delta
        unified = parser.final_response()
        assert reasoning == "Let me reason"
        assert unified.reasoning is not None
        assert unified.reasoning.text == "Let me reason"
        assert unified.reasoning.signature == "sig_123"
        assert unified.content == "Answer"

    def test_tool_use_arguments_fragments_are_joined(self) -> None:
        parser = AnthropicStreamParser()
        for event in fx.ANTHROPIC_STREAM_TOOL:
            parser.feed(event)
        unified = parser.final_response()
        assert len(unified.tool_calls) == 1
        assert unified.tool_calls[0].id == "toolu_1"
        assert unified.tool_calls[0].name == "get_weather"
        assert unified.tool_calls[0].arguments == {"city": "Paris"}
        assert unified.finish_status == "tool_calls"

    def test_incomplete_tool_use_raises(self) -> None:
        parser = AnthropicStreamParser()
        for event in fx.ANTHROPIC_STREAM_INCOMPLETE:
            parser.feed(event)
        with pytest.raises(UnifiedProtocolError) as excinfo:
            parser.final_response()
        assert excinfo.value.code == "tool_call_incomplete"
