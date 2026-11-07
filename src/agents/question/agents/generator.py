#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Generator - Generate Q-A pairs from QuestionTemplate with dynamic tool selection.

The Generator uses a two-step process:
1. Plan which tools to use (LLM-driven decision)
2. Execute only the planned tools and generate the Q-A pair
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from src.agents.base_agent import BaseAgent
from src.agents.question.models import QAPair, QuestionTemplate
from src.tools.code_executor import run_code
from src.tools.rag_tool import rag_search
from src.tools.web_search import web_search


class Generator(BaseAgent):
    """
    Generate a question/answer pair with LLM-driven tool selection.

    Instead of always calling all tools, the Generator first asks the LLM
    which tools would be helpful for the given template, then only executes
    those tools before generating the final Q-A pair.
    """

    def __init__(
        self,
        kb_name: str | None = None,
        rag_mode: str = "naive",
        language: str = "en",
        tool_flags: dict[str, bool] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            module_name="question",
            agent_name="generator",
            language=language,
            **kwargs,
        )
        self.kb_name = kb_name
        self.rag_mode = rag_mode
        self.tool_flags = tool_flags or {}

    async def process(
        self,
        template: QuestionTemplate,
        user_topic: str = "",
        preference: str = "",
        validator_feedback: str = "",
    ) -> QAPair:
        """
        Generate one Q-A pair from a template.

        Flow:
        1. Ask LLM which tools to use (plan_tools)
        2. Execute only the planned tools
        3. Generate the Q-A pair with tool context
        4. Optionally run verification code if the plan included write_code
        """
        # Step 1: Plan tools
        tool_plan = await self._plan_tools(template, user_topic, preference)
        plan_prompt_trace = tool_plan.pop("_prompt_trace", {})

        # Step 2: Execute planned tools
        tool_context = await self._execute_tools(template, user_topic, tool_plan)

        # Step 3: Generate Q-A pair
        payload, generation_prompt_trace = await self._generate_payload(
            template=template,
            user_topic=user_topic,
            preference=preference,
            validator_feedback=validator_feedback,
            tool_context=tool_context,
        )

        # Step 4: Optionally verify with code (only if planned)
        code_result: dict[str, Any] = {}
        if tool_plan.get("use_code") and payload.get("verification_code"):
            code_result = await self._execute_verification_code(
                payload["verification_code"]
            )

        return QAPair(
            question_id=template.question_id,
            question=payload.get("question", ""),
            correct_answer=payload.get("correct_answer", ""),
            explanation=payload.get("explanation", ""),
            question_type=payload.get("question_type", template.question_type),
            options=(
                payload.get("options")
                if isinstance(payload.get("options"), dict)
                else None
            ),
            concentration=template.concentration,
            difficulty=template.difficulty,
            metadata={
                "source": template.source,
                "reference_question": template.reference_question,
                "tool_plan": tool_plan,
                "tool_context_keys": [k for k, v in tool_context.items() if v],
                "prompt_trace": {
                    "tool_plan_prompt": plan_prompt_trace,
                    "generation_prompt": generation_prompt_trace,
                },
                "code_result": code_result,
                "verification_code": payload.get("verification_code", ""),
                "validator_feedback": validator_feedback,
            },
        )

    # ------------------------------------------------------------------
    # Step 1: Tool Planning
    # ------------------------------------------------------------------

    async def _plan_tools(
        self,
        template: QuestionTemplate,
        user_topic: str,
        preference: str,
    ) -> dict[str, Any]:
        """Ask LLM which tools to use for this specific template."""
        plan_prompt_template = self.get_prompt("plan_tools", "")
        if not plan_prompt_template:
            # No prompt available — fall back to conservative defaults
            return self._default_tool_plan()

        system_prompt = self.get_prompt("system", "") or ""
        prompt = plan_prompt_template.format(
            template=json.dumps(template.__dict__, ensure_ascii=False, indent=2),
            user_topic=user_topic,
            preference=preference or "(none)",
            available_tools=self._describe_available_tools(),
        )

        try:
            try:
                response = await self.call_llm(
                    user_prompt=prompt,
                    system_prompt=system_prompt,
                    response_format={"type": "json_object"},
                    stage="generator_plan_tools",
                )
            except Exception as exc:
                self.logger.warning(
                    f"Tool planning JSON mode failed, retrying without response_format: {exc}"
                )
                response = await self.call_llm(
                    user_prompt=prompt,
                    system_prompt=system_prompt,
                    stage="generator_plan_tools_fallback",
                )
            plan = self._parse_json_like(response)

            # Respect config-level tool flags (config can disable tools globally)
            plan["use_rag"] = bool(plan.get("use_rag", True)) and self.tool_flags.get(
                "rag_tool", True
            )
            plan["use_web"] = bool(
                plan.get("use_web", False)
            ) and self.tool_flags.get("web_search", True)
            plan["use_code"] = bool(
                plan.get("use_code", False)
            ) and self.tool_flags.get("write_code", True)
            plan["_prompt_trace"] = {
                "system_prompt": system_prompt,
                "user_prompt": prompt,
            }
            return plan

        except Exception as exc:
            self.logger.warning(f"Tool planning failed, using defaults: {exc}")
            return self._default_tool_plan()

    def _default_tool_plan(self) -> dict[str, Any]:
        """Conservative default: only RAG if available."""
        return {
            "use_rag": self.tool_flags.get("rag_tool", True),
            "use_web": False,
            "use_code": False,
            "reasoning": "default plan (no LLM planning)",
            "_prompt_trace": {},
        }

    def _describe_available_tools(self) -> str:
        tools: list[str] = []
        if self.tool_flags.get("rag_tool", True):
            tools.append(
                "rag_tool: Retrieve relevant knowledge from the course knowledge base. "
                "Useful for factual, conceptual, and curriculum-aligned questions."
            )
        if self.tool_flags.get("web_search", True):
            tools.append(
                "web_search: Search the web for up-to-date or supplementary information. "
                "Useful when the topic requires current data, real-world examples, or goes beyond the KB."
            )
        if self.tool_flags.get("write_code", True):
            tools.append(
                "write_code: Execute Python code to compute or verify answers. "
                "Useful for coding questions, mathematical computations, and algorithm verification."
            )
        return "\n".join(f"- {t}" for t in tools) or "(no tools available)"

    # ------------------------------------------------------------------
    # Step 2: Execute Tools
    # ------------------------------------------------------------------

    async def _execute_tools(
        self,
        template: QuestionTemplate,
        user_topic: str,
        tool_plan: dict[str, Any],
    ) -> dict[str, str]:
        """Execute only the tools chosen by the tool plan."""
        context: dict[str, str] = {}

        if tool_plan.get("use_rag"):
            try:
                query = (
                    tool_plan.get("rag_query")
                    or template.concentration
                    or user_topic
                )
                rag_result = await rag_search(
                    query=query,
                    kb_name=self.kb_name,
                    mode=self.rag_mode,
                    only_need_context=True,
                )
                context["rag"] = (rag_result.get("answer", "") or "")[:4000]
            except Exception as exc:
                self.logger.warning(f"RAG tool failed: {exc}")

        if tool_plan.get("use_web"):
            try:
                query = (
                    tool_plan.get("web_query")
                    or template.concentration
                    or user_topic
                )
                # web_search is synchronous — run in thread to avoid blocking
                web_result = await asyncio.to_thread(web_search, query=query)
                context["web"] = (web_result.get("answer", "") or "")[:2000]
            except Exception as exc:
                self.logger.warning(f"Web search tool failed: {exc}")

        return context

    # ------------------------------------------------------------------
    # Step 3: Generate Q-A Pair
    # ------------------------------------------------------------------

    async def _generate_payload(
        self,
        template: QuestionTemplate,
        user_topic: str,
        preference: str,
        validator_feedback: str,
        tool_context: dict[str, str],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        system_prompt = self.get_prompt("system", "")
        user_prompt_template = self.get_prompt("generate", "")
        if not user_prompt_template:
            user_prompt_template = (
                "Template: {template}\n"
                "User topic: {user_topic}\n"
                "Preference: {preference}\n"
                "Validator feedback: {validator_feedback}\n"
                "Tool context: {tool_context}\n\n"
                'Return JSON {{"question_type":"","question":"","options":{{}},"correct_answer":"","explanation":"","verification_code":""}}'
            )

        # Build a concise tool context description
        tool_summary = {}
        if tool_context.get("rag"):
            tool_summary["rag_knowledge"] = tool_context["rag"]
        if tool_context.get("web"):
            tool_summary["web_results"] = tool_context["web"]
        if not tool_summary:
            tool_summary["note"] = "No external tool context was used for this question."

        user_prompt = user_prompt_template.format(
            template=json.dumps(template.__dict__, ensure_ascii=False, indent=2),
            user_topic=user_topic,
            preference=preference or "(none)",
            validator_feedback=validator_feedback or "(none)",
            tool_context=json.dumps(tool_summary, ensure_ascii=False, indent=2),
        )

        try:
            response = await self.call_llm(
                user_prompt=user_prompt,
                system_prompt=system_prompt or "",
                response_format={"type": "json_object"},
                stage="generator_build_qa",
            )
        except Exception as exc:
            self.logger.warning(
                f"Generator JSON mode failed, retrying without response_format: {exc}"
            )
            response = await self.call_llm(
                user_prompt=user_prompt,
                system_prompt=system_prompt or "",
                stage="generator_build_qa_fallback",
            )
        payload = self._parse_json_like(response)

        if "question" not in payload or not str(payload.get("question", "")).strip():
            payload["question"] = (
                f"Based on {template.concentration}, answer this {template.difficulty} "
                f"{template.question_type} question."
            )
        if "correct_answer" not in payload:
            payload["correct_answer"] = "N/A"
        if "explanation" not in payload:
            payload["explanation"] = "N/A"
        if "question_type" not in payload:
            payload["question_type"] = template.question_type

        return payload, {
            "system_prompt": system_prompt or "",
            "user_prompt": user_prompt,
            "tool_context": tool_summary,
        }

    # ------------------------------------------------------------------
    # Step 4: Optional Code Verification
    # ------------------------------------------------------------------

    async def _execute_verification_code(self, code: str) -> dict[str, Any]:
        if not code or not isinstance(code, str):
            return {}
        try:
            result = await run_code(language="python", code=code, timeout=10)
            return {
                "stdout": (result.get("stdout", "") or "")[:800],
                "stderr": (result.get("stderr", "") or "")[:800],
                "exit_code": result.get("exit_code", -1),
            }
        except Exception as exc:
            self.logger.warning(f"write_code tool failed: {exc}")
            return {"stderr": str(exc), "exit_code": -1}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_json_like(content: str) -> dict[str, Any]:
        if not content or not content.strip():
            return {}

        cleaned = re.sub(
            r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", "", content.strip()
        )
        block_match = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL)
        if block_match:
            cleaned = block_match.group(1).strip()

        try:
            payload = json.loads(cleaned)
            return payload if isinstance(payload, dict) else {}
        except Exception:
            pass

        obj_match = re.search(r"\{[\s\S]*\}", cleaned)
        if obj_match:
            try:
                payload = json.loads(obj_match.group(0))
                return payload if isinstance(payload, dict) else {}
            except Exception:
                return {}
        return {}
