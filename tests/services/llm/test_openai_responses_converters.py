"""Tests for the Responses API converter helpers."""

from __future__ import annotations

from deeptutor.services.llm.provider_core.openai_responses import (
    adapt_chat_kwargs_to_responses,
    convert_messages,
)


class TestAdaptChatKwargsToResponses:
    def test_passes_through_unrelated_kwargs(self) -> None:
        result = adapt_chat_kwargs_to_responses({"temperature": 0.2, "tool_choice": "auto"})
        assert result == {"temperature": 0.2, "tool_choice": "auto"}

    def test_drops_none_values(self) -> None:
        result = adapt_chat_kwargs_to_responses({"temperature": 0.2, "response_format": None})
        assert result == {"temperature": 0.2}

    def test_translates_max_completion_tokens_to_max_output_tokens(self) -> None:
        # Regression for DeepTutor#437: gpt-5.x callers pass
        # `max_completion_tokens` from `get_token_limit_kwargs(model, n)`,
        # but the Responses API only accepts `max_output_tokens`.
        result = adapt_chat_kwargs_to_responses({"max_completion_tokens": 8192, "temperature": 0.2})
        assert result == {"max_output_tokens": 8192, "temperature": 0.2}
        assert "max_completion_tokens" not in result

    def test_translates_legacy_max_tokens_to_max_output_tokens(self) -> None:
        result = adapt_chat_kwargs_to_responses({"max_tokens": 2048, "temperature": 0.2})
        assert result == {"max_output_tokens": 2048, "temperature": 0.2}
        assert "max_tokens" not in result

    def test_drops_max_completion_tokens_when_none(self) -> None:
        result = adapt_chat_kwargs_to_responses({"max_completion_tokens": None, "temperature": 0.2})
        assert result == {"temperature": 0.2}

    def test_explicit_max_output_tokens_wins_over_alias(self) -> None:
        # If the caller already set the Responses API name explicitly, do not
        # overwrite it with the chat-completions alias value.
        result = adapt_chat_kwargs_to_responses(
            {"max_completion_tokens": 8192, "max_output_tokens": 4096}
        )
        assert result == {"max_output_tokens": 4096}

    def test_max_completion_tokens_wins_when_both_chat_aliases_are_present(self) -> None:
        result = adapt_chat_kwargs_to_responses({"max_tokens": 2048, "max_completion_tokens": 8192})
        assert result == {"max_output_tokens": 8192}

    def test_empty_input_returns_empty_dict(self) -> None:
        assert adapt_chat_kwargs_to_responses({}) == {}

    def test_does_not_mutate_input(self) -> None:
        source = {"max_completion_tokens": 8192, "temperature": 0.2}
        adapt_chat_kwargs_to_responses(source)
        assert source == {"max_completion_tokens": 8192, "temperature": 0.2}


def test_convert_messages_replays_native_reasoning_turn() -> None:
    response_output_items = [
        {"type": "reasoning", "id": "rs_1", "content": [], "summary": []},
        {
            "type": "function_call",
            "id": "fc_1",
            "call_id": "call_1",
            "name": "rag",
            "arguments": "{}",
        },
    ]
    messages = [
        {
            "role": "assistant",
            "content": None,
            "_responses_output_items": response_output_items,
            "tool_calls": [],
        },
        {"role": "tool", "tool_call_id": "call_1|fc_1", "content": "context"},
    ]

    _, input_items = convert_messages(messages)

    assert input_items == [
        *response_output_items,
        {"type": "function_call_output", "call_id": "call_1", "output": "context"},
    ]


def test_convert_messages_without_native_items_keeps_legacy_conversion() -> None:
    messages = [
        {
            "role": "assistant",
            "content": "Checking.",
            "tool_calls": [
                {
                    "id": "call_1|fc_1",
                    "type": "function",
                    "function": {"name": "rag", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1|fc_1", "content": "context"},
    ]

    _, input_items = convert_messages(messages)

    assert [item["type"] for item in input_items] == [
        "message",
        "function_call",
        "function_call_output",
    ]
    assert input_items[1]["call_id"] == "call_1"
    assert input_items[2]["call_id"] == "call_1"
