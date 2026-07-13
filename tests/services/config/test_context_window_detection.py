from __future__ import annotations

import asyncio

from deeptutor.services.config import context_window_detection as detection_module
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


def test_detect_context_window_uses_known_model_metadata_when_provider_omits_window(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "deeptutor.services.config.context_window_detection._detect_from_models_endpoint",
        _metadata_none,
    )
    result = asyncio.run(detect_context_window(_config(model="deepseek-v4-flash")))

    assert result.context_window == 1_000_000
    assert result.source == "known_model"


def test_models_endpoint_probe_honors_disable_ssl_verify(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeConnector:
        pass

    class FakeResponse:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def json(self):
            return {"data": [{"id": "gpt-4o-mini", "context_window": 123456}]}

    class FakeSession:
        def __init__(self, **kwargs):
            captured["session_kwargs"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def get(self, url, headers):
            captured["url"] = url
            captured["headers"] = headers
            return FakeResponse()

    def fake_connector(**kwargs):
        captured["connector_kwargs"] = kwargs
        return FakeConnector()

    monkeypatch.setattr(detection_module, "disable_ssl_verify_enabled", lambda: True)
    monkeypatch.setattr(detection_module.aiohttp, "TCPConnector", fake_connector)
    monkeypatch.setattr(detection_module.aiohttp, "ClientSession", FakeSession)

    result = asyncio.run(detection_module._detect_from_models_endpoint(_config()))

    assert result == 123456
    assert captured["url"] == "https://api.example.com/v1/models"
    assert captured["connector_kwargs"] == {"ssl": False}
    assert isinstance(captured["session_kwargs"]["connector"], FakeConnector)
