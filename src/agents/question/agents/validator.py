#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Validator - Validate generated Q-A pairs with dynamic tool usage.

The Validator first makes an LLM-based quality judgment, then optionally
runs code verification only when the LLM deems it necessary.
"""

from __future__ import annotations

import json
import re
from typing import Any

from src.agents.base_agent import BaseAgent
from src.agents.question.models import QAPair, QuestionTemplate
from src.tools.code_executor import run_code


class Validator(BaseAgent):
    """
    Validate generated output against template requirements.

    Two-step process:
    1. LLM evaluates the Q-A pair and decides if code verification is needed
    2. If code check requested and code is available, run it and finalize
    """

    def __init__(
        self,
        language: str = "en",
        tool_flags: dict[str, bool] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            module_name="question",
            agent_name="validator",
            language=language,
            **kwargs,
        )
        self.tool_flags = tool_flags or {}

    async def process(
        self,
        template: QuestionTemplate,
        qa_pair: QAPair,
    ) -> dict[str, Any]:
        """
        Return approval decision and feedback.

        Flow:
        1. LLM validates quality and decides if code check is needed
        2. If code check requested, run verification code
        3. If code check reveals issues, append findings to feedback
        """
        verification_code = str(qa_pair.metadata.get("verification_code", "")).strip()
        has_code = bool(verification_code)
        code_enabled = self.tool_flags.get("write_code", True)

        # Step 1: LLM validation (includes decision on code check)
        llm_result = await self._validate_with_llm(
            template=template,
            qa_pair=qa_pair,
            has_verification_code=has_code and code_enabled,
        )

        decision = str(llm_result.get("decision", "reject")).lower()
        if decision not in {"approve", "reject"}:
            decision = "reject"

        issues = llm_result.get("issues", [])
        if not isinstance(issues, list):
            issues = []

        feedback = str(llm_result.get("feedback", "")).strip()
        needs_code_check = bool(llm_result.get("needs_code_check", False))

        # Step 2: Optionally run code verification
        code_check: dict[str, Any] = {}
        if needs_code_check and has_code and code_enabled:
            code_check = await self._run_code_check(verification_code)

            # If code check failed, downgrade approval or augment feedback
            if code_check.get("exit_code", -1) != 0:
                stderr = code_check.get("stderr", "")
                if decision == "approve":
                    decision = "reject"
                    feedback = (
                        f"Code verification failed (exit_code={code_check.get('exit_code')}). "
                        f"stderr: {stderr[:300]}. "
                        f"Original feedback: {feedback}"
                    )
                    issues.append("code_verification_failed")
                else:
                    feedback += (
                        f" | Code check also failed: {stderr[:200]}"
                    )

        if decision == "reject" and not feedback:
            feedback = (
                "Answer quality or alignment is insufficient. "
                "Regenerate with stricter alignment to the template."
            )

        return {
            "decision": decision,
            "approved": decision == "approve",
            "feedback": feedback,
            "issues": issues,
            "code_check": code_check,
            "needs_code_check": needs_code_check,
        }

    async def _validate_with_llm(
        self,
        template: QuestionTemplate,
        qa_pair: QAPair,
        has_verification_code: bool,
    ) -> dict[str, Any]:
        """Run LLM validation. The LLM also decides if code check is needed."""
        system_prompt = self.get_prompt("system", "")
        validate_prompt = self.get_prompt("validate", "")
        if not validate_prompt:
            validate_prompt = (
                "Template:\n{template}\n\n"
                "QA Pair:\n{qa_pair}\n\n"
                "Verification code available: {has_code}\n\n"
                'Return JSON {{"decision":"approve|reject","feedback":"","issues":[],"needs_code_check":true|false}}'
            )

        user_prompt = validate_prompt.format(
            template=json.dumps(template.__dict__, ensure_ascii=False, indent=2),
            qa_pair=json.dumps(qa_pair.__dict__, ensure_ascii=False, indent=2),
            has_code=str(has_verification_code).lower(),
        )

        try:
            try:
                response = await self.call_llm(
                    user_prompt=user_prompt,
                    system_prompt=system_prompt or "",
                    response_format={"type": "json_object"},
                    temperature=0.2,
                    stage="validator_decision",
                )
            except Exception as exc:
                self.logger.warning(
                    f"Validator JSON mode failed, retrying without response_format: {exc}"
                )
                response = await self.call_llm(
                    user_prompt=user_prompt,
                    system_prompt=system_prompt or "",
                    temperature=0.2,
                    stage="validator_decision_fallback",
                )
            return self._parse_json_like(response)
        except Exception as exc:
            self.logger.warning(f"Validator LLM failed, fallback reject: {exc}")
            return {
                "decision": "reject",
                "feedback": str(exc),
                "issues": ["validator_error"],
                "needs_code_check": False,
            }

    async def _run_code_check(self, code: str) -> dict[str, Any]:
        """Execute verification code."""
        try:
            result = await run_code(language="python", code=code, timeout=10)
            return {
                "exit_code": result.get("exit_code", -1),
                "stdout": (result.get("stdout", "") or "")[:800],
                "stderr": (result.get("stderr", "") or "")[:800],
            }
        except Exception as exc:
            return {"exit_code": -1, "stderr": str(exc)}

    @staticmethod
    def _parse_json_like(content: str) -> dict[str, Any]:
        if not content:
            return {}
        cleaned = re.sub(
            r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", "", content.strip()
        )
        block = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL)
        if block:
            cleaned = block.group(1).strip()

        try:
            data = json.loads(cleaned)
            return data if isinstance(data, dict) else {}
        except Exception:
            pass
        obj = re.search(r"\{[\s\S]*\}", cleaned)
        if obj:
            try:
                data = json.loads(obj.group(0))
                return data if isinstance(data, dict) else {}
            except Exception:
                return {}
        return {}
