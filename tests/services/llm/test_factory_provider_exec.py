"""Tests for provider-backed execution in llm.factory."""

from __future__ import annotations

import pytest

from deeptutor.services.llm.config import LLMConfig
from deeptutor.services.llm.factory import complete, stream


# ---------------------------------------------------------------------------
# extra_headers dedup / merge (regression for #324)
# ---------------------------------------------------------------------------


def _make_cfg(**overrides):
    defaults = dict(
        model="gpt-4o-mini",
        api_key="test-key",
        base_url="https://api.example.com/v1",
        binding="openai",
        provider_name="openai",
        provider_mode="standard",
    )
    defaults.update(overrides)
    return LLMConfig(**defaults)


@pytest.mark.asyncio
async def test_complete_extra_headers_from_kwargs_no_duplicate(monkeypatch) -> None:
    """Passing extra_headers via kwargs must not cause 'multiple values' TypeError."""
    cfg = _make_cfg(extra_headers={})
    captured: dict[str, object] = {}

    async def _fake_sdk_complete(**kwargs):
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr("deeptutor.services.llm.factory.get_llm_config", lambda: cfg)
    monkeypatch.setattr("deeptutor.services.llm.executors.sdk_complete", _fake_sdk_complete)
    monkeypatch.setattr("deeptutor.services.llm.factory.sdk_complete", _fake_sdk_complete)

    result = await complete("hello", extra_headers={"X-Custom": "val"})
    assert result == "ok"
    assert captured["extra_headers"] == {"X-Custom": "val"}


@pytest.mark.asyncio
async def test_complete_merges_config_and_caller_extra_headers(monkeypatch) -> None:
    """Caller extra_headers should be merged with config-level headers."""
    cfg = _make_cfg(extra_headers={"X-Config": "from-config"})
    captured: dict[str, object] = {}

    async def _fake_sdk_complete(**kwargs):
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr("deeptutor.services.llm.factory.get_llm_config", lambda: cfg)
    monkeypatch.setattr("deeptutor.services.llm.executors.sdk_complete", _fake_sdk_complete)
    monkeypatch.setattr("deeptutor.services.llm.factory.sdk_complete", _fake_sdk_complete)

    result = await complete("hello", extra_headers={"X-Caller": "from-caller"})
    assert result == "ok"
    headers = captured["extra_headers"]
    assert headers["X-Config"] == "from-config"
    assert headers["X-Caller"] == "from-caller"


@pytest.mark.asyncio
async def test_stream_extra_headers_from_kwargs_no_duplicate(monkeypatch) -> None:
    """Passing extra_headers via kwargs to stream must not cause 'multiple values' TypeError."""
    cfg = _make_cfg(extra_headers={})
    captured: dict[str, object] = {}

    async def _fake_sdk_stream(**kwargs):
        captured.update(kwargs)
        yield "chunk"

    monkeypatch.setattr("deeptutor.services.llm.factory.get_llm_config", lambda: cfg)
    monkeypatch.setattr("deeptutor.services.llm.executors.sdk_stream", _fake_sdk_stream)
    monkeypatch.setattr("deeptutor.services.llm.factory.sdk_stream", _fake_sdk_stream)

    chunks = []
    async for c in stream("hello", extra_headers={"X-Custom": "val"}):
        chunks.append(c)
    assert chunks == ["chunk"]
    assert captured["extra_headers"] == {"X-Custom": "val"}


@pytest.mark.asyncio
async def test_stream_merges_config_and_caller_extra_headers(monkeypatch) -> None:
    """Caller extra_headers should be merged with config-level headers in stream."""
    cfg = _make_cfg(extra_headers={"X-Config": "cfg"})
    captured: dict[str, object] = {}

    async def _fake_sdk_stream(**kwargs):
        captured.update(kwargs)
        yield "chunk"

    monkeypatch.setattr("deeptutor.services.llm.factory.get_llm_config", lambda: cfg)
    monkeypatch.setattr("deeptutor.services.llm.executors.sdk_stream", _fake_sdk_stream)
    monkeypatch.setattr("deeptutor.services.llm.factory.sdk_stream", _fake_sdk_stream)

    chunks = []
    async for c in stream("hello", extra_headers={"X-Caller": "clr"}):
        chunks.append(c)
    assert chunks == ["chunk"]
    headers = captured["extra_headers"]
    assert headers["X-Config"] == "cfg"
    assert headers["X-Caller"] == "clr"


@pytest.mark.asyncio
async def test_factory_complete_uses_litellm(monkeypatch) -> None:
    cfg = LLMConfig(
        model="google/gemini-2.5-pro",
        api_key="sk-or-test",
        base_url="https://openrouter.ai/api/v1",
        binding="openrouter",
        provider_name="openrouter",
        provider_mode="gateway",
    )
    captured: dict[str, object] = {}

    async def _fake_litellm_complete(**kwargs):
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr("deeptutor.services.llm.factory.get_llm_config", lambda: cfg)
    monkeypatch.setattr("deeptutor.services.llm.factory.litellm_available", lambda: True)
    monkeypatch.setattr("deeptutor.services.llm.factory.litellm_complete", _fake_litellm_complete)

    result = await complete("hello")
    assert result == "ok"
    assert captured["provider_name"] == "openrouter"
    assert captured["model"] == "google/gemini-2.5-pro"


@pytest.mark.asyncio
async def test_factory_complete_uses_direct_azure(monkeypatch) -> None:
    cfg = LLMConfig(
        model="gpt-4o-mini",
        api_key="azure-key",
        base_url="https://example.openai.azure.com/openai/deployments/demo",
        binding="azure_openai",
        provider_name="azure_openai",
        provider_mode="direct",
        api_version="2024-10-21",
    )
    captured: dict[str, object] = {}

    async def _fake_cloud_complete(**kwargs):
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr("deeptutor.services.llm.factory.get_llm_config", lambda: cfg)
    monkeypatch.setattr("deeptutor.services.llm.factory.litellm_available", lambda: False)
    monkeypatch.setattr("deeptutor.services.llm.cloud_provider.complete", _fake_cloud_complete)

    result = await complete("hello")
    assert result == "ok"
    assert captured["binding"] == "azure_openai"


@pytest.mark.asyncio
async def test_factory_complete_openai_codex_requires_oauth(monkeypatch) -> None:
    cfg = LLMConfig(
        model="openai_codex/codex-mini-latest",
        api_key="",
        base_url="https://chatgpt.com/backend-api",
        binding="openai_codex",
        provider_name="openai_codex",
        provider_mode="oauth",
    )
    monkeypatch.setattr("deeptutor.services.llm.factory.get_llm_config", lambda: cfg)
    monkeypatch.setattr("deeptutor.services.llm.factory.litellm_available", lambda: False)

    with pytest.raises(Exception):
        await complete("hello", max_retries=0)


@pytest.mark.asyncio
async def test_factory_stream_uses_litellm(monkeypatch) -> None:
    cfg = LLMConfig(
        model="deepseek-chat",
        api_key="deep-key",
        base_url="https://api.deepseek.com/v1",
        binding="deepseek",
        provider_name="deepseek",
        provider_mode="standard",
    )

    async def _fake_litellm_stream(**kwargs):
        _ = kwargs
        yield "a"
        yield "b"

    monkeypatch.setattr("deeptutor.services.llm.factory.get_llm_config", lambda: cfg)
    monkeypatch.setattr("deeptutor.services.llm.factory.litellm_available", lambda: True)
    monkeypatch.setattr("deeptutor.services.llm.factory.litellm_stream", _fake_litellm_stream)

    chunks = []
    async for item in stream("hello"):
        chunks.append(item)
    assert "".join(chunks) == "ab"
