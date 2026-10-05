"""Retry decisions must not interpret digits embedded in request IDs as HTTP statuses."""

from __future__ import annotations

from typing import Any

import pytest

from deeptutor.services.llm.provider_core.base import LLMProvider, LLMResponse


class _FailingProvider(LLMProvider):
    def __init__(self, error: str | Exception) -> None:
        super().__init__()
        self.error = error
        self.calls = 0

    async def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> LLMResponse:
        self.calls += 1
        if isinstance(self.error, Exception):
            raise self.error
        return LLMResponse(content=self.error, finish_reason="error")

    def get_default_model(self) -> str:
        return "test-model"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        "credit insufficient balance: balance=0 required=118 (request id: req202601010005000123)",
        "invalid API key (request id: abc429def)",
        "invalid model (request id: 1502)",
        "invalid parameter (request id: trace503end)",
        "invalid request (request id: 1504)",
        "HTTP 400: invalid request (request id: req-500-abcd)",
        "HTTP 401: invalid API key (request id: req-503-abcd)",
    ],
)
async def test_permanent_error_with_status_digits_is_not_retried(error: str) -> None:
    provider = _FailingProvider(error)
    response = await provider.chat_with_retry(
        messages=[{"role": "user", "content": "hello"}], retry_delays=(0.001,)
    )
    assert response.content == error
    assert provider.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        "Error code: 429 - rate limit exceeded",
        "Error code: 500 - internal error",
        'Error: {"code":502,"message":"upstream failure"}',
        "HTTP 503: unavailable",
        "504 Gateway Timeout",
        "request timed out",
        "connection reset by peer",
        "stream stalled",
        TimeoutError(),
        ConnectionResetError("peer reset"),
    ],
)
async def test_transient_errors_still_retry(error: str | Exception) -> None:
    provider = _FailingProvider(error)
    response = await provider.chat_with_retry(
        messages=[{"role": "user", "content": "hello"}], retry_delays=(0.001,)
    )
    expected_content = error if isinstance(error, str) else f"Error calling LLM: {error}"
    assert response.content == expected_content
    assert provider.calls == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "message", "expected_calls"),
    [
        (400, "HTTP 503: temporary gateway error (request id: req-503-abcd)", 1),
        (503, "HTTP 400: invalid request", 2),
    ],
)
async def test_structured_status_overrides_message_status(
    status_code: int, message: str, expected_calls: int
) -> None:
    class StructuredError(Exception):
        pass

    error = StructuredError(message)
    error.status_code = status_code
    provider = _FailingProvider(error)
    response = await provider.chat_with_retry(
        messages=[{"role": "user", "content": "hello"}], retry_delays=(0.001,)
    )
    assert response.finish_reason == "error"
    assert provider.calls == expected_calls
