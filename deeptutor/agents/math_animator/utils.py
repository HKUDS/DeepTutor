"""Utility helpers for the math animator pipeline."""

from __future__ import annotations

import re

from deeptutor.agents._shared.json_output import extract_json_object


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


__all__ = [
    "build_repair_error_message",
    "extract_json_object",
    "slugify_filename",
    "trim_error_message",
]
