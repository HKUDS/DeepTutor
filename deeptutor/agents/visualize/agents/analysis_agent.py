"""Analysis stage: decide SVG vs Chart.js and produce a structured brief."""

from __future__ import annotations

from deeptutor.agents.base_agent import BaseAgent
from deeptutor.core.trace import build_trace_metadata, new_call_id

from ..models import VisualizationAnalysis
from ..utils import extract_json_object


class AnalysisAgent(BaseAgent):
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        api_version: str | None = None,
        language: str = "zh",
    ) -> None:
        super().__init__(
            module_name="visualize",
            agent_name="analysis_agent",
            api_key=api_key,
            base_url=base_url,
            api_version=api_version,
            language=language,
        )

    async def process(
        self,
        *,
        user_input: str,
        history_context: str,
        render_mode: str = "auto",
    ) -> VisualizationAnalysis:
        if render_mode in ("svg", "chartjs", "mermaid"):
            system_prompt = self.get_prompt("system_fixed")
            user_template = self.get_prompt("user_template_fixed")
        else:
            system_prompt = self.get_prompt("system")
            user_template = self.get_prompt("user_template")
        if not system_prompt or not user_template:
            raise ValueError("AnalysisAgent prompts are not configured.")

        format_kwargs: dict[str, str] = {
            "user_input": user_input.strip(),
            "history_context": history_context.strip() or "(none)",
        }
        if render_mode in ("svg", "chartjs", "mermaid"):
            format_kwargs["render_type"] = render_mode

        user_prompt = user_template.format(**format_kwargs)

        chunks: list[str] = []
        async for chunk in self.stream_llm(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            response_format={"type": "json_object"},
            stage="analyzing",
            trace_meta=build_trace_metadata(
                call_id=new_call_id("viz-analysis"),
                phase="analyzing",
                label="Visualization analysis",
                call_kind="viz_analysis",
                trace_role="analyze",
                trace_kind="llm_output",
            ),
        ):
            chunks.append(chunk)
        response = "".join(chunks)
        result = VisualizationAnalysis.model_validate(extract_json_object(response))
        if render_mode in ("svg", "chartjs", "mermaid"):
            result.render_type = render_mode  # type: ignore[assignment]
        return result
