"""Visual quality review stage for math animator outputs."""

from __future__ import annotations

import json

from deeptutor.agents._shared.structured_llm import stream_and_validate_json
from deeptutor.agents.base_agent import BaseAgent
from deeptutor.core.context import Attachment
from deeptutor.core.trace import build_trace_metadata, new_call_id
from deeptutor.services.llm import supports_vision

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

        def _messages(prompt: str) -> list[dict[str, str]]:
            return [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ]

        try:
            result = await stream_and_validate_json(
                stream=self.stream_llm,
                user_prompt=user_prompt,
                model_type=VisualReviewResult,
                build_messages=_messages,
                stream_kwargs={
                    "system_prompt": system_prompt,
                    "attachments": attachments,
                    "response_format": {"type": "json_object"},
                    "model": model,
                    "stage": "render_output",
                    "trace_meta": build_trace_metadata(
                        call_id=new_call_id("math-visual-review"),
                        phase="render_output",
                        label="Visual quality review",
                        call_kind="math_visual_review",
                        trace_role="review",
                        trace_kind="llm_output",
                    ),
                },
                is_complete=lambda payload: bool(payload.summary.strip()),
                # The whole review call sits inside retry_manager's
                # review_timeout_seconds; a third attempt risks turning a
                # slow reviewer into a timeout that re-renders a good result.
                max_attempts=2,
            )
        except ValueError:
            # An unreadable verdict must not destroy the render it judged —
            # same "cannot judge, keep the result" policy as the skip paths.
            self.logger.warning("Visual review returned no usable JSON; keeping the current render")
            return VisualReviewResult(
                passed=True,
                summary="Visual review skipped because the reviewer returned no readable verdict.",
                reviewed_frames=len(attachments),
            )
        if not result.reviewed_frames:
            result.reviewed_frames = len(attachments)
        return result


__all__ = ["VisualReviewAgent"]
