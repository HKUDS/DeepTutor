"""Non-streaming converter contract tests for the three LLM protocols.

Every test drives the deterministic outbound builder with the same normalized
unified request and feeds wire-shaped fixtures into the inbound parser.  No
real endpoint is contacted.
"""

from __future__ import annotations

import pytest

from deeptutor.services.llm.provider_core.unified import (
    build_anthropic_request,
    build_chat_completions_request,
    build_responses_request,
    parse_anthropic_response,
    parse_chat_completions_response,
    parse_responses_response,
)
from deeptutor.services.llm.provider_core.unified.common import (
    normalize_messages,
    normalize_tools,
    parse_usage,
)
from deeptutor.services.llm.provider_core.unified.types import (
    PROTOCOL_ANTHROPIC,
    PROTOCOL_CHAT_COMPLETIONS,
    PROTOCOL_RESPONSES,
    UnifiedProtocolError,
    UnifiedRequest,
)

from . import unified_fixtures as fx


def _request(messages=None, **overrides) -> UnifiedRequest:
    base = {
        "messages": normalize_messages(messages or fx.LEGACY_MESSAGES),
        "tools": normalize_tools(
            [
                {
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "description": "Get the weather",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ]
        ),
        "model": "gpt-5.6",
        "max_tokens": 512,
        "temperature": 0.2,
    }
    base.update(overrides)
    return UnifiedRequest(**base)


class TestChatCompletionsOutbound:
    def test_system_user_conversation(self) -> None:
        body = build_chat_completions_request(
            _request(
                messages=[
                    {"role": "system", "content": "Be brief"},
                    {"role": "user", "content": "Hi"},
                ]
            )
        )
        assert body["model"] == "gpt-5.6"
        assert body["max_tokens"] == 512
        assert body["messages"] == [
            {"role": "system", "content": "Be brief"},
            {"role": "user", "content": "Hi"},
        ]
        assert body["temperature"] == 0.2

    def test_assistant_tool_call_and_tool_result_preserve_ids(self) -> None:
        body = build_chat_completions_request(_request())
        messages = {m["role"]: m for m in body["messages"]}
        assert messages["assistant"]["tool_calls"][0]["id"] == "call_1"
        assert messages["assistant"]["tool_calls"][0]["function"]["name"] == "get_weather"
        assert messages["tool"]["tool_call_id"] == "call_1"
        assert messages["tool"]["content"] == "21C, sunny"

    def test_tools_are_serialized_in_openai_format(self) -> None:
        body = build_chat_completions_request(_request())
        assert body["tools"] == [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get the weather",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]
        assert body["tool_choice"] == "auto"


class TestChatCompletionsInbound:
    def test_parses_text_and_usage(self) -> None:
        unified = parse_chat_completions_response(fx.CHAT_COMPLETIONS_TEXT)
        assert unified.id == "chatcmpl_123"
        assert unified.model == "gpt-5.6"
        assert unified.content == "Hello there!"
        assert unified.finish_status == "stop"
        assert unified.usage == parse_usage(
            {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}
        )

    def test_parses_multiple_tool_calls(self) -> None:
        unified = parse_chat_completions_response(fx.CHAT_COMPLETIONS_TOOL)
        assert unified.finish_status == "tool_calls"
        assert [tc.name for tc in unified.tool_calls] == ["get_weather", "get_time"]
        assert [tc.id for tc in unified.tool_calls] == ["call_1", "call_2"]
        assert unified.tool_calls[0].arguments == {"city": "Paris"}
        assert unified.content is None

    def test_parses_reasoning_content(self) -> None:
        unified = parse_chat_completions_response(fx.CHAT_COMPLETIONS_REASONING)
        assert unified.reasoning is not None
        assert unified.reasoning.text == "Let me think step by step."
        assert unified.content is None

    def test_empty_choices_raises_stable_error(self) -> None:
        with pytest.raises(UnifiedProtocolError) as excinfo:
            parse_chat_completions_response({"id": "x", "choices": []})
        assert excinfo.value.code == "empty_provider_response"

    def test_malformed_tool_arguments_raise(self) -> None:
        raw = {
            "id": "x",
            "model": "m",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "f", "arguments": "{nope"},
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
        }
        with pytest.raises(UnifiedProtocolError) as excinfo:
            parse_chat_completions_response(raw)
        assert excinfo.value.code == "tool_call_invalid_arguments"


class TestResponsesOutbound:
    def test_system_becomes_instructions(self) -> None:
        body = build_responses_request(
            _request(
                messages=[
                    {"role": "system", "content": "Be brief"},
                    {"role": "user", "content": "Hi"},
                ]
            )
        )
        assert body["instructions"] == "Be brief"
        assert body["input"] == [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "Hi"}],
            }
        ]
        assert body["max_output_tokens"] == 512

    def test_tool_call_and_result_preserve_call_id(self) -> None:
        body = build_responses_request(_request())
        call = next(item for item in body["input"] if item["type"] == "function_call")
        output = next(item for item in body["input"] if item["type"] == "function_call_output")
        assert call["call_id"] == "call_1"
        assert call["name"] == "get_weather"
        assert call["arguments"] == '{"city": "Paris"}'
        assert output["call_id"] == "call_1"
        assert output["output"] == "21C, sunny"

    def test_background_flag(self) -> None:
        body = build_responses_request(_request(background=True))
        assert body["background"] is True


class TestResponsesInbound:
    def test_parses_text_and_usage(self) -> None:
        unified = parse_responses_response(fx.RESPONSES_TEXT)
        assert unified.id == "resp_123"
        assert unified.status == "completed"
        assert unified.finish_status == "stop"
        assert unified.content == "Hello there!"

    def test_parses_multiple_function_calls_with_compound_ids(self) -> None:
        unified = parse_responses_response(fx.RESPONSES_TOOL)
        assert [tc.id for tc in unified.tool_calls] == ["call_1|fc_1", "call_2|fc_2"]
        assert [tc.name for tc in unified.tool_calls] == ["get_weather", "get_time"]
        assert unified.tool_calls[0].arguments == {"city": "Paris"}

    def test_parses_reasoning_summary(self) -> None:
        unified = parse_responses_response(fx.RESPONSES_REASONING)
        assert unified.reasoning is not None
        assert unified.reasoning.text == "Reasoning summary"
        assert unified.content == "Final answer"

    def test_malformed_tool_arguments_raise(self) -> None:
        raw = {
            "id": "x",
            "model": "m",
            "status": "completed",
            "output": [
                {
                    "type": "function_call",
                    "id": "fc_1",
                    "call_id": "call_1",
                    "name": "f",
                    "arguments": "{oops",
                }
            ],
        }
        with pytest.raises(UnifiedProtocolError) as excinfo:
            parse_responses_response(raw)
        assert excinfo.value.code == "tool_call_invalid_arguments"


class TestAnthropicOutbound:
    def test_system_becomes_top_level_and_user_message(self) -> None:
        body = build_anthropic_request(
            _request(
                messages=[
                    {"role": "system", "content": "Be brief"},
                    {"role": "user", "content": "Hi"},
                ]
            )
        )
        assert body["system"] == "Be brief"
        assert body["model"] == "gpt-5.6"
        assert body["messages"] == [{"role": "user", "content": [{"type": "text", "text": "Hi"}]}]

    def test_tool_use_and_tool_result_preserve_ids(self) -> None:
        body = build_anthropic_request(_request())
        assistant = next(m for m in body["messages"] if m["role"] == "assistant")
        user_msgs = [m for m in body["messages"] if m["role"] == "user"]
        tool_use = next(b for b in assistant["content"] if b["type"] == "tool_use")
        tool_results = [
            b
            for m in user_msgs
            for b in (m["content"] if isinstance(m["content"], list) else [])
            if isinstance(b, dict) and b.get("type") == "tool_result"
        ]
        assert tool_use["id"] == "call_1"
        assert tool_use["name"] == "get_weather"
        assert tool_use["input"] == {"city": "Paris"}
        assert tool_results[0]["tool_use_id"] == "call_1"
        assert tool_results[0]["content"] == "21C, sunny"


class TestAnthropicInbound:
    def test_parses_text_and_usage(self) -> None:
        unified = parse_anthropic_response(fx.ANTHROPIC_TEXT)
        assert unified.id == "msg_123"
        assert unified.model == "claude-sonnet-4"
        assert unified.content == "Hello there!"
        assert unified.finish_status == "stop"
        assert unified.usage.completion_tokens == 2

    def test_parses_tool_use(self) -> None:
        unified = parse_anthropic_response(fx.ANTHROPIC_TOOL)
        assert unified.finish_status == "tool_calls"
        assert unified.content == "I will check the weather."
        assert unified.tool_calls[0].id == "toolu_1"
        assert unified.tool_calls[0].name == "get_weather"
        assert unified.tool_calls[0].arguments == {"city": "Paris"}

    def test_malformed_tool_input_raises(self) -> None:
        raw = {
            "id": "x",
            "model": "claude-sonnet-4",
            "stop_reason": "tool_use",
            "content": [{"type": "tool_use", "id": "toolu_1", "name": "f", "input": "not-a-dict"}],
        }
        with pytest.raises(UnifiedProtocolError) as excinfo:
            parse_anthropic_response(raw)
        assert excinfo.value.code == "tool_call_invalid_arguments"


class TestProtocolIdentifiers:
    def test_protocol_constants_match_model_catalog(self) -> None:
        from deeptutor.services.config.model_catalog import EXPLICIT_LLM_API_PROTOCOLS

        assert set(EXPLICIT_LLM_API_PROTOCOLS) == {
            PROTOCOL_CHAT_COMPLETIONS,
            PROTOCOL_RESPONSES,
            PROTOCOL_ANTHROPIC,
        }
