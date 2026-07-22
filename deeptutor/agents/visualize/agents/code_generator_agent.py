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
        # Structured prompt assembly: every render type loads the shared
        # base + general rules, plus exactly one format-specific rule block.
        # This keeps the per-call prompt dense with the rules that matter for
        # *this* format without ever paying for the union of all four.
        # render_type here is always one of svg/chartjs/mermaid/html — manim
        # is dispatched away in the capability layer before code generation.
        system_parts = (
            self.get_prompt("system_base"),
            self.get_prompt("rules_general"),
            self.get_prompt(f"rules_{analysis.render_type}"),
        )
        system_prompt = "\n\n".join(part.strip() for part in system_parts if part and part.strip())
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
        elif analysis.render_type == "html":
            lang_hint = "html"
        else:
            lang_hint = "javascript"

        extracted = extract_code_block(response, lang_hint) or extract_code_block(response)

        # For html, the model sometimes returns the full document with no fence.
        # `extract_code_block` will then return the trimmed raw response — accept
        # it as long as it looks like an HTML document.
        if analysis.render_type == "html" and not extracted:
            stripped = (response or "").strip()
            lowered = stripped.lower()
            if lowered.startswith("<!doctype") or lowered.startswith("<html"):
                return stripped

        # The renderers expect their payload to start cleanly with the right
        # root tag. Models often wrap output with prose ("Here you go: <svg>…")
        # or emit a code fence on the same line as the closing tag, which
        # `extract_code_block`'s regex (requiring a leading \n before ```) does
        # not strip. Trim to the outermost root tags as a defensive net.
        if extracted:
            if analysis.render_type == "svg":
                lower = extracted.lower()
                start = lower.find("<svg")
                end = lower.rfind("</svg>")
                if start != -1 and end != -1 and end > start:
                    extracted = extracted[start : end + len("</svg>")]
            elif analysis.render_type == "html":
                lower = extracted.lower()
                start = lower.find("<!doctype")
                if start == -1:
                    start = lower.find("<html")
                end = lower.rfind("</html>")
                if start != -1 and end != -1 and end > start:
                    extracted = extracted[start : end + len("</html>")]

        return extracted
