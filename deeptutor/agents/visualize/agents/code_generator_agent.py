"""Code generation stage: produce SVG or Chart.js code from the analysis."""

from __future__ import annotations

import json

from deeptutor.agents.base_agent import BaseAgent
from deeptutor.core.trace import build_trace_metadata, new_call_id

from ..models import VisualizationAnalysis
from deeptutor.services.llm import StreamOutcome
from deeptutor.services.llm.reasoning_params import RETRY_REASONING_EFFORT

from ..utils import extract_code_block, validate_book_widget_html


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
        book_block_id: str | None = None,
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
        outcome = StreamOutcome() if book_block_id is not None else None
        call_id = new_call_id("viz-codegen")
        if outcome is not None:
            user_prompt += (
                "\nReturn one compact, complete HTML document. Use one small interaction, "
                "minimal inline CSS and JavaScript, no external dependencies, and no prose. "
                "Prioritize closing the script, body, and html tags over decorative details."
            )
        response = await self.call_llm(
            outcome=outcome,
            reasoning_effort=RETRY_REASONING_EFFORT if outcome is not None else None,
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            stage="generating",
            trace_meta=build_trace_metadata(
                call_id=call_id,
                phase="generating",
                label="Code generation",
                call_kind="viz_code_generation",
                trace_role="generate",
                trace_kind="llm_output",
            ),
        )

        if analysis.render_type == "svg":
            lang_hint = "svg"
        elif analysis.render_type in ("mermaid", "mindmap"):
            lang_hint = "mermaid"
        elif analysis.render_type == "html":
            lang_hint = "html"
        else:
            lang_hint = "javascript"

        extracted = extract_code_block(response, lang_hint) or extract_code_block(response)

        # For html, the model sometimes returns the full document with no fence.
        # `extract_code_block` will then return the trimmed raw response — accept
        # it as long as it looks like an HTML document.
        if outcome is None and analysis.render_type == "html" and not extracted:
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

        if outcome is not None:
            ok, detail = validate_book_widget_html(extracted)
            if outcome.truncated:
                ok = False
                detail = "Model hit the output token limit while generating interactive HTML."
            elif outcome.finish_reason in {"content_filter", "safety", "refusal"}:
                ok = False
                detail = "Provider stopped interactive HTML generation for a content restriction."
            self.logger.log(
                20 if ok else 30,
                "Book widget block=%s call=%s decision=%s finish_reason=%s "
                "prompt_tokens=%s completion_tokens=%s reasoning_tokens=%s "
                "total_tokens=%s max_tokens=%s html_chars=%d detail=%s",
                book_block_id, call_id, "accepted" if ok else "rejected",
                outcome.finish_reason or "unreported",
                outcome.usage.get("prompt_tokens"), outcome.usage.get("completion_tokens"),
                outcome.usage.get("reasoning_tokens"), outcome.usage.get("total_tokens"),
                self.get_max_tokens(), len(extracted), detail or "complete_html",
            )
            if not ok:
                raise ValueError(detail)
        return extracted
