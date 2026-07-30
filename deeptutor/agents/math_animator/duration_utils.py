"""Duration helpers for math animator prompts."""

from __future__ import annotations

import re

_SECOND_PATTERN = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s*(?:s|sec|secs|second|seconds|秒(?:钟)?)",
    re.IGNORECASE,
)
_MINUTE_PATTERN = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s*(?:min(?:ute)?s?|分钟|m(?![sS]))",
    re.IGNORECASE,
)


def parse_target_duration_seconds(text: str) -> float | None:
    """Parse explicit duration target from user text."""
    raw = str(text or "").strip()
    if not raw:
        return None

    candidates: list[float] = []
    for match in _SECOND_PATTERN.finditer(raw):
        try:
            candidates.append(float(match.group("value")))
        except (TypeError, ValueError):
            continue
    for match in _MINUTE_PATTERN.finditer(raw):
        try:
            candidates.append(float(match.group("value")) * 60.0)
        except (TypeError, ValueError):
            continue
    if not candidates:
        return None
    return max(candidates)
