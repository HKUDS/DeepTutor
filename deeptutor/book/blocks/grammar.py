"""Grammar block – pattern, explanation, examples, and one exercise.

Prompts live in ``deeptutor/book/prompts/{en,zh}/grammar.yaml``.
"""

from __future__ import annotations

from typing import Any

from ..models import BlockType, SourceAnchor
from ._llm_writer import llm_json
from ._prompts import get_book_prompt, load_book_prompts
from .base import BlockContext, BlockGenerator, GenerationFailure


class GrammarGenerator(BlockGenerator):
    block_type = BlockType.GRAMMAR

    async def _generate(
        self, ctx: BlockContext
    ) -> tuple[dict[str, Any], list[SourceAnchor], dict[str, Any]]:
        params = ctx.block.params
        chapter_title = str(params.get("chapter_title") or ctx.chapter.title)
        chapter_summary = str(params.get("chapter_summary") or ctx.chapter.summary)
        objectives = params.get("objectives") or ctx.chapter.learning_objectives
        focus = str(params.get("topic") or ctx.block.title or chapter_title)

        prompts = load_book_prompts("grammar", ctx.language)
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
            max_tokens=1500,
            temperature=0.3,
            language=ctx.language,
            expected_key="examples",
        )

        pattern = str(data.get("pattern") or "").strip()
        explanation = str(data.get("explanation") or "").strip()
        examples: list[dict[str, str]] = []
        examples_raw = data.get("examples")
        if isinstance(examples_raw, list):
            for item in examples_raw[:6]:
                if not isinstance(item, dict):
                    continue
                sentence = str(item.get("sentence") or "").strip()
                if not sentence:
                    continue
                highlight = str(item.get("highlight") or "").strip()
                examples.append(
                    {
                        "sentence": sentence[:500],
                        "highlight": highlight[:160] if highlight in sentence else "",
                    }
                )

        exercise_raw = data.get("exercise")
        exercise: dict[str, Any] = {}
        if isinstance(exercise_raw, dict):
            question = str(exercise_raw.get("question") or "").strip()
            answer = str(exercise_raw.get("answer") or "").strip()
            options: list[str] = []
            options_raw = exercise_raw.get("options")
            if isinstance(options_raw, list):
                for item in options_raw:
                    option = str(item or "").strip()
                    if option and option not in options:
                        options.append(option[:200])
            if answer and answer not in options:
                options.append(answer[:200])
            if len(options) > 6:
                options = options[:5] + ([answer[:200]] if answer not in options[:5] else [])
            exercise = {
                "question": question[:600],
                "answer": answer[:200],
                "options": options,
            }

        if not pattern or not explanation or not examples:
            raise GenerationFailure("LLM returned an incomplete grammar explanation.")
        if (
            not exercise.get("question")
            or not exercise.get("answer")
            or len(exercise.get("options") or []) < 2
        ):
            raise GenerationFailure("LLM returned an incomplete grammar exercise.")

        metadata = data.get("_metadata")
        return (
            {
                "pattern": pattern[:300],
                "explanation": explanation[:1200],
                "examples": examples,
                "exercise": exercise,
            },
            [],
            metadata if isinstance(metadata, dict) else {},
        )


__all__ = ["GrammarGenerator"]
