"""Learner-facing explanation text, separate from QTI scorer metadata."""

from __future__ import annotations

import re

_GUIDANCE_PREFIX = "Reactutor scorer guidance v1:"
_BLANK_SCORE = re.compile(r"^Blank\s+[^:]+:\s+.*\([^)]*_v\d+\)")


def readable_explanation(text: str) -> str:
    """Keep prose guidance without treating embedded metadata as authority.

    Older imports stored the entire scorer rubric in the explanation column.
    Use the same projection on read so those rows need no destructive rewrite.
    """
    prose = text.split(_GUIDANCE_PREFIX, 1)[0]
    prose = prose.split("Source QTI scoring rules (inert XML):", 1)[0]
    lines: list[str] = []
    for line in prose.splitlines():
        stripped = line.strip()
        if stripped.startswith("Reference answer:") or _BLANK_SCORE.match(stripped):
            continue
        if stripped.startswith("Scoring guidance:"):
            line = stripped.removeprefix("Scoring guidance:").lstrip()
        lines.append(line)
    return "\n".join(lines).strip()
