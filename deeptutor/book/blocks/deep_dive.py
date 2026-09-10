"""Deep-dive block – Phase 3 implementation.

Renders a "Go deeper" call-to-action card. The actual sub-page is created on
demand by the BookEngine (``create_deep_dive_subpage``) when the user clicks
the card; we only emit suggested topics here so the page reader can render
the affordance.

Prompts live in ``deeptutor/book/prompts/{en,zh}/deep_dive.yaml``.
"""

from __future__ import annotations

from typing import Any

from ..models import BlockType, SourceAnchor
from ._llm_writer import llm_json
from ._prompts import get_book_prompt, load_book_prompts
from .base import BlockContext, BlockGenerator, GenerationFailure


class DeepDiveGenerator(BlockGenerator):
    block_type = BlockType.DEEP_DIVE

    async def _generate(
        self, ctx: BlockContext
    ) -> tuple[dict[str, Any], list[SourceAnchor], dict[str, Any]]:
        params = ctx.block.params
        chapter_title = params.get("chapter_title", ctx.chapter.title)
        chapter_summary = params.get("chapter_summary", ctx.chapter.summary)

        prompts = load_book_prompts("deep_dive", ctx.language)
        none_label = "(无)" if ctx.language == "zh" else "(none)"
        user_prompt = get_book_prompt(prompts, "user_template").format(
            chapter_title=chapter_title,
            chapter_summary=chapter_summary or none_label,
        )
        data = await llm_json(
            user_prompt=user_prompt,
            system_prompt=get_book_prompt(prompts, "system"),
            max_tokens=500,
            temperature=0.4,
            language=ctx.language,
            expected_key="suggestions",
            reasoning_effort="none",
        )
        suggestions_raw = data.get("suggestions") if isinstance(data, dict) else None
        suggestions: list[dict[str, str]] = []
        if isinstance(suggestions_raw, list):
            for item in suggestions_raw[:5]:
                if not isinstance(item, dict):
                    continue
                topic = str(item.get("topic") or "").strip()
                if not topic:
                    continue
                suggestions.append(
                    {
                        "topic": topic[:160],
                        "rationale": str(item.get("rationale") or "").strip()[:300],
                    }
                )
        if not suggestions:
            raise GenerationFailure("LLM returned no deep-dive suggestions.")
        return (
            {"suggestions": suggestions},
            [],
            data.get("_metadata") if isinstance(data.get("_metadata"), dict) else {},
        )


__all__ = ["DeepDiveGenerator"]
