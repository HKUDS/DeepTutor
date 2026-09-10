"""Code generation and repair stages for math animator."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from deeptutor.agents.base_agent import BaseAgent
from deeptutor.core.trace import build_trace_metadata, new_call_id

from ..models import ConceptAnalysis, GeneratedCode, SceneDesign
from ..utils import build_repair_error_message, extract_json_object


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
        """

        max_retries = max(0, int(self.get_max_retries()))
        last_error: Exception | None = None
        for structured_attempt in range(max_retries + 1):
            retry_instruction = ""
            if structured_attempt:
                retry_instruction = (
                    "\n\nYour previous response contained no usable structured code. "
                    "Return exactly one JSON object with a non-empty `code` field."
                )
            chunks: list[str] = []
            async for chunk in self.stream_llm(
                user_prompt=user_prompt + retry_instruction,
                system_prompt=system_prompt,
                response_format={"type": "json_object"},
                stage=stage,
                trace_meta=build_trace_metadata(
                    call_id=new_call_id(call_id_prefix),
                    **trace_meta,
                    structured_attempt=structured_attempt + 1,
                ),
            ):
                chunks.append(chunk)

            try:
                generated = GeneratedCode.model_validate(extract_json_object("".join(chunks)))
                if not generated.code.strip():
                    raise ValueError("structured response has an empty code field")
                return generated
            except (json.JSONDecodeError, ValueError) as exc:
                last_error = exc
                if structured_attempt >= max_retries:
                    break
                self.logger.warning(
                    "Math animator %s returned unusable structured output; retrying (%d/%d)",
                    stage,
                    structured_attempt + 1,
                    max_retries,
                )
                await asyncio.sleep(min(0.25 * (2**structured_attempt), 2.0))

        attempts = max_retries + 1
        raise GeneratedCodeOutputError(
            f"Math animator {stage} returned no usable code after {attempts} attempts."
        ) from last_error


__all__ = ["CodeGeneratorAgent", "GeneratedCodeOutputError"]
