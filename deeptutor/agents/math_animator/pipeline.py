"""Orchestrates the math animator generation flow."""

from __future__ import annotations

import time
from typing import Any, Callable

from deeptutor.core.context import Attachment

from .agents import (
    CodeGeneratorAgent,
    ConceptAnalysisAgent,
    ConceptDesignAgent,
    SummaryAgent,
    VisualReviewAgent,
)
from .duration_utils import parse_target_duration_seconds
from .models import RenderResult, VisualReviewResult
from .renderer import ManimRenderService
from .request_config import MathAnimatorRequestConfig
from .retry_manager import CodeRetryManager
from .visual_review import VisualReviewService


class MathAnimatorPipeline:
    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str | None,
        api_version: str | None,
        language: str = "zh",
        trace_callback: Callable[[dict[str, Any]], Any] | None = None,
        enable_visual_review: bool = False,
    ) -> None:
        self.enable_visual_review = enable_visual_review
        self.analysis_agent = ConceptAnalysisAgent(
            api_key=api_key,
            base_url=base_url,
            api_version=api_version,
            language=language,
        )
        self.design_agent = ConceptDesignAgent(
            api_key=api_key,
            base_url=base_url,
            api_version=api_version,
            language=language,
        )
        self.code_agent = CodeGeneratorAgent(
            api_key=api_key,
            base_url=base_url,
            api_version=api_version,
            language=language,
        )
        self.summary_agent = SummaryAgent(
            api_key=api_key,
            base_url=base_url,
            api_version=api_version,
            language=language,
        )
        self.visual_review_agent = (
            VisualReviewAgent(
                api_key=api_key,
                base_url=base_url,
                api_version=api_version,
                language=language,
            )
            if enable_visual_review
            else None
        )
        self.set_trace_callback(trace_callback)

    def set_trace_callback(self, callback: Callable[[dict[str, Any]], Any] | None) -> None:
        for agent in (
            self.analysis_agent,
            self.design_agent,
            self.code_agent,
            self.summary_agent,
            self.visual_review_agent,
        ):
            if agent is not None:
                agent.set_trace_callback(callback)

    async def run_analysis(
        self,
        *,
        user_input: str,
        history_context: str,
        request_config: MathAnimatorRequestConfig,
        attachments: list[Attachment],
    ):
        return await self.analysis_agent.process(
            user_input=user_input,
            history_context=history_context,
            output_mode=request_config.output_mode,
            style_hint=request_config.style_hint,
            attachments=attachments,
        )

    async def run_design(
        self,
        *,
        user_input: str,
        request_config: MathAnimatorRequestConfig,
        analysis,
    ):
        return await self.design_agent.process(
            user_input=user_input,
            output_mode=request_config.output_mode,
            analysis=analysis,
            style_hint=request_config.style_hint,
        )

    async def run_code_generation(
        self,
        *,
        user_input: str,
        request_config: MathAnimatorRequestConfig,
        analysis,
        design,
    ):
        duration_target_seconds = parse_target_duration_seconds(
            " ".join(
                part.strip()
                for part in (user_input, request_config.style_hint)
                if isinstance(part, str) and part.strip()
            )
        )
        return await self.code_agent.generate(
            user_input=user_input,
            output_mode=request_config.output_mode,
            analysis=analysis,
            design=design,
            duration_target_seconds=duration_target_seconds,
        )

    async def run_render(
        self,
        *,
        turn_id: str,
        user_input: str,
        request_config: MathAnimatorRequestConfig,
        initial_code: str,
        on_retry: Callable[[Any], Any] | None = None,
        on_render_progress: Callable[[str, bool], Any] | None = None,
        on_retry_status: Callable[[str], Any] | None = None,
    ) -> tuple[str, RenderResult]:
        renderer = ManimRenderService(turn_id, progress_callback=on_render_progress)
        duration_target_seconds = parse_target_duration_seconds(
            " ".join(
                part.strip()
                for part in (user_input, request_config.style_hint)
                if isinstance(part, str) and part.strip()
            )
        )
        review_callback: Callable[[str, RenderResult], Any] | None = None
        if self.enable_visual_review and self.visual_review_agent is not None:
            review_service = VisualReviewService(turn_id, progress_callback=on_render_progress)

            async def _review_callback(
                current_code: str, render_result: RenderResult
            ) -> VisualReviewResult:
                attachments = await review_service.build_attachments(render_result)
                return await self.visual_review_agent.process(
                    user_input=user_input,
                    output_mode=request_config.output_mode,
                    current_code=current_code,
                    render_result=render_result,
                    attachments=attachments,
                )

            review_callback = _review_callback

        retry_manager = CodeRetryManager(
            renderer=renderer,
            max_retries=4,
            on_retry=on_retry,
            on_status=on_retry_status,
            review_callback=review_callback,
            repair_callback=lambda current_code, error_message, attempt: self.code_agent.repair(
                user_input=user_input,
                output_mode=request_config.output_mode,
                current_code=current_code,
                error_message=error_message,
                attempt=attempt,
                duration_target_seconds=duration_target_seconds,
            ),
        )
        final_code, render_result = await retry_manager.render_with_retries(
            initial_code=initial_code,
            output_mode=request_config.output_mode,
            quality=request_config.quality,
        )
        return final_code, RenderResult.model_validate(render_result.model_dump())

    async def run_summary(
        self,
        *,
        user_input: str,
        request_config: MathAnimatorRequestConfig,
        analysis,
        design,
        render_result: RenderResult,
    ):
        return await self.summary_agent.process(
            user_input=user_input,
            output_mode=request_config.output_mode,
            analysis=analysis,
            design=design,
            render_result=render_result,
        )

    async def run(
        self,
        *,
        turn_id: str,
        user_input: str,
        history_context: str,
        request_config: MathAnimatorRequestConfig,
        attachments: list[Attachment],
    ) -> dict[str, Any]:
        timings: dict[str, float] = {}

        start = time.perf_counter()
        analysis = await self.run_analysis(
            user_input=user_input,
            history_context=history_context,
            request_config=request_config,
            attachments=attachments,
        )
        timings["concept_analysis"] = round(time.perf_counter() - start, 3)

        start = time.perf_counter()
        design = await self.run_design(
            user_input=user_input,
            request_config=request_config,
            analysis=analysis,
        )
        timings["concept_design"] = round(time.perf_counter() - start, 3)

        start = time.perf_counter()
        generated = await self.run_code_generation(
            user_input=user_input,
            request_config=request_config,
            analysis=analysis,
            design=design,
        )
        timings["code_generation"] = round(time.perf_counter() - start, 3)

        start = time.perf_counter()
        final_code, render_result = await self.run_render(
            turn_id=turn_id,
            user_input=user_input,
            request_config=request_config,
            initial_code=generated.code,
        )
        timings["code_retry"] = round(time.perf_counter() - start, 3)

        start = time.perf_counter()
        summary = await self.run_summary(
            user_input=user_input,
            request_config=request_config,
            analysis=analysis,
            design=design,
            render_result=render_result,
        )
        timings["summary"] = round(time.perf_counter() - start, 3)

        timings["render_output"] = timings["code_retry"]
        return {
            "analysis": analysis,
            "design": design,
            "code": final_code,
            "render_result": render_result,
            "summary": summary,
            "timings": timings,
        }


__all__ = ["MathAnimatorPipeline"]
