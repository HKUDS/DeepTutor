"""Helpers for reasoning about model context-window budgets."""

from __future__ import annotations

from typing import Any

DEFAULT_CONTEXT_WINDOW_FALLBACK = 16_384
MAX_EFFECTIVE_CONTEXT_WINDOW = 1_000_000
LARGE_CONTEXT_MODEL_DEFAULT = 65_536
KNOWN_LARGE_CONTEXT_MARKERS = (
    "gpt-4.1",
    "gpt-4o",
    "gpt-5",
    "o1",
    "o3",
    "o4",
    "claude",
    "gemini",
    "qwen",
    "deepseek",
    "moonshot",
    "kimi",
)


def coerce_positive_int(value: Any) -> int | None:
    """Parse a positive integer from arbitrary input."""
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def looks_like_large_context_model(model: str) -> bool:
    """Return True when a model family is typically backed by a large window."""
    normalized = (model or "").strip().lower()
    return any(marker in normalized for marker in KNOWN_LARGE_CONTEXT_MARKERS)


def default_context_window_for_model(
    *,
    model: str,
    max_tokens: Any = None,
) -> int:
    """Return the fallback window used when no explicit model metadata exists."""
    if looks_like_large_context_model(model):
        return LARGE_CONTEXT_MODEL_DEFAULT
    output_limit = coerce_positive_int(max_tokens) or 4096
    return max(DEFAULT_CONTEXT_WINDOW_FALLBACK, output_limit * 4)


def resolve_effective_context_window(
    *,
    context_window: Any = None,
    model: str,
    max_tokens: Any = None,
) -> int:
    """Resolve the bounded history-planning window for the current model."""
    configured = coerce_positive_int(context_window)
    if configured is not None:
        return min(configured, MAX_EFFECTIVE_CONTEXT_WINDOW)
    return min(
        default_context_window_for_model(model=model, max_tokens=max_tokens),
        MAX_EFFECTIVE_CONTEXT_WINDOW,
    )


__all__ = [
    "DEFAULT_CONTEXT_WINDOW_FALLBACK",
    "MAX_EFFECTIVE_CONTEXT_WINDOW",
    "LARGE_CONTEXT_MODEL_DEFAULT",
    "KNOWN_LARGE_CONTEXT_MARKERS",
    "coerce_positive_int",
    "default_context_window_for_model",
    "looks_like_large_context_model",
    "resolve_effective_context_window",
]
