#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ResearchAgent - Research Agent
Responsible for executing research logic and tool call decisions
"""

from collections.abc import Awaitable, Callable
from pathlib import Path
import re
from string import Template
import sys
from typing import Any

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.agents.base_agent import BaseAgent
from src.agents.research.data_structures import DynamicTopicQueue, TopicBlock

from ..utils.json_utils import extract_json_from_text


class ResearchAgent(BaseAgent):
    """Research Agent"""

    def __init__(
        self,
        config: dict[str, Any],
        api_key: str | None = None,
        base_url: str | None = None,
        api_version: str | None = None,
    ):
        language = config.get("system", {}).get("language", "zh")
        super().__init__(
            module_name="research",
            agent_name="research_agent",
            api_key=api_key,
            base_url=base_url,
            api_version=api_version,
            language=language,
            config=config,
        )
        self.researching_config = config.get("researching", {})
        self.max_iterations = self.researching_config.get("max_iterations", 5)
        # Iteration mode: "fixed" (must explore all iterations) or "flexible" (can stop early)
        # In "fixed" mode, agent should be more conservative about declaring knowledge sufficient
        # In "flexible" mode (auto), agent can stop early when knowledge is truly sufficient
        self.iteration_mode = self.researching_config.get("iteration_mode", "fixed")
        # Tool availability configuration
        self.enable_rag = self.researching_config.get(
            "enable_rag_hybrid", True
        ) or self.researching_config.get("enable_rag_naive", True)
        # Web search: global switch (tools.web_search.enabled) has higher priority
        # Only enabled when both global switch and module switch are True
        tools_web_search_enabled = (
            config.get("tools", {}).get("web_search", {}).get("enabled", True)
        )
        research_web_search_enabled = self.researching_config.get("enable_web_search", False)
        self.enable_web_search = tools_web_search_enabled and research_web_search_enabled
        self.enable_paper_search = self.researching_config.get("enable_paper_search", False)
        self.enable_run_code = self.researching_config.get("enable_run_code", True)
        # Store enabled tools list for prompt generation
        self.enabled_tools = self.researching_config.get("enabled_tools", ["RAG"])

    @staticmethod
    def _convert_to_template_format(template_str: str) -> str:
        """
        Convert {var} style placeholders to $var style for string.Template.
        This avoids conflicts with LaTeX braces like {\rho}.
        """
        # Only convert simple {var_name} patterns, not nested or complex ones
        return re.sub(r"\{(\w+)\}", r"$\1", template_str)

    def _safe_format(self, template_str: str, **kwargs) -> str:
        """
        Safe string formatting using string.Template to avoid LaTeX brace conflicts.
        """
        converted = self._convert_to_template_format(template_str)
        return Template(converted).safe_substitute(**kwargs)

    def _generate_available_tools_text(self) -> str:
        """
        Generate available tools list based on enabled_tools configuration

        Returns:
            Available tools text for prompt
        """
        tools = []
        if self.enable_rag:
            tools.append(
                "- rag_hybrid: Hybrid RAG retrieval (knowledge base) | Query format: Natural language"
            )
            tools.append(
                "- rag_naive: Basic RAG retrieval (knowledge base) | Query format: Natural language"
            )
            tools.append(
                "- query_item: Entity/item query (e.g., Theorem 3.1, Fig 2.1) | Query format: Entry number"
            )
        if self.enable_paper_search:
            tools.append(
                "- paper_search: Academic paper search | Query format: 3-5 English keywords, space-separated"
            )
        if self.enable_web_search:
            tools.append(
                "- web_search: Web search for latest information | Query format: Natural language"
            )
        if self.enable_run_code:
            tools.append(
                "- run_code: Code execution for calculation/visualization | Query format: Python code"
            )

        if not tools:
            tools.append(
                "- rag_hybrid: Hybrid RAG retrieval (default) | Query format: Natural language"
            )

        return "\n".join(tools)

    def _generate_tool_phase_guidance(self) -> str:
        """
        Generate phased tool selection guidance based on enabled tools.
        Only includes guidance for tools that are actually enabled.

        Returns:
            Tool phase guidance text for prompt
        """
        # Determine which tool categories are enabled
        has_rag = self.enable_rag
        has_paper = self.enable_paper_search
        has_web = self.enable_web_search
        has_code = self.enable_run_code

        # Build phase guidance dynamically based on enabled tools
        guidance_parts = []

        # Phase 1: Basic exploration (always includes RAG if enabled)
        phase1_tools = []
        if has_rag:
            phase1_tools.append(
                "- `rag_hybrid`: Get comprehensive information, core concepts, mechanism principles"
            )
            phase1_tools.append("- `rag_naive`: Query specific definitions, precise formulas")
            phase1_tools.append(
                "- `query_item`: Get content with specific entry numbers (if known)"
            )

        if phase1_tools:
            guidance_parts.append(f"""**Phase 1: Basic Exploration (early iterations)**
Focus on building foundational knowledge:
{chr(10).join(phase1_tools)}""")

        # Phase 2: Deep mining (introduce external tools if enabled)
        phase2_tools = []
        if has_rag:
            phase2_tools.append(
                "- Continue using `rag_hybrid` to explore different angles (applications, relationships, comparisons)"
            )
        if has_paper:
            phase2_tools.append(
                "- `paper_search`: Get cutting-edge academic research (if topic involves academic fields)"
            )
        if has_web:
            phase2_tools.append("- `web_search`: Get practical application cases, industry trends")

        if phase2_tools:
            guidance_parts.append(f"""**Phase 2: Deep Mining (middle iterations)**
Deep dive and expand knowledge:
{chr(10).join(phase2_tools)}""")

        # Phase 3: Completion (all available external tools)
        phase3_tools = []
        if has_paper:
            phase3_tools.append(
                "- `paper_search`: Cutting-edge research, specific methods, experimental results"
            )
        if has_web:
            phase3_tools.append(
                "- `web_search`: Latest developments, practical cases, industry applications"
            )
        if has_code:
            phase3_tools.append(
                "- `run_code`: Algorithm verification, numerical calculation, visualization"
            )

        if phase3_tools:
            guidance_parts.append(f"""**Phase 3: Completion and Supplement (late iterations)**
Fill gaps and expand horizons:
{chr(10).join(phase3_tools)}""")

        # If no external tools enabled, add a note
        if not has_paper and not has_web:
            guidance_parts.append("""**Note**: Only knowledge base tools (RAG) are available.
Focus on thoroughly exploring the knowledge base from multiple angles.""")

        return "\n\n".join(guidance_parts)

    def _generate_research_depth_guidance(self, iteration: int, used_tools: list[str]) -> str:
        """
        Generate research depth guidance based on iteration, used tools, and iteration_mode

        Args:
            iteration: Current iteration number
            used_tools: List of tools already used

        Returns:
            Research depth guidance text
        """
        # Determine research phase based on max_iterations
        early_threshold = max(2, self.max_iterations // 3)
        middle_threshold = max(4, self.max_iterations * 2 // 3)

        if iteration <= early_threshold:
            phase = "early"
            phase_desc = f"Early Stage (Iteration 1-{early_threshold})"
            guidance = "Focus on building foundational knowledge using RAG/knowledge base tools."
        elif iteration <= middle_threshold:
            phase = "middle"
            phase_desc = f"Middle Stage (Iteration {early_threshold + 1}-{middle_threshold})"
            if self.enable_paper_search or self.enable_web_search:
                guidance = "Consider using Paper/Web search to add academic depth and real-time information."
            else:
                guidance = "Deepen knowledge coverage, explore different angles of the topic."
        else:
            phase = "late"
            phase_desc = f"Late Stage (Iteration {middle_threshold + 1}+)"
            guidance = "Fill knowledge gaps, ensure completeness before concluding."

        # Tool diversity analysis
        unique_tools = set(used_tools)
        available_tools = []
        if self.enable_rag and not any(
            t in unique_tools for t in ["rag_hybrid", "rag_naive", "query_item"]
        ):
            available_tools.append("RAG tools (rag_hybrid/rag_naive/query_item)")
        if self.enable_paper_search and "paper_search" not in unique_tools:
            available_tools.append("paper_search")
        if self.enable_web_search and "web_search" not in unique_tools:
            available_tools.append("web_search")

        diversity_hint = ""
        if available_tools and phase != "early":
            diversity_hint = f"\n**Tool Diversity Suggestion**: Consider using unexplored tools: {', '.join(available_tools)}"

        # Iteration mode specific guidance
        if self.iteration_mode == "flexible":
            # Auto/flexible mode: agent can decide when to stop
            mode_guidance = """
**Iteration Mode: FLEXIBLE (Auto)**
You have autonomy to decide when knowledge is sufficient. You may stop early if:
- Core concepts are well covered from multiple angles
- Key questions about the topic have been addressed
- Further iterations would only add marginal value
However, ensure you have made meaningful exploration before concluding."""
        else:
            # Fixed mode: more conservative about stopping
            mode_guidance = """
**Iteration Mode: FIXED**
This mode requires thorough exploration. Be CONSERVATIVE about declaring knowledge sufficient:
- In early iterations (first third), rarely conclude sufficiency
- In middle iterations, require strong evidence of comprehensive coverage
- Only in late iterations, conclude if truly comprehensive"""

        return f"""
**Research Phase Guidance** ({phase_desc}):
{guidance}

Current iteration: {iteration}/{self.max_iterations}
Tools already used: {", ".join(used_tools) if used_tools else "None"}
{diversity_hint}
{mode_guidance}
"""

    def _generate_online_search_instruction(self) -> str:
        """
        Generate online search guidance instructions from YAML config

        Returns:
            Online search guidance text, returns empty string if not enabled
        """
        if not self.enable_web_search and not self.enable_paper_search:
            return ""

        if self.enable_web_search and self.enable_paper_search:
            instruction = self.get_prompt("guidance", "online_search_both")
            if instruction:
                return instruction
        elif self.enable_web_search:
            instruction = self.get_prompt("guidance", "online_search_web_only")
            if instruction:
                return instruction
        elif self.enable_paper_search:
            instruction = self.get_prompt("guidance", "online_search_paper_only")
            if instruction:
                return instruction

        return ""

    def _generate_iteration_mode_criteria(self, iteration: int) -> str:
        """
        Generate iteration mode specific criteria for sufficiency check from YAML config

        Args:
            iteration: Current iteration number

        Returns:
            Iteration mode criteria text
        """
        # Calculate early threshold
        early_threshold = max(2, self.max_iterations // 3)

        if self.iteration_mode == "flexible":
            criteria = self.get_prompt("guidance", "iteration_mode_flexible")
            if criteria:
                return criteria
            # Fallback if YAML not configured
            return "- **FLEXIBLE mode (Auto)**: You have autonomy to decide sufficiency."
        else:
            criteria = self.get_prompt("guidance", "iteration_mode_fixed")
            if criteria:
                return criteria.format(early_threshold=early_threshold)
            # Fallback if YAML not configured
            return f"- **FIXED mode**: Be CONSERVATIVE about declaring sufficiency. Early threshold: {early_threshold}"

    async def check_sufficiency(
        self,
        topic: str,
        overview: str,
        current_knowledge: str,
        iteration: int,
        used_tools: list[str] | None = None,
    ) -> dict[str, Any]:
        system_prompt = self.get_prompt("system", "role")
        if not system_prompt:
            raise ValueError(
                "ResearchAgent missing system prompt, please configure system.role in prompts/{lang}/research_agent.yaml"
            )
        user_prompt_template = self.get_prompt("process", "check_sufficiency")
        if not user_prompt_template:
            raise ValueError(
                "ResearchAgent missing check_sufficiency prompt, please configure process.check_sufficiency in prompts/{lang}/research_agent.yaml"
            )

        # Generate online search guidance (if web_search or paper_search is enabled)
        online_search_instruction = self._generate_online_search_instruction()

        # Generate research depth guidance
        research_depth_guidance = self._generate_research_depth_guidance(
            iteration, used_tools or []
        )

        # Generate iteration mode specific criteria
        iteration_mode_criteria = self._generate_iteration_mode_criteria(iteration)

        # Use safe_format to avoid conflicts with LaTeX braces like {\rho}
        user_prompt = self._safe_format(
            user_prompt_template,
            topic=topic,
            overview=overview,
            current_knowledge=current_knowledge if current_knowledge else "(None)",
            iteration=iteration,
            max_iterations=self.max_iterations,
            online_search_instruction=online_search_instruction,
            research_depth_guidance=research_depth_guidance,
            iteration_mode_criteria=iteration_mode_criteria,
        )
        response = await self.call_llm(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            stage="check_sufficiency",
            verbose=False,
        )
        from ..utils.json_utils import ensure_json_dict, ensure_keys

        data = extract_json_from_text(response)
        obj = ensure_json_dict(data)
        ensure_keys(obj, ["is_sufficient", "reason"])
        return obj

    async def generate_query_plan(
        self,
        topic: str,
        overview: str,
        current_knowledge: str,
        iteration: int,
        existing_topics: list[str] | None = None,
        used_tools: list[str] | None = None,
    ) -> dict[str, Any]:
        system_prompt = self.get_prompt("system", "role")
        if not system_prompt:
            raise ValueError(
                "ResearchAgent missing system prompt, please configure system.role in prompts/{lang}/research_agent.yaml"
            )
        user_prompt_template = self.get_prompt("process", "generate_query_plan")
        if not user_prompt_template:
            raise ValueError(
                "ResearchAgent missing generate_query_plan prompt, please configure process.generate_query_plan in prompts/{lang}/research_agent.yaml"
            )
        topics_text = "(No other topics)"
        if existing_topics:
            topics_text = "\n".join([f"- {t}" for t in existing_topics])

        # Generate available tools list based on configuration (only enabled tools)
        available_tools_text = self._generate_available_tools_text()

        # Generate tool phase guidance based on enabled tools
        tool_phase_guidance = self._generate_tool_phase_guidance()

        # Generate research depth guidance
        research_depth_guidance = self._generate_research_depth_guidance(
            iteration, used_tools or []
        )

        # Use safe_format to avoid conflicts with LaTeX braces like {\rho}
        user_prompt = self._safe_format(
            user_prompt_template,
            topic=topic,
            overview=overview,
            current_knowledge=current_knowledge[:2000] if current_knowledge else "(None)",
            iteration=iteration,
            max_iterations=self.max_iterations,
            existing_topics=topics_text,
            available_tools=available_tools_text,
            tool_phase_guidance=tool_phase_guidance,
            research_depth_guidance=research_depth_guidance,
        )
        response = await self.call_llm(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            stage="generate_query_plan",
            verbose=False,
        )
        from ..utils.json_utils import ensure_json_dict, ensure_keys

        data = extract_json_from_text(response)
        obj = ensure_json_dict(data)
        ensure_keys(obj, ["query", "tool_type", "rationale"])
        return obj

    async def process(
        self,
        topic_block: TopicBlock,
        call_tool_callback: Callable[[str, str], Awaitable[str]],
        note_agent,
        citation_manager,
        queue: DynamicTopicQueue,
        manager_agent,
        config: dict[str, Any],
        progress_callback: Callable[[str, Any], None] | None = None,
    ) -> dict[str, Any]:
        """
        Execute research for a single topic block (complete multi-round retrieval loop)

        Args:
            topic_block: Topic block to research
            call_tool_callback: Tool call callback function (tool_type, query) -> raw_answer
            note_agent: NoteAgent instance for generating summaries
            citation_manager: CitationManager instance for managing citations
            queue: DynamicTopicQueue instance for getting existing topic list
            manager_agent: ManagerAgent instance for adding new topics
            config: Configuration dictionary for getting parameters
            progress_callback: Optional callback for iteration progress (event_type, **data)

        Returns:
            Research result
            {
                "block_id": str,
                "iterations": int,
                "final_knowledge": str,
                "tools_used": List[str],
                "queries_used": List[dict],
                "status": str
            }
        """
        block_id_prefix = f"[{topic_block.block_id}]"
        print(f"\n{block_id_prefix} {'=' * 70}")
        print(f"{block_id_prefix} 🔬 ResearchAgent - Executing Research")
        print(f"{block_id_prefix} {'=' * 70}")
        print(f"{block_id_prefix} Topic: {topic_block.sub_topic}")
        print(f"{block_id_prefix} Overview: {topic_block.overview}")
        print(
            f"{block_id_prefix} Max iterations: {self.max_iterations}, Mode: {self.iteration_mode}\n"
        )

        iteration = 0
        current_knowledge = ""
        tools_used = []
        queries_used = []  # Track all queries for progress display

        # Helper to send progress updates
        def send_progress(event_type: str, **data):
            if progress_callback:
                try:
                    progress_callback(event_type, **data)
                except Exception:
                    pass  # Ignore callback errors

        while iteration < self.max_iterations:
            iteration += 1
            print(f"{block_id_prefix} \n【Iteration {iteration}/{self.max_iterations}】")

            # Send iteration started progress
            send_progress(
                "iteration_started",
                iteration=iteration,
                max_iterations=self.max_iterations,
                tools_used=tools_used.copy(),
            )

            # Step 1: Check if knowledge is sufficient
            send_progress(
                "checking_sufficiency", iteration=iteration, max_iterations=self.max_iterations
            )
            suff = await self.check_sufficiency(
                topic=topic_block.sub_topic,
                overview=topic_block.overview,
                current_knowledge=current_knowledge,
                iteration=iteration,
                used_tools=tools_used,
            )

            if suff.get("is_sufficient", False):
                print(
                    f"{block_id_prefix}   ✓ Current topic is sufficient, ending research for this topic"
                )
                send_progress(
                    "knowledge_sufficient",
                    iteration=iteration,
                    max_iterations=self.max_iterations,
                    reason=suff.get("reason", ""),
                )
                break

            # Step 2: Generate query plan
            send_progress(
                "generating_query", iteration=iteration, max_iterations=self.max_iterations
            )
            plan = await self.generate_query_plan(
                topic=topic_block.sub_topic,
                overview=topic_block.overview,
                current_knowledge=current_knowledge,
                iteration=iteration,
                existing_topics=queue.list_topics(),
                used_tools=tools_used,
            )

            # Dynamic splitting: if new topic is discovered, add to queue tail
            new_topic = plan.get("new_sub_topic")
            new_overview = plan.get("new_overview")
            new_topic_score = float(plan.get("new_topic_score") or 0)
            should_add_new_topic = plan.get("should_add_new_topic")
            min_score = config.get("researching", {}).get("new_topic_min_score", 0.75)
            new_topic_reason = plan.get("new_topic_reason")

            if isinstance(new_topic, str) and new_topic.strip():
                trimmed_topic = new_topic.strip()
                if should_add_new_topic is False:
                    print(
                        f"{block_id_prefix}   ↩️ LLM determined not to add new topic《{trimmed_topic}》, skipping"
                    )
                elif new_topic_score < min_score:
                    print(
                        f"{block_id_prefix}   ↩️ New topic《{trimmed_topic}》score {new_topic_score:.2f} below threshold {min_score:.2f}, skipping"
                    )
                else:
                    # Support both sync and async manager_agent
                    import inspect

                    add_topic_method = getattr(manager_agent, "add_new_topic")
                    if inspect.iscoroutinefunction(add_topic_method):
                        added = await add_topic_method(trimmed_topic, new_overview or "")
                    else:
                        added = manager_agent.add_new_topic(trimmed_topic, new_overview or "")
                    if added:
                        print(f"{block_id_prefix}   ✓ Added new topic《{trimmed_topic}》to queue")
                        send_progress(
                            "new_topic_added",
                            iteration=iteration,
                            max_iterations=self.max_iterations,
                            new_topic=trimmed_topic,
                            new_overview=new_overview or "",
                        )
                if new_topic_reason:
                    print(f"{block_id_prefix}     Reason: {new_topic_reason}")

            query = plan.get("query", "").strip()
            tool_type = plan.get("tool_type", "rag_hybrid")
            rationale = plan.get("rationale", "")

            if not query:
                print(f"{block_id_prefix}   ⚠️ Generated query is empty, skipping this iteration")
                send_progress(
                    "query_empty", iteration=iteration, max_iterations=self.max_iterations
                )
                continue

            # Track this query
            query_info = {
                "query": query,
                "tool_type": tool_type,
                "rationale": rationale,
                "iteration": iteration,
            }
            queries_used.append(query_info)

            # Send progress before tool call
            send_progress(
                "tool_calling",
                iteration=iteration,
                max_iterations=self.max_iterations,
                tool_type=tool_type,
                query=query,
                rationale=rationale,
            )

            # Step 3: Call tool
            raw_answer = await call_tool_callback(tool_type, query)

            # Send progress after tool call (summary will be added after NoteAgent processes)
            send_progress(
                "tool_completed",
                iteration=iteration,
                max_iterations=self.max_iterations,
                tool_type=tool_type,
                query=query,
            )

            # Step 4: Get citation ID from CitationManager (unified ID generation)
            send_progress(
                "processing_notes", iteration=iteration, max_iterations=self.max_iterations
            )

            # Get citation_id from CitationManager - support both sync and async
            import inspect

            if hasattr(
                citation_manager, "get_next_citation_id_async"
            ) and inspect.iscoroutinefunction(
                getattr(citation_manager, "get_next_citation_id_async", None)
            ):
                citation_id = await citation_manager.get_next_citation_id_async(
                    stage="research", block_id=topic_block.block_id
                )
            else:
                citation_id = citation_manager.get_next_citation_id(
                    stage="research", block_id=topic_block.block_id
                )

            # Step 5: NoteAgent records summary with the citation ID
            trace = await note_agent.process(
                tool_type=tool_type,
                query=query,
                raw_answer=raw_answer,
                citation_id=citation_id,
                topic=topic_block.sub_topic,
                context=current_knowledge,
            )
            topic_block.add_tool_trace(trace)

            # Send note_generated event with the summary for UI display
            send_progress(
                "note_generated",
                iteration=iteration,
                max_iterations=self.max_iterations,
                tool_type=tool_type,
                query=query,
                summary=trace.summary,
                citation_id=citation_id,
            )

            # Step 6: Add citation information to citation manager
            # Support both sync and async citation_manager
            if hasattr(citation_manager, "add_citation") and callable(
                getattr(citation_manager, "add_citation", None)
            ):
                add_citation_method = getattr(citation_manager, "add_citation")
                if inspect.iscoroutinefunction(add_citation_method):
                    await add_citation_method(
                        citation_id=citation_id,
                        tool_type=tool_type,
                        tool_trace=trace,
                        raw_answer=raw_answer,
                    )
                else:
                    citation_manager.add_citation(
                        citation_id=citation_id,
                        tool_type=tool_type,
                        tool_trace=trace,
                        raw_answer=raw_answer,
                    )
            else:
                # Fallback to sync version
                citation_manager.add_citation(
                    citation_id=citation_id,
                    tool_type=tool_type,
                    tool_trace=trace,
                    raw_answer=raw_answer,
                )

            # Step 7: Update knowledge (accumulate summaries)
            current_knowledge = (current_knowledge + "\n" + trace.summary).strip()
            topic_block.iteration_count = iteration
            tools_used.append(tool_type)

            # Send iteration completed progress
            send_progress(
                "iteration_completed",
                iteration=iteration,
                max_iterations=self.max_iterations,
                tool_type=tool_type,
                query=query,
                tools_used=tools_used.copy(),
            )

        return {
            "block_id": topic_block.block_id,
            "iterations": iteration,
            "final_knowledge": current_knowledge,
            "tools_used": tools_used,
            "queries_used": queries_used,
            "status": "completed" if iteration < self.max_iterations else "max_iterations_reached",
        }


__all__ = ["ResearchAgent"]
