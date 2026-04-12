#!/usr/bin/env python
"""
Generator - Generate Q-A pairs from QuestionTemplate in a single LLM call.
"""

from __future__ import annotations

import json
import re
from typing import Any

from deeptutor.agents.base_agent import BaseAgent
from deeptutor.agents.question.models import QAPair, QuestionTemplate
from deeptutor.core.trace import build_trace_metadata, new_call_id
from deeptutor.runtime.registry.tool_registry import get_tool_registry


class Generator(BaseAgent):
    """
    Generate a question/answer pair from one template.

    The simplified pipeline injects the user's enabled tools as prompt guidance
    and relies on the knowledge context already prepared upstream.
    """

    def __init__(
        self,
        kb_name: str | None = None,
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
        self.tool_flags = tool_flags or {}
        self._tool_registry = get_tool_registry()

    async def process(
        self,
        template: QuestionTemplate,
        user_topic: str = "",
        preference: str = "",
        history_context: str = "",
    ) -> QAPair:
        """
        Generate one Q-A pair from a template in a single call.
        """
        available_tools = self._build_available_tools_text()
        knowledge_context = str(template.metadata.get("knowledge_context", "")).strip()
        payload = await self._generate_payload(
            template=template,
            user_topic=user_topic,
            preference=preference,
            history_context=history_context,
            knowledge_context=knowledge_context,
            available_tools=available_tools,
        )
        payload, validation = await self._validate_and_repair_payload(
            template=template,
            payload=payload,
            user_topic=user_topic,
            preference=preference,
            history_context=history_context,
            knowledge_context=knowledge_context,
            available_tools=available_tools,
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
            validation=validation,
            metadata={
                "source": template.source,
                "reference_question": template.reference_question,
                "enabled_tools": self._enabled_tool_names(),
                "available_tools": available_tools,
                "knowledge_context": knowledge_context,
            },
        )

    def _build_available_tools_text(self) -> str:
        enabled_tools = self._enabled_tool_names()
        if not enabled_tools:
            return "(no tools available)"
        return self._tool_registry.build_prompt_text(
            enabled_tools,
            format="list",
            language=self.language,
            kb_name=self.kb_name or "",
        )

    async def _generate_payload(
        self,
        template: QuestionTemplate,
        user_topic: str,
        preference: str,
        history_context: str,
        knowledge_context: str,
        available_tools: str,
    ) -> dict[str, Any]:
        system_prompt = self.get_prompt("system", "")
        user_prompt_template = self.get_prompt("generate", "")
        if not user_prompt_template:
            user_prompt_template = (
                "Template: {template}\n"
                "User topic: {user_topic}\n"
                "Preference: {preference}\n"
                "Conversation context: {history_context}\n"
                "Knowledge context: {knowledge_context}\n"
                "Enabled tools: {available_tools}\n\n"
                'Return JSON {{"question_type":"","question":"","options":{{}},"correct_answer":"","explanation":""}}'
            )

        user_prompt = user_prompt_template.format(
            template=json.dumps(template.__dict__, ensure_ascii=False, indent=2),
            user_topic=user_topic,
            preference=preference or "(none)",
            history_context=history_context or "(none)",
            knowledge_context=knowledge_context or "(none)",
            available_tools=available_tools,
        )

        _chunks: list[str] = []
        async for _c in self.stream_llm(
            user_prompt=user_prompt,
            system_prompt=system_prompt or "",
            response_format={"type": "json_object"},
            stage="generator_build_qa",
            trace_meta=build_trace_metadata(
                call_id=new_call_id(f"quiz-{template.question_id}"),
                phase="generation",
                label=f"Generate {template.question_id}",
                call_kind="llm_generation",
                trace_id=template.question_id,
                question_id=template.question_id,
            ),
        ):
            _chunks.append(_c)
        response = "".join(_chunks)
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

        return payload

    async def _validate_and_repair_payload(
        self,
        template: QuestionTemplate,
        payload: dict[str, Any],
        user_topic: str,
        preference: str,
        history_context: str,
        knowledge_context: str,
        available_tools: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        expected_type = self._normalize_question_type(template.question_type)
        normalized = self._normalize_payload_shape(expected_type, payload)
        issues = self._collect_payload_issues(expected_type, normalized)
        repaired = False

        if issues:
            repaired_payload = await self._repair_payload(
                template=template,
                payload=normalized,
                issues=issues,
                user_topic=user_topic,
                preference=preference,
                history_context=history_context,
                knowledge_context=knowledge_context,
                available_tools=available_tools,
            )
            if repaired_payload:
                candidate = self._normalize_payload_shape(expected_type, repaired_payload)
                candidate_issues = self._collect_payload_issues(expected_type, candidate)
                if not candidate_issues or len(candidate_issues) <= len(issues):
                    normalized = candidate
                    issues = candidate_issues
                    repaired = True

        validation = {
            "requested_question_type": expected_type,
            "schema_ok": not issues,
            "repaired": repaired,
            "issues": issues,
        }
        return normalized, validation

    async def _repair_payload(
        self,
        template: QuestionTemplate,
        payload: dict[str, Any],
        issues: list[str],
        user_topic: str,
        preference: str,
        history_context: str,
        knowledge_context: str,
        available_tools: str,
    ) -> dict[str, Any]:
        expected_type = self._normalize_question_type(template.question_type)
        repair_prompt = (
            "You are repairing an invalid quiz question JSON.\n\n"
            f"QuestionTemplate:\n{json.dumps(template.__dict__, ensure_ascii=False, indent=2)}\n\n"
            f"User topic:\n{user_topic or '(none)'}\n\n"
            f"User preference:\n{preference or '(none)'}\n\n"
            f"Conversation context:\n{history_context or '(none)'}\n\n"
            f"Knowledge context:\n{knowledge_context or '(none)'}\n\n"
            f"Enabled tools:\n{available_tools}\n\n"
            f"Invalid payload:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
            f"Detected issues:\n{json.dumps(issues, ensure_ascii=False)}\n\n"
            f"Rewrite the payload so it strictly matches question_type='{expected_type}'.\n"
            "Hard rules:\n"
            "- Keep the same concentration and difficulty intent.\n"
            "- question_type must exactly match the template.\n"
            "- If question_type is choice: provide exactly 4 options (A-D), and correct_answer must be the correct option key.\n"
            "- If question_type is written: do not provide options, and the learner must write an explanation or short answer.\n"
            "- If question_type is coding: do not provide options, and the learner must write code, pseudocode, or an algorithmic solution.\n"
            "- For written/coding questions, never ask the learner to select, choose, or pick among options.\n"
            "- Return JSON only with keys: question_type, question, options, correct_answer, explanation.\n"
        )

        _chunks: list[str] = []
        async for _c in self.stream_llm(
            user_prompt=repair_prompt,
            system_prompt="You fix malformed quiz payloads and return valid JSON only.",
            response_format={"type": "json_object"},
            stage="generator_repair_qa",
            trace_meta=build_trace_metadata(
                call_id=new_call_id(f"quiz-repair-{template.question_id}"),
                phase="generation",
                label=f"Repair question {self._humanize_question_id(template.question_id)} format",
                call_kind="llm_generation",
                trace_id=template.question_id,
                question_id=template.question_id,
            ),
        ):
            _chunks.append(_c)
        response = "".join(_chunks)
        return self._parse_json_like(response)

    @classmethod
    def _normalize_question_type(cls, question_type: str) -> str:
        normalized = str(question_type or "").strip().lower()
        return normalized if normalized in {"choice", "written", "coding"} else "written"

    @classmethod
    def _normalize_payload_shape(
        cls,
        expected_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        normalized = dict(payload or {})
        normalized["question_type"] = expected_type
        normalized["question"] = str(normalized.get("question", "") or "").strip()
        normalized["correct_answer"] = str(
            normalized.get("correct_answer", "") or ""
        ).strip()
        normalized["explanation"] = str(normalized.get("explanation", "") or "").strip()

        raw_options = normalized.get("options")
        if expected_type == "choice":
            clean_options: dict[str, str] = {}
            if isinstance(raw_options, dict):
                for key, value in raw_options.items():
                    option_key = str(key or "").strip().upper()[:1]
                    option_value = str(value or "").strip()
                    if option_key in {"A", "B", "C", "D"} and option_value:
                        clean_options[option_key] = option_value
            normalized["options"] = clean_options if clean_options else None
            if normalized["correct_answer"] and clean_options:
                answer_upper = normalized["correct_answer"].upper()
                if answer_upper in clean_options:
                    normalized["correct_answer"] = answer_upper
                else:
                    for key, value in clean_options.items():
                        if normalized["correct_answer"].strip().lower() == value.lower():
                            normalized["correct_answer"] = key
                            break
        else:
            normalized["options"] = None

        return normalized

    @classmethod
    def _collect_payload_issues(
        cls,
        expected_type: str,
        payload: dict[str, Any],
    ) -> list[str]:
        issues: list[str] = []
        question = str(payload.get("question", "") or "")
        correct_answer = str(payload.get("correct_answer", "") or "").strip()
        options = payload.get("options")

        if expected_type == "choice":
            option_keys = set(options.keys()) if isinstance(options, dict) else set()
            if not option_keys:
                issues.append("choice_missing_options")
            elif option_keys != {"A", "B", "C", "D"}:
                issues.append("choice_options_must_be_a_to_d")
            if correct_answer.upper() not in {"A", "B", "C", "D"}:
                issues.append("choice_correct_answer_must_be_option_key")
        else:
            if cls._payload_looks_like_choice(question=question, correct_answer=correct_answer, options=options):
                issues.append("non_choice_payload_looks_like_multiple_choice")

        if not question:
            issues.append("missing_question")
        if not correct_answer:
            issues.append("missing_correct_answer")
        if not str(payload.get("explanation", "") or "").strip():
            issues.append("missing_explanation")
        return issues

    @staticmethod
    def _payload_looks_like_choice(
        question: str,
        correct_answer: str,
        options: Any,
    ) -> bool:
        if isinstance(options, dict) and bool(options):
            return True
        lowered = question.lower()
        if re.search(
            r"\b(select|choose|pick|which of the following|which option|multiple[- ]choice)\b",
            lowered,
        ):
            return True
        if re.search(r"(^|\n)\s*[A-D][\.\):]\s+", question):
            return True
        return correct_answer.upper() in {"A", "B", "C", "D"}

    @staticmethod
    def _humanize_question_id(question_id: str) -> str:
        match = re.fullmatch(r"q_(\d+)", str(question_id or "").strip().lower())
        if match:
            return f"question {match.group(1)}"
        return str(question_id or "question").strip() or "question"

    def _is_tool_enabled(self, tool_name: str) -> bool:
        aliases = {
            "rag": ["rag", "rag_tool"],
            "web_search": ["web_search"],
            "code_execution": ["code_execution", "write_code"],
        }
        keys = aliases.get(tool_name, [tool_name])
        present = [key for key in keys if key in self.tool_flags]
        if not present:
            return True
        return any(bool(self.tool_flags.get(key)) for key in present)

    def _enabled_tool_names(self) -> list[str]:
        enabled_tools: list[str] = []
        if self._is_tool_enabled("rag"):
            enabled_tools.append("rag")
        if self._is_tool_enabled("web_search"):
            enabled_tools.append("web_search")
        if self._is_tool_enabled("code_execution"):
            enabled_tools.append("code_execution")
        return enabled_tools

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
