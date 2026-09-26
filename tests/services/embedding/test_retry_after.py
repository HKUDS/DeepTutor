"""Rate-limit retry coverage for OpenAI-compatible embeddings."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from typing import Any

import httpx
import pytest

from deeptutor.services.embedding.adapters.base import EmbeddingProviderError, EmbeddingRequest
from deeptutor.services.embedding.adapters.openai_compatible import (
    OpenAICompatibleEmbeddingAdapter,
)


class _RateLimitedTransport(httpx.AsyncBaseTransport):
    """Return rate limits before an optional successful embedding response."""

    def __init__(self, retry_after: str, *, succeed_after: int | None) -> None:
        self.retry_after = retry_after
        self.succeed_after = succeed_after
        self.calls = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if self.succeed_after is None or self.calls <= self.succeed_after:
            return httpx.Response(
                429,
                headers={"Retry-After": self.retry_after},
                request=request,
            )
        return httpx.Response(
            200,
            json={"data": [{"embedding": [0.1, 0.2]}], "model": "test-model"},
            request=request,
        )


def _install_transport(
    monkeypatch: pytest.MonkeyPatch,
    transport: httpx.AsyncBaseTransport,
) -> None:
    real_client_init = httpx.AsyncClient.__init__

    def _patched_init(self: httpx.AsyncClient, *args: Any, **kwargs: Any) -> None:
        kwargs["transport"] = transport
        real_client_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", _patched_init)


def _make_adapter() -> OpenAICompatibleEmbeddingAdapter:
    return OpenAICompatibleEmbeddingAdapter(
        {
            "api_key": "sk-test",
            "base_url": "https://api.example.test/v1/embeddings",
            "model": "test-model",
            "request_timeout": 5,
        }
    )


@pytest.mark.asyncio
async def test_http_date_retry_after_retries_without_value_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    retry_at = format_datetime(
        datetime.now(timezone.utc) + timedelta(minutes=5),
        usegmt=True,
    )
    transport = _RateLimitedTransport(retry_at, succeed_after=1)
    _install_transport(monkeypatch, transport)
    sleeps: list[float] = []

    async def _record_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(asyncio, "sleep", _record_sleep)

    result = await _make_adapter().embed(EmbeddingRequest(texts=["hello"], model="test-model"))

    assert result.embeddings == [[0.1, 0.2]]
    assert transport.calls == 2
    assert len(sleeps) == 1
    assert sleeps[0] > 200


@pytest.mark.asyncio
async def test_malformed_retry_after_uses_existing_minimum_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _RateLimitedTransport("not-a-delay", succeed_after=1)
    _install_transport(monkeypatch, transport)
    sleeps: list[float] = []

    async def _record_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(asyncio, "sleep", _record_sleep)

    await _make_adapter().embed(EmbeddingRequest(texts=["hello"], model="test-model"))

    assert sleeps == [60]


@pytest.mark.asyncio
async def test_http_date_survives_terminal_rate_limit_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    retry_at = format_datetime(
        datetime.now(timezone.utc) + timedelta(minutes=5),
        usegmt=True,
    )
    transport = _RateLimitedTransport(retry_at, succeed_after=None)
    _install_transport(monkeypatch, transport)

    async def _skip_sleep(delay: float) -> None:
        del delay

    monkeypatch.setattr(asyncio, "sleep", _skip_sleep)

    with pytest.raises(EmbeddingProviderError, match="Retry-After"):
        await _make_adapter().embed(EmbeddingRequest(texts=["hello"], model="test-model"))

    assert transport.calls == 9
