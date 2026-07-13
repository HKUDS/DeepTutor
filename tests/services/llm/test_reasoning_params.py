"""Tests for the centralized reasoning-effort registry."""

from __future__ import annotations

import pytest

from deeptutor.services.llm.reasoning_params import (
    build_openai_compatible_reasoning_kwargs,
    default_reasoning_effort_for,
)


class TestDefaultReasoningEffortFor:
    """Single source of truth for the implicit per-provider/model effort."""

    @pytest.mark.parametrize(
        "model",
        [
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "gemini-2.5-flash-lite",
            "GEMINI-2.5-FLASH",
            "models/gemini-2.5-flash",
            "gemini-3.0-pro",
        ],
    )
    def test_gemini_thinking_models_default_to_none(self, model: str) -> None:
        assert default_reasoning_effort_for("gemini", model) == "none"

    @pytest.mark.parametrize(
        "model",
        ["gemini-1.5-flash", "gemini-1.5-pro", "gemini-2.0-flash"],
    )
    def test_gemini_legacy_models_unaffected(self, model: str) -> None:
        assert default_reasoning_effort_for("gemini", model) is None

    def test_other_providers_unaffected(self) -> None:
        assert default_reasoning_effort_for("openai", "gpt-5") is None
        assert default_reasoning_effort_for("deepseek", "deepseek-v4") is None
        assert default_reasoning_effort_for("dashscope", "qwen3-max") is None

    def test_missing_provider_or_model(self) -> None:
        assert default_reasoning_effort_for(None, "gemini-2.5-flash") is None
        assert default_reasoning_effort_for("gemini", None) is None
        assert default_reasoning_effort_for("", "") is None

    def test_provider_name_case_insensitive(self) -> None:
        assert default_reasoning_effort_for("Gemini", "gemini-2.5-flash") == "none"
        assert default_reasoning_effort_for("GEMINI", "gemini-2.5-flash") == "none"


class TestBuildOpenAICompatibleReasoningKwargsForGemini:
    """The OpenAI-compat helper consults the same registry."""

    def test_gemini_25_defaults_off_when_unspecified(self) -> None:
        kwargs = build_openai_compatible_reasoning_kwargs(
            spec=None, binding="gemini", model="gemini-2.5-flash", reasoning_effort=None
        )
        assert kwargs == {"reasoning_effort": "none"}

    def test_models_prefix_still_matches(self) -> None:
        kwargs = build_openai_compatible_reasoning_kwargs(
            spec=None,
            binding="gemini",
            model="models/gemini-2.5-flash",
            reasoning_effort=None,
        )
        assert kwargs == {"reasoning_effort": "none"}

    def test_explicit_effort_takes_precedence(self) -> None:
        kwargs = build_openai_compatible_reasoning_kwargs(
            spec=None,
            binding="gemini",
            model="gemini-2.5-flash",
            reasoning_effort="high",
        )
        assert kwargs == {"reasoning_effort": "high"}

    def test_gemini_15_left_untouched(self) -> None:
        kwargs = build_openai_compatible_reasoning_kwargs(
            spec=None,
            binding="gemini",
            model="gemini-1.5-flash",
            reasoning_effort=None,
        )
        assert kwargs == {}

    def test_openai_left_untouched(self) -> None:
        kwargs = build_openai_compatible_reasoning_kwargs(
            spec=None, binding="openai", model="gpt-4o", reasoning_effort=None
        )
        assert kwargs == {}
