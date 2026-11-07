"""Tests for BaseLLMProvider retry behavior."""

import asyncio

from src.services.llm.config import LLMConfig
from src.services.llm.exceptions import LLMRateLimitError
from src.services.llm.providers.base_provider import BaseLLMProvider


class DummyProvider(BaseLLMProvider):
    """Minimal provider used for retry tests."""

    async def complete(self, prompt: str, **kwargs: object):
        raise NotImplementedError

    async def stream(self, prompt: str, **kwargs: object):
        raise NotImplementedError


def test_execute_with_retry_succeeds_after_rate_limit() -> None:
    """execute_with_retry should retry on rate limit errors."""
    config = LLMConfig(model="test", api_key="", base_url="http://localhost:1234")
    provider = DummyProvider(config)
    attempts = {"count": 0}

    async def _call() -> str:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise LLMRateLimitError("rate limited", provider="test")
        return "ok"

    async def _no_sleep(_delay: float) -> None:
        return None

    result = asyncio.run(provider.execute_with_retry(_call, max_retries=2, sleep=_no_sleep))

    assert result == "ok"
    assert attempts["count"] == 3
