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
from deeptutor.logging import get_logger

from deeptutor.core.content_filter import ContentFilter
from ..memory.scratchpad import Entry, Scratchpad, Source
from ..tool_runtime import SolveToolRuntime
from ..utils.json_utils import extract_json_from_text

logger = get_logger("solve.critic_agent")


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
        content_filter: ContentFilter | None = None,
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
        self._content_filter = content_filter or ContentFilter()

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

        verification_report["rounds"] = 1

        # Validate all sources in parallel — removes dead/unsafe from entries in-place
        summary_observation, _per_group_results = await self._validate_all_sources(
            scratchpad=scratchpad,
            kb_name=kb_name,
            question=question,
        )

        # Record audit entry — sources removed in-place, no redundant source list
        scratchpad.add_entry(
            step_id="critic",
            round_num=1,
            thought="Validated all cited sources for aliveness and content claims.",
            action="visit_url",
            action_input="(all sources)",
            observation=summary_observation,
            self_note="",
            sources=[],
        )

        # Get LLM's summary assessment of verified/uncertain claims
        audit_decision = await self._run_audit_round(
            question=question,
            scratchpad=scratchpad,
            memory_context=memory_context,
            image_url=image_url,
            round_index=1,
        )
        verification_report["summary"] = audit_decision.get("verification_report", "")

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

        llm_kwargs: dict[str, Any] = {
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

    async def _validate_all_sources(
        self,
        scratchpad: Scratchpad,
        kb_name: str | None,
        question: str,
    ) -> tuple[str, list[tuple[dict[str, Any], dict[str, Any], bool]]]:
        """Validate all cited URLs with duplicate-aware fallback, returning (summary, per_group_results).

        summary: concise human-readable summary string such as
            "Validated 3 source groups: 1 had duplicates 2 alive 1 dead/unreachable"

        per_group_results: list of (src, result, used_alternate) tuples.
            result: raw per-URL data including is_safe, safety_category, etc.
            used_alternate: True if primary URL failed and an alternate succeeded.
                On used_alternate=True, the result reflects the successful alternate URL
                and src.url reflects that alternate URL (not the original).
        """
        import asyncio

        all_sources = scratchpad.get_all_sources()
        url_sources = [src for src in all_sources if src.get("url")]

        if not url_sources:
            return "No URLs to validate.", []

        logger.info(f"Validating {len(url_sources)} URLs in parallel")

        # Group sources by fuzzy URL/title similarity (80% token_set_ratio threshold).
        # Each group is validated as a unit: primary URL first, then alternates on failure.
        from rapidfuzz import fuzz

        group_reps: list[tuple[str, str]] = []  # (primary_url, primary_file) per group
        groups: list[list[dict[str, Any]]] = []
        group_alts: list[list[str]] = []  # deduped alternate URLs per group
        for src in url_sources:
            placed = False
            src_url = src.get("url", "")
            src_file = src.get("file", "")
            for gi, rep_src in enumerate(group_reps):
                rep_url, rep_file = rep_src
                # Exact URL match → same group
                if src_url and rep_url and src_url == rep_url:
                    groups[gi].append(src)
                    placed = True
                    break
                # Fuzzy URL match → same group
                if src_url and rep_url:
                    ratio = fuzz.token_set_ratio(src_url, rep_url)
                    if ratio >= 80:
                        groups[gi].append(src)
                        placed = True
                        break
                # Fuzzy title/file match → same group
                if src_file and rep_file:
                    ratio = fuzz.token_set_ratio(src_file, rep_file)
                    if ratio >= 80:
                        groups[gi].append(src)
                        placed = True
                        break
            if not placed:
                group_reps.append((src_url, src_file))
                groups.append([src])
                group_alts.append([])

        # Pre-compute deduped alternate URLs per group (before asyncio.gather)
        for gi, group in enumerate(groups):
            primary_url = group[0].get("url", "")
            seen: set[str] = {primary_url} if primary_url else set()
            alts: list[str] = []
            for src in group[1:]:
                alt = src.get("url", "")
                if alt and alt not in seen:
                    alts.append(alt)
                    seen.add(alt)
            group_alts[gi] = alts

        async def _fetch_one(target_url: str) -> dict[str, Any]:
            """Fetch a single URL and return structured result."""
            try:
                from deeptutor.core.tool_protocol import ToolResult
                from deeptutor.tools.builtin import VisitUrlTool

                tool = VisitUrlTool()
                result: ToolResult = await tool.execute(url=target_url, claim="")
                raw_content = result.content or ""
                safety = self._content_filter.check(raw_content, url=target_url)
                return {
                    "alive": result.metadata.get("alive", False),
                    "content": raw_content,
                    "sources": result.sources,
                    "status_code": result.metadata.get("status_code"),
                    "claim_verified": result.metadata.get("claim_verified"),
                    "is_safe": safety.is_safe,
                    "safety_category": safety.category.value if safety.category else None,
                    "safety_confidence": safety.confidence,
                    "safety_filter_used": safety.filter_used,
                    "matched_patterns": safety.matched_patterns,
                    "llm_reason": safety.llm_reason,
                    "url": target_url,
                }
            except Exception as exc:
                logger.warning(f"visit_url failed for {target_url}: {exc}")
                return {
                    "alive": False,
                    "content": f"Error: {exc}",
                    "sources": [],
                    "error": str(exc),
                    "url": target_url,
                }

        async def validate_group(
            group: list[dict[str, Any]],
            alts: list[str],
        ) -> tuple[dict[str, Any], dict[str, Any], bool]:
            """Validate a group: try primary URL first, then alternates on failure."""
            primary_src = group[0]
            primary_url = primary_src.get("url", "")

            # Try primary
            result = await _fetch_one(primary_url)
            if result.get("alive") and result.get("is_safe", True):
                return primary_src, result, False

            # Primary failed — try alternates
            for alt_url in alts:
                alt_result = await _fetch_one(alt_url)
                if alt_result.get("alive") and alt_result.get("is_safe", True):
                    src = dict(primary_src)
                    src["url"] = alt_url
                    return src, alt_result, True

            # All failed — return primary result
            return primary_src, result, False

        results: list[tuple[dict[str, Any], dict[str, Any], bool]] = await asyncio.gather(
            *[validate_group(g, a) for g, a in zip(groups, group_alts)]
        )

        total_groups = len(groups)
        dup_groups = sum(1 for g in groups if len(g) > 1)
        alive_count = 0
        dead_count = 0
        unsafe_count = 0
        alternate_used_count = 0

        dead_or_unsafe_urls: list[str] = []

        for src, result, used_alternate in results:
            if used_alternate:
                alternate_used_count += 1
            url = result.get("url", "")
            alive = result.get("alive", False)
            status_code = result.get("status_code")
            claim_verified = result.get("claim_verified")
            is_safe = result.get("is_safe", True)
            safety_category = result.get("safety_category")

            if not alive:
                logger.warning(f"URL dead or unreachable url={url} status={status_code}")
                if url:
                    dead_or_unsafe_urls.append(url)
                dead_count += 1
            elif not is_safe:
                logger.warning(f"Unsafe content detected url={url} category={safety_category}")
                if url:
                    dead_or_unsafe_urls.append(url)
                unsafe_count += 1
            else:
                if claim_verified is True:
                    logger.info(f"Claim supported by page url={url}")
                elif claim_verified is False:
                    logger.warning(f"Claim not supported by page url={url}")
                alive_count += 1

            if result.get("error"):
                logger.warning(f"URL error url={url} error={result['error']}")

            if used_alternate:
                logger.info(f"Primary URL failed, switched to alternate: {url}")

        if dead_or_unsafe_urls:
            removed = scratchpad.remove_sources_by_url(dead_or_unsafe_urls)
            logger.info(f"Removed {removed} dead/unsafe sources from scratchpad entries")

        parts = [f"Validated {total_groups} source groups:"]
        if dup_groups:
            parts.append(f"{dup_groups} had duplicates")
        if alive_count:
            parts.append(f"{alive_count} alive")
        if dead_count:
            parts.append(f"{dead_count} dead/unreachable")
        if unsafe_count:
            parts.append(f"{unsafe_count} unsafe")
        if alternate_used_count:
            parts.append(f"{alternate_used_count} via alternate")
        summary = " ".join(parts)
        return summary, list(results)

    async def _execute_audit_tool(
        self,
        action: str,
        action_input: str,
        kb_name: str | None,
        question: str,
        scratchpad: Scratchpad,
    ) -> tuple[str, list[Source]]:
        """Execute a tool for the audit loop, returning (observation, sources)."""
        if action == "audit":
            return "audit is a control action — skipping tool execution", []
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
            if not result.success:
                logger.warning(f"Audit tool failed action={action} input={action_input}")
            return result.content, sources
        except Exception as e:
            logger.warning(f"Audit tool exception action={action} input={action_input} error={e}")
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
        return (
            f"You are a fact-checking auditor for educational content.\n"
            f"You have access to these tools:\n{tools_desc}\n"
            "Your job is to verify that cited sources actually support the claims made in the answer. "
            "Focus on: aliveness of URLs, content safety, and whether the cited source actually supports the claim."
        )

    def _build_user_prompt(
        self,
        question: str,
        scratchpad: Scratchpad,
        memory_context: str,
    ) -> str:
        all_sources = scratchpad.format_sources_markdown()
        plan = scratchpad._format_plan() if scratchpad.plan else "(no plan)"

        # Format entries as a readable log
        if scratchpad.entries:
            entry_lines = []
            for e in scratchpad.entries:
                note = f"  Note: {e.self_note}" if e.self_note else ""
                entry_lines.append(
                    f"[{e.step_id}] Round {e.round}: {e.thought}\n"
                    f"  Action: {e.action} | Input: {e.action_input}\n"
                    f"  Observation: {e.observation[:200]}{'...' if len(e.observation) > 200 else ''}\n"
                    f"  Sources: {', '.join(s.url or s.file or s.chunk_id or '?' for s in e.sources) or 'none'}"
                    + (f"\n  Note: {e.self_note}" if e.self_note else "")
                )
            entries_str = "\n\n".join(entry_lines)
        else:
            entries_str = "(no entries)"

        prompt = self.get_prompt("user") if self.has_prompts() else None
        if prompt:
            try:
                return prompt.format(
                    question=question,
                    plan=plan,
                    entries=entries_str,
                    sources=all_sources,
                    memory_context=memory_context,
                )
            except KeyError:
                pass

        return (
            f"## Question\n{question}\n\n"
            f"## Plan\n{plan}\n\n"
            f"## Memory Context\n{memory_context or '(none)'}\n\n"
            f"## Sources\n{all_sources}\n\n"
            f"## Entries\n{entries_str}\n\n"
            "## Your Task\n"
            "Review the entries above and assess:\n"
            "1. Are all cited sources alive and accessible?\n"
            "2. Do the sources actually support the claims made?\n"
            "3. Are there any unsafe or unreliable sources?\n"
            "Respond with a JSON object."
        )

    def _format_sources(self, sources: list[dict[str, Any]]) -> str:
        if not sources:
            return "(no sources)"
        lines = []
        for src in sources:
            label = src.get("file") or src.get("url") or src.get("chunk_id") or "?"
            src_id = src.get("id", "")
            src_type = src.get("type", "?")
            lines.append(f"- [{src_type}] {label} (id={src_id})")
        return "\n".join(lines)

    def _parse_audit_decision(self, response: str) -> dict[str, Any]:
        """Parse LLM JSON response into an audit decision dict."""
        data = extract_json_from_text(response)
        if not isinstance(data, dict):
            return {
                "action": "done",
                "action_input": "",
                "thought": "",
                "self_note": f"parse error: expected dict, got {type(data).__name__}",
                "verification_report": "",
                "updated_notes": {},
                "invalid_sources": [],
            }

        return {
            "action": data.get("action", "done"),
            "action_input": data.get("action_input", ""),
            "thought": data.get("thought", ""),
            "self_note": data.get("self_note", ""),
            "verification_report": data.get("verification_report", ""),
            "updated_notes": data.get("updated_notes", {}),
            "invalid_sources": data.get("invalid_sources", []),
        }
