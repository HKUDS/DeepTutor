"""Code generation and repair stages for math animator."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from deeptutor.agents.base_agent import BaseAgent
from deeptutor.core.trace import build_trace_metadata, new_call_id
from deeptutor.services.llm import has_thinking_tags

from ..models import ConceptAnalysis, GeneratedCode, SceneDesign
from ..utils import build_repair_error_message, extract_json_object

# Provider terminals that mean the output hit its token cap. Same set the
# chat loop uses; a missing or ordinary stop reason is not truncation.
_TRUNCATED_FINISH_REASONS = frozenset({"length", "max_tokens", "max_output_tokens"})
_TRUNCATION_BUDGET_MULTIPLIER = 2
_MAX_OUTPUT_TOKEN_BUDGET = 131_072

_UNUSABLE_RETRY_INSTRUCTION = (
    "\n\nYour previous response contained no usable structured code. "
    "Return exactly one JSON object with a non-empty `code` field."
)
_TRUNCATION_RETRY_INSTRUCTION = (
    "\n\nYour previous response was cut off by the token budget. "
    "Return exactly one complete JSON object. The `code` field must "
    "contain the full Manim source, not a fragment."
)
_REASONING_TRUNCATION_RETRY_INSTRUCTION = (
    "\n\nYour previous response was cut off because it exhausted the token budget. "
    "Compress your reasoning into a few sentences, then return exactly one complete "
    "JSON object. The `code` field must contain the full Manim source, not a fragment."
)


class GeneratedCodeOutputError(ValueError):
    """The model exhausted its retries without returning runnable code."""


def _finish_was_truncated(reason: object) -> bool:
    """Return whether the provider stopped because output hit a token cap."""
    return str(reason or "").strip().lower() in _TRUNCATED_FINISH_REASONS


def _next_output_budget(current: int) -> int:
    """Raise a truncated call's budget without growing past the safety cap."""
    if current <= 0:
        return current
    raised = current * _TRUNCATION_BUDGET_MULTIPLIER
    if raised <= current:
        raised = current + 1
    return min(raised, _MAX_OUTPUT_TOKEN_BUDGET)


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

    def _output_uses_reasoning(self, text: str) -> bool:
        """Whether this response came from a model that spends tokens on thinking."""
        if "<think>" in text.lower():
            return True
        model: str | None = None
        try:
            model = self.get_model()
        except Exception:
            model = None
        try:
            return bool(has_thinking_tags(self.binding or "", model))
        except Exception:
            return False

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
        content is blank, reasoning-only, or malformed JSON (#1202).  A
        truncated finish raises the next attempt's token budget instead of
        repeating the same cap.  Parsing stays strict and callers never
        proceed to the renderer with ``code=''``.
        """

        max_retries = max(0, int(self.get_max_retries()))
        configured_budget = max(0, int(self.get_max_tokens() or 0))
        budget = configured_budget
        last_error: Exception | None = None
        previous_truncated = False
        previous_reasoning = False
        last_finish_reason = ""
        last_budget = budget
        attempts_made = 0
        for structured_attempt in range(max_retries + 1):
            attempts_made = structured_attempt + 1
            if structured_attempt and previous_truncated:
                retry_instruction = (
                    _REASONING_TRUNCATION_RETRY_INSTRUCTION
                    if previous_reasoning
                    else _TRUNCATION_RETRY_INSTRUCTION
                )
            elif structured_attempt:
                retry_instruction = _UNUSABLE_RETRY_INSTRUCTION
                budget = configured_budget
            else:
                retry_instruction = ""

            stream_meta: dict[str, Any] = {}
            chunks: list[str] = []
            async for chunk in self.stream_llm(
                user_prompt=user_prompt + retry_instruction,
                system_prompt=system_prompt,
                response_format={"type": "json_object"},
                max_tokens=budget or None,
                stage=stage,
                stream_meta=stream_meta,
                trace_meta=build_trace_metadata(
                    call_id=new_call_id(call_id_prefix),
                    **trace_meta,
                    structured_attempt=structured_attempt + 1,
                ),
            ):
                chunks.append(chunk)

            response_text = "".join(chunks)
            finish_reason = stream_meta.get("finish_reason")
            finish_reason_text = "" if finish_reason is None else str(finish_reason).strip()
            truncated = _finish_was_truncated(finish_reason_text)
            retry_budget = _next_output_budget(budget) if truncated else configured_budget
            self.logger.debug(
                "Math animator %s attempt %d/%d finish_reason=%s response_chars=%d "
                "requested_max_tokens=%d retry_max_tokens=%d",
                stage,
                attempts_made,
                max_retries + 1,
                finish_reason_text or "none",
                len(response_text),
                budget,
                retry_budget,
            )

            try:
                generated = GeneratedCode.model_validate(extract_json_object(response_text))
                if not generated.code.strip():
                    raise ValueError("structured response has an empty code field")
                return generated
            except (json.JSONDecodeError, ValueError) as exc:
                last_error = exc
                last_finish_reason = finish_reason_text
                last_budget = budget
                previous_truncated = truncated
                previous_reasoning = self._output_uses_reasoning(response_text)
                at_cap = truncated and retry_budget <= budget
                if at_cap or structured_attempt >= max_retries:
                    break
                if truncated:
                    budget = retry_budget
                self.logger.warning(
                    "Math animator %s returned unusable structured output; retrying (%d/%d)",
                    stage,
                    structured_attempt + 1,
                    max_retries,
                )
                await asyncio.sleep(min(0.25 * (2**structured_attempt), 2.0))

        if previous_truncated:
            # Do not chain the parse error: its payload can be the thinking text.
            attempt_label = "attempt" if attempts_made == 1 else "attempts"
            raise GeneratedCodeOutputError(
                f"Math animator {stage} output was truncated by the token budget "
                f"(finish_reason={last_finish_reason or 'length'}, max_tokens={last_budget}) "
                f"after {attempts_made} {attempt_label}."
            ) from ValueError("model output was truncated before it contained usable code")
        raise GeneratedCodeOutputError(
            f"Math animator {stage} returned no usable code after {attempts_made} attempts."
        ) from last_error


__all__ = ["CodeGeneratorAgent", "GeneratedCodeOutputError"]
