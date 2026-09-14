"""Poetry block – original lines, pinyin, and concise annotations.

Prompts live in ``deeptutor/book/prompts/{en,zh}/poetry.yaml``.
"""

from __future__ import annotations

from typing import Any

from ..models import BlockType, SourceAnchor
from ._llm_writer import llm_json
from ._prompts import get_book_prompt, load_book_prompts
from .base import BlockContext, BlockGenerator, GenerationFailure


class PoetryGenerator(BlockGenerator):
    block_type = BlockType.POETRY

    async def _generate(
        self, ctx: BlockContext
    ) -> tuple[dict[str, Any], list[SourceAnchor], dict[str, Any]]:
        params = ctx.block.params
        chapter_title = str(params.get("chapter_title") or ctx.chapter.title)
        chapter_summary = str(params.get("chapter_summary") or ctx.chapter.summary)
        objectives = params.get("objectives") or ctx.chapter.learning_objectives
        focus = str(
            params.get("topic")
            or params.get("title")
            or ctx.block.title
            or chapter_title
        )

        prompts = load_book_prompts("poetry", ctx.language)
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
            temperature=0.3,
            language=ctx.language,
            expected_key="lines",
        )

        lines: list[dict[str, str]] = []
        lines_raw = data.get("lines")
        if isinstance(lines_raw, list):
            for item in lines_raw[:24]:
                if not isinstance(item, dict):
                    continue
                text = str(item.get("text") or "").strip()
                if not text:
                    continue
                lines.append(
                    {
                        "text": text[:200],
                        "pinyin": str(item.get("pinyin") or "").strip()[:300],
                    }
                )
        if not lines:
            raise GenerationFailure("LLM did not return any poetry lines.")

        annotations: list[dict[str, str]] = []
        annotations_raw = data.get("annotations")
        if isinstance(annotations_raw, list):
            for item in annotations_raw[:12]:
                if not isinstance(item, dict):
                    continue
                term = str(item.get("term") or "").strip()
                explanation = str(item.get("explanation") or "").strip()
                if term and explanation:
                    annotations.append(
                        {
                            "term": term[:80],
                            "explanation": explanation[:400],
                        }
                    )

        metadata = data.get("_metadata")
        return (
            {
                "title": str(data.get("title") or focus).strip()[:160],
                "author": str(data.get("author") or "").strip()[:80],
                "dynasty": str(data.get("dynasty") or "").strip()[:40],
                "lines": lines,
                "annotations": annotations,
            },
            [],
            metadata if isinstance(metadata, dict) else {},
        )


__all__ = ["PoetryGenerator"]
