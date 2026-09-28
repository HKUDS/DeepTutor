"""Helpers for reasoning about model context-window budgets."""

from __future__ import annotations

import re
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
    # xAI: grok-3/4+ all ship >=128k windows; without this, an un-annotated
    # model entry falls back to 16_384 and the agentic loop snips every tool
    # result (see context_window_guard in agents/loop/pipeline.py).
    "grok",
)


# Context capacities only; never output/input token limits. Snapshot of
# https://models.dev/api.json (2026-09-17), original provider entries.
# Provider metadata remains authoritative for deployment-specific limits.
KNOWN_CONTEXT_WINDOWS: dict[str, int] = {
    "claude-fable-5": 1000000,
    "claude-fable-5-1": 1000000,
    "claude-haiku-4-5": 200000,
    "claude-haiku-4-5-20251001": 200000,
    "claude-opus-4-5": 200000,
    "claude-opus-4-5-20251101": 200000,
    "claude-opus-4-6": 1000000,
    "claude-opus-4-7": 1000000,
    "claude-opus-4-8": 1000000,
    "claude-opus-5": 1000000,
    "claude-sonnet-4-5": 1000000,
    "claude-sonnet-4-5-20250929": 1000000,
    "claude-sonnet-4-6": 1000000,
    "claude-sonnet-5": 1000000,
    "deepseek-flash": 1000000,
    "deepseek-v4": 1000000,
    "deepseek-v4-flash": 1000000,
    "deepseek-v4-flash-vision-exp": 1000000,
    "deepseek-v4-pro": 1000000,
    "gemini-2.5-computer-use-preview-10-2025": 131072,
    "gemini-2.5-flash": 1048576,
    "gemini-2.5-flash-lite": 1048576,
    "gemini-2.5-pro": 1048576,
    "gemini-3-flash-preview": 1048576,
    "gemini-3.1-flash-lite": 1048576,
    "gemini-3.1-flash-lite-preview": 1048576,
    "gemini-3.1-pro-preview": 1048576,
    "gemini-3.1-pro-preview-customtools": 1048576,
    "gemini-3.5-flash": 1048576,
    "gemini-3.5-flash-lite": 1048576,
    "gemini-3.6-flash": 1048576,
    "gemini-3.7-flash": 1048576,
    "gemini-3.8-flash": 1048576,
    "gemini-flash-latest": 1048576,
    "gemini-flash-lite-latest": 1048576,
    "gemma-4-26b-a4b-it": 262144,
    "gemma-4-31b-it": 262144,
    "glm-4.5": 131072,
    "glm-4.5-air": 131072,
    "glm-4.5-flash": 131072,
    "glm-4.5v": 64000,
    "glm-4.6": 204800,
    "glm-4.6v": 128000,
    "glm-4.7": 204800,
    "glm-4.7-flash": 200000,
    "glm-4.7-flashx": 200000,
    "glm-5": 204800,
    "glm-5.1": 200000,
    "glm-5.2": 1000000,
    "glm-5.3": 1000000,
    "glm-5.3-flash": 1000000,
    "glm-5v-turbo": 200000,
    "gpt-3.5-turbo": 16385,
    "gpt-4": 8192,
    "gpt-4-turbo": 128000,
    "gpt-4.1": 1047576,
    "gpt-4.1-mini": 1047576,
    "gpt-4.1-nano": 1047576,
    "gpt-4o": 128000,
    "gpt-4o-2024-05-13": 128000,
    "gpt-4o-2024-08-06": 128000,
    "gpt-4o-2024-11-20": 128000,
    "gpt-4o-mini": 128000,
    "gpt-5": 400000,
    "gpt-5-mini": 400000,
    "gpt-5-nano": 400000,
    "gpt-5-pro": 400000,
    "gpt-5.1": 400000,
    "gpt-5.2": 400000,
    "gpt-5.2-chat-latest": 128000,
    "gpt-5.2-pro": 400000,
    "gpt-5.3-chat-latest": 128000,
    "gpt-5.3-codex": 400000,
    "gpt-5.3-codex-spark": 128000,
    "gpt-5.4": 1050000,
    "gpt-5.4-mini": 400000,
    "gpt-5.4-nano": 400000,
    "gpt-5.4-pro": 1050000,
    "gpt-5.5": 1050000,
    "gpt-5.5-pro": 1050000,
    "gpt-5.6": 1050000,
    "gpt-5.6-luna": 1050000,
    "gpt-5.6-sol": 1050000,
    "gpt-5.6-terra": 1050000,
    "gpt-6-astra": 1050000,
    "kimi-k2.6": 262144,
    "kimi-k2.7-code": 262144,
    "kimi-k2.7-code-highspeed": 262144,
    "kimi-k3": 1048576,
    "minimax-m2": 204800,
    "minimax-m2.1": 204800,
    "minimax-m2.5": 204800,
    "minimax-m2.5-highspeed": 204800,
    "minimax-m2.7": 204800,
    "minimax-m2.7-highspeed": 204800,
    "minimax-m3": 1000000,
    "o1": 200000,
    "o1-pro": 200000,
    "o3": 200000,
    "o3-mini": 200000,
    "o3-pro": 200000,
    "o4-mini": 200000,
    "text-embedding-3-large": 8191,
    "text-embedding-3-small": 8191,
    "text-embedding-ada-002": 8192,
}


def known_context_window(model: str) -> int | None:
    name = (model or "").strip().lower()
    # Provider namespaces are allowed; quantization tags are NOT model aliases.
    names = [name, name.rsplit("/", 1)[-1]]
    for candidate in names:
        if candidate in KNOWN_CONTEXT_WINDOWS:
            return KNOWN_CONTEXT_WINDOWS[candidate]
        dated = re.sub(r"-\d{4}-?\d{2}-?\d{2}$", "", candidate)
        if dated in KNOWN_CONTEXT_WINDOWS:
            return KNOWN_CONTEXT_WINDOWS[dated]
    return None


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
    known = known_context_window(model)
    if known is not None:
        return known
    # Output limits cannot tell us the input + output context capacity.
    return (
        LARGE_CONTEXT_MODEL_DEFAULT
        if looks_like_large_context_model(model)
        else DEFAULT_CONTEXT_WINDOW_FALLBACK
    )


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
