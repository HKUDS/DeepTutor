"""
Generation estimates
====================

What a book will cost to build, derived from the Section Architect's own
templates so the number cannot drift away from what actually gets generated.

Confirming a spine kicks off dozens of LLM calls and many minutes of work. The
reader deserves to know roughly what they are approving *before* they approve
it — and, having approved it, to recognise the shape of what comes back.

The API exposes the per-chapter *basis* rather than a single total, so the
editor can keep the estimate live while chapters are being added, removed, or
retyped without a round trip per keystroke.
"""

from __future__ import annotations

from .agents.page_planner import _TEMPLATES_V2
from .models import BlockType, ContentType, depth_scale

# Rough throughput of one block, end to end (prompt + generation + persist).
# Prose blocks dominate; the small structured ones are far quicker.
_SECONDS_PER_PROSE_BLOCK = 45.0
_SECONDS_PER_SUPPORT_BLOCK = 15.0

_PROSE_TYPES = frozenset({BlockType.SECTION, BlockType.TEXT})


def chapter_basis(depth: str | None = None) -> dict[str, dict[str, float]]:
    """Per-content-type cost of one chapter at *depth*.

    Returns ``{content_type: {"blocks": n, "words": n, "seconds": n}}``.
    """
    scale = depth_scale(depth)
    basis: dict[str, dict[str, float]] = {}

    for content_type, template in _TEMPLATES_V2.items():
        words = 0.0
        seconds = 0.0
        for block_type, params in template:
            target = params.get("target_words")
            if isinstance(target, (int, float)):
                words += float(target) * scale
            seconds += (
                _SECONDS_PER_PROSE_BLOCK
                if block_type in _PROSE_TYPES
                else _SECONDS_PER_SUPPORT_BLOCK
            )
        basis[content_type.value] = {
            "blocks": float(len(template)),
            "words": round(words),
            "seconds": round(seconds),
        }

    # The overview chapter is rendered deterministically from the spine — no
    # LLM, no wait. Reporting it as free is the honest answer.
    basis[ContentType.OVERVIEW.value] = {"blocks": 3.0, "words": 0.0, "seconds": 0.0}
    return basis


__all__ = ["chapter_basis"]
