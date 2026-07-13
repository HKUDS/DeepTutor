"""Orchestrates the three-stage visualization generation flow."""

from __future__ import annotations

from typing import Any, Callable

from deeptutor.core.context import Attachment

from .agents import AnalysisAgent, CodeGeneratorAgent, ReviewAgent
from .models import ReviewResult, VisualizationAnalysis


class VisualizePipeline:
    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str | None,
        api_version: str | None,
        language: str = "zh",
        trace_callback: Callable[[dict[str, Any]], Any] | None = None,
    ) -> None:
        self.analysis_agent = AnalysisAgent(
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
        self.review_agent = ReviewAgent(
            api_key=api_key,
            base_url=base_url,
            api_version=api_version,
            language=language,
        )
        self.set_trace_callback(trace_callback)

    def set_trace_callback(self, callback: Callable[[dict[str, Any]], Any] | None) -> None:
        for agent in (self.analysis_agent, self.code_agent, self.review_agent):
            agent.set_trace_callback(callback)

    async def run_analysis(
        self,
        *,
        user_input: str,
        history_context: str,
        render_mode: str = "auto",
        attachments: list[Attachment] | None = None,
    ) -> VisualizationAnalysis:
        return await self.analysis_agent.process(
            user_input=user_input,
            history_context=history_context,
            render_mode=render_mode,
            attachments=attachments,
        )

    async def run_code_generation(
        self,
        *,
        user_input: str,
        history_context: str,
        analysis: VisualizationAnalysis,
    ) -> str:
        return await self.code_agent.process(
            user_input=user_input,
            history_context=history_context,
            analysis=analysis,
        )

    async def run_repair(
        self,
        *,
        user_input: str,
        analysis: VisualizationAnalysis,
        code: str,
        error: str,
    ) -> ReviewResult:
        return await self.review_agent.process(
            user_input=user_input,
            analysis=analysis,
            code=code,
            error=error,
        )


__all__ = ["VisualizePipeline"]
