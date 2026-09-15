"""Retrieval-practice block — YuEdu error loop (提取练习).

Short recall questions on what the learner just read. When the learner's
mastery path carries a KP-bound question bank
(``kp.meta["question_bank"]``), the real bank items are used verbatim —
the model never re-invents them. With no bank attached, the LLM drafts a
small practice set and the payload is marked ``generated: true`` so the
reader can tell it apart from bank material.

Prompts live in ``deeptutor/book/prompts/{en,zh}/retrieval_practice.yaml``.
"""

from __future__ import annotations

from typing import Any

from ..models import BlockType, SourceAnchor
from ._learning_data import load_kp_question_banks, pick_bank_items
from ._llm_writer import llm_json
from ._prompts import get_book_prompt, load_book_prompts
from .base import BlockContext, BlockGenerator, GenerationFailure


class RetrievalPracticeGenerator(BlockGenerator):
    block_type = BlockType.RETRIEVAL_PRACTICE

    async def _generate(
        self, ctx: BlockContext
    ) -> tuple[dict[str, Any], list[SourceAnchor], dict[str, Any]]:
        params = ctx.block.params
        chapter_title = params.get("chapter_title", ctx.chapter.title)
        chapter_summary = params.get("chapter_summary", ctx.chapter.summary)
        objectives = params.get("objectives") or ctx.chapter.learning_objectives
        count = _clamp_count(params.get("count"), default=5)

        # D4 hard rule: a bound question bank always wins over model-drafted
        # questions. `ctx.extra` is the injection point (same pattern as the
        # concept_graph block); the store read is the fail-open fallback.
        entries = ctx.extra.get("kp_question_banks") or load_kp_question_banks(ctx.book_id)
        items = pick_bank_items(entries, count)
        if items:
            kp_names = sorted({str(item["kp_name"]) for item in items if item.get("kp_name")})
            return (
                {"items": items, "source": "question_bank", "kp_names": kp_names},
                [],
                {},
            )

        return await self._llm_fallback(
            ctx,
            chapter_title=str(chapter_title),
            chapter_summary=str(chapter_summary or ""),
            objectives=[str(o) for o in objectives],
            count=count,
        )

    async def _llm_fallback(
        self,
        ctx: BlockContext,
        *,
        chapter_title: str,
        chapter_summary: str,
        objectives: list[str],
        count: int,
    ) -> tuple[dict[str, Any], list[SourceAnchor], dict[str, Any]]:
        prompts = load_book_prompts("retrieval_practice", ctx.language)
        none_label = "(无)" if ctx.language == "zh" else "(none)"
        user_prompt = get_book_prompt(prompts, "user_template").format(
            chapter_title=chapter_title,
            chapter_summary=chapter_summary or none_label,
            objectives_inline="; ".join(objectives) or none_label,
            count_line=get_book_prompt(prompts, "count_line").format(count=count),
        )
        data = await llm_json(
            user_prompt=user_prompt,
            system_prompt=get_book_prompt(prompts, "system"),
            max_tokens=1600,
            temperature=0.4,
            language=ctx.language,
            expected_key="items",
        )
        items = _normalise_items(data.get("items") if isinstance(data, dict) else None)
        if not items:
            raise GenerationFailure("LLM returned no retrieval-practice items.")
        items = items[:count]
        return (
            {
                "items": items,
                "source": "llm",
                # D4: LLM-drafted payload must be marked as generated, so the
                # reader never mistakes it for bound bank material.
                "generated": True,
            },
            [],
            data.get("_metadata") if isinstance(data.get("_metadata"), dict) else {},
        )


def _clamp_count(value: Any, *, default: int) -> int:
    try:
        return max(3, min(8, int(value)))
    except (TypeError, ValueError):
        return default


def _normalise_items(raw: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return items
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        question = str(entry.get("question") or "").strip()
        if not question:
            continue
        raw_options = entry.get("options")
        items.append(
            {
                "question": question[:2000],
                "question_type": str(entry.get("question_type") or "short").strip() or "short",
                "options": (
                    {str(k): str(v) for k, v in raw_options.items() if str(v).strip()}
                    if isinstance(raw_options, dict)
                    else {}
                ),
                "answer": str(entry.get("answer") or "").strip()[:500],
                "explanation": str(entry.get("explanation") or "").strip()[:2000],
                "difficulty": str(entry.get("difficulty") or "").strip()[:16],
                "source": "generated",
            }
        )
    return items


__all__ = ["RetrievalPracticeGenerator"]
