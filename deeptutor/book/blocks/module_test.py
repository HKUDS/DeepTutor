"""Module-test block — YuEdu error loop (模块测验).

A short end-of-module check. Questions come from the learner's KP-bound
question bank (``kp.meta["question_bank"]``) whenever one is mounted —
real bank items only, never model re-creations. Without a bank the LLM
drafts the test and the payload is marked ``generated: true``.

Prompts live in ``deeptutor/book/prompts/{en,zh}/module_test.yaml``.
"""

from __future__ import annotations

from typing import Any

from ..models import BlockType, SourceAnchor
from ._learning_data import load_kp_question_banks, pick_bank_items
from ._llm_writer import llm_json
from ._prompts import get_book_prompt, load_book_prompts
from .base import BlockContext, BlockGenerator, GenerationFailure


class ModuleTestGenerator(BlockGenerator):
    block_type = BlockType.MODULE_TEST

    async def _generate(
        self, ctx: BlockContext
    ) -> tuple[dict[str, Any], list[SourceAnchor], dict[str, Any]]:
        params = ctx.block.params
        chapter_title = params.get("chapter_title", ctx.chapter.title)
        chapter_summary = params.get("chapter_summary", ctx.chapter.summary)
        objectives = params.get("objectives") or ctx.chapter.learning_objectives
        count = _clamp_count(params.get("num_questions") or params.get("count"), default=8)
        # The planner stamps the module this page closes when it knows one;
        # otherwise the whole book's bank is in scope.
        module_id = str(params.get("module_id") or "").strip() or None

        entries = ctx.extra.get("kp_question_banks") or load_kp_question_banks(ctx.book_id)
        items = pick_bank_items(entries, count, module_id=module_id)
        if items:
            module_names = sorted(
                {str(entry.get("module_name")) for entry in entries if entry.get("module_name")}
            )
            if module_id is not None:
                module_names = [
                    str(entry.get("module_name"))
                    for entry in entries
                    if entry.get("module_id") == module_id and entry.get("module_name")
                ]
            kp_ids = sorted({str(item["kp_id"]) for item in items if item.get("kp_id")})
            kp_names = sorted({str(item["kp_name"]) for item in items if item.get("kp_name")})
            return (
                {
                    "questions": items,
                    "source": "question_bank",
                    "module_id": module_id or "",
                    "module_names": sorted(set(module_names)),
                    "kp_ids": kp_ids,
                    "kp_names": kp_names,
                },
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
        prompts = load_book_prompts("module_test", ctx.language)
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
            max_tokens=2400,
            temperature=0.4,
            language=ctx.language,
            expected_key="questions",
        )
        questions = _normalise_questions(data.get("questions") if isinstance(data, dict) else None)
        if not questions:
            raise GenerationFailure("LLM returned no module-test questions.")
        questions = questions[:count]
        return (
            {
                "questions": questions,
                "source": "llm",
                # D4: LLM-drafted payload must be marked as generated.
                "generated": True,
            },
            [],
            data.get("_metadata") if isinstance(data.get("_metadata"), dict) else {},
        )


def _clamp_count(value: Any, *, default: int) -> int:
    try:
        return max(4, min(12, int(value)))
    except (TypeError, ValueError):
        return default


def _normalise_questions(raw: Any) -> list[dict[str, Any]]:
    questions: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return questions
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        question = str(entry.get("question") or "").strip()
        if not question:
            continue
        raw_options = entry.get("options")
        questions.append(
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
    return questions


__all__ = ["ModuleTestGenerator"]
