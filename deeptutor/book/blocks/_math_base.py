"""Shared base for the 8 ported math-interactive block generators.

These generators are near-identical in shape (read chapter context -> LLM JSON
-> validate -> payload), so they share a common skeleton here. Each subclass
declares its ``BlockType``, prompt bundle name, expected JSON key, and a
``build_payload`` hook that turns the LLM object into the renderer payload.
"""

from __future__ import annotations

from typing import Any

from ..models import SourceAnchor
from ._llm_writer import llm_json
from ._prompts import get_book_prompt, load_book_prompts
from .base import BlockContext, BlockGenerator, GenerationFailure


class MathBlockGenerator(BlockGenerator):
    """Skeleton for ported math blocks (desmos/geometry/geogebra/...)."""

    prompt_name: str = ""
    expected_key: str | None = None
    max_tokens: int = 1200
    temperature: float = 0.3

    async def _generate(
        self, ctx: BlockContext
    ) -> tuple[dict[str, Any], list[SourceAnchor], dict[str, Any]]:
        params = ctx.block.params
        chapter_title = str(params.get("chapter_title") or ctx.chapter.title)
        chapter_summary = str(params.get("chapter_summary") or ctx.chapter.summary)
        objectives = params.get("objectives") or ctx.chapter.learning_objectives
        focus = str(params.get("topic") or ctx.block.title or chapter_title)

        prompts = load_book_prompts(self.prompt_name, ctx.language)
        none_label = "(无)" if ctx.language == "zh" else "(none)"
        user_prompt = get_book_prompt(prompts, "user_template").format(
            chapter_title=chapter_title,
            chapter_summary=chapter_summary or none_label,
            objectives_inline="; ".join(str(item) for item in objectives) or none_label,
            focus=focus or none_label,
        )
        data = await llm_json(
            user_prompt=user_prompt,
            system_prompt=get_book_prompt(prompts, "system"),
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            language=ctx.language,
            expected_key=self.expected_key,
        )

        payload = self.build_payload(data, focus)
        metadata = data.get("_metadata")
        return payload, [], metadata if isinstance(metadata, dict) else {}

    def build_payload(self, data: dict[str, Any], focus: str) -> dict[str, Any]:
        raise NotImplementedError


__all__ = ["MathBlockGenerator", "GenerationFailure"]
