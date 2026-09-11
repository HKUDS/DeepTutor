"""Callout block – key idea / common pitfall / summary highlight.

Prompts live in ``deeptutor/book/prompts/{en,zh}/callout.yaml``.
"""

from __future__ import annotations

from typing import Any

from ..models import BlockType, SourceAnchor
from ._llm_writer import llm_text
from ._prompts import get_book_prompt, load_book_prompts
from .base import BlockContext, BlockGenerator, GenerationFailure

_VARIANT_LABELS = {
    "key_idea": ("Key Idea", "核心要点"),
    "common_pitfall": ("Watch Out", "常见误区"),
    "summary": ("Summary", "小结"),
    "tip": ("Tip", "小提示"),
}


class CalloutGenerator(BlockGenerator):
    block_type = BlockType.CALLOUT

    async def _generate(
        self, ctx: BlockContext
    ) -> tuple[dict[str, Any], list[SourceAnchor], dict[str, Any]]:
        params = ctx.block.params
        variant = str(params.get("variant") or "key_idea")
        labels = _VARIANT_LABELS.get(variant, _VARIANT_LABELS["key_idea"])
        label = labels[1] if ctx.language == "zh" else labels[0]

        chapter_title = params.get("chapter_title", ctx.chapter.title)
        chapter_summary = params.get("chapter_summary", ctx.chapter.summary)
        objectives = params.get("objectives") or ctx.chapter.learning_objectives

        prompts = load_book_prompts("callout", ctx.language)
        none_label = "(无)" if ctx.language == "zh" else "(none)"
        user_prompt = get_book_prompt(prompts, "user_template").format(
            chapter_title=chapter_title,
            chapter_summary=chapter_summary or none_label,
            objectives_inline="; ".join(objectives) or none_label,
            variant=variant,
            label=label,
        )
        body = await llm_text(
            user_prompt=user_prompt,
            system_prompt=get_book_prompt(prompts, "system"),
            max_tokens=250,
            temperature=0.5,
            language=ctx.language,
            reasoning_effort="none",
        )
        if not body.strip():
            raise GenerationFailure("LLM returned no visible callout content.")
        return (
            {"variant": variant, "label": label, "body": body},
            [],
            {},
        )


__all__ = ["CalloutGenerator"]
