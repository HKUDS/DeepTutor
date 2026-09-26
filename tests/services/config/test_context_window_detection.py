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

    assert result.context_window == 16384
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


def test_detect_context_window_uses_known_minimax_m3_window(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "deeptutor.services.config.context_window_detection._detect_from_models_endpoint",
        _metadata_none,
    )
    result = asyncio.run(detect_context_window(_config(model="MiniMax-M3")))

    assert result.context_window == 1_000_000
    assert result.source == "known_model"


def test_extract_context_window_reads_novita_context_size_key() -> None:
    """Novita's /openai/models advertises the window as ``context_size``."""
    payload = {
        "data": [
            {"id": "deepseek/deepseek-v3.2", "context_size": 1_000_000},
        ]
    }

    assert (
        detection_module._extract_context_window_from_payload(payload, "deepseek/deepseek-v3.2")
        == 1_000_000
    )


def test_extract_context_window_reads_llamacpp_n_ctx_meta() -> None:
    """llama.cpp exposes the effective window as ``meta.n_ctx`` for loaded models."""
    payload = {
        "data": [
            {
                "id": "Qwen3.8-27B:Q6_K_XL",
                "status": {
                    "value": "loaded",
                    "args": ["--alias", "Qwen3.8-27B:Q6_K_XL", "--ctx-size", "400000"],
                },
                "preset": "ctx-size = 400000\n",
                "meta": {"n_ctx": 200_192, "n_ctx_train": 262_144},
            },
        ]
    }

    assert (
        detection_module._extract_context_window_from_payload(payload, "Qwen3.8-27B:Q6_K_XL")
        == 200_192
    )


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


def test_glm_flash_uses_context_capacity_not_output_limit(monkeypatch):
    monkeypatch.setattr(detection_module, "_detect_from_models_endpoint", _metadata_none)
    result = asyncio.run(detect_context_window(_config(model="glm-5.3-flash", binding="zhipu")))
    assert result.context_window == 1_000_000
    assert result.source == "known_model"


def test_input_and_output_limits_are_not_context_capacity():
    extract = detection_module._extract_context_window_from_payload
    for key in (
        "max_tokens",
        "max_input_tokens",
        "max_output_tokens",
        "input_token_limit",
        "max_prompt_tokens",
    ):
        assert extract({"data": [{"id": "example", key: 16384}]}, "example") is None
    assert (
        extract(
            {
                "data": [
                    {
                        "id": "example",
                        "max_input_tokens": 16384,
                        "meta": {"context_length": 1000000},
                    }
                ]
            },
            "example",
        )
        == 1000000
    )


def test_model_aliases_do_not_confuse_quantizations_or_providers():
    extract = detection_module._extract_context_window_from_payload
    payload = {
        "data": [
            {"id": "a/model", "context_length": 32768},
            {"id": "b/model", "context_length": 131072},
        ]
    }
    assert extract(payload, "b/model") == 131072
    assert extract(payload, "model") is None
    assert extract({"data": [{"id": "other:Q4", "context_length": 8000}]}, "target:Q4") is None


def test_context_fallback_does_not_depend_on_max_output_tokens():
    from deeptutor.services.llm.context_window import (
        default_context_window_for_model,
        known_context_window,
    )

    assert default_context_window_for_model(model="unknown", max_tokens=131072) == 16384
    assert default_context_window_for_model(model="glm-5.3-flash", max_tokens=1024) == 1000000
    assert known_context_window("not-glm-5.3-flash-custom") is None
