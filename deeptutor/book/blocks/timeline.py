"""Timeline block – LLM-generated chronological events list.

Phase 2 implementation. Returns a structured list of events the frontend
renders as a vertical timeline.

Prompts live in ``deeptutor/book/prompts/{en,zh}/timeline.yaml``.
"""

from __future__ import annotations

from typing import Any

from ..models import BlockType, SourceAnchor
from ._llm_writer import llm_json
from ._prompts import get_book_prompt, load_book_prompts
from .base import BlockContext, BlockGenerator, GenerationFailure


class TimelineGenerator(BlockGenerator):
    block_type = BlockType.TIMELINE

    async def _generate(
        self, ctx: BlockContext
    ) -> tuple[dict[str, Any], list[SourceAnchor], dict[str, Any]]:
        params = ctx.block.params
        chapter_title = params.get("chapter_title", ctx.chapter.title)
        chapter_summary = params.get("chapter_summary", ctx.chapter.summary)

        prompts = load_book_prompts("timeline", ctx.language)
        none_label = "(无)" if ctx.language == "zh" else "(none)"
        user_prompt = get_book_prompt(prompts, "user_template").format(
            chapter_title=chapter_title,
            chapter_summary=chapter_summary or none_label,
        )
        data = await llm_json(
            user_prompt=user_prompt,
            system_prompt=get_book_prompt(prompts, "system"),
            max_tokens=800,
            temperature=0.4,
            language=ctx.language,
            expected_key="events",
            reasoning_effort="none",
        )
        events_raw = data.get("events") if isinstance(data, dict) else None
        events: list[dict[str, str]] = []
        if isinstance(events_raw, list):
            for item in events_raw[:8]:
                if not isinstance(item, dict):
                    continue
                events.append(
                    {
                        "date": str(item.get("date") or "")[:80],
                        "title": str(item.get("title") or "")[:160],
                        "description": str(item.get("description") or "")[:600],
                    }
                )
        if not events:
            raise GenerationFailure("LLM did not return any timeline events.")
        return (
            {"events": events},
            [],
            data.get("_metadata") if isinstance(data.get("_metadata"), dict) else {},
        )


__all__ = ["TimelineGenerator"]
