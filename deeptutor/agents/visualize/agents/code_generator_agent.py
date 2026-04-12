"""Code generation stage: produce SVG or Chart.js code from the analysis."""

from __future__ import annotations

import json

from deeptutor.agents.base_agent import BaseAgent
from deeptutor.core.trace import build_trace_metadata, new_call_id

from ..models import VisualizationAnalysis
from ..utils import extract_code_block


class CodeGeneratorAgent(BaseAgent):
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        api_version: str | None = None,
        language: str = "zh",
    ) -> None:
        super().__init__(
            module_name="visualize",
            agent_name="code_generator_agent",
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
        analysis: VisualizationAnalysis,
    ) -> str:
        system_prompt = self.get_prompt("system")
        user_template = self.get_prompt("user_template")
        if not system_prompt or not user_template:
            raise ValueError("CodeGeneratorAgent prompts are not configured.")

        user_prompt = user_template.format(
            user_input=user_input.strip(),
            history_context=history_context.strip() or "(none)",
            render_type=analysis.render_type,
            analysis_json=json.dumps(analysis.model_dump(), ensure_ascii=False, indent=2),
        )

        chunks: list[str] = []
        async for chunk in self.stream_llm(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            stage="generating",
            trace_meta=build_trace_metadata(
                call_id=new_call_id("viz-codegen"),
                phase="generating",
                label="Code generation",
                call_kind="viz_code_generation",
                trace_role="generate",
                trace_kind="llm_output",
            ),
        ):
            chunks.append(chunk)
        response = "".join(chunks)

        if analysis.render_type == "svg":
            lang_hint = "svg"
        elif analysis.render_type == "mermaid":
            lang_hint = "mermaid"
        else:
            lang_hint = "javascript"
        return extract_code_block(response, lang_hint) or extract_code_block(response)
