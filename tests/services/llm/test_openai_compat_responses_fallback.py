"""Tests for Responses-error fallback classification on the OpenAI-compatible provider."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from deeptutor.services.llm.provider_core.openai_compat_provider import (
    OpenAICompatProvider,
)
from deeptutor.services.provider_registry import find_by_name


class _FakeHTTPError(Exception):
    def __init__(self, status_code: int, body: str) -> None:
        super().__init__(body)
        self.status_code = status_code
        self.body = body


class TestResponsesReasoningReplayFallback:
    @pytest.mark.parametrize(
        "message",
        [
            "The reasoning_text in the thinking mode must be passed back to the API.",
            "The reasoning_content in the thinking mode must be passed back to the API.",
        ],
    )
    def test_deepseek_reasoning_replay_400_falls_back(self, message: str) -> None:
        exc = _FakeHTTPError(400, f"{{'message': '{message}', 'code': 'invalid_request_error'}}")
        assert OpenAICompatProvider._should_fallback_from_responses_error(exc) is True

    def test_unrelated_400_still_does_not_fall_back(self) -> None:
        exc = _FakeHTTPError(
            400, "{'message': 'Invalid model id', 'code': 'invalid_request_error'}"
        )
        assert OpenAICompatProvider._should_fallback_from_responses_error(exc) is False

    @pytest.mark.parametrize(
        "message",
        [
            "reasoning_text is invalid",
            "thinking mode is unavailable",
            "The previous response must be passed back",
        ],
    )
    def test_partial_reasoning_markers_do_not_fall_back(self, message: str) -> None:
        exc = _FakeHTTPError(400, message)
        assert OpenAICompatProvider._should_fallback_from_responses_error(exc) is False

    def test_non_4xx_reasoning_error_does_not_fall_back(self) -> None:
        exc = _FakeHTTPError(
            500,
            "The reasoning_text in the thinking mode must be passed back to the API.",
        )
        assert OpenAICompatProvider._should_fallback_from_responses_error(exc) is False

    @pytest.mark.asyncio
    async def test_automatic_responses_mode_retries_through_chat_completions(self) -> None:
        calls = {"responses": 0, "chat": 0}

        class FailingResponses:
            async def create(self, **_kwargs):
                calls["responses"] += 1
                raise _FakeHTTPError(
                    400,
                    "The reasoning_text in the thinking mode must be passed back to the API.",
                )

        class SuccessfulChatCompletions:
            async def create(self, **_kwargs):
                calls["chat"] += 1
                message = SimpleNamespace(
                    content="fallback answer",
                    reasoning_content=None,
                    reasoning=None,
                    tool_calls=None,
                )
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=message, finish_reason="stop")],
                    usage=None,
                )

        provider = OpenAICompatProvider(
            api_key="test-key",
            default_model="deepseek-v4-flash",
            spec=find_by_name("deepseek"),
            provider_name="deepseek",
            wire_api="auto",
        )
        provider._client = SimpleNamespace(
            responses=FailingResponses(),
            chat=SimpleNamespace(completions=SuccessfulChatCompletions()),
        )

        result = await provider.chat(
            messages=[{"role": "user", "content": "search"}],
            model="deepseek-v4-flash",
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "web_search",
                        "description": "Search the web",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
        )

        assert result.content == "fallback answer"
        assert calls == {"responses": 1, "chat": 1}
