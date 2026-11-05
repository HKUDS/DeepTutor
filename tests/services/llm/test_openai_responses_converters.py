"""Tests for the Responses API converter helpers."""

from __future__ import annotations

import pytest

from deeptutor.services.llm.provider_core.openai_responses import (
    adapt_chat_kwargs_to_responses,
    convert_messages,
    convert_tool_choice,
    parse_response_output,
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


class TestConvertMessages:
    def test_replays_persisted_native_output_items(self) -> None:
        native_items = [
            {
                "type": "reasoning",
                "id": "rs_1",
                "content": [{"type": "reasoning_text", "text": "Need to inspect the MCP status."}],
                "summary": [],
            },
            {
                "type": "message",
                "id": "msg_1",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "previous answer"}],
            },
        ]

        _instructions, input_items = convert_messages(
            [
                {
                    "role": "assistant",
                    "content": "previous answer",
                    "_provider_response_state": {"responses_output_items": native_items},
                }
            ]
        )

        assert input_items == native_items

    def test_replay_leaves_out_a_null_status(self) -> None:
        # The SDK dumps an item that arrived without a status as
        # ``"status": None``; the Responses API rejects that null on input
        # ("Unknown parameter: 'input[N].status'").
        native_items = [
            {
                "type": "reasoning",
                "id": "rs_1",
                "summary": [],
                "content": None,
                "encrypted_content": "enc",
                "status": None,
            },
            {
                "type": "function_call",
                "id": "fc_1",
                "call_id": "call_1",
                "name": "rag",
                "arguments": "{}",
                "status": None,
            },
        ]

        _instructions, input_items = convert_messages(
            [
                {
                    "role": "assistant",
                    "content": None,
                    "_provider_response_state": {"responses_output_items": native_items},
                }
            ]
        )

        assert all("status" not in item for item in input_items)
        # Nothing else is touched: the encrypted reasoning and call linkage stay.
        assert input_items[0] == {
            "type": "reasoning",
            "id": "rs_1",
            "summary": [],
            "content": None,
            "encrypted_content": "enc",
        }
        assert input_items[1]["call_id"] == "call_1"

    def test_replay_keeps_a_status_the_provider_sent(self) -> None:
        native_items = [
            {
                "type": "message",
                "id": "msg_1",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "previous answer"}],
                "status": "completed",
            },
            {
                "type": "reasoning",
                "id": "rs_1",
                "summary": [],
                "status": "incomplete",
            },
        ]

        _instructions, input_items = convert_messages(
            [
                {
                    "role": "assistant",
                    "content": "previous answer",
                    "_provider_response_state": {"responses_output_items": native_items},
                }
            ]
        )

        assert input_items == native_items

    def test_replays_a_reasoning_item_as_the_sdk_dumps_it(self) -> None:
        # Regression for DeepTutor#2373: the dump of a real SDK reasoning item
        # carries ``status: None``, which used to be replayed on the next
        # round after a tool call.
        responses = pytest.importorskip("openai.types.responses")

        reasoning = responses.ResponseReasoningItem(
            id="rs_1", summary=[], type="reasoning", encrypted_content="enc"
        )
        parsed = parse_response_output({"status": "completed", "output": [reasoning]})
        native_items = parsed.provider_specific_fields["native_output_items"]

        _instructions, input_items = convert_messages(
            [
                {
                    "role": "assistant",
                    "content": None,
                    "_provider_response_state": {"responses_output_items": native_items},
                }
            ]
        )

        assert len(input_items) == 1
        assert input_items[0]["type"] == "reasoning"
        assert input_items[0]["id"] == "rs_1"
        assert input_items[0]["encrypted_content"] == "enc"
        assert "status" not in input_items[0]


class TestConvertToolChoice:
    """The two endpoints name a forced tool differently.

    Ask Questions forces ``ask_user`` on its first round. Sent in the Chat
    Completions shape, a Responses endpoint rejects the whole request with
    "tool_choice: missing field `name`", so the capability failed before the
    model was ever called.
    """

    def test_lifts_the_nested_chat_completions_name_to_the_top_level(self) -> None:
        assert convert_tool_choice({"type": "function", "function": {"name": "ask_user"}}) == {
            "type": "function",
            "name": "ask_user",
        }

    def test_a_choice_already_in_responses_shape_is_untouched(self) -> None:
        choice = {"type": "function", "name": "ask_user"}
        assert convert_tool_choice(choice) == choice

    def test_mode_strings_and_none_pass_through(self) -> None:
        assert convert_tool_choice("auto") == "auto"
        assert convert_tool_choice("required") == "required"
        assert convert_tool_choice(None) is None

    def test_a_hosted_tool_choice_is_left_for_the_provider_to_validate(self) -> None:
        assert convert_tool_choice({"type": "web_search"}) == {"type": "web_search"}

    def test_a_function_choice_with_no_name_is_not_invented(self) -> None:
        choice = {"type": "function", "function": {}}
        assert convert_tool_choice(choice) == choice
