"""Concept analysis stage for math animator."""

from __future__ import annotations

from deeptutor.agents.base_agent import BaseAgent
from deeptutor.core.context import Attachment
from deeptutor.core.trace import build_trace_metadata, new_call_id
from deeptutor.services.prompt import get_prompt_manager

from ..models import ConceptAnalysis
from ..utils import extract_json_object


class ConceptAnalysisAgent(BaseAgent):
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        api_version: str | None = None,
        language: str = "zh",
    ) -> None:
        super().__init__(
            module_name="math_animator",
            agent_name="concept_analysis_agent",
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
        output_mode: str,
        style_hint: str,
        attachments: list[Attachment],
    ) -> ConceptAnalysis:
        system_prompt = self.get_prompt("system")
        user_template = self.get_prompt("user_template")
        if not system_prompt or not user_template:
            # Retry once: a worker that looked the prompts up before the
            # package finished installing used to cache the empty result
            # forever. PromptManager no longer caches misses, so a reload can
            # now actually recover — and it stays the one place that knows how
            # to find a prompt file.
            self.prompts = get_prompt_manager().reload_prompts(
                "math_animator", "concept_analysis_agent", self.language
            )
            system_prompt = self.get_prompt("system")
            user_template = self.get_prompt("user_template")

        if not system_prompt or not user_template:
            raise ValueError("ConceptAnalysisAgent prompts are not configured.")

        reference_count = sum(1 for item in attachments if item.type == "image")
        user_prompt = user_template.format(
            user_input=user_input.strip(),
            history_context=history_context.strip() or "(none)",
            output_mode=output_mode,
            style_hint=style_hint.strip() or "(none)",
            reference_count=reference_count,
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        _chunks: list[str] = []
        async for _c in self.stream_llm(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            messages=messages,
            attachments=attachments,
            response_format={"type": "json_object"},
            stage="concept_analysis",
            trace_meta=build_trace_metadata(
                call_id=new_call_id("math-analysis"),
                phase="concept_analysis",
                label="Concept analysis",
                call_kind="math_concept_analysis",
                trace_role="analyze",
                trace_kind="llm_output",
            ),
        ):
            _chunks.append(_c)
        response = "".join(_chunks)
        return ConceptAnalysis.model_validate(extract_json_object(response))
