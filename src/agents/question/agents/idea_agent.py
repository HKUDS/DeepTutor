#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
IdeaAgent - Generate candidate question directions from topic and preference.
"""

from __future__ import annotations

import json
from typing import Any

from src.agents.base_agent import BaseAgent
from src.tools.rag_tool import rag_search


class IdeaAgent(BaseAgent):
    """
    Generate candidate question ideas with knowledge grounding.
    """

    def __init__(
        self,
        kb_name: str | None = None,
        rag_mode: str = "naive",
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
        self.rag_mode = rag_mode
        self.enable_rag = enable_rag

    async def process(
        self,
        user_topic: str,
        preference: str = "",
        evaluator_feedback: str = "",
        num_ideas: int = 5,
        target_difficulty: str = "",
        target_question_type: str = "",
    ) -> dict[str, Any]:
        """
        Build grounded candidate ideas for evaluator ranking.
        """
        if self.enable_rag and self.kb_name:
            queries = await self._generate_rag_queries(user_topic=user_topic, num_queries=3)
            retrievals = await self._retrieve_context(queries)
            raw_context = self._build_context(retrievals)
            knowledge_context = await self._aggregate_context(
                user_topic=user_topic, raw_context=raw_context
            )
        else:
            queries = []
            retrievals = []
            raw_context = "Retrieval disabled."
            knowledge_context = raw_context
        ideas = await self._generate_ideas(
            user_topic=user_topic,
            preference=preference,
            evaluator_feedback=evaluator_feedback,
            knowledge_context=knowledge_context,
            num_ideas=num_ideas,
            target_difficulty=target_difficulty,
            target_question_type=target_question_type,
        )
        return {
            "ideas": ideas,
            "queries": queries,
            "retrievals": retrievals,
            "raw_context": raw_context,
            "knowledge_context": knowledge_context,
        }

    async def _generate_rag_queries(self, user_topic: str, num_queries: int) -> list[str]:
        system_prompt = self.get_prompt("system", "")
        query_prompt = self.get_prompt("generate_queries", "")
        if not query_prompt:
            query_prompt = (
                "Generate {num_queries} concise knowledge search queries for topic:\n"
                "{user_topic}\n"
                'Return JSON: {"queries":["..."]}'
            )

        user_prompt = query_prompt.format(
            user_topic=user_topic,
            num_queries=num_queries,
        )
        try:
            response = await self.call_llm(
                user_prompt=user_prompt,
                system_prompt=system_prompt or "",
                response_format={"type": "json_object"},
                stage="idea_generate_queries",
            )
            payload = json.loads(response)
            queries = payload.get("queries", [])
            if not isinstance(queries, list):
                queries = []
            clean = [q.strip() for q in queries if isinstance(q, str) and q.strip()]
            return clean[:num_queries] or [user_topic]
        except Exception as exc:
            self.logger.warning(f"Failed generating queries, fallback to topic: {exc}")
            return [user_topic]

    async def _retrieve_context(self, queries: list[str]) -> list[dict[str, Any]]:
        retrievals: list[dict[str, Any]] = []
        for query in queries:
            try:
                result = await rag_search(
                    query=query,
                    kb_name=self.kb_name,
                    mode=self.rag_mode,
                    only_need_context=True,
                )
                retrievals.append(
                    {
                        "query": query,
                        "answer": result.get("answer", ""),
                        "mode": result.get("mode", self.rag_mode),
                    }
                )
            except Exception as exc:
                self.logger.warning(f"RAG retrieval failed for query '{query}': {exc}")
                retrievals.append({"query": query, "answer": "", "error": str(exc)})
        return retrievals

    def _build_context(self, retrievals: list[dict[str, Any]]) -> str:
        sections: list[str] = []
        for item in retrievals:
            answer = item.get("answer", "")
            if not answer:
                continue
            clipped = answer[:2000] + ("...[truncated]" if len(answer) > 2000 else "")
            sections.append(f"=== Query: {item.get('query','')} ===\n{clipped}")
        return "\n\n".join(sections) if sections else "No retrieval context available."

    async def _aggregate_context(self, user_topic: str, raw_context: str) -> str:
        if not raw_context or raw_context == "No retrieval context available.":
            return raw_context

        system_prompt = self.get_prompt("system", "")
        agg_prompt = self.get_prompt("aggregate_context", "")
        if not agg_prompt:
            return raw_context

        user_prompt = agg_prompt.format(user_topic=user_topic, raw_context=raw_context)
        try:
            aggregated = await self.call_llm(
                user_prompt=user_prompt,
                system_prompt=system_prompt or "",
                stage="idea_aggregate_context",
            )
            return aggregated.strip() if aggregated.strip() else raw_context
        except Exception as exc:
            self.logger.warning(f"Context aggregation failed, using raw context: {exc}")
            return raw_context

    async def _generate_ideas(
        self,
        user_topic: str,
        preference: str,
        evaluator_feedback: str,
        knowledge_context: str,
        num_ideas: int,
        target_difficulty: str = "",
        target_question_type: str = "",
    ) -> list[dict[str, Any]]:
        system_prompt = self.get_prompt("system", "")
        idea_prompt = self.get_prompt("generate_ideas", "")
        if not idea_prompt:
            idea_prompt = (
                "Topic: {user_topic}\n"
                "Preference: {preference}\n"
                "Evaluator feedback: {evaluator_feedback}\n"
                "Knowledge context:\n{knowledge_context}\n\n"
                "Generate {num_ideas} candidate question ideas.\n"
                'Return JSON {"ideas":[{"concentration":"","question_type":"","difficulty":"","rationale":""}]}'
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
            evaluator_feedback=evaluator_feedback or "(none)",
            knowledge_context=knowledge_context[:6000],
            num_ideas=num_ideas,
        )

        try:
            response = await self.call_llm(
                user_prompt=user_prompt,
                system_prompt=system_prompt or "",
                response_format={"type": "json_object"},
                stage="idea_generate_candidates",
            )
            payload = json.loads(response)
            ideas_raw = payload.get("ideas", [])
            if not isinstance(ideas_raw, list):
                ideas_raw = []
        except Exception as exc:
            self.logger.warning(f"Idea generation failed, fallback used: {exc}")
            ideas_raw = []

        ideas: list[dict[str, Any]] = []
        for idx, item in enumerate(ideas_raw, 1):
            if not isinstance(item, dict):
                continue
            concentration = str(item.get("concentration", "")).strip()
            if not concentration:
                continue
            ideas.append(
                {
                    "idea_id": item.get("idea_id", f"idea_{idx}"),
                    "concentration": concentration,
                    "question_type": str(item.get("question_type", "written")).strip()
                    or "written",
                    "difficulty": str(item.get("difficulty", "medium")).strip() or "medium",
                    "rationale": str(item.get("rationale", "")).strip(),
                }
            )
            if len(ideas) >= num_ideas:
                break

        if len(ideas) < num_ideas:
            for idx in range(len(ideas) + 1, num_ideas + 1):
                ideas.append(
                    {
                        "idea_id": f"idea_{idx}",
                        "concentration": f"{user_topic} - aspect {idx}",
                        "question_type": "written",
                        "difficulty": "medium",
                        "rationale": "Fallback idea generated due to parsing issues.",
                    }
                )

        return ideas
