"""Tests for the routing provider wrapper."""

import asyncio
from collections.abc import AsyncGenerator

from src.services.llm.config import LLMConfig
from src.services.llm.providers.routing import RoutingProvider


async def _collect_stream(provider: RoutingProvider) -> list[object]:
    chunks: list[object] = []
    async for chunk in provider.stream("hello", max_retries=0):
        chunks.append(chunk)
    return chunks


def test_routing_provider_local_complete(monkeypatch) -> None:
    """Routing provider should delegate to local provider for local URLs."""

    async def _fake_local_complete(**_kwargs: object) -> str:
        return "local"

    monkeypatch.setattr(
        "src.services.llm.local_provider.complete",
        _fake_local_complete,
    )

    config = LLMConfig(model="test", api_key="", base_url="http://localhost:11434")
    provider = RoutingProvider(config)
    result = asyncio.run(provider.complete("hello", use_cache=False, max_retries=0))

    assert result.content == "local"
    assert result.provider == "local"


def test_routing_provider_cloud_complete(monkeypatch) -> None:
    """Routing provider should delegate to cloud provider for remote URLs."""

    async def _fake_cloud_complete(**_kwargs: object) -> str:
        return "cloud"

    monkeypatch.setattr(
        "src.services.llm.cloud_provider.complete",
        _fake_cloud_complete,
    )

    config = LLMConfig(model="test", api_key="", base_url="https://api.openai.com")
    provider = RoutingProvider(config)
    result = asyncio.run(provider.complete("hello", use_cache=False, max_retries=0))

    assert result.content == "cloud"
    assert result.provider == "routing"


def test_routing_provider_stream(monkeypatch) -> None:
    """Routing provider should emit accumulated stream chunks."""

    async def _fake_stream(**_kwargs: object) -> AsyncGenerator[str, None]:
        yield "A"
        yield "B"

    monkeypatch.setattr("src.services.llm.local_provider.stream", _fake_stream)

    config = LLMConfig(model="test", api_key="", base_url="http://localhost:1234")
    provider = RoutingProvider(config)
    chunks = asyncio.run(_collect_stream(provider))

    assert chunks
    assert chunks[-1].is_complete is True
    assert chunks[-1].content == "AB"
