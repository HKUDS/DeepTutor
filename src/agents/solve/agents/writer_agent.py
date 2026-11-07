"""
WriterAgent — Generates the final structured answer from the Scratchpad.

Supports two modes:
  - **Simple** (`process`): single LLM call producing the complete answer.
  - **Detailed / Iterative** (`process_iterative`): step-by-step incremental
    writing that processes evidence in chunks, then generates a concise answer.
"""

from __future__ import annotations

from typing import Any

from src.agents.base_agent import BaseAgent

from ..memory.scratchpad import Scratchpad


class WriterAgent(BaseAgent):
    """Produces the final answer from accumulated evidence."""

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        api_version: str | None = None,
        token_tracker: Any | None = None,
        language: str = "en",
    ) -> None:
        super().__init__(
            module_name="solve",
            agent_name="writer_agent",
            api_key=api_key,
            base_url=base_url,
            model=model,
            api_version=api_version,
            config=config or {},
            token_tracker=token_tracker,
            language=language,
        )

    # ==================================================================
    # Simple mode — single-shot writing
    # ==================================================================

    async def process(
        self,
        question: str,
        scratchpad: Scratchpad,
        language: str = "en",
        preference: str = "",
    ) -> str:
        """Generate the final Markdown answer in a single LLM call.

        Args:
            question: Original user question.
            scratchpad: Completed scratchpad with all evidence.
            language: Output language hint (e.g. "en", "zh").
            preference: Optional personalisation context.

        Returns:
            Markdown-formatted answer string.
        """
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(question, scratchpad, language, preference)

        response = await self.call_llm(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            max_tokens=self.get_max_tokens() or 8192,
            stage="write",
        )

        return response.strip()

    # ==================================================================
    # Detailed / Iterative mode
    # ==================================================================

    async def process_iterative(
        self,
        question: str,
        scratchpad: Scratchpad,
        language: str = "en",
        preference: str = "",
    ) -> str:
        """Generate a detailed answer through iterative step-by-step writing.

        Flow:
            Iteration 1 : evidence(S1) + evidence(S2) → draft_1
            Iteration 2 : draft_1 + evidence(S3) → draft_2
            ...
            Final        : draft_N → concise_answer
            Output       : concise_answer + "---" + draft_N

        Args:
            question: Original user question.
            scratchpad: Completed scratchpad with all evidence.
            language: Output language hint.
            preference: Optional personalisation context.

        Returns:
            Combined Markdown string: concise answer + detailed answer.
        """
        if scratchpad.plan is None:
            # Fallback: no plan, use simple mode
            return await self.process(question, scratchpad, language, preference)

        # Collect completed/in_progress steps that have entries
        steps_with_evidence = []
        for step in scratchpad.plan.steps:
            if step.status in ("completed", "in_progress"):
                entries = scratchpad.get_entries_for_step(step.id)
                # Only include steps with actual tool observations
                evidence_entries = [e for e in entries if e.action not in ("done", "replan") and e.observation]
                if evidence_entries:
                    steps_with_evidence.append((step, evidence_entries))

        if not steps_with_evidence:
            return await self.process(question, scratchpad, language, preference)

        sources_text = scratchpad.format_sources_markdown()

        # --- Iterative draft building ---
        draft = ""

        for i, (step, entries) in enumerate(steps_with_evidence):
            step_evidence = self._format_step_evidence(step, entries)

            if i == 0:
                # First iteration: if there's a second step, bundle it
                if len(steps_with_evidence) > 1:
                    step2, entries2 = steps_with_evidence[1]
                    step_evidence += "\n\n---\n\n" + self._format_step_evidence(step2, entries2)
                draft = await self._write_draft(
                    question=question,
                    previous_draft="(this is the first draft — no previous draft)",
                    new_evidence=step_evidence,
                    sources=sources_text,
                    language=language,
                    iteration=i + 1,
                    preference=preference,
                )
            elif i == 1:
                # Second step was already bundled in iteration 0; skip
                continue
            else:
                # Subsequent iterations: previous draft + new step evidence
                draft = await self._write_draft(
                    question=question,
                    previous_draft=draft,
                    new_evidence=step_evidence,
                    sources=sources_text,
                    language=language,
                    iteration=i,
                    preference=preference,
                )

        # --- Concise answer generation ---
        concise = await self._write_concise(
            question=question,
            detailed_answer=draft,
            language=language,
            preference=preference,
        )

        # --- Assemble final output ---
        final = f"## Summary\n\n{concise}\n\n---\n\n{draft}"
        return final

    # ------------------------------------------------------------------
    # Internal helpers for iterative mode
    # ------------------------------------------------------------------

    async def _write_draft(
        self,
        question: str,
        previous_draft: str,
        new_evidence: str,
        sources: str,
        language: str,
        iteration: int,
        preference: str = "",
    ) -> str:
        """Run one iteration of the incremental draft builder."""
        system_prompt = self._get_iterative_system_prompt()
        template = self.get_prompt("iterative_user_template") if self.has_prompts() else None

        if template:
            user_prompt = template.format(
                question=question,
                previous_draft=previous_draft,
                new_evidence=new_evidence,
                sources=sources or "(no external sources)",
                preference=preference or "(no specific preference)",
                language=language,
            )
        else:
            user_prompt = (
                f"## Question\n{question}\n\n"
                f"## Previous Draft\n{previous_draft}\n\n"
                f"## New Evidence\n{new_evidence}\n\n"
                f"## Available Sources\n{sources or '(none)'}\n\n"
                f"## User Preference\n{preference or '(none)'}\n\n"
                f"## Language\n{language}"
            )

        response = await self.call_llm(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            max_tokens=self.get_max_tokens() or 8192,
            stage=f"write_iter_{iteration}",
        )
        return response.strip()

    async def _write_concise(
        self,
        question: str,
        detailed_answer: str,
        language: str,
        preference: str = "",
    ) -> str:
        """Generate a concise answer from the completed detailed draft."""
        system_prompt = self._get_concise_system_prompt()
        template = self.get_prompt("concise_user_template") if self.has_prompts() else None

        if template:
            user_prompt = template.format(
                question=question,
                detailed_answer=detailed_answer,
                language=language,
            )
        else:
            user_prompt = (
                f"## Question\n{question}\n\n"
                f"## Detailed Answer\n{detailed_answer}\n\n"
                f"## Language\n{language}"
            )

        response = await self.call_llm(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            max_tokens=1024,
            stage="write_concise",
        )
        return response.strip()

    @staticmethod
    def _format_step_evidence(step, entries) -> str:
        """Format raw observations from a step into a single evidence block."""
        parts = [f"### Step {step.id}: {step.goal}"]
        for e in entries:
            block = (
                f"**Action**: {e.action}({e.action_input})\n"
                f"**Observation**:\n{e.observation}"
            )
            parts.append(block)
        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_system_prompt(self) -> str:
        prompt = self.get_prompt("system") if self.has_prompts() else None
        if prompt:
            return prompt
        return (
            "You are an expert answer writer. Write a structured, comprehensive answer "
            "based on gathered evidence. Use Markdown with proper headings. "
            "All math must use LaTeX: inline $...$ and block $$...$$. "
            "Cite sources inline as [source-id]. Include a ## References section at the end."
        )

    def _get_iterative_system_prompt(self) -> str:
        prompt = self.get_prompt("iterative_system") if self.has_prompts() else None
        if prompt:
            return prompt
        return (
            "You are an expert answer writer building an answer incrementally. "
            "You receive a previous draft and new evidence. Expand and refine the draft "
            "by integrating the new evidence. Use Markdown, LaTeX for math, and cite sources."
        )

    def _get_concise_system_prompt(self) -> str:
        prompt = self.get_prompt("concise_system") if self.has_prompts() else None
        if prompt:
            return prompt
        return (
            "Produce a concise answer (2-4 sentences) for the question based on the "
            "detailed answer. If it's a multiple-choice or fill-in-the-blank question, "
            "give the direct answer first."
        )

    def _build_user_prompt(
        self,
        question: str,
        scratchpad: Scratchpad,
        language: str,
        preference: str,
    ) -> str:
        template = self.get_prompt("user_template") if self.has_prompts() else None

        scratchpad_content = scratchpad.build_writer_context()
        sources_text = scratchpad.format_sources_markdown()

        if template:
            return template.format(
                question=question,
                scratchpad_content=scratchpad_content,
                sources=sources_text or "(no external sources)",
                preference=preference or "(no specific preference)",
                language=language,
            )

        return (
            f"## Question\n{question}\n\n"
            f"## Gathered Evidence\n{scratchpad_content}\n\n"
            f"## Available Sources\n{sources_text or '(none)'}\n\n"
            f"## User Preference\n{preference or '(none)'}\n\n"
            f"## Language\n{language}"
        )
