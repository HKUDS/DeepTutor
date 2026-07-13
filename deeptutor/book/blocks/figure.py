"""Figure block – static visual figure (svg / chartjs / mermaid).

Wraps :class:`deeptutor.agents.visualize.pipeline.VisualizePipeline` with
``render_mode="figure"`` so the LLM picks the best static rendering for the
chapter, but never falls back to interactive HTML (handled by the
``interactive`` block type).

Like the chat capability, the draft is checked by the deterministic local
``validate_visualization``; only on failure do we spend one targeted repair
call. If the code still fails after repair we raise ``GenerationFailure`` so
the book engine can retry, instead of baking a broken figure into the book.
"""

from __future__ import annotations

import logging
from typing import Any

from ..models import BlockType, SourceAnchor
from .base import BlockContext, BlockGenerator, GenerationFailure

logger = logging.getLogger(__name__)


class FigureGenerator(BlockGenerator):
    block_type = BlockType.FIGURE

    async def _generate(
        self, ctx: BlockContext
    ) -> tuple[dict[str, Any], list[SourceAnchor], dict[str, Any]]:
        params = ctx.block.params
        chapter_title = params.get("chapter_title", ctx.chapter.title)
        chapter_summary = params.get("chapter_summary", ctx.chapter.summary)
        objectives = params.get("objectives") or ctx.chapter.learning_objectives
        variant = str(params.get("variant") or "diagram")
        focus = str(params.get("focus") or "")

        history_lines: list[str] = []
        if chapter_summary:
            history_lines.append(f"Chapter summary: {chapter_summary}")
        if objectives:
            history_lines.append("Learning objectives:")
            for obj in objectives:
                history_lines.append(f"- {obj}")
        history_context = "\n".join(history_lines)

        focus_clause = f" focusing on {focus}" if focus else ""
        user_input = (
            f"Create a {variant} figure for the chapter "
            f'"{chapter_title}"{focus_clause}. The figure should help a '
            "learner build intuition about the core relationships covered above."
        )

        try:
            from deeptutor.agents.visualize.models import ReviewResult
            from deeptutor.agents.visualize.pipeline import VisualizePipeline
            from deeptutor.agents.visualize.utils import validate_visualization
            from deeptutor.services.llm.config import get_llm_config

            llm_config = get_llm_config()
            pipeline = VisualizePipeline(
                api_key=llm_config.api_key,
                base_url=llm_config.base_url,
                api_version=llm_config.api_version,
                language=ctx.language,
            )
            analysis = await pipeline.run_analysis(
                user_input=user_input,
                history_context=history_context,
                render_mode="figure",
            )
            code = await pipeline.run_code_generation(
                user_input=user_input,
                history_context=history_context,
                analysis=analysis,
            )
            ok, validation_error = validate_visualization(code, analysis.render_type)
            if ok:
                review = ReviewResult(
                    optimized_code=code,
                    changed=False,
                    review_notes="Passed local validation.",
                )
            else:
                review = await pipeline.run_repair(
                    user_input=user_input,
                    analysis=analysis,
                    code=code,
                    error=validation_error,
                )
        except Exception as exc:
            logger.warning(f"FigureGenerator failed: {exc}", exc_info=True)
            raise GenerationFailure(f"figure generation failed: {exc}") from exc

        final_code = review.optimized_code or code
        render_type = analysis.render_type
        final_ok, residual_error = validate_visualization(final_code, render_type)
        if not final_ok:
            raise GenerationFailure(f"figure failed validation after repair: {residual_error}")
        lang_tag = {
            "svg": "svg",
            "mermaid": "mermaid",
            "chartjs": "javascript",
        }.get(render_type, "svg")

        return (
            {
                "render_type": render_type,
                "code": {"language": lang_tag, "content": final_code},
                "description": analysis.description,
                "chart_type": analysis.chart_type,
            },
            [],
            {
                "review_changed": review.changed,
                "review_notes": review.review_notes,
            },
        )


__all__ = ["FigureGenerator"]
