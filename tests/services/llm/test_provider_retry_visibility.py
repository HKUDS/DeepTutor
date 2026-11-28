"""Provider retry sleeps must be observable (#2693 P0)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from deeptutor.services.llm.provider_core.base import LLMProvider, LLMResponse


class _FlakyProvider(LLMProvider):
    """Fails with a retryable 500 the first N times, then answers."""

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0
        self.generation = SimpleNamespace(max_tokens=64, temperature=0.0, reasoning_effort=None)

    def get_default_model(self) -> str:
        return "demo-model"

    async def chat(self, **kwargs):  # noqa: ANN003 - mirrors the base signature
        self.calls += 1
        if self.calls <= self.failures:
            return LLMResponse(content="HTTP 500 server error", finish_reason="error")
        return LLMResponse(content="ok", finish_reason="stop")


@pytest.mark.asyncio
async def test_observer_sees_each_retry_before_the_sleep() -> None:
    provider = _FlakyProvider(failures=2)
    seen: list[tuple[int, int, float]] = []

    async def observe(*, attempt: int, total: int, delay: float, detail: str) -> None:
        seen.append((attempt, total, delay))

    provider.retry_observer = observe

    response = await provider.chat_with_retry(
        messages=[{"role": "user", "content": "hi"}],
        retry_delays=(0.01, 0.01),
    )

    assert response.content == "ok"
    assert provider.calls == 3
    # Two retries, each announced before its sleep, with the caller's schedule.
    assert [(a, t) for a, t, _ in seen] == [(1, 3), (2, 3)]


@pytest.mark.asyncio
async def test_failing_observer_never_breaks_the_retry() -> None:
    provider = _FlakyProvider(failures=1)

    async def observe(**kwargs):  # noqa: ANN003
        raise RuntimeError("the reporter is broken")

    provider.retry_observer = observe

    response = await provider.chat_with_retry(
        messages=[{"role": "user", "content": "hi"}],
        retry_delays=(0.01,),
    )

    assert response.content == "ok"
