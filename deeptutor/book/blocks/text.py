"""Text block generator – Markdown body.

Also exposes :func:`generate_bridge_text` so the compiler can attach a short
1-2 sentence transition to *any* block's payload (not as a separate block).

Prompts live in ``deeptutor/book/prompts/{en,zh}/text.yaml``.
"""

from __future__ import annotations

from typing import Any

from ..models import BlockType, SourceAnchor
from ._llm_writer import llm_text
from ._prompts import get_book_prompt, load_book_prompts
from ._rag_helpers import optional_rag_lookup
from .base import BlockContext, BlockGenerator, GenerationFailure

_NONE_LABEL = {"zh": "(无)", "en": "(none)"}


def _format_objectives(objectives: list[str]) -> str:
    return "\n".join(f"- {o}" for o in objectives) or "(none)"


def _none_label(language: str) -> str:
    return _NONE_LABEL.get(language, _NONE_LABEL["en"])


class TextGenerator(BlockGenerator):
    block_type = BlockType.TEXT

    async def _generate(
        self, ctx: BlockContext
    ) -> tuple[dict[str, Any], list[SourceAnchor], dict[str, Any]]:
        params = ctx.block.params
        chapter_title = params.get("chapter_title", ctx.chapter.title)
        chapter_summary = params.get("chapter_summary", ctx.chapter.summary)
        objectives: list[str] = params.get("objectives") or ctx.chapter.learning_objectives
        role: str = str(params.get("role") or "explanation")
        previous_block_summary: str = str(params.get("previous_block_summary") or "")

        rag = await optional_rag_lookup(
            query=f"{chapter_title}: {role}. Objectives: {'; '.join(objectives)}",
            ctx=ctx,
        )

        prompts = load_book_prompts("text", ctx.language)
        none_label = _none_label(ctx.language)
        rag_section = f"\n[Relevant source material]\n{rag.text}\n" if rag.text else ""
        prev_section = (
            f"\n[Previous block recap]\n{previous_block_summary}\n"
            if previous_block_summary
            else ""
        )
        user_prompt = get_book_prompt(prompts, "user_template").format(
            chapter_title=chapter_title,
            chapter_summary=chapter_summary or none_label,
            objectives_block=_format_objectives(objectives),
            role=role,
            previous_section=prev_section,
            rag_section=rag_section,
        )
        body = await llm_text(
            user_prompt=user_prompt,
            system_prompt=get_book_prompt(prompts, "system"),
            max_tokens=1400,
            temperature=0.45,
            language=ctx.language,
            reasoning_effort="none",
        )
        if not body.strip():
            raise GenerationFailure("LLM returned no visible text content.")

        return (
            {
                "format": "markdown",
                "body": body,
                "role": role,
            },
            rag.anchors,
            {"used_rag": rag.used, "kb": ctx.primary_kb},
        )


async def generate_bridge_text(
    *,
    chapter_title: str,
    previous_block_summary: str,
    next_block_hint: str,
    language: str,
) -> str:
    """Produce 1-2 short Markdown sentences that bridge two adjacent blocks.

    Used by :class:`deeptutor.book.compiler.BookCompiler` to attach a plain
    transition paragraph onto a target block's ``payload['bridge_text']``,
    instead of materialising a dedicated bridge block.
    """
    prompts = load_book_prompts("text", language)
    none_label = _none_label(language)
    user_prompt = get_book_prompt(prompts, "bridge_user_template").format(
        chapter_title=chapter_title,
        previous_block_summary=previous_block_summary or none_label,
        next_block_hint=next_block_hint or none_label,
    )
    body = await llm_text(
        user_prompt=user_prompt,
        system_prompt=get_book_prompt(prompts, "bridge_system"),
        max_tokens=300,
        temperature=0.5,
        language=language,
        reasoning_effort="none",
    )
    return body.strip()


__all__ = ["TextGenerator", "generate_bridge_text"]
