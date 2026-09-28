"""Code generation and repair stages for math animator."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from deeptutor.agents.base_agent import BaseAgent
from deeptutor.core.trace import build_trace_metadata, new_call_id
from deeptutor.services.llm import StreamOutcome
from deeptutor.services.llm.reasoning_params import RETRY_REASONING_EFFORT

from ..models import ConceptAnalysis, GeneratedCode, SceneDesign
from ..utils import (
    build_repair_error_message,
    describe_unusable_output,
    escalated_max_tokens,
    extract_json_object,
)

#: How much of a failed response to keep in the debug log. Enough to see where
#: a truncated generation stopped, short enough to stay readable (#1545).
_RAW_EXCERPT_CHARS = 200


class GeneratedCodeOutputError(ValueError):
    """The model exhausted its retries without returning runnable code."""


class CodeGeneratorAgent(BaseAgent):
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        api_version: str | None = None,
        language: str = "zh",
    ) -> None:
        super().__init__(
            module_name="math_animator",
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
        output_mode: str,
        analysis: ConceptAnalysis,
        design: SceneDesign,
        duration_target_seconds: float | None = None,
    ) -> GeneratedCode:
        """BaseAgent-compatible entrypoint for the default generation path."""
        return await self.generate(
            user_input=user_input,
            output_mode=output_mode,
            analysis=analysis,
            design=design,
            duration_target_seconds=duration_target_seconds,
        )

    async def generate(
        self,
        *,
        user_input: str,
        output_mode: str,
        analysis: ConceptAnalysis,
        design: SceneDesign,
        duration_target_seconds: float | None = None,
    ) -> GeneratedCode:
        system_prompt = self.get_prompt("generate_system")
        user_template = self.get_prompt("generate_user_template")
        if not system_prompt or not user_template:
            raise ValueError("CodeGeneratorAgent generation prompts are not configured.")

        user_prompt = user_template.format(
            user_input=user_input.strip(),
            output_mode=output_mode,
            duration_requirement=(
                f"用户明确目标时长约 {duration_target_seconds:.1f} 秒，生成代码必须围绕该时长做节奏预算。"
                if duration_target_seconds is not None
                else "用户未给出明确秒数时长，可按标准教学节奏生成。"
            ),
            analysis_json=json.dumps(analysis.model_dump(), ensure_ascii=False, indent=2),
            design_json=json.dumps(design.model_dump(), ensure_ascii=False, indent=2),
        )
        return await self._request_generated_code(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            stage="code_generation",
            call_id_prefix="math-codegen",
            trace_meta={
                "phase": "code_generation",
                "label": "Code generation",
                "call_kind": "math_code_generation",
                "trace_role": "generate",
                "trace_kind": "llm_output",
            },
        )

    async def repair(
        self,
        *,
        user_input: str,
        output_mode: str,
        current_code: str,
        error_message: str,
        attempt: int,
        duration_target_seconds: float | None = None,
    ) -> GeneratedCode:
        system_prompt = self.get_prompt("retry_system")
        user_template = self.get_prompt("retry_user_template")
        if not system_prompt or not user_template:
            raise ValueError("CodeGeneratorAgent retry prompts are not configured.")

        user_prompt = user_template.format(
            user_input=user_input.strip(),
            output_mode=output_mode,
            attempt=attempt,
            duration_requirement=(
                f"目标时长约 {duration_target_seconds:.1f} 秒，修复后仍需保持接近该时长。"
                if duration_target_seconds is not None
                else "无明确目标时长。"
            ),
            error_message=build_repair_error_message(error_message),
            current_code=current_code,
        )
        return await self._request_generated_code(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            stage="code_retry",
            call_id_prefix="math-retry",
            trace_meta={
                "phase": "code_retry",
                "label": f"Code retry #{attempt}",
                "call_kind": "math_code_retry",
                "trace_role": "repair",
                "trace_kind": "llm_output",
                "attempt": attempt,
            },
        )

    async def _request_generated_code(
        self,
        *,
        user_prompt: str,
        system_prompt: str,
        stage: str,
        call_id_prefix: str,
        trace_meta: dict[str, Any],
    ) -> GeneratedCode:
        """Retry model-success responses that contain no usable code.

        Provider retries already cover transport failures.  This second,
        deliberately narrow boundary covers a successful response whose
        content is blank, reasoning-only, or malformed JSON (#1202).  Parsing
        stays strict and callers never proceed to the renderer with ``code=''``.

        A retry is not a repeat.  The provider reports whether it stopped at the
        output cap, and a reasoning model that spent the whole budget on
        chain-of-thought fails that way every time on the same request (#1547),
        so a truncated attempt is retried with a larger budget and lower
        reasoning effort. Whichever way the attempt failed, the
        reason reaches both the log and the raised error (#1545).
        """

        max_retries = max(0, int(self.get_max_retries()))
        base_max_tokens = max(0, int(self.get_max_tokens() or 0))
        attempts = max_retries + 1
        last_error: Exception | None = None
        last_failure = ""
        truncations = 0
        for structured_attempt in range(attempts):
            max_tokens = escalated_max_tokens(base_max_tokens, truncations)
            retry_instruction = self._retry_instruction(
                attempt=structured_attempt, after_truncation=truncations > 0
            )
            outcome = StreamOutcome()
            chunks: list[str] = []
            async for chunk in self.stream_llm(
                user_prompt=user_prompt + retry_instruction,
                system_prompt=system_prompt,
                response_format={"type": "json_object"},
                max_tokens=max_tokens or None,
                reasoning_effort=(RETRY_REASONING_EFFORT if structured_attempt else None),
                stage=stage,
                trace_meta=build_trace_metadata(
                    call_id=new_call_id(call_id_prefix),
                    **trace_meta,
                    structured_attempt=structured_attempt + 1,
                ),
                outcome=outcome,
            ):
                chunks.append(chunk)
            raw_response = "".join(chunks)

            try:
                generated = GeneratedCode.model_validate(extract_json_object(raw_response))
                if not generated.code.strip():
                    raise ValueError("structured response has an empty code field")
                return generated
            except (json.JSONDecodeError, ValueError) as exc:
                last_error = exc
                last_failure = describe_unusable_output(
                    error=exc,
                    raw_response=raw_response,
                    outcome=outcome,
                    max_tokens=max_tokens,
                )
                if outcome.truncated:
                    truncations += 1
                self.logger.warning(
                    "Math animator %s attempt %d/%d produced no usable code: %s",
                    stage,
                    structured_attempt + 1,
                    attempts,
                    last_failure,
                )
                self.logger.debug(
                    "Math animator %s attempt %d raw response head=%r tail=%r",
                    stage,
                    structured_attempt + 1,
                    raw_response[:_RAW_EXCERPT_CHARS],
                    raw_response[-_RAW_EXCERPT_CHARS:],
                )
                if structured_attempt >= max_retries:
                    break
                await asyncio.sleep(min(0.25 * (2**structured_attempt), 2.0))

        raise GeneratedCodeOutputError(
            f"Math animator {stage} returned no usable code after {attempts} attempts. "
            f"Last attempt: {last_failure}"
        ) from last_error

    @staticmethod
    def _retry_instruction(*, attempt: int, after_truncation: bool) -> str:
        """The nudge appended to the prompt on retry, matched to the failure."""

        if not attempt:
            return ""
        if after_truncation:
            # Asking again for "structured code" is useless when the previous
            # response was a complete thought and an incomplete answer: the
            # budget, not the format, is what ran out (#1547).
            return (
                "\n\nYour previous response hit the output token limit before the JSON "
                "was complete. Keep your internal reasoning to a few sentences and spend "
                "the budget on the code itself. Return exactly one JSON object with a "
                "non-empty `code` field and nothing else."
            )
        return (
            "\n\nYour previous response contained no usable structured code. "
            "Return exactly one JSON object with a non-empty `code` field."
        )


__all__ = ["CodeGeneratorAgent", "GeneratedCodeOutputError"]
