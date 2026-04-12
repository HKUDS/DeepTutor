#!/usr/bin/env python
"""
IdeaAgent - Generate candidate question directions from topic and preference.
"""

from __future__ import annotations

import json
from typing import Any

from deeptutor.agents.base_agent import BaseAgent
from deeptutor.agents.question.models import QuestionTemplate
from deeptutor.core.trace import build_trace_metadata, new_call_id
from deeptutor.tools.rag_tool import rag_search


BATCH_SIZE = 5


class IdeaAgent(BaseAgent):
    """
    Generate candidate question ideas with knowledge grounding.
    """

    def __init__(
        self,
        kb_name: str | None = None,
        enable_rag: bool = True,
        language: str = "en",
        **kwargs: Any,
    ) -> None:
        super().__init__(
            module_name="question",
            agent_name="idea_agent",
            language=language,
            **kwargs,
        )
        self.kb_name = kb_name
        self.enable_rag = enable_rag

    async def process(
        self,
        user_topic: str,
        preference: str = "",
        num_ideas: int = 5,
        target_difficulty: str = "",
        target_question_type: str = "",
        existing_concentrations: list[str] | None = None,
        batch_number: int | None = None,
    ) -> dict[str, Any]:
        """
        Build grounded question templates in a single pass.
        """
        batch_size = max(1, min(int(num_ideas or 1), BATCH_SIZE))
        trace_id = f"batch-{batch_number}" if batch_number is not None else "ideation"
        if self.enable_rag and self.kb_name:
            retrievals = await self._retrieve_context(
                user_topic,
                trace_id=trace_id,
                batch_number=batch_number,
            )
            knowledge_context = self._build_context(retrievals)
        else:
            retrievals = []
            knowledge_context = "Retrieval disabled."

        templates = await self._generate_templates(
            user_topic=user_topic,
            preference=preference,
            knowledge_context=knowledge_context,
            num_ideas=batch_size,
            target_difficulty=target_difficulty,
            target_question_type=target_question_type,
            existing_concentrations=existing_concentrations or [],
            retrieval_queries=[
                item.get("query", "") for item in retrievals if isinstance(item, dict)
            ],
            trace_id=trace_id,
            batch_number=batch_number,
        )
        return {
            "templates": templates,
            "retrievals": retrievals,
            "knowledge_context": knowledge_context,
            "batch_size": batch_size,
        }

    async def _retrieve_context(
        self,
        user_topic: str,
        trace_id: str,
        batch_number: int | None = None,
    ) -> list[dict[str, Any]]:
        retrievals: list[dict[str, Any]] = []
        call_id = new_call_id("quiz-rag")
        trace_meta = build_trace_metadata(
            call_id=call_id,
            phase="ideation",
            label=(
                f"Retrieve knowledge (batch {batch_number})"
                if batch_number is not None
                else "Retrieve knowledge"
            ),
            call_kind="tool_lookup",
            trace_id=trace_id,
            batch=batch_number,
        )
        try:
            await self._emit_trace_event(
                {
                    "event": "tool_call",
                    "state": "running",
                    "tool_name": "rag",
                    "tool_args": {
                        "query": user_topic,
                        "kb_name": self.kb_name,
                        "only_need_context": True,
                    },
                    **trace_meta,
                }
            )
            result = await rag_search(
                query=user_topic,
                kb_name=self.kb_name,
                only_need_context=True,
            )
            await self._emit_trace_event(
                {
                    "event": "tool_result",
                    "state": "complete",
                    "tool_name": "rag",
                    "result": result.get("answer", ""),
                    **trace_meta,
                }
            )
            retrievals.append(
                {
                    "query": user_topic,
                    "answer": result.get("answer", ""),
                    "provider": result.get("provider", ""),
                }
            )
        except Exception as exc:
            self.logger.warning(f"RAG retrieval failed for topic '{user_topic}': {exc}")
            await self._emit_trace_event(
                {
                    "event": "tool_result",
                    "state": "error",
                    "tool_name": "rag",
                    "result": str(exc),
                    **trace_meta,
                }
            )
            retrievals.append({"query": user_topic, "answer": "", "error": str(exc)})
        return retrievals

    def _build_context(self, retrievals: list[dict[str, Any]]) -> str:
        sections: list[str] = []
        for item in retrievals:
            answer = item.get("answer", "")
            if not answer:
                continue
            clipped = answer[:4000] + ("...[truncated]" if len(answer) > 4000 else "")
            sections.append(f"=== Query: {item.get('query','')} ===\n{clipped}")
        return "\n\n".join(sections) if sections else "No retrieval context available."

    async def _generate_templates(
        self,
        user_topic: str,
        preference: str,
        knowledge_context: str,
        num_ideas: int,
        target_difficulty: str = "",
        target_question_type: str = "",
        existing_concentrations: list[str] | None = None,
        retrieval_queries: list[str] | None = None,
        trace_id: str = "ideation",
        batch_number: int | None = None,
    ) -> list[QuestionTemplate]:
        system_prompt = self.get_prompt("system", "")
        idea_prompt = self.get_prompt("generate_ideas", "")
        if not idea_prompt:
            idea_prompt = (
                "Topic: {user_topic}\n"
                "Preference: {preference}\n"
                "Existing concentrations:\n{existing_concentrations}\n"
                "Knowledge context:\n{knowledge_context}\n\n"
                "Generate {num_ideas} candidate question ideas.\n"
                'Return JSON {{"ideas":[{{"concentration":"","question_type":"","difficulty":"","rationale":""}}]}}'
            )

        constraints: list[str] = []
        if target_difficulty:
            constraints.append(f"Target difficulty: {target_difficulty}")
        if target_question_type:
            constraints.append(f"Target question type: {target_question_type}")
        effective_preference = preference or "(none)"
        if constraints:
            effective_preference = f"{effective_preference}\n" + "\n".join(constraints)

        user_prompt = idea_prompt.format(
            user_topic=user_topic,
            preference=effective_preference,
            knowledge_context=knowledge_context,
            num_ideas=num_ideas,
            existing_concentrations=json.dumps(existing_concentrations or [], ensure_ascii=False, indent=2),
        )
        try:
            _chunks: list[str] = []
            async for _c in self.stream_llm(
                user_prompt=user_prompt,
                system_prompt=system_prompt or "",
                response_format={"type": "json_object"},
                stage="idea_generate_templates",
                trace_meta=build_trace_metadata(
                    call_id=new_call_id("quiz-ideation"),
                    phase="ideation",
                    label=(
                        f"Generate templates (batch {batch_number})"
                        if batch_number is not None
                        else "Generate templates"
                    ),
                    call_kind="llm_generation",
                    trace_id=trace_id,
                    batch=batch_number,
                ),
            ):
                _chunks.append(_c)
            response = "".join(_chunks)
            payload = json.loads(response)
            ideas_raw = payload.get("ideas", [])
            if not isinstance(ideas_raw, list):
                ideas_raw = []
        except Exception as exc:
            self.logger.warning(f"Idea generation failed, fallback used: {exc}")
            ideas_raw = []

        seen = {item.strip().lower() for item in (existing_concentrations or []) if item}
        retrieval_queries = retrieval_queries or []
        templates: list[QuestionTemplate] = []
        for idx, item in enumerate(ideas_raw, 1):
            if not isinstance(item, dict):
                continue
            concentration = str(item.get("concentration", "")).strip()
            normalized_concentration = concentration.lower()
            if not concentration or normalized_concentration in seen:
                continue
            seen.add(normalized_concentration)
            resolved_question_type = (
                target_question_type
                or str(item.get("question_type", "written")).strip()
                or "written"
            )
            resolved_difficulty = (
                target_difficulty
                or str(item.get("difficulty", "medium")).strip()
                or "medium"
            )
            templates.append(
                QuestionTemplate(
                    question_id=f"q_{idx}",
                    concentration=concentration,
                    question_type=resolved_question_type,
                    difficulty=resolved_difficulty,
                    source="custom",
                    metadata={
                        "idea_id": item.get("idea_id", f"idea_{idx}"),
                        "rationale": str(item.get("rationale", "")).strip(),
                        "knowledge_context": knowledge_context[:6000],
                        "retrieval_queries": retrieval_queries,
                        "requested_question_type": target_question_type or None,
                        "requested_difficulty": target_difficulty or None,
                    },
                )
            )
            if len(templates) >= num_ideas:
                break

        if len(templates) < num_ideas:
            for idx in range(len(templates) + 1, num_ideas + 1):
                fallback_concentration = f"{user_topic} - aspect {idx}"
                templates.append(
                    QuestionTemplate(
                        question_id=f"q_{idx}",
                        concentration=fallback_concentration,
                        question_type=target_question_type or "written",
                        difficulty=target_difficulty or "medium",
                        source="custom",
                        metadata={
                            "idea_id": f"idea_{idx}",
                            "rationale": "Fallback template generated due to parsing issues.",
                            "knowledge_context": knowledge_context[:6000],
                            "retrieval_queries": retrieval_queries,
                        },
                    )
                )

        return templates
