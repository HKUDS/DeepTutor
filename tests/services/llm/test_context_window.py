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


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("k3", 1_048_576),
        ("k3-256k", 262_144),
        ("k3.1-pro", 1_048_576),
        ("k3.1-pro-highspeed", 1_048_576),
        ("kimi-for-coding", 1_048_576),
        ("kimi-for-coding-highspeed", 262_144),
        ("moonshot/k3-256k", 262_144),
    ],
)
def test_moonshot_k3_family_windows(model: str, expected: int) -> None:
    """The ids Moonshot's coding endpoint advertises must resolve exactly."""
    assert known_context_window(model) == expected
    # The planner clamps to its own ceiling; the table stays the provider value.
    assert resolve_effective_context_window(model=model) == min(
        expected, MAX_EFFECTIVE_CONTEXT_WINDOW
    )


def test_moonshot_k3_names_do_not_fall_back_to_the_small_window() -> None:
    """A bare ``k3-256k`` id carries no "kimi"/"moonshot" marker.

    It used to resolve to ``DEFAULT_CONTEXT_WINDOW_FALLBACK`` (16_384), which
    caps the history plan at 5_734 tokens: any tool-heavy exchange then
    overflowed the plan with no complete exchange left to drop, and the turn
    failed with ``HistoryBudgetExceeded`` instead of compacting.
    """
    for model in ("k3", "k3-256k", "k3.1-pro"):
        window = resolve_effective_context_window(model=model)
        assert window > DEFAULT_CONTEXT_WINDOW_FALLBACK
        assert window == min(known_context_window(model), MAX_EFFECTIVE_CONTEXT_WINDOW)


def test_un_annotated_k3_variant_keeps_a_large_window() -> None:
    """Future K3 ids without a table entry must not drop to the 16k guess."""
    assert looks_like_large_context_model("k3.2-flash") is True
    assert resolve_effective_context_window(model="k3.2-flash") == LARGE_CONTEXT_MODEL_DEFAULT
