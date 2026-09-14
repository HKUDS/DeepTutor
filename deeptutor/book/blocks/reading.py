"""Reading block – verbatim textbook canon; passthrough with zero LLM step.

Unlike ``user_note`` (a personal note card), ``reading`` carries the
textbook's own prose: same ``compile_now=false → READY`` guarantee, but the
payload is rendered as textbook content and may carry a 栏目 ``variant``
(e.g. 探究与分享 / 相关链接) plus a ``source_label`` for traceability.
"""

from __future__ import annotations

from typing import Any

from ..models import BlockType, SourceAnchor
from .base import BlockContext, BlockGenerator

_VALID_VARIANTS = {"prose", "activity", "link", "quote"}


class ReadingGenerator(BlockGenerator):
    block_type = BlockType.READING

    async def _generate(
        self, ctx: BlockContext
    ) -> tuple[dict[str, Any], list[SourceAnchor], dict[str, Any]]:
        params = ctx.block.params
        body = str(params.get("body") or "").strip()
        variant = str(params.get("variant") or "prose").strip().lower()
        if variant not in _VALID_VARIANTS:
            variant = "prose"
        return (
            {
                "format": "markdown",
                "body": body,
                "variant": variant,
                "source_label": str(params.get("source_label") or ""),
                "author": "textbook",
            },
            [],
            {},
        )


__all__ = ["ReadingGenerator"]
