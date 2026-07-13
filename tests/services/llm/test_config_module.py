"""Tests for LLM configuration helpers."""

from __future__ import annotations

import os

import pytest

from deeptutor.services.config.provider_runtime import ResolvedLLMConfig
from deeptutor.services.llm import config as config_module
from deeptutor.services.llm.config import LLMConfig
from deeptutor.services.llm.exceptions import LLMConfigError


def _reset_config_cache() -> None:
    config_module._LLM_CONFIG_CACHE = None


def test_get_llm_config_from_resolver(monkeypatch) -> None:
    """Resolver-backed loading should populate provider metadata."""
    _reset_config_cache()

    def _fake_resolver() -> ResolvedLLMConfig:
        return ResolvedLLMConfig(
            model="openai/gpt-4o-mini",
            provider_name="openrouter",
            provider_mode="gateway",
            binding_hint="openrouter",
            binding="openrouter",
            api_key="sk-or-test",
            base_url="https://openrouter.ai/api/v1",
            effective_url="https://openrouter.ai/api/v1",
            api_version=None,
            extra_headers={"X-Test": "1"},
            reasoning_effort="medium",
            context_window=128000,
        )

    monkeypatch.setattr(config_module, "resolve_llm_runtime_config", _fake_resolver)
    config = config_module.get_llm_config()

    assert isinstance(config, LLMConfig)
    assert config.model == "openai/gpt-4o-mini"
    assert config.provider_name == "openrouter"
    assert config.provider_mode == "gateway"
    assert config.base_url == "https://openrouter.ai/api/v1"
    assert config.extra_headers == {"X-Test": "1"}
    assert config.reasoning_effort == "medium"
    assert config.context_window == 128000


def test_get_llm_config_raises_when_resolver_fails(monkeypatch) -> None:
    _reset_config_cache()
    monkeypatch.setattr(
        config_module,
        "resolve_llm_runtime_config",
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    with pytest.raises(RuntimeError, match="boom"):
        config_module.get_llm_config()


def test_scoped_llm_config_takes_precedence_over_global_cache(monkeypatch) -> None:
    _reset_config_cache()
    monkeypatch.setattr(
        config_module,
        "resolve_llm_runtime_config",
        lambda: ResolvedLLMConfig(
            model="gpt-global",
            provider_name="openai",
            provider_mode="standard",
            binding_hint="openai",
            binding="openai",
            api_key="sk-global",
            base_url="https://global.example/v1",
            effective_url="https://global.example/v1",
            api_version=None,
            extra_headers={},
            reasoning_effort=None,
            context_window=None,
        ),
    )
    global_cfg = config_module.get_llm_config()
    scoped_cfg = global_cfg.model_copy(update={"model": "gpt-scoped"})

    token = config_module.set_scoped_llm_config(scoped_cfg)
    try:
        assert config_module.get_llm_config().model == "gpt-scoped"
    finally:
        config_module.reset_scoped_llm_config(token)

    assert config_module.get_llm_config().model == "gpt-global"


def test_initialize_environment_sets_openai_env(monkeypatch) -> None:
    """initialize_environment should set OPENAI env vars from resolver output."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    monkeypatch.setattr(
        config_module,
        "resolve_llm_runtime_config",
        lambda: ResolvedLLMConfig(
            model="gpt-4o-mini",
            provider_name="openai",
            provider_mode="standard",
            binding_hint="openai",
            binding="openai",
            api_key="test-key",
            base_url="https://example.com/v1",
            effective_url="https://example.com/v1",
            api_version=None,
            extra_headers={},
            reasoning_effort=None,
            context_window=None,
        ),
    )
    config_module.initialize_environment()
    assert os.environ["OPENAI_API_KEY"] == "test-key"
    assert os.environ["OPENAI_BASE_URL"] == "https://example.com/v1"


def test_initialize_environment_skips_openai_env_for_custom_anthropic(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    monkeypatch.setattr(
        config_module,
        "resolve_llm_runtime_config",
        lambda: ResolvedLLMConfig(
            model="claude-sonnet-4-20250514",
            provider_name="custom_anthropic",
            provider_mode="direct",
            binding_hint="custom_anthropic",
            binding="custom_anthropic",
            api_key="anthropic-key",
            base_url="https://claude-proxy.example/v1",
            effective_url="https://claude-proxy.example/v1",
            api_version=None,
            extra_headers={},
            reasoning_effort=None,
            context_window=None,
        ),
    )
    config_module.initialize_environment()
    assert "OPENAI_API_KEY" not in os.environ
    assert "OPENAI_BASE_URL" not in os.environ


def test_resolver_missing_model_raises(monkeypatch) -> None:
    _reset_config_cache()

    monkeypatch.setattr(
        config_module,
        "resolve_llm_runtime_config",
        lambda: ResolvedLLMConfig(
            model="",
            provider_name="openai",
            provider_mode="standard",
            binding_hint="openai",
            binding="openai",
            api_key="test-key",
            base_url="https://example.com/v1",
            effective_url="https://example.com/v1",
            api_version=None,
            extra_headers={},
            reasoning_effort=None,
            context_window=None,
        ),
    )
    with pytest.raises(LLMConfigError):
        config_module.get_llm_config()
