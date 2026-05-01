"""
CriticAgent — Fact-checking auditor that verifies citations and fills evidence gaps.

Runs after the ReAct solve phase and before the WriterAgent.
Uses an iterative audit loop (similar to SolverAgent's ReAct loop) to:
  1. Verify that cited sources actually support their claims
  2. Identify missing or weak evidence
  3. Use tools to retrieve additional evidence when gaps are found
  4. Update scratchpad entries with corrected/qualified notes
"""

from __future__ import annotations

from typing import Any

from deeptutor.agents.base_agent import BaseAgent
from deeptutor.core.context import Attachment
from deeptutor.core.trace import build_trace_metadata, new_call_id

from ..memory.scratchpad import Entry, Scratchpad, Source
from ..tool_runtime import SolveToolRuntime
from ..utils.json_utils import extract_json_from_text


class CriticAgent(BaseAgent):
    """Fact-checking auditor — iterative audit loop before writing."""

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        api_version: str | None = None,
        token_tracker: Any | None = None,
        language: str = "en",
        tool_runtime: SolveToolRuntime | None = None,
        max_audit_rounds: int = 3,
    ) -> None:
        super().__init__(
            module_name="solve",
            agent_name="critic_agent",
            api_key=api_key,
            base_url=base_url,
            model=model,
            api_version=api_version,
            config=config or {},
            token_tracker=token_tracker,
            language=language,
        )
        self._tool_runtime = tool_runtime or SolveToolRuntime(
            ["visit_url"], language=language
        )
        self._max_audit_rounds = max_audit_rounds

    async def process(
        self,
        question: str,
        scratchpad: Scratchpad,
        memory_context: str = "",
        image_url: str | None = None,
        kb_name: str | None = None,
    ) -> tuple[Scratchpad, dict[str, Any]]:
        """Run the iterative audit loop.

        Args:
            question: The user's original question.
            scratchpad: Current scratchpad state after solve phase.
            memory_context: Historical memory context string.
            image_url: Optional image URL for multimodal questions.
            kb_name: Knowledge base name for RAG tools.

        Returns:
            Tuple of (revised_scratchpad, verification_report_dict)
        """
        verification_report: dict[str, Any] = {
            "verified_claims": [],
            "gaps": [],
            "uncertain_claims": [],
            "updated_notes": {},
            "new_sources": [],
            "rounds": 0,
        }

        for round_num in range(self._max_audit_rounds):
            audit_decision = await self._run_audit_round(
                question=question,
                scratchpad=scratchpad,
                memory_context=memory_context,
                image_url=image_url,
                round_index=round_num + 1,
            )

            action = audit_decision.get("action", "done")
            action_input = audit_decision.get("action_input", "")
            self_note = audit_decision.get("self_note", "")
            verification_report["rounds"] = round_num + 1

            # Always process invalid_sources and updated_notes — even on "done"
            invalid_sources = audit_decision.get("invalid_sources", [])
            for item in invalid_sources:
                src_id = item if isinstance(item, str) else item.get("source_id")
                url = item.get("url") if isinstance(item, dict) else None
                if src_id:
                    scratchpad.mark_source_invalid(src_id)
                elif url:
                    src_id = scratchpad.find_source_id_by_url(url)
                    if src_id:
                        scratchpad.mark_source_invalid(src_id)

            updated_notes = audit_decision.get("updated_notes", {})
            for step_id, note in updated_notes.items():
                self._update_entry_note(scratchpad, step_id, note)

            if action == "done":
                if audit_decision.get("verification_report"):
                    verification_report["summary"] = audit_decision["verification_report"]
                break

            # audit action — tool execution to fill evidence gaps
            observation, sources = await self._execute_audit_tool(
                action=action,
                action_input=action_input,
                kb_name=kb_name,
                question=question,
                scratchpad=scratchpad,
            )

            # Merge new sources into scratchpad
            for src in sources:
                self._add_source_to_scratchpad(scratchpad, src)

            # Record the audit round entry
            scratchpad.add_entry(
                step_id="critic",
                round_num=round_num + 1,
                thought=audit_decision.get("thought", ""),
                action=action,
                action_input=action_input,
                observation=observation,
                self_note=self_note,
                sources=sources,
            )

            if audit_decision.get("verification_report"):
                verification_report["summary"] = audit_decision["verification_report"]

        return scratchpad, verification_report

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _run_audit_round(
        self,
        question: str,
        scratchpad: Scratchpad,
        memory_context: str,
        image_url: str | None,
        round_index: int,
    ) -> dict[str, Any]:
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(
            question=question,
            scratchpad=scratchpad,
            memory_context=memory_context,
        )

        trace_meta = build_trace_metadata(
            call_id=new_call_id("critic"),
            phase="reasoning",
            label=f"CriticAudit round {round_index}",
            call_kind="react_round",
            trace_id=f"critic-round-{round_index}",
            trace_role="thought",
            trace_group="critic_audit",
            step_id="critic",
            round=round_index,
        )

        llm_kwargs: dict[str, object] = {
            "user_prompt": user_prompt,
            "system_prompt": system_prompt,
            "response_format": {"type": "json_object"},
            "stage": "critic_audit",
            "trace_meta": trace_meta,
        }

        if image_url:
            llm_kwargs["attachments"] = [Attachment(type="image", url=image_url)]

        chunks: list[str] = []
        async for chunk in self.stream_llm(**llm_kwargs):
            chunks.append(chunk)
        response = "".join(chunks)

        return self._parse_audit_decision(response)

    async def _execute_audit_tool(
        self,
        action: str,
        action_input: str,
        kb_name: str | None,
        question: str,
        scratchpad: Scratchpad,
    ) -> tuple[str, list[Source]]:
        """Execute a tool for the audit loop, returning (observation, sources)."""
        if action not in self._tool_runtime.valid_actions:
            return f"Unknown audit action: {action}", []

        try:
            from deeptutor.core.tool_protocol import ToolResult

            result: ToolResult = await self._tool_runtime.execute(
                action=action,
                action_input=action_input,
                kb_name=kb_name,
                reason_context=self._build_reason_context(question, scratchpad),
            )
            sources = self._convert_sources(result.sources)
            return result.content, sources
        except Exception as e:
            return f"Tool execution error: {e}", []

    def _build_reason_context(self, question: str, scratchpad: Scratchpad) -> str:
        parts = [f"Question: {question}"]
        if scratchpad.plan:
            parts.append(f"Plan:\n{scratchpad._format_plan()}")
        completed = scratchpad.get_completed_steps()
        if completed:
            notes = []
            for step in completed:
                entries = scratchpad.get_entries_for_step(step.id)
                step_notes = [e.self_note for e in entries if e.self_note]
                if step_notes:
                    notes.append(f"[{step.id}] {step.goal}: {' '.join(step_notes)}")
            if notes:
                parts.append("Completed steps:\n" + "\n".join(notes))
        return "\n\n".join(parts)

    def _convert_sources(self, tool_sources: list[dict[str, Any]]) -> list[Source]:
        """Convert tool result sources to Scratchpad Source objects."""
        converted = []
        for item in tool_sources:
            src = Source(
                type=item.get("type", "rag"),
                file=item.get("file") or item.get("title") or item.get("kb_name"),
                page=item.get("page"),
                url=item.get("url"),
                chunk_id=item.get("chunk_id") or item.get("query") or item.get("identifier"),
            )
            converted.append(src)
        return converted

    def _add_source_to_scratchpad(self, scratchpad: Scratchpad, source: Source) -> None:
        """Append a new source to the most recent critic entry."""
        if not scratchpad.entries:
            return
        # Find the last critic entry and append source
        for entry in reversed(scratchpad.entries):
            if entry.step_id == "critic":
                entry.sources.append(source)
                return

    def _update_entry_note(self, scratchpad: Scratchpad, step_id: str, note: str) -> None:
        """Update the self_note on the most recent entry for a given step."""
        entries = scratchpad.get_entries_for_step(step_id)
        if not entries:
            return
        # Update the latest entry for this step
        entries[-1].self_note = note

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_system_prompt(self) -> str:
        tools_desc = self._tool_runtime.build_solver_description()

        prompt = self.get_prompt("system") if self.has_prompts() else None
        if prompt:
            try:
                return prompt.format(tools_description=tools_desc)
            except KeyError:
                return prompt

        # Fallback
        return (
            "You are an expert fact-checker. Verify evidence and citations. "
            "Output strict JSON with keys: thought, action, action_input, self_note, "
            "verification_report, updated_notes.\n\n"
            f"Available actions:\n{tools_desc}"
        )

    def _build_user_prompt(
        self,
        question: str,
        scratchpad: Scratchpad,
        memory_context: str = "",
    ) -> str:
        template = self.get_prompt("user_template") if self.has_prompts() else None

        scratchpad_content = scratchpad.build_writer_context(max_tokens=12000)
        sources_list = self._format_sources(scratchpad.get_all_sources())
        plan_text = scratchpad._format_plan() if scratchpad.plan else "(no plan)"

        if template:
            return template.format(
                question=question,
                plan=plan_text,
                scratchpad_content=scratchpad_content,
                sources=sources_list,
                memory_context=memory_context or "(no historical memory)",
            )

        # Fallback
        return (
            f"## Original Question\n{question}\n\n"
            f"## Plan\n{plan_text}\n\n"
            f"## Gathered Evidence\n{scratchpad_content}\n\n"
            f"## Available Sources\n{sources_list}\n\n"
            f"## Historical Knowledge\n{memory_context or '(none)'}"
        )

    def _format_sources(self, sources: list[dict[str, Any]]) -> str:
        """Format sources as a numbered list for the prompt."""
        if not sources:
            return "(no sources)"
        lines = []
        for s in sources:
            label = s.get("file") or s.get("url") or s.get("chunk_id") or "unknown"
            src_type = s.get("type", "unknown")
            lines.append(f"- [{s['id']}] ({src_type}) {label}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    def _parse_audit_decision(self, response: str) -> dict[str, Any]:
        """Parse the LLM JSON response into an audit decision dict."""
        data = extract_json_from_text(response)

        if not data or not isinstance(data, dict):
            return {
                "thought": "Failed to parse audit response; ending audit.",
                "action": "done",
                "action_input": "",
                "self_note": "Parse error — ending audit.",
                "verification_report": "Parse error",
                "updated_notes": {},
                "invalid_sources": [],
            }

        action = str(data.get("action", "done")).strip().lower()
        if action not in self._tool_runtime.valid_actions:
            action = "done"

        return {
            "thought": str(data.get("thought", "")),
            "action": action,
            "action_input": str(data.get("action_input", "")),
            "self_note": str(data.get("self_note", "")),
            "verification_report": str(data.get("verification_report", "")),
            "updated_notes": data.get("updated_notes", {}),
            "invalid_sources": data.get("invalid_sources", []),
        }