"""Tests for uses_max_completion_tokens and get_token_limit_kwargs.

Covers the bug fix for issue #274 (o4-mini / o4 model detection) and
protects against future regressions when new model families are released.
"""

from __future__ import annotations

import pytest

from deeptutor.services.llm.config import get_token_limit_kwargs, uses_max_completion_tokens


# ── o-series reasoning models (require max_completion_tokens) ────────


@pytest.mark.parametrize(
    "model",
    [
        "o1",
        "o1-mini",
        "O1-preview",  # case-insensitivity check
        "o1-2024-12-17",
    ],
    ids=lambda m: m,
)
def test_o1_models_use_max_completion_tokens(model: str) -> None:
    assert uses_max_completion_tokens(model) is True


@pytest.mark.parametrize(
    "model",
    ["o3", "O3-MINI", "o3-mini-2025-01-31"],
    ids=lambda m: m,
)
def test_o3_models_use_max_completion_tokens(model: str) -> None:
    assert uses_max_completion_tokens(model) is True


@pytest.mark.parametrize(
    "model",
    ["o4-mini", "o4", "O4-mini-2025-04-16"],
    ids=lambda m: m,
)
def test_o4_models_use_max_completion_tokens(model: str) -> None:
    """Regression test for issue #274 — o4 models were previously missed."""
    assert uses_max_completion_tokens(model) is True


# ── gpt-4o series (require max_completion_tokens) ───────────────────


@pytest.mark.parametrize(
    "model",
    ["gpt-4o", "GPT-4O-MINI", "gpt-4o-2024-08-06"],
    ids=lambda m: m,
)
def test_gpt4o_models_use_max_completion_tokens(model: str) -> None:
    assert uses_max_completion_tokens(model) is True


# ── Future gpt-5+ models (require max_completion_tokens) ────────────


@pytest.mark.parametrize(
    "model",
    ["gpt-5", "GPT-5-turbo", "gpt-9", "gpt-10", "gpt-10-mini", "gpt-42"],
    ids=lambda m: m,
)
def test_gpt5_and_future_models_use_max_completion_tokens(model: str) -> None:
    assert uses_max_completion_tokens(model) is True


# ── Legacy models (use max_tokens) ──────────────────────────────────


@pytest.mark.parametrize(
    "model",
    [
        "gpt-3.5-turbo",
        "gpt-4",
        "gpt-4-turbo",
        "gpt-4-1106-preview",
        "claude-3-opus",
        "deepseek-chat",
        "mistral-large",
        "qwen-max",
        "",  # edge case empty string
        "openai/o4-mini",  # provider prefix should strictly fail
    ],
    ids=lambda m: m,
)
def test_legacy_models_do_not_use_max_completion_tokens(model: str) -> None:
    assert uses_max_completion_tokens(model) is False


# ── get_token_limit_kwargs integration tests ────────────────────────


def test_get_token_limit_kwargs_returns_max_completion_tokens_for_new_model() -> None:
    result = get_token_limit_kwargs("o4-mini", 4096)
    assert result == {"max_completion_tokens": 4096}


def test_get_token_limit_kwargs_returns_max_tokens_for_legacy_model() -> None:
    result = get_token_limit_kwargs("gpt-4", 4096)
    assert result == {"max_tokens": 4096}
