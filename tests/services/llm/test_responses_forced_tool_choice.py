"""A forced tool must reach a Responses endpoint in the shape it accepts.

Ask Questions forces ``ask_user`` on its first round. The agent loop composes
that choice in the Chat Completions shape (``{"type": "function", "function":
{"name": ...}}``), which every Responses endpoint rejects outright —
"tool_choice: missing field `name`" — so the capability failed before the
model was ever called. Each provider that builds a Responses body is covered
here, because the fix is one shared converter applied in three places.
"""

from __future__ import annotations

from typing import Any

import pytest

from deeptutor.services.llm import capabilities as llm_capabilities
from deeptutor.services.llm.capabilities import is_forced_tool_choice_disabled_at_runtime
from deeptutor.services.llm.provider_core.azure_openai_provider import AzureOpenAIProvider
from deeptutor.services.llm.provider_core.openai_compat_provider import OpenAICompatProvider
from deeptutor.services.provider_registry import find_by_name


@pytest.fixture(autouse=True)
def _forget_runtime_downgrades() -> None:
    """The downgrade cache is process-global; keep it out of other tests."""
    llm_capabilities._RUNTIME_DISABLED_FORCED_TOOL_CHOICE.clear()


_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": "Ask the learner a question",
            "parameters": {"type": "object", "properties": {"questions": {"type": "array"}}},
        },
    }
]
# What ``agent_loop._call_llm`` composes for a forced round.
_CHAT_SHAPE = {"type": "function", "function": {"name": "ask_user"}}
_RESPONSES_SHAPE = {"type": "function", "name": "ask_user"}


def test_openai_compatible_responses_body_names_the_tool_at_the_top_level() -> None:
    provider = OpenAICompatProvider(
        api_key="test-key",
        api_base="https://api.deepseek.com",
        default_model="deepseek-v4-flash",
        spec=find_by_name("deepseek"),
        provider_name="deepseek",
    )

    body = provider._build_responses_body(
        [{"role": "user", "content": "什么是 agent"}],
        _TOOLS,
        "deepseek-v4-flash",
        256,
        0.7,
        None,
        _CHAT_SHAPE,
    )

    assert body["tool_choice"] == _RESPONSES_SHAPE
    # The forced tool is one the request actually declares.
    assert "ask_user" in {tool.get("name") for tool in body["tools"]}


def test_azure_responses_body_names_the_tool_at_the_top_level() -> None:
    provider = AzureOpenAIProvider(
        api_key="test-key",
        api_base="https://example.openai.azure.com",
        api_version="2025-04-01-preview",
        default_model="gpt-5",
    )

    body = provider._build_body(
        [{"role": "user", "content": "什么是 agent"}],
        _TOOLS,
        "gpt-5",
        256,
        0.7,
        None,
        _CHAT_SHAPE,
    )

    assert body["tool_choice"] == _RESPONSES_SHAPE


def test_an_unforced_round_still_asks_for_auto() -> None:
    provider = OpenAICompatProvider(
        api_key="test-key",
        api_base="https://api.deepseek.com",
        default_model="deepseek-v4-flash",
        spec=find_by_name("deepseek"),
        provider_name="deepseek",
    )

    body = provider._build_responses_body(
        [{"role": "user", "content": "什么是 agent"}],
        _TOOLS,
        "deepseek-v4-flash",
        256,
        0.7,
        None,
        None,
    )

    assert body["tool_choice"] == "auto"


def _provider() -> OpenAICompatProvider:
    return OpenAICompatProvider(
        api_key="test-key",
        api_base="https://api.deepseek.com",
        default_model="deepseek-v4-flash",
        spec=find_by_name("deepseek"),
        provider_name="deepseek",
    )


class TestForcedToolChoiceDowngrade:
    """Some providers accept tools but refuse to be told which one to call.

    DeepSeek V4 with thinking enabled answers "Thinking mode does not support
    this tool_choice", which failed the whole Ask Questions turn — its first
    round forces ``ask_user``. Recording the refusal and asking for
    ``"required"`` instead keeps the round alive; if the model then answers in
    prose, the loop already wraps that question into a local card.
    """

    def test_a_refusal_is_recorded_and_asks_for_a_retry(self) -> None:
        provider = _provider()
        refusal = RuntimeError(
            "Error: {'message': 'Thinking mode does not support this tool_choice', "
            "'type': 'invalid_request_error'}"
        )

        assert provider._note_forced_tool_choice_rejected(refusal, _CHAT_SHAPE, "deepseek-v4-flash")
        assert is_forced_tool_choice_disabled_at_runtime("deepseek", "deepseek-v4-flash")

    def test_a_recorded_pair_is_softened_before_the_request(self) -> None:
        provider = _provider()
        provider._note_forced_tool_choice_rejected(
            RuntimeError("tool_choice is not supported"), _CHAT_SHAPE, "deepseek-v4-flash"
        )

        body = provider._build_responses_body(
            [{"role": "user", "content": "什么是 agent"}],
            _TOOLS,
            "deepseek-v4-flash",
            256,
            0.7,
            None,
            _CHAT_SHAPE,
        )

        assert body["tool_choice"] == "required"

    def test_a_provider_that_honours_a_forced_tool_keeps_getting_one(self) -> None:
        provider = OpenAICompatProvider(
            api_key="test-key",
            api_base="https://api.deepseek.com",
            default_model="deepseek-reasoner",
            spec=find_by_name("deepseek"),
            provider_name="deepseek",
        )

        body = provider._build_responses_body(
            [{"role": "user", "content": "什么是 agent"}],
            _TOOLS,
            "deepseek-reasoner",
            256,
            0.7,
            None,
            _CHAT_SHAPE,
        )

        assert body["tool_choice"] == _RESPONSES_SHAPE

    def test_a_malformed_choice_is_a_bug_to_fix_not_a_capability_to_drop(self) -> None:
        """The shape error this module's other tests cover must not downgrade."""
        provider = _provider()
        shape_error = RuntimeError(
            "Failed to deserialize the JSON body into the target type: "
            "tool_choice: missing field `name` at line 1 column 19930"
        )

        assert not provider._note_forced_tool_choice_rejected(
            shape_error, _CHAT_SHAPE, "deepseek-reasoner"
        )

    def test_an_unrelated_failure_never_downgrades(self) -> None:
        provider = _provider()

        assert not provider._note_forced_tool_choice_rejected(
            RuntimeError("rate limit exceeded"), _CHAT_SHAPE, "deepseek-reasoner"
        )

    def test_an_unforced_round_is_not_a_downgrade_candidate(self) -> None:
        provider = _provider()

        assert not provider._note_forced_tool_choice_rejected(
            RuntimeError("Thinking mode does not support this tool_choice"),
            "auto",
            "deepseek-reasoner",
        )
