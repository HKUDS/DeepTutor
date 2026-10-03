"""Retry decisions must not interpret digits embedded in request IDs as HTTP statuses."""

from __future__ import annotations

from typing import Any

import pytest

from deeptutor.services.llm.provider_core.base import LLMProvider, LLMResponse


class _FailingProvider(LLMProvider):
    def __init__(self, error: str) -> None:
        super().__init__()
        self.error = error
        self.calls = 0

    async def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> LLMResponse:
        self.calls += 1
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
    ],
)
async def test_transient_errors_still_retry(error: str) -> None:
    provider = _FailingProvider(error)
    response = await provider.chat_with_retry(
        messages=[{"role": "user", "content": "hello"}], retry_delays=(0.001,)
    )
    assert response.content == error
    assert provider.calls == 2
