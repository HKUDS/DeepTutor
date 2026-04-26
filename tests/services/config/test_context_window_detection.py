from __future__ import annotations

import asyncio

from deeptutor.services.config.context_window_detection import (
    detect_context_window,
)
from deeptutor.services.llm.config import LLMConfig


def _config(**overrides):
    defaults = {
        "model": "gpt-4o-mini",
        "api_key": "sk-test",
        "base_url": "https://api.example.com/v1",
        "effective_url": "https://api.example.com/v1",
        "binding": "openai",
        "provider_name": "openai",
        "provider_mode": "standard",
        "api_version": None,
        "extra_headers": {},
        "reasoning_effort": None,
        "max_tokens": 4096,
    }
    defaults.update(overrides)
    return LLMConfig(**defaults)


async def _metadata_128k(*_args, **_kwargs):
    return 128000


async def _metadata_none(*_args, **_kwargs):
    return None


def test_detect_context_window_prefers_provider_metadata(monkeypatch) -> None:
    monkeypatch.setattr(
        "deeptutor.services.config.context_window_detection._detect_from_models_endpoint",
        _metadata_128k,
    )
    result = asyncio.run(detect_context_window(_config(model="kimi-k2.6")))

    assert result.context_window == 128000
    assert result.source == "metadata"


def test_detect_context_window_uses_runtime_default_when_metadata_missing(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "deeptutor.services.config.context_window_detection._detect_from_models_endpoint",
        _metadata_none,
    )
    result = asyncio.run(detect_context_window(_config(model="unknown-model", max_tokens=5000)))

    assert result.context_window == 20000
    assert result.source == "default"
