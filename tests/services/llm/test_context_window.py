"""Fallback window heuristics for un-annotated model names."""

from __future__ import annotations

from deeptutor.services.llm.context_window import (
    DEFAULT_CONTEXT_WINDOW_FALLBACK,
    LARGE_CONTEXT_MODEL_DEFAULT,
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
