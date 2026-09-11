"""Shared text-window helpers for source-grounded reading extensions."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deeptutor.reading.extensions import ReadingContext

MAX_GROUNDING_CONTEXT_CHARS = 6_000


def normalized_with_map(value: str) -> tuple[str, list[int]]:
    """Collapse whitespace while retaining an index for every output character."""
    normalized: list[str] = []
    source_positions: list[int] = []
    for index, character in enumerate(value):
        if character.isspace():
            if normalized and normalized[-1] != " ":
                normalized.append(" ")
                source_positions.append(index)
            continue
        normalized.append(character)
        source_positions.append(index)
    if normalized and normalized[-1] == " ":
        normalized.pop()
        source_positions.pop()
    return "".join(normalized), source_positions


def selection_range(text: str, selection: str) -> tuple[int, int] | None:
    if not selection:
        return None
    exact = text.find(selection)
    if exact >= 0:
        return exact, exact + len(selection)

    normalized_text, positions = normalized_with_map(text)
    normalized_selection, _ = normalized_with_map(selection)
    if not normalized_selection:
        return None
    found = normalized_text.find(normalized_selection)
    if found < 0 or found + len(normalized_selection) > len(positions):
        return None
    start = positions[found]
    end = positions[found + len(normalized_selection) - 1] + 1
    return start, end


def grounding_context(
    text: str,
    selection: str,
    *,
    max_chars: int = MAX_GROUNDING_CONTEXT_CHARS,
) -> str:
    """Return a bounded source window centered on the verified selection."""
    if max_chars <= 0:
        return ""
    bounds = selection_range(text, selection) if selection else None
    if bounds is None or len(text) <= max_chars:
        return text[:max_chars]
    start, end = bounds
    midpoint = (start + end) // 2
    window_start = max(0, midpoint - max_chars // 2)
    window_end = min(len(text), window_start + max_chars)
    window_start = max(0, window_end - max_chars)
    return text[window_start:window_end]


def grounded_prompt(context: ReadingContext) -> str:
    """The user-turn payload every source-grounded reading extension sends.

    All four of them ask the same question of the same two fields — the
    selection, and a bounded window of the page around it — so they ask it
    in one place.
    """
    return json.dumps(
        {
            "selection": context.selection,
            "surrounding_context": grounding_context(
                context.visible_text,
                context.selection,
            ),
        },
        ensure_ascii=False,
    )


__all__ = [
    "MAX_GROUNDING_CONTEXT_CHARS",
    "grounded_prompt",
    "grounding_context",
    "normalized_with_map",
    "selection_range",
]
