"""Summary stage for math animator."""

from __future__ import annotations

import json

from deeptutor.agents.base_agent import BaseAgent
from deeptutor.core.trace import build_trace_metadata, new_call_id
from deeptutor.services.llm.structured_retry import json_with_reasoning_retry

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

        async def _run(reasoning_effort: str | None) -> str:
            chunks: list[str] = []
            async for chunk in self.stream_llm(
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                response_format={"type": "json_object"},
                reasoning_effort=reasoning_effort,
                stage="summary",
                trace_meta=build_trace_metadata(
                    call_id=new_call_id("math-summary"),
                    phase="summary",
                    label="Summarize result",
                    call_kind="math_summary",
                    trace_role="summarize",
                    trace_kind="llm_output",
                ),
            ):
                chunks.append(chunk)
            return "".join(chunks)

        payload = await json_with_reasoning_retry(
            _run, expected_key="summary_text", logger_instance=self.logger
        )
        # Rendering has already succeeded. Keep returning its artifacts if the
        # summary remains empty after the low-effort retry.
        return SummaryPayload.model_validate(payload)
