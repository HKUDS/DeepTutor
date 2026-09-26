"""Utility helpers for the math animator pipeline."""

from __future__ import annotations

import re

from deeptutor.agents._shared.json_output import extract_json_object
from deeptutor.services.llm import StreamOutcome
from deeptutor.services.llm.utils import clean_thinking_tags


def slugify_filename(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", (value or "").strip()).strip("-")
    return cleaned or fallback


def trim_error_message(stderr: str, limit: int = 1200) -> str:
    text = (stderr or "").strip()
    if len(text) <= limit:
        return text
    return text[-limit:]


def build_repair_error_message(error_message: str) -> str:
    text = (error_message or "").strip()
    lowered = text.lower()
    hints: list[str] = []

    if "append_points" in lowered and "shape (1,2)" in lowered and "shape (1,3)" in lowered:
        hints.append(
            "Detected a 2D-to-3D point mismatch in Manim. Every point array passed into "
            "Line/Polygon/VMobject/set_points_as_corners/append_points must be 3D."
        )
        hints.append(
            "Replace points like [x, y] or np.array([x, y]) with [x, y, 0] or np.array([x, y, 0])."
        )
        hints.append(
            "If coordinates come from axes or planes, prefer axes.c2p(...) / plane.c2p(...) so Manim receives 3D points."
        )
        hints.append(
            "Check any custom point lists, helper lines, braces, polygons, or manually assembled VMobject paths."
        )

    if not hints:
        return text

    return text + "\n\nTargeted repair hints:\n- " + "\n- ".join(hints)


def describe_unusable_output(
    *,
    error: Exception | None,
    raw_response: str,
    outcome: StreamOutcome,
    max_tokens: int,
) -> str:
    """Name which of the three code-generation failures actually happened.

    Truncated output, an empty response and malformed JSON all used to surface
    as the same "no usable code" message with the parse error only in the
    traceback, so nobody could tell them apart without patching the file
    (#1545). The three read very differently to whoever has to act: only the
    first one is fixed by raising the budget.
    """

    thinking_chars = max(0, len(raw_response) - len(clean_thinking_tags(raw_response)))
    shape = f"{len(raw_response)} chars"
    if thinking_chars:
        shape += f", {thinking_chars} of them chain-of-thought"
    reason = (outcome.finish_reason or "none").strip() or "none"
    if outcome.truncated:
        reported = ", ".join(
            f"{key}={outcome.usage[key]}"
            for key in ("completion_tokens", "reasoning_tokens")
            if key in outcome.usage
        )
        detail = f"finish_reason={reason}" + (f", {reported}" if reported else "")
        return (
            f"the response ({shape}) was cut off at the {max_tokens}-token output cap "
            f"({detail}), so the code JSON never completed — raise the math animator's "
            "max tokens in Settings → Capabilities, or pick a model that reasons less"
        )
    if not raw_response.strip():
        return f"the model returned no text at all (finish_reason={reason})"
    return f"the response ({shape}) contained no usable JSON object: {error}"


def escalated_max_tokens(base: int, truncations: int) -> int:
    """Grow the output budget after a truncation instead of repeating it.

    Retrying a truncated generation on the same budget is deterministic waste —
    9 attempts, 21 minutes, same ending (#1547). The growth is capped at twice
    the configured budget because a ``max_tokens`` above the model's own output
    limit is rejected outright, which would turn a truncated answer into no
    answer at all.
    """

    if base <= 0 or truncations <= 0:
        return base
    return min(int(base * 2), int(base * 1.5**truncations))


__all__ = [
    "build_repair_error_message",
    "describe_unusable_output",
    "escalated_max_tokens",
    "extract_json_object",
    "slugify_filename",
    "trim_error_message",
]
