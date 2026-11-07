"""
PlannerAgent — Decomposes the user question into ordered solving steps.

Called once at the start (Phase 1) and optionally on replan requests.
Before planning, performs parallel RAG pre-retrieval and LLM aggregation
to provide the planner with relevant knowledge context.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from src.agents.base_agent import BaseAgent

from ..memory.scratchpad import Plan, PlanStep, Scratchpad
from ..tools import ToolRegistry
from ..utils.json_utils import extract_json_from_text

logger = logging.getLogger(__name__)

_MAX_CHARS_PER_RETRIEVAL = 2000
_MAX_AGGREGATE_INPUT_CHARS = 6000
_NUM_QUERIES = 3


def _build_multimodal_messages(
    system_prompt: str,
    user_prompt: str,
    image_url: str,
) -> list[dict[str, Any]]:
    """Build OpenAI-compatible multimodal messages with an image."""
    return [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_prompt},
                {"type": "image_url", "image_url": {"url": image_url}},
            ],
        },
    ]


class PlannerAgent(BaseAgent):
    """Generates a high-level solving plan from the user question."""

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        api_version: str | None = None,
        token_tracker: Any | None = None,
        language: str = "en",
        tool_registry: ToolRegistry | None = None,
        enable_pre_retrieve: bool = True,
    ) -> None:
        super().__init__(
            module_name="solve",
            agent_name="planner_agent",
            api_key=api_key,
            base_url=base_url,
            model=model,
            api_version=api_version,
            config=config or {},
            token_tracker=token_tracker,
            language=language,
        )
        self._tool_registry = tool_registry or ToolRegistry.create_default(language)
        self._enable_pre_retrieve = enable_pre_retrieve

    async def process(
        self,
        question: str,
        scratchpad: Scratchpad,
        kb_name: str = "",
        replan: bool = False,
        memory_context: str = "",
        image_url: str | None = None,
    ) -> Plan:
        """Generate or revise the solving plan.

        Args:
            question: The user's original question.
            scratchpad: Current scratchpad state.
            kb_name: Knowledge base name (informational).
            replan: If True, this is a replan request — include progress so far.
            memory_context: Historical memory context string.
            image_url: Optional image URL for multimodal questions.

        Returns:
            A Plan object with ordered steps.
        """
        rag_context = (
            await self._pre_retrieve(question, kb_name)
            if self._enable_pre_retrieve
            else "(retrieval disabled)"
        )

        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(
            question=question,
            scratchpad=scratchpad,
            kb_name=kb_name,
            replan=replan,
            memory_context=memory_context,
            rag_context=rag_context,
        )

        llm_kwargs: dict[str, Any] = {
            "user_prompt": user_prompt,
            "system_prompt": system_prompt,
            "response_format": {"type": "json_object"},
            "stage": "plan" if not replan else "replan",
        }

        if image_url:
            llm_kwargs["messages"] = _build_multimodal_messages(
                system_prompt, user_prompt, image_url,
            )

        response = await self.call_llm(**llm_kwargs)

        return self._parse_plan(response, scratchpad if replan else None)

    # ------------------------------------------------------------------
    # RAG pre-retrieval pipeline
    # ------------------------------------------------------------------

    async def _pre_retrieve(self, question: str, kb_name: str) -> str:
        """Run the full pre-retrieval pipeline: generate queries → parallel
        RAG search → LLM aggregation.  Returns the aggregated knowledge
        context string, or a fallback placeholder on any failure."""
        if not kb_name:
            return "(no knowledge base available)"
        try:
            queries = await self._generate_search_queries(question)
            retrievals = await self._parallel_rag_search(queries, kb_name)
            if not any(r.get("answer") for r in retrievals):
                return "(no relevant knowledge retrieved)"
            return await self._aggregate_rag_results(retrievals)
        except Exception as exc:
            logger.warning("Pre-retrieval pipeline failed: %s", exc)
            return "(knowledge retrieval failed)"

    async def _generate_search_queries(
        self, question: str, num_queries: int = _NUM_QUERIES,
    ) -> list[str]:
        """Use a lightweight LLM call to derive multiple search queries from
        the user question."""
        prompt_template = (
            self.get_prompt("generate_queries") if self.has_prompts() else None
        )
        if not prompt_template:
            prompt_template = (
                "Generate {num_queries} concise and diverse knowledge-base "
                "search queries for the following question. Each query should "
                "target a different aspect (e.g. definitions, formulas, "
                "theorems, examples).\n\n"
                "Question: {question}\n\n"
                'Return strict JSON: {{"queries": ["q1", "q2", "q3"]}}'
            )

        user_prompt = prompt_template.format(
            question=question, num_queries=num_queries,
        )
        try:
            response = await self.call_llm(
                user_prompt=user_prompt,
                system_prompt="",
                response_format={"type": "json_object"},
                stage="plan_generate_queries",
            )
            payload = json.loads(response)
            queries = payload.get("queries", [])
            if not isinstance(queries, list):
                queries = []
            clean = [q.strip() for q in queries if isinstance(q, str) and q.strip()]
            result = clean[:num_queries] or [question]
            logger.info("Generated %d search queries", len(result))
            return result
        except Exception as exc:
            logger.warning("Query generation failed, fallback to raw question: %s", exc)
            return [question]

    async def _parallel_rag_search(
        self, queries: list[str], kb_name: str,
    ) -> list[dict[str, Any]]:
        """Execute RAG searches for all queries in parallel."""
        from src.tools.rag_tool import rag_search

        async def _single_search(query: str) -> dict[str, Any]:
            try:
                result = await rag_search(
                    query=query, kb_name=kb_name,
                    mode="hybrid", only_need_context=True, top_k=8,
                )
                return {"query": query, "answer": result.get("answer", "") or result.get("content", "")}
            except Exception as exc:
                logger.warning("RAG search failed for query '%s': %s", query[:60], exc)
                return {"query": query, "answer": ""}

        results = await asyncio.gather(*[_single_search(q) for q in queries])
        logger.info(
            "Parallel RAG search: %d/%d returned content",
            sum(1 for r in results if r.get("answer")), len(results),
        )
        return list(results)

    async def _aggregate_rag_results(
        self, retrievals: list[dict[str, Any]],
    ) -> str:
        """Use an LLM call to aggregate raw retrieval results into a
        structured knowledge summary.  The user question is NOT passed
        to keep the output neutral (pure knowledge consolidation)."""
        sections: list[str] = []
        total_chars = 0
        for item in retrievals:
            answer = (item.get("answer") or "").strip()
            if not answer:
                continue
            clipped = answer[:_MAX_CHARS_PER_RETRIEVAL]
            if total_chars + len(clipped) > _MAX_AGGREGATE_INPUT_CHARS:
                clipped = clipped[:max(0, _MAX_AGGREGATE_INPUT_CHARS - total_chars)]
            if clipped:
                sections.append(f"=== Source: {item.get('query', '?')} ===\n{clipped}")
                total_chars += len(clipped)

        if not sections:
            return "(no relevant knowledge retrieved)"

        raw_text = "\n\n".join(sections)

        prompt_template = (
            self.get_prompt("aggregate_context") if self.has_prompts() else None
        )
        if not prompt_template:
            prompt_template = (
                "Below are several passages retrieved from a knowledge base. "
                "Your task is to consolidate them into a single structured "
                "knowledge summary.\n\n"
                "Rules:\n"
                "- Remove duplicate information.\n"
                "- Organize by topic (definitions, formulas/theorems, key facts, examples).\n"
                "- Do NOT solve any problem or make inferences.\n"
                "- Do NOT reference any question — just organize the knowledge.\n"
                "- Be concise; keep the summary under 3000 characters.\n\n"
                "{raw_retrieval_text}"
            )

        user_prompt = prompt_template.format(raw_retrieval_text=raw_text)
        try:
            result = await self.call_llm(
                user_prompt=user_prompt,
                system_prompt="You are a knowledge organizer. Consolidate the provided passages into a clean, structured summary.",
                stage="plan_aggregate_context",
            )
            logger.info("Aggregated RAG context: %d chars", len(result))
            return result.strip() or raw_text
        except Exception as exc:
            logger.warning("RAG aggregation failed, using raw text: %s", exc)
            return raw_text

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_system_prompt(self) -> str:
        prompt = self.get_prompt("system") if self.has_prompts() else None
        if prompt:
            return prompt
        return (
            "You are a problem-solving planner. Analyze the user's question and "
            "decompose it into ordered steps. Each step should be a verifiable sub-goal "
            "describing WHAT to establish, not HOW. Do not specify tools. "
            "Simple questions need only 1 step; complex ones may need 3-6 steps. "
            "If retrieved knowledge is provided, use it to make a more informed plan. "
            "Output strict JSON: {\"analysis\": \"...\", \"steps\": [{\"id\": \"S1\", "
            "\"goal\": \"...\"}]}"
        )

    def _build_user_prompt(
        self,
        question: str,
        scratchpad: Scratchpad,
        kb_name: str,
        replan: bool,
        memory_context: str = "",
        rag_context: str = "",
    ) -> str:
        template = self.get_prompt("user_template") if self.has_prompts() else None

        # Build scratchpad summary for replan
        scratchpad_summary = "(initial plan — no progress yet)"
        if replan and scratchpad.plan:
            parts: list[str] = []
            for step in scratchpad.plan.steps:
                entries = scratchpad.get_entries_for_step(step.id)
                notes = " | ".join(e.self_note for e in entries if e.self_note)
                status_label = step.status.upper()
                parts.append(f"[{step.id}] ({status_label}) {step.goal}")
                if notes:
                    parts.append(f"    Notes: {notes}")
            # Include the replan reason from the last entry
            if scratchpad.entries:
                last = scratchpad.entries[-1]
                if last.action == "replan" and last.action_input:
                    parts.append(f"\nReplan reason: {last.action_input}")
            scratchpad_summary = "\n".join(parts)

        tools_desc = self._tool_registry.build_planner_description(kb_name=kb_name)

        if template:
            return template.format(
                question=question,
                rag_context=rag_context or "(no retrieved knowledge)",
                tools_description=tools_desc,
                scratchpad_summary=scratchpad_summary,
                memory_context=memory_context or "(no historical memory)",
            )

        # Fallback
        return (
            f"## Question\n{question}\n\n"
            f"## Retrieved Knowledge\n{rag_context or '(none)'}\n\n"
            f"## Available Tools\n{tools_desc}\n\n"
            f"## Progress So Far\n{scratchpad_summary}\n\n"
            f"## Memory Context\n{memory_context or '(none)'}"
        )

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    def _parse_plan(self, response: str, old_scratchpad: Scratchpad | None) -> Plan:
        """Parse LLM JSON response into a Plan object."""
        data = extract_json_from_text(response)
        if not data or not isinstance(data, dict):
            # Graceful fallback: single-step plan
            return Plan(
                analysis="Failed to parse plan; using single-step fallback.",
                steps=[PlanStep(id="S1", goal="Answer the question directly")],
            )

        analysis = data.get("analysis", "")
        raw_steps = data.get("steps", [])

        steps: list[PlanStep] = []
        for i, s in enumerate(raw_steps):
            step_id = s.get("id", f"S{i + 1}")
            goal = s.get("goal", "")
            tools_hint = s.get("tools_hint", [])
            if isinstance(tools_hint, str):
                tools_hint = [tools_hint]
            steps.append(PlanStep(id=step_id, goal=goal, tools_hint=tools_hint))

        if not steps:
            steps = [PlanStep(id="S1", goal="Answer the question")]

        return Plan(analysis=analysis, steps=steps)
