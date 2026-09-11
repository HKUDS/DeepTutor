"""Tests for the Responses API converter helpers."""

from __future__ import annotations

from deeptutor.services.llm.provider_core.openai_responses import (
    adapt_chat_kwargs_to_responses,
    convert_messages,
    convert_tool_choice,
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
