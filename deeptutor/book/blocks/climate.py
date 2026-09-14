"""Climate block – monthly temperature and precipitation series.

Prompts live in ``deeptutor/book/prompts/{en,zh}/climate.yaml``.
"""

from __future__ import annotations

import math
from typing import Any

from ..models import BlockType, SourceAnchor
from ._llm_writer import llm_json
from ._prompts import get_book_prompt, load_book_prompts
from .base import BlockContext, BlockGenerator, GenerationFailure


def _finite_numbers(value: Any) -> list[float]:
    if not isinstance(value, list):
        return []
    numbers: list[float] = []
    for item in value[:12]:
        if isinstance(item, bool):
            return []
        try:
            number = float(item)
        except (TypeError, ValueError):
            return []
        if not math.isfinite(number):
            return []
        numbers.append(number)
    return numbers


class ClimateGenerator(BlockGenerator):
    block_type = BlockType.CLIMATE

    async def _generate(
        self, ctx: BlockContext
    ) -> tuple[dict[str, Any], list[SourceAnchor], dict[str, Any]]:
        params = ctx.block.params
        chapter_title = str(params.get("chapter_title") or ctx.chapter.title)
        chapter_summary = str(params.get("chapter_summary") or ctx.chapter.summary)
        objectives = params.get("objectives") or ctx.chapter.learning_objectives
        focus = str(params.get("topic") or ctx.block.title or chapter_title)

        prompts = load_book_prompts("climate", ctx.language)
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
            max_tokens=1200,
            temperature=0.2,
            language=ctx.language,
            expected_key="months",
        )

        months_raw = data.get("months")
        months = (
            [str(item).strip()[:40] for item in months_raw[:12] if str(item).strip()]
            if isinstance(months_raw, list)
            else []
        )
        temperature = _finite_numbers(data.get("temperature"))
        precipitation = _finite_numbers(data.get("precipitation"))
        if (
            not months
            or len(months) != len(temperature)
            or len(months) != len(precipitation)
        ):
            raise GenerationFailure(
                "LLM returned invalid climate series; months, temperature, and precipitation "
                "must be non-empty arrays of equal length."
            )

        metadata = data.get("_metadata")
        return (
            {
                "title": str(data.get("title") or focus).strip()[:200],
                "description": str(data.get("description") or "").strip()[:1200],
                "months": months,
                "temperature": temperature,
                "precipitation": precipitation,
            },
            [],
            metadata if isinstance(metadata, dict) else {},
        )


__all__ = ["ClimateGenerator"]
