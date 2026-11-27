"""Cap a request's output-token budget to what the model can return.

Budgets in agents.yaml are ceilings chosen for the task (visualize asks for
32k so a reasoning model has room to think and still write the page). Sent
as-is, a budget above the model's output limit is rejected with HTTP 400, and
on a local server the prompt plus the budget must fit in the context window.
So every request carries ``min(budget, model output limit, window // 2)``.

``KNOWN_OUTPUT_LIMITS`` lists models whose output limit is below the budgets
DeepTutor uses (values from models.dev, 2026-11-27). Models not listed are
sent the budget unchanged.
"""

from __future__ import annotations

import re

KNOWN_OUTPUT_LIMITS: dict[str, int] = {
    "gpt-3.5-turbo": 4096,
    "gpt-4": 8192,
    "gpt-4-turbo": 4096,
    "gpt-4o": 16384,
    # The first gpt-4o snapshot predates the 16k output limit.
    "gpt-4o-2024-05-13": 4096,
    "gpt-4o-mini": 16384,
    "gpt-4.1": 32768,
    "gpt-4.1-mini": 32768,
    "gpt-4.1-nano": 32768,
    "glm-4.5v": 16384,
    "glm-4.6v": 32768,
    "qwen-max": 8192,
    "qwen-plus": 32768,
    "qwen-flash": 32768,
    "gemma-4-26b-a4b-it": 32768,
    "gemma-4-31b-it": 32768,
}


def known_output_limit(model: str) -> int | None:
    """Output limit for ``model``, accepting a provider prefix or a dated id."""
    name = (model or "").strip().lower()
    for candidate in (name, name.rsplit("/", 1)[-1]):
        if candidate in KNOWN_OUTPUT_LIMITS:
            return KNOWN_OUTPUT_LIMITS[candidate]
        undated = re.sub(r"-\d{4}-?\d{2}-?\d{2}$", "", candidate)
        if undated in KNOWN_OUTPUT_LIMITS:
            return KNOWN_OUTPUT_LIMITS[undated]
    return None


def cap_output_tokens(
    max_tokens: int, *, model: str | None, context_window: int | None = None
) -> int:
    """The budget to send: the configured one, lowered to fit the model.

    ``context_window`` is the window the user configured or that was detected
    for this model (not a guessed fallback); half of it is left for the prompt.
    """
    capped = int(max_tokens)
    limit = known_output_limit(model or "")
    if limit:
        capped = min(capped, limit)
    if context_window and context_window > 0:
        capped = min(capped, max(1, int(context_window) // 2))
    return capped


__all__ = ["KNOWN_OUTPUT_LIMITS", "cap_output_tokens", "known_output_limit"]
