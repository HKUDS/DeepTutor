"""Animation block – Manim-rendered math animation.

Calls :class:`deeptutor.agents.math_animator.pipeline.MathAnimatorPipeline`
to generate a video clip explaining the chapter. The payload exposes the
rendered artifact URL(s) plus a short summary.

This block requires the optional ``math-animator`` extras (LaTeX, ffmpeg,
manim, …). When those packages are missing the generator raises
:class:`GenerationFailure` with a clear install hint.
"""

from __future__ import annotations

import importlib.util
import logging
from typing import Any

from deeptutor.services.keypool import primary_api_key

from ..models import BlockType, SourceAnchor
from ._prompts import get_book_prompt, load_book_prompts
from .base import BlockContext, BlockGenerator, GenerationFailure

logger = logging.getLogger(__name__)


class AnimationGenerator(BlockGenerator):
    block_type = BlockType.ANIMATION

    async def _generate(
        self, ctx: BlockContext
    ) -> tuple[dict[str, Any], list[SourceAnchor], dict[str, Any]]:
        if importlib.util.find_spec("manim") is None:
            raise GenerationFailure(
                "AnimationGenerator requires the optional math-animator extras. "
                "Install with `pip install -e '.[math-animator]'` "
                "or `pip install -r requirements/math-animator.txt`."
            )

        params = ctx.block.params
        chapter_title = params.get("chapter_title", ctx.chapter.title)
        chapter_summary = params.get("chapter_summary", ctx.chapter.summary)
        objectives = params.get("objectives") or ctx.chapter.learning_objectives
        focus = str(params.get("focus") or "")
        quality = str(params.get("quality") or "medium")
        style_hint = str(params.get("style_hint") or "")
        prompts = load_book_prompts("animation", ctx.language)

        history_lines: list[str] = []
        if chapter_summary:
            history_lines.append(
                get_book_prompt(prompts, "context_summary")
                .strip()
                .format(chapter_summary=chapter_summary)
            )
        if objectives:
            history_lines.append(get_book_prompt(prompts, "context_objectives").strip())
            for obj in objectives:
                history_lines.append(f"- {obj}")
        history_context = "\n".join(history_lines)

        focus_clause = (
            get_book_prompt(prompts, "focus_clause").rstrip().format(focus=focus) if focus else ""
        )
        user_input = (
            get_book_prompt(prompts, "brief")
            .strip()
            .format(chapter_title=chapter_title, focus_clause=focus_clause)
        )

        try:
            from deeptutor.agents.math_animator.pipeline import MathAnimatorPipeline
            from deeptutor.agents.math_animator.request_config import (
                MathAnimatorRequestConfig,
            )
            from deeptutor.services.llm.config import get_llm_config

            llm_config = get_llm_config()
            request_config = MathAnimatorRequestConfig(
                output_mode="video",
                quality=quality if quality in ("low", "medium", "high") else "medium",
                style_hint=style_hint,
            )
            pipeline = MathAnimatorPipeline(
                api_key=primary_api_key(llm_config.api_key),
                base_url=llm_config.base_url,
                api_version=llm_config.api_version,
                language=ctx.language,
            )
            turn_id = f"book-{ctx.book_id}-{ctx.block.id}"
            result = await pipeline.run(
                turn_id=turn_id,
                user_input=user_input,
                history_context=history_context,
                request_config=request_config,
                attachments=[],
            )
        except Exception as exc:
            logger.warning(f"AnimationGenerator failed: {exc}", exc_info=True)
            raise GenerationFailure(f"animation generation failed: {exc}") from exc

        render_result = result["render_result"]
        summary_payload = result["summary"]
        analysis = result["analysis"]
        artifacts = [artifact.model_dump() for artifact in render_result.artifacts]
        primary = next(
            (
                a
                for a in artifacts
                if a.get("type") == "video" or "video" in (a.get("content_type") or "")
            ),
            artifacts[0] if artifacts else None,
        )

        return (
            {
                "render_type": "video",
                "artifacts": artifacts,
                "video_url": (primary or {}).get("url", ""),
                "filename": (primary or {}).get("filename", ""),
                "summary": getattr(summary_payload, "summary_text", "") or "",
                "key_points": list(getattr(summary_payload, "key_points", []) or []),
                "description": getattr(analysis, "learning_goal", "") or "",
            },
            [],
            {
                "retry_attempts": render_result.retry_attempts,
                "quality": request_config.quality,
            },
        )


__all__ = ["AnimationGenerator"]
