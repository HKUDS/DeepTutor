"""Code generation stage: produce SVG or Chart.js code from the analysis."""

from __future__ import annotations

import json

from deeptutor.agents.base_agent import BaseAgent
from deeptutor.core.trace import build_trace_metadata, new_call_id
from deeptutor.services.llm.reasoning_params import RETRY_REASONING_EFFORT
from deeptutor.services.llm.utils import clean_thinking_tags

from ..models import VisualizationAnalysis
from ..utils import extract_code_block

_LANG_HINTS = {
    "svg": "svg",
    "mermaid": "mermaid",
    "mindmap": "mermaid",
    "html": "html",
}


def _slice_root_element(text: str, render_type: str) -> str | None:
    lower = text.lower()
    close_tag = "</svg>" if render_type == "svg" else "</html>"
    start = (
        lower.find("<svg")
        if render_type == "svg"
        else (lower.find("<!doctype") if lower.find("<!doctype") != -1 else lower.find("<html"))
    )
    end = lower.rfind(close_tag)
    if 0 <= start < end:
        return text[start : end + len(close_tag)]
    return None


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

        # Blocking rather than streamed: the fenced block is only usable whole.
        async def _generate_once(reasoning_effort: str | None) -> str:
            response = await self.call_llm(
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                reasoning_effort=reasoning_effort,
                stage="generating",
                trace_meta=build_trace_metadata(
                    call_id=new_call_id("viz-codegen"),
                    phase="generating",
                    label="Code generation",
                    call_kind="viz_code_generation",
                    trace_role="generate",
                    trace_kind="llm_output",
                ),
            )
            return self._extract_code(response, analysis.render_type)

        first = await _generate_once(None)
        if self._is_usable_code(first, analysis.render_type):
            return first

        # Reasoning models spend hidden tokens out of max_tokens and can exhaust
        # the budget before finishing the visualization (#2914).
        self.logger.warning(
            "Visualize code generation (%s) returned no complete code; "
            "retrying with reasoning_effort=%s",
            analysis.render_type,
            RETRY_REASONING_EFFORT,
        )
        retried = await _generate_once(RETRY_REASONING_EFFORT)
        if self._is_usable_code(retried, analysis.render_type):
            return retried
        return retried or first

    @staticmethod
    def _extract_code(response: str, render_type: str) -> str:
        cleaned = clean_thinking_tags(response or "")
        lang_hint = _LANG_HINTS.get(render_type, "javascript")
        extracted = extract_code_block(cleaned, lang_hint) or extract_code_block(cleaned)

        # The renderers expect their payload to start cleanly with the right
        # root tag. Models often wrap output with prose, omit fences, or include
        # nested ``` fences inside <pre>/<script> that make non-greedy fence
        # matching stop before </html>.
        if render_type in ("svg", "html"):
            sliced = _slice_root_element(extracted, render_type) or _slice_root_element(
                cleaned, render_type
            )
            if sliced is not None:
                return sliced
            if render_type == "html" and not extracted:
                stripped = cleaned.strip()
                if stripped.lower().startswith(("<!doctype", "<html")):
                    return stripped

        return extracted

    @staticmethod
    def _is_usable_code(code: str, render_type: str) -> bool:
        if not code or code.lstrip().startswith("```"):
            return False
        lower = code.lower()
        if render_type == "html" and ("<!doctype" in lower or "<html" in lower):
            return "</html>" in lower
        if render_type == "svg" and "<svg" in lower:
            return "</svg>" in lower
        return True
