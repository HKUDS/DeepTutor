"""Tests for LLM capability helpers."""

from deeptutor.services.llm.capabilities import (
    get_capability,
    get_effective_temperature,
    has_thinking_tags,
    supports_response_format,
)


def test_model_override_capability() -> None:
    """Model overrides should take precedence over provider defaults."""
    assert supports_response_format("openai", "deepseek-reasoner") is False
    assert has_thinking_tags("openai", "deepseek-reasoner") is True


def test_gemma_response_format_disabled() -> None:
    """Gemma models do not support json_object response_format (only json_schema/text).

    LM Studio with gemma-4 and similar models returns a 400 error when
    response_format={"type": "json_object"} is used.  See issue #344.
    """
    assert supports_response_format("lm_studio", "gemma-4-e2b") is False
    assert supports_response_format("lm_studio", "gemma-3-4b") is False
    assert supports_response_format("lm_studio", "gemma-2-9b") is False
    # Other non-gemma local models should still support response_format
    assert supports_response_format("lm_studio", "mistral-7b") is True
    assert supports_response_format("lm_studio", "llama-3") is True


def test_capability_fallback_default() -> None:
    """Unknown provider should fall back to defaults and explicit values."""
    assert get_capability("unknown", "supports_streaming") is True
    assert get_capability("unknown", "nonexistent", default=False) is False


def test_effective_temperature_override() -> None:
    """Forced temperature overrides should be applied for reasoning models."""
    assert get_effective_temperature("openai", "gpt-5") == 1.0
    assert get_effective_temperature("openai", "gpt-4o", requested_temp=0.4) == 0.4
