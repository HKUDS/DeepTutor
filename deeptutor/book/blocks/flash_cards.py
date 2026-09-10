"""Flash-cards block – LLM-generated study cards.

Returns ``cards: [{front, back, hint}]`` ready for the frontend
``FlashCardsBlock`` component.

Prompts live in ``deeptutor/book/prompts/{en,zh}/flash_cards.yaml``.
"""

from __future__ import annotations

from typing import Any

from ..models import BlockType, SourceAnchor
from ._llm_writer import llm_json
from ._prompts import get_book_prompt, load_book_prompts
from .base import BlockContext, BlockGenerator, GenerationFailure


class FlashCardsGenerator(BlockGenerator):
    block_type = BlockType.FLASH_CARDS

    async def _generate(
        self, ctx: BlockContext
    ) -> tuple[dict[str, Any], list[SourceAnchor], dict[str, Any]]:
        params = ctx.block.params
        chapter_title = params.get("chapter_title", ctx.chapter.title)
        chapter_summary = params.get("chapter_summary", ctx.chapter.summary)
        objectives = params.get("objectives") or ctx.chapter.learning_objectives
        count = max(3, min(8, int(params.get("count") or 5)))

        prompts = load_book_prompts("flash_cards", ctx.language)
        none_label = "(无)" if ctx.language == "zh" else "(none)"
        system_prompt = get_book_prompt(prompts, "system_template").format(count=count)
        user_prompt = get_book_prompt(prompts, "user_template").format(
            chapter_title=chapter_title,
            chapter_summary=chapter_summary or none_label,
            objectives_inline="; ".join(objectives) or none_label,
        )
        data = await llm_json(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            max_tokens=900,
            temperature=0.4,
            language=ctx.language,
            expected_key="cards",
            reasoning_effort="none",
        )
        cards_raw = data.get("cards") if isinstance(data, dict) else None
        cards: list[dict[str, str]] = []
        if isinstance(cards_raw, list):
            for item in cards_raw[:count]:
                if not isinstance(item, dict):
                    continue
                front = str(item.get("front") or "").strip()
                back = str(item.get("back") or "").strip()
                if not front or not back:
                    continue
                cards.append(
                    {
                        "front": front[:300],
                        "back": back[:600],
                        "hint": str(item.get("hint") or "").strip()[:200],
                    }
                )
        if not cards:
            raise GenerationFailure("LLM did not return any flashcards.")
        return (
            {"cards": cards},
            [],
            data.get("_metadata") if isinstance(data.get("_metadata"), dict) else {},
        )


__all__ = ["FlashCardsGenerator"]
