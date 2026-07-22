"""Repair stage: targeted fix after deterministic local validation fails."""

from __future__ import annotations

import json

from deeptutor.agents.base_agent import BaseAgent
from deeptutor.core.trace import build_trace_metadata, new_call_id

from ..models import ReviewResult, VisualizationAnalysis
from ..utils import extract_json_object


class ReviewAgent(BaseAgent):
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        api_version: str | None = None,
        language: str = "zh",
    ) -> None:
        super().__init__(
            module_name="visualize",
            agent_name="review_agent",
            api_key=api_key,
            base_url=base_url,
            api_version=api_version,
            language=language,
        )

    async def process(
        self,
        *,
        user_input: str,
        analysis: VisualizationAnalysis,
        code: str,
        error: str,
    ) -> ReviewResult:
        """Targeted repair pass — this agent's single job.

        Only invoked *after* the deterministic local validation has failed,
        and handed the concrete error so the model fixes one specific defect
        instead of re-judging everything (chat and Book share this path).
        """
        system_prompt = self.get_prompt("repair_system")
        user_template = self.get_prompt("repair_user_template")
        if not system_prompt or not user_template:
            raise ValueError("ReviewAgent repair prompts are not configured.")

        user_prompt = user_template.format(
            user_input=user_input.strip(),
            render_type=analysis.render_type,
            error=error.strip() or "(unspecified)",
            analysis_json=json.dumps(analysis.model_dump(), ensure_ascii=False, indent=2),
            code=code,
        )

        chunks: list[str] = []
        async for chunk in self.stream_llm(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            response_format={"type": "json_object"},
            stage="reviewing",
            trace_meta=build_trace_metadata(
                call_id=new_call_id("viz-repair"),
                phase="reviewing",
                label="Code repair",
                call_kind="viz_code_repair",
                trace_role="review",
                trace_kind="llm_output",
            ),
        ):
            chunks.append(chunk)
        response = "".join(chunks)
        return ReviewResult.model_validate(extract_json_object(response))
