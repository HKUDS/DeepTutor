"""Tests for LLM configuration helpers."""

from __future__ import annotations

import os
import sys

import pytest

from src.services.llm import config as config_module
from src.services.llm.config import LLMConfig
from src.services.llm.exceptions import LLMConfigError


def _reset_config_cache() -> None:
    config_module._LLM_CONFIG_CACHE = None


def test_get_llm_config_from_env(monkeypatch) -> None:
    """Environment-based config loading should populate required fields."""
    _reset_config_cache()
    fake_module = type("_Config", (), {"get_active_llm_config": lambda: None})
    monkeypatch.setitem(sys.modules, "src.services.config", fake_module)
    monkeypatch.setenv("LLM_MODEL", "gpt-test")
    monkeypatch.setenv("LLM_HOST", "https://api.openai.com")
    monkeypatch.setenv("LLM_API_KEY", "key")

    config = config_module.get_llm_config()

    assert isinstance(config, LLMConfig)
    assert config.model == "gpt-test"
    assert config.base_url == "https://api.openai.com"
    assert config.api_key == "key"


def test_initialize_environment_sets_openai_env(monkeypatch) -> None:
    """initialize_environment should set OpenAI env vars for compatible bindings."""
    monkeypatch.setenv("LLM_BINDING", "openai")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_HOST", "https://example.com")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    config_module.initialize_environment()

    assert os.environ["OPENAI_API_KEY"] == "test-key"
    assert os.environ["OPENAI_BASE_URL"] == "https://example.com"


def test_strip_value_handles_quotes() -> None:
    """_strip_value should remove surrounding quotes and whitespace."""
    assert config_module._strip_value(" 'value' ") == "value"


def test_get_llm_config_missing_env(monkeypatch) -> None:
    """Missing required env values should raise LLMConfigError."""
    _reset_config_cache()
    monkeypatch.setenv("LLM_MODEL", "")
    monkeypatch.setenv("LLM_HOST", "")
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("LLM_BINDING", "openai")

    fake_module = type("_Config", (), {"get_active_llm_config": lambda: None})
    monkeypatch.setitem(sys.modules, "src.services.config", fake_module)

    with pytest.raises(LLMConfigError):
        config_module.get_llm_config()
