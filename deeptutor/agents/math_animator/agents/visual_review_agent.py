"""Visual quality review stage for math animator outputs."""

from __future__ import annotations

import json

from deeptutor.agents.base_agent import BaseAgent
from deeptutor.core.context import Attachment
from deeptutor.core.trace import build_trace_metadata, new_call_id
from deeptutor.services.llm import supports_vision
from deeptutor.services.llm.structured_retry import json_with_reasoning_retry

from ..models import RenderResult, VisualReviewResult


class VisualReviewAgent(BaseAgent):
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        api_version: str | None = None,
        language: str = "zh",
    ) -> None:
        super().__init__(
            module_name="math_animator",
            agent_name="visual_review_agent",
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
        current_code: str,
        render_result: RenderResult,
        attachments: list[Attachment],
    ) -> VisualReviewResult:
        if not attachments:
            return VisualReviewResult(
                passed=True,
                summary="Visual review skipped because no review frames were available.",
                reviewed_frames=0,
            )

        model = self.get_model()
        if not supports_vision(self.binding, model):
            return VisualReviewResult(
                passed=True,
                summary="Visual review skipped because the current model does not support image inspection.",
                reviewed_frames=len(attachments),
            )

        system_prompt = self.get_prompt("system")
        user_template = self.get_prompt("user_template")
        if not system_prompt or not user_template:
            raise ValueError("VisualReviewAgent prompts are not configured.")

        user_prompt = user_template.format(
            user_input=user_input.strip(),
            output_mode=output_mode,
            reviewed_frames=len(attachments),
            render_json=json.dumps(
                render_result.model_dump(exclude={"visual_review"}), ensure_ascii=False, indent=2
            ),
            current_code=current_code,
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        async def _run(reasoning_effort: str | None) -> str:
            chunks: list[str] = []
            async for chunk in self.stream_llm(
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                messages=messages,
                attachments=attachments,
                response_format={"type": "json_object"},
                reasoning_effort=reasoning_effort,
                model=model,
                stage="render_output",
                trace_meta=build_trace_metadata(
                    call_id=new_call_id("math-visual-review"),
                    phase="render_output",
                    label="Visual quality review",
                    call_kind="math_visual_review",
                    trace_role="review",
                    trace_kind="llm_output",
                ),
            ):
                chunks.append(chunk)
            return "".join(chunks)

        payload = await json_with_reasoning_retry(_run, logger_instance=self.logger)
        if not payload:
            # The reviewer never gave a verdict, on either attempt. Rendering
            # already succeeded, and reporting ``passed=False`` here would send a
            # silent model into up to four repair-and-re-render cycles, so keep
            # the video and say that no review took place. Falling through to
            # ``VisualReviewResult``'s defaults would claim the opposite:
            # ``passed=True`` over ``reviewed_frames`` that were never looked at.
            return VisualReviewResult(
                passed=True,
                summary="Visual review was skipped because the reviewer returned no verdict.",
                reviewed_frames=0,
            )
        payload.setdefault("reviewed_frames", len(attachments))
        return VisualReviewResult.model_validate(payload)


__all__ = ["VisualReviewAgent"]
