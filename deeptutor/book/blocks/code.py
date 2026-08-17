"""Code block – generates a runnable code snippet plus brief explanation.

Phase 2 implementation. Uses the unified LLM service with a strict JSON
response. The frontend ``CodeBlock`` component renders the code and the
explanation side-by-side; the playground "code_execution" tool can be
hooked in later for live runs.

Prompts live in ``deeptutor/book/prompts/{en,zh}/code.yaml``.
"""

from __future__ import annotations

from typing import Any

from ..models import BlockType, SourceAnchor
from ._llm_writer import llm_json
from ._prompts import get_book_prompt, load_book_prompts
from .base import BlockContext, BlockGenerator, GenerationFailure


def _check_python(code: str) -> str | None:
    import ast

    try:
        ast.parse(code)
    except SyntaxError as exc:
        return f"line {exc.lineno}: {exc.msg}"
    return None


def _check_json(code: str) -> str | None:
    import json

    try:
        json.loads(code)
    except ValueError as exc:
        return str(exc)
    return None


# Languages we can validate for free, in-process, with no side effects. Parsing
# only — never execution: a generated snippet may open files or hit the network,
# and the point is to catch truncation and malformed output, not to run it.
_CHECKABLE = {
    "python": _check_python,
    "py": _check_python,
    "json": _check_json,
}


def _syntax_error(code: str, language: str) -> str | None:
    """Return a human-readable syntax error, or None if it parses / is unchecked."""
    checker = _CHECKABLE.get((language or "").strip().lower())
    if checker is None:
        return None
    try:
        return checker(code)
    except Exception:  # noqa: BLE001 - a checker must never break generation
        return None


class CodeGenerator(BlockGenerator):
    block_type = BlockType.CODE

    async def _generate(
        self, ctx: BlockContext
    ) -> tuple[dict[str, Any], list[SourceAnchor], dict[str, Any]]:
        params = ctx.block.params
        chapter_title = params.get("chapter_title", ctx.chapter.title)
        chapter_summary = params.get("chapter_summary", ctx.chapter.summary)
        objectives = params.get("objectives") or ctx.chapter.learning_objectives
        language = str(params.get("language") or "python")
        intent = str(params.get("intent") or "demonstrate")

        prompts = load_book_prompts("code", ctx.language)
        none_label = "(无)" if ctx.language == "zh" else "(none)"
        user_prompt = get_book_prompt(prompts, "user_template").format(
            chapter_title=chapter_title,
            chapter_summary=chapter_summary or none_label,
            objectives_inline="; ".join(objectives) or none_label,
            intent=intent,
            language=language,
        )
        data = await llm_json(
            user_prompt=user_prompt,
            system_prompt=get_book_prompt(prompts, "system"),
            max_tokens=900,
            temperature=0.3,
            language=ctx.language,
        )

        code = str(data.get("code") or "").strip()
        if not code:
            raise GenerationFailure("LLM did not return any code.")
        if "<think" in code.lower() or "</think" in code.lower():
            raise GenerationFailure("prompt leak detected in generated code.")

        code_language = str(data.get("language") or language).strip() or language
        syntax_error = _syntax_error(code, code_language)
        if syntax_error:
            # A truncated or malformed snippet is worse than none: the reader
            # copies it, it fails, and nothing said it was never checked. Fail
            # the block so the compiler's retry path gets a second attempt.
            raise GenerationFailure(f"generated code does not parse: {syntax_error}")

        metadata = data.get("_metadata") if isinstance(data.get("_metadata"), dict) else {}
        return (
            {
                "language": code_language,
                "code": code,
                "explanation": str(data.get("explanation") or "").strip(),
                "intent": intent,
            },
            [],
            {**metadata, "syntax_checked": _CHECKABLE.get(code_language.lower()) is not None},
        )


__all__ = ["CodeGenerator"]
