"""Fallback window heuristics for un-annotated model names."""

from __future__ import annotations

import pytest

from deeptutor.services.llm.context_window import (
    DEFAULT_CONTEXT_WINDOW_FALLBACK,
    LARGE_CONTEXT_MODEL_DEFAULT,
    MAX_EFFECTIVE_CONTEXT_WINDOW,
    known_context_window,
    looks_like_large_context_model,
    resolve_effective_context_window,
)


def test_grok_is_treated_as_a_large_context_family() -> None:
    """Un-annotated grok names must not fall back to the 16k default.

    The agentic loop's context-window guard snips every tool result once the
    estimated history exceeds 90% of the resolved window. A 16k guess on a
    128k+ Grok model therefore empties every tool payload and the model
    re-calls the same tool forever.
    """
    assert looks_like_large_context_model("grok-4.6") is True
    assert looks_like_large_context_model("grok-4") is True
    window = resolve_effective_context_window(model="grok-4.6")
    assert window == LARGE_CONTEXT_MODEL_DEFAULT
    assert window > DEFAULT_CONTEXT_WINDOW_FALLBACK


def test_unknown_model_still_uses_the_small_fallback() -> None:
    assert looks_like_large_context_model("mystery-7b") is False
    assert resolve_effective_context_window(model="mystery-7b") == (DEFAULT_CONTEXT_WINDOW_FALLBACK)


def test_explicit_catalog_window_wins_over_the_family_heuristic() -> None:
    assert resolve_effective_context_window(context_window=500_000, model="grok-4.6") == 500_000


@pytest.mark.parametrize("model", ["gpt-6-luna", "gpt-6-sol", "gpt-6.1-sol", "gpt-6.1-terra"])
def test_published_gpt6_windows_and_catalog_override(model: str) -> None:
    assert known_context_window(model) == 1_050_000
    assert known_context_window(f"openai/{model}") == 1_050_000
    assert resolve_effective_context_window(model=model) == MAX_EFFECTIVE_CONTEXT_WINDOW
    assert resolve_effective_context_window(model=model, context_window=500_000) == 500_000
