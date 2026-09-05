"""Summary stage for math animator."""

from __future__ import annotations

import json

from deeptutor.agents._shared.structured_llm import stream_and_validate_json
from deeptutor.agents.base_agent import BaseAgent
from deeptutor.core.trace import build_trace_metadata, new_call_id

from ..models import ConceptAnalysis, RenderResult, SceneDesign, SummaryPayload


class SummaryAgent(BaseAgent):
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        api_version: str | None = None,
        language: str = "zh",
    ) -> None:
        super().__init__(
            module_name="math_animator",
            agent_name="summary_agent",
            api_key=api_key,
            base_url=base_url,
            api_version=api_version,
            language=language,
        )

    async def process(
        self,
        *,
        user_input: str,
        output_mode: str,
        analysis: ConceptAnalysis,
        design: SceneDesign,
        render_result: RenderResult,
    ) -> SummaryPayload:
        system_prompt = self.get_prompt("system")
        user_template = self.get_prompt("user_template")
        if not system_prompt or not user_template:
            raise ValueError("SummaryAgent prompts are not configured.")

        user_prompt = user_template.format(
            user_input=user_input.strip(),
            output_mode=output_mode,
            analysis_json=json.dumps(analysis.model_dump(), ensure_ascii=False, indent=2),
            design_json=json.dumps(design.model_dump(), ensure_ascii=False, indent=2),
            render_json=json.dumps(render_result.model_dump(), ensure_ascii=False, indent=2),
        )
        try:
            return await stream_and_validate_json(
                stream=self.stream_llm,
                user_prompt=user_prompt,
                model_type=SummaryPayload,
                stream_kwargs={
                    "system_prompt": system_prompt,
                    "response_format": {"type": "json_object"},
                    "stage": "summary",
                    "trace_meta": build_trace_metadata(
                        call_id=new_call_id("math-summary"),
                        phase="summary",
                        label="Summarize result",
                        call_kind="math_summary",
                        trace_role="summarize",
                        trace_kind="llm_output",
                    ),
                },
                is_complete=lambda payload: bool(payload.summary_text.strip()),
            )
        except ValueError:
            # The render already succeeded, so an unusable summary must not
            # discard it. Fall back to the localized text earlier stages did
            # produce instead of leaving the turn with a blank caption.
            self.logger.warning("Summary stage returned no usable JSON; using fallback text")
            return SummaryPayload(
                user_request=user_input.strip(),
                summary_text=(
                    analysis.learning_goal.strip() or design.title.strip() or user_input.strip()
                ),
            )
