"""Tests for LLM capability helpers."""

from src.services.llm.capabilities import (
    get_capability,
    get_effective_temperature,
    has_thinking_tags,
    supports_response_format,
)


def test_model_override_capability() -> None:
    """Model overrides should take precedence over provider defaults."""
    assert supports_response_format("openai", "deepseek-reasoner") is False
    assert has_thinking_tags("openai", "deepseek-reasoner") is True


def test_capability_fallback_default() -> None:
    """Unknown provider should fall back to defaults and explicit values."""
    assert get_capability("unknown", "supports_streaming") is True
    assert get_capability("unknown", "nonexistent", default=False) is False


def test_effective_temperature_override() -> None:
    """Forced temperature overrides should be applied for reasoning models."""
    assert get_effective_temperature("openai", "gpt-5") == 1.0
    assert get_effective_temperature("openai", "gpt-4o", requested_temp=0.4) == 0.4
