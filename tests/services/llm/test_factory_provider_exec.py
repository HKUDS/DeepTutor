"""Tests for provider-backed execution in llm.factory."""

from __future__ import annotations

from typing import Any

import pytest

from deeptutor.services.llm.config import LLMConfig
from deeptutor.services.llm.factory import complete, stream
from deeptutor.services.llm.provider_core.base import LLMResponse


class _FakeProvider:
    def __init__(
        self,
        *,
        complete_response: LLMResponse | None = None,
        stream_response: LLMResponse | None = None,
        stream_chunk: str = "chunk",
    ) -> None:
        self.complete_kwargs: dict[str, Any] = {}
        self.stream_kwargs: dict[str, Any] = {}
        self.complete_response = complete_response or LLMResponse(content="ok")
        self.stream_response = stream_response or LLMResponse(content=stream_chunk)
        self.stream_chunk = stream_chunk

    async def chat_with_retry(self, **kwargs: Any) -> LLMResponse:
        self.complete_kwargs = kwargs
        return self.complete_response

    async def chat_stream_with_retry(self, **kwargs: Any) -> LLMResponse:
        self.stream_kwargs = kwargs
        on_content_delta = kwargs.get("on_content_delta")
        if on_content_delta is not None:
            await on_content_delta(self.stream_chunk)
        return self.stream_response


def _make_cfg(**overrides: Any) -> LLMConfig:
    defaults = dict(
        model="gpt-4o-mini",
        api_key="test-key",
        base_url="https://api.example.com/v1",
        effective_url="https://api.example.com/v1",
        binding="openai",
        provider_name="openai",
        provider_mode="standard",
        extra_headers={},
    )
    defaults.update(overrides)
    return LLMConfig(**defaults)


@pytest.mark.asyncio
async def test_complete_merges_config_and_caller_extra_headers(monkeypatch) -> None:
    cfg = _make_cfg(extra_headers={"X-Config": "from-config"})
    provider = _FakeProvider()
    captured_config: dict[str, Any] = {}

    monkeypatch.setattr("deeptutor.services.llm.factory.get_llm_config", lambda: cfg)

    def _fake_get_runtime_provider(config: LLMConfig):
        captured_config["config"] = config
        return provider

    monkeypatch.setattr(
        "deeptutor.services.llm.factory.get_runtime_provider", _fake_get_runtime_provider
    )

    result = await complete("hello", extra_headers={"X-Caller": "from-caller"})

    assert result == "ok"
    merged = captured_config["config"].extra_headers
    assert merged == {"X-Config": "from-config", "X-Caller": "from-caller"}


@pytest.mark.asyncio
async def test_stream_merges_config_and_caller_extra_headers(monkeypatch) -> None:
    cfg = _make_cfg(extra_headers={"X-Config": "cfg"})
    provider = _FakeProvider(stream_chunk="A")
    captured_config: dict[str, Any] = {}

    monkeypatch.setattr("deeptutor.services.llm.factory.get_llm_config", lambda: cfg)

    def _fake_get_runtime_provider(config: LLMConfig):
        captured_config["config"] = config
        return provider

    monkeypatch.setattr(
        "deeptutor.services.llm.factory.get_runtime_provider", _fake_get_runtime_provider
    )

    chunks = []
    async for chunk in stream("hello", extra_headers={"X-Caller": "clr"}):
        chunks.append(chunk)

    assert chunks == ["A"]
    merged = captured_config["config"].extra_headers
    assert merged == {"X-Config": "cfg", "X-Caller": "clr"}


@pytest.mark.asyncio
async def test_complete_injects_openai_image_parts(monkeypatch) -> None:
    cfg = _make_cfg(model="gpt-4o-mini", binding="openai", provider_name="openai")
    provider = _FakeProvider()

    monkeypatch.setattr("deeptutor.services.llm.factory.get_llm_config", lambda: cfg)
    monkeypatch.setattr(
        "deeptutor.services.llm.factory.get_runtime_provider",
        lambda _config: provider,
    )

    result = await complete(
        "ignored",
        messages=[{"role": "user", "content": "hi"}],
        image_data="abc123",
    )

    assert result == "ok"
    content = provider.complete_kwargs["messages"][0]["content"]
    assert isinstance(content, list)
    assert content[0]["type"] == "text"
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,abc123")


@pytest.mark.asyncio
async def test_complete_injects_anthropic_image_parts(monkeypatch) -> None:
    cfg = _make_cfg(
        model="claude-sonnet-4-20250514",
        binding="anthropic",
        provider_name="anthropic",
    )
    provider = _FakeProvider()

    monkeypatch.setattr("deeptutor.services.llm.factory.get_llm_config", lambda: cfg)
    monkeypatch.setattr(
        "deeptutor.services.llm.factory.get_runtime_provider",
        lambda _config: provider,
    )

    result = await complete(
        "ignored",
        messages=[{"role": "user", "content": "hi"}],
        image_data="abc123",
    )

    assert result == "ok"
    content = provider.complete_kwargs["messages"][0]["content"]
    assert isinstance(content, list)
    assert content[1]["type"] == "image"
    assert content[1]["source"]["type"] == "base64"


@pytest.mark.asyncio
async def test_complete_injects_custom_anthropic_image_parts(monkeypatch) -> None:
    cfg = _make_cfg(
        model="claude-sonnet-4-20250514",
        binding="custom_anthropic",
        provider_name="custom_anthropic",
    )
    provider = _FakeProvider()

    monkeypatch.setattr("deeptutor.services.llm.factory.get_llm_config", lambda: cfg)
    monkeypatch.setattr(
        "deeptutor.services.llm.factory.get_runtime_provider",
        lambda _config: provider,
    )

    result = await complete(
        "ignored",
        messages=[{"role": "user", "content": "hi"}],
        image_data="abc123",
    )

    assert result == "ok"
    content = provider.complete_kwargs["messages"][0]["content"]
    assert isinstance(content, list)
    assert content[1]["type"] == "image"
    assert content[1]["source"]["type"] == "base64"


@pytest.mark.asyncio
async def test_complete_strips_unsupported_response_format(monkeypatch) -> None:
    cfg = _make_cfg(
        model="deepseek-reasoner",
        binding="deepseek",
        provider_name="deepseek",
    )
    provider = _FakeProvider()

    monkeypatch.setattr("deeptutor.services.llm.factory.get_llm_config", lambda: cfg)
    monkeypatch.setattr(
        "deeptutor.services.llm.factory.get_runtime_provider",
        lambda _config: provider,
    )

    result = await complete(
        "hello",
        response_format={"type": "json_object"},
    )

    assert result == "ok"
    assert "response_format" not in provider.complete_kwargs


@pytest.mark.asyncio
async def test_complete_passes_retry_delays(monkeypatch) -> None:
    cfg = _make_cfg()
    provider = _FakeProvider()

    monkeypatch.setattr("deeptutor.services.llm.factory.get_llm_config", lambda: cfg)
    monkeypatch.setattr(
        "deeptutor.services.llm.factory.get_runtime_provider",
        lambda _config: provider,
    )

    await complete("hello", max_retries=3, retry_delay=0.5, exponential_backoff=True)

    assert provider.complete_kwargs["retry_delays"] == (0.5, 1.0, 2.0)
