from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deeptutor.services.config.runtime_settings import RuntimeSettingsService
from deeptutor.services.llm import stream_timeout
from deeptutor.services.llm.provider_core import (
    anthropic_provider,
    azure_openai_provider,
    openai_compat_provider,
)


@pytest.fixture
def settings(monkeypatch, tmp_path):
    service = RuntimeSettingsService(tmp_path / "settings", process_env={})
    monkeypatch.setattr(stream_timeout, "get_runtime_settings_service", lambda: service)
    return service


def test_default_and_call_time_settings(settings):
    assert stream_timeout.get_stream_idle_timeout_seconds() == 90
    settings.save_system({"llm_stream_idle_timeout_seconds": 240})
    assert stream_timeout.get_stream_idle_timeout_seconds() == 240
    settings.save_system({"llm_stream_idle_timeout_seconds": 360})
    assert stream_timeout.get_stream_idle_timeout_seconds() == 360


@pytest.mark.parametrize(
    ("value", "expected"),
    [(1, 30), (9999, 1800), ("300", 300), ("invalid", 90), ("", 90), (None, 90)],
)
def test_normalization(settings, value, expected):
    settings.save_system({"llm_stream_idle_timeout_seconds": value})
    assert stream_timeout.get_stream_idle_timeout_seconds() == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [("480", 480), ("1", 30), ("9999", 1800), ("invalid", 90), ("", 240)],
)
def test_environment_override(settings, value, expected):
    settings.save_system({"llm_stream_idle_timeout_seconds": 240})
    settings.process_env["DEEPTUTOR_STREAM_IDLE_TIMEOUT_SECONDS"] = value
    assert stream_timeout.get_stream_idle_timeout_seconds() == expected
    assert (
        settings.load_system(include_process_overrides=False)["llm_stream_idle_timeout_seconds"]
        == 240
    )


def test_rendered_environment_does_not_pin_setting(settings):
    settings.save_system({"llm_stream_idle_timeout_seconds": 240})
    assert settings.render_environment()["DEEPTUTOR_STREAM_IDLE_TIMEOUT_SECONDS"] == "240"
    settings.export_environment()
    settings.save_system({"llm_stream_idle_timeout_seconds": 360})
    assert stream_timeout.get_stream_idle_timeout_seconds() == 360


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("module", "provider_class"),
    [
        (openai_compat_provider, openai_compat_provider.OpenAICompatProvider),
        (azure_openai_provider, azure_openai_provider.AzureOpenAIProvider),
        (anthropic_provider, anthropic_provider.AnthropicProvider),
    ],
)
async def test_providers_bound_reads_with_resolved_timeout(monkeypatch, module, provider_class):
    provider = object.__new__(provider_class)
    monkeypatch.setattr(provider, "_build_kwargs", lambda *a, **kw: {}, raising=False)
    monkeypatch.setattr(provider, "_build_body", lambda *a, **kw: {}, raising=False)
    monkeypatch.setattr(provider, "_should_use_responses_api", lambda *a: False, raising=False)
    provider._spec = None
    stream = AsyncMock()
    stream.__aiter__ = lambda self: self
    stream.__anext__ = AsyncMock(side_effect=StopAsyncIteration)
    stream.__aenter__.return_value = stream
    provider._client = SimpleNamespace(
        responses=SimpleNamespace(create=AsyncMock(return_value=stream)),
        chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=stream))),
        messages=SimpleNamespace(stream=lambda **kw: stream),
    )
    provider._create_with_key_rotation = AsyncMock(return_value=stream)
    seen = []

    async def stalled_read(awaitable, timeout):
        seen.append(timeout)
        awaitable.close()
        raise asyncio.TimeoutError

    monkeypatch.setattr(module.asyncio, "wait_for", stalled_read)
    monkeypatch.setattr(module, "get_stream_idle_timeout_seconds", lambda: 345)
    response = await provider.chat_stream(
        messages=[{"role": "user", "content": "Hello"}],
        on_content_delta=AsyncMock(),
    )
    assert seen == [345]
    assert response.finish_reason == "error"
    assert "345 seconds" in response.content
