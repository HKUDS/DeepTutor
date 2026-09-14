"""Terrain block – an interactive-map description and geographic markers.

Prompts live in ``deeptutor/book/prompts/{en,zh}/terrain.yaml``.
"""

from __future__ import annotations

import math
from typing import Any

from ..models import BlockType, SourceAnchor
from ._llm_writer import llm_json
from ._prompts import get_book_prompt, load_book_prompts
from .base import BlockContext, BlockGenerator, GenerationFailure


class TerrainGenerator(BlockGenerator):
    block_type = BlockType.TERRAIN

    async def _generate(
        self, ctx: BlockContext
    ) -> tuple[dict[str, Any], list[SourceAnchor], dict[str, Any]]:
        params = ctx.block.params
        chapter_title = str(params.get("chapter_title") or ctx.chapter.title)
        chapter_summary = str(params.get("chapter_summary") or ctx.chapter.summary)
        objectives = params.get("objectives") or ctx.chapter.learning_objectives
        focus = str(params.get("topic") or ctx.block.title or chapter_title)

        prompts = load_book_prompts("terrain", ctx.language)
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
            max_tokens=1400,
            temperature=0.2,
            language=ctx.language,
            expected_key="markers",
        )

        markers: list[dict[str, Any]] = []
        markers_raw = data.get("markers")
        if isinstance(markers_raw, list):
            for item in markers_raw[:12]:
                if not isinstance(item, dict):
                    continue
                try:
                    lat = float(item.get("lat"))
                    lng = float(item.get("lng"))
                except (TypeError, ValueError):
                    continue
                if not math.isfinite(lat) or not math.isfinite(lng):
                    continue
                if not -90 <= lat <= 90 or not -180 <= lng <= 180:
                    continue
                name = str(item.get("name") or "").strip().replace("<", "").replace(">", "")
                event = str(item.get("event") or "").strip().replace("<", "").replace(">", "")
                if not name:
                    continue
                markers.append(
                    {
                        "name": name[:160],
                        "lat": lat,
                        "lng": lng,
                        "event": event[:600],
                    }
                )
        if not markers:
            raise GenerationFailure("LLM did not return any valid terrain markers.")

        try:
            zoom = int(float(data.get("zoom", 4)))
        except (TypeError, ValueError):
            zoom = 4
        zoom = max(1, min(18, zoom))

        metadata = data.get("_metadata")
        return (
            {
                "title": str(data.get("title") or focus).strip()[:200],
                "description": str(data.get("description") or "").strip()[:1200],
                "zoom": zoom,
                "markers": markers,
            },
            [],
            metadata if isinstance(metadata, dict) else {},
        )


__all__ = ["TerrainGenerator"]
