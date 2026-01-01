#!/usr/bin/env python
"""
SolveAgent - Tool planner
Responsible for evaluating existing materials based on step_target and generating tool call trajectories to execute
"""

from pathlib import Path
import re
import sys
from typing import Any

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from ..base_agent import BaseAgent
from ..memory import CitationMemory, InvestigateMemory, SolveChainStep, SolveMemory
from ..utils.json_utils import extract_json_from_text


class SolveAgent(BaseAgent):
    """Solver Agent - Plans and records tool calls"""

    SUPPORTED_TOOL_TYPES = {
        "none",
        "rag_naive",
        "rag_hybrid",
        "web_search",
        "code_execution",
        "finish",
    }

    def __init__(self, config: dict[str, Any], api_key: str, base_url: str, token_tracker=None):
        super().__init__(
            config=config,
            api_key=api_key,
            base_url=base_url,
            agent_name="solve_agent",
            use_prompt_loader=True,
            token_tracker=token_tracker,
        )
        # Read web_search enabled config from tools.web_search.enabled
        self.enable_web_search = config.get("tools", {}).get("web_search", {}).get("enabled", True)

    async def process(
        self,
        question: str,
        current_step: SolveChainStep,
        solve_memory: SolveMemory,
        investigate_memory: InvestigateMemory,
        citation_memory: CitationMemory,
        kb_name: str = "ai_textbook",
        output_dir: str | None = None,
        verbose: bool = True,
    ) -> dict[str, Any]:
        if not current_step:
            raise ValueError("No pending solve-chain step to execute")

        context = self._build_context(
            question=question,
            current_step=current_step,
            solve_memory=solve_memory,
            investigate_memory=investigate_memory,
        )

        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(context)

        response = await self.call_llm(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            verbose=verbose,
            response_format={"type": "json_object"},  # Force JSON
        )

        tool_plan = self._parse_tool_plan(response)
        if not tool_plan:
            # Try to be compatible with old logic, or raise error
            # For robustness, if JSON parsing fails, raise more specific error
            self.logger.warning(
                f"SolveAgent JSON parsing failed or empty, Raw: {response[:200]}..."
            )
            # If empty list, also treat as exception, because SolveAgent should output at least none or finish
            raise ValueError(
                "SolveAgent did not parse any valid tool_calls structure from LLM output"
            )

        finish_requested = any(item["type"] == "finish" for item in tool_plan)
        newly_created: list[dict[str, Any]] = []
        existing_calls = len(current_step.tool_calls)

        for order, item in enumerate(tool_plan, start=1):
            tool_type = item["type"]
            query = item["query"]

            if tool_type == "finish":
                continue

            normalized_query = self._prepare_query(tool_type, query, current_step)

            cite_id = None
            if tool_type != "none":
                cite_id = citation_memory.add_citation(
                    tool_type=tool_type,
                    query=normalized_query,
                    raw_result="",
                    content="",
                    stage="solve",
                    step_id=current_step.step_id,
                )

            record = solve_memory.append_tool_call(
                step_id=current_step.step_id,
                tool_type=tool_type,
                query=normalized_query,
                cite_id=cite_id,
                metadata={
                    "plan_order": existing_calls + order,
                    "kb_name": kb_name,
                },
            )

            request_info = {
                "call_id": record.call_id,
                "tool_type": tool_type,
                "query": normalized_query,
                "cite_id": cite_id,
                "status": record.status,
            }

            if tool_type == "none":
                summary = self._summarize_none_answer(normalized_query)
                solve_memory.update_tool_call_result(
                    step_id=current_step.step_id,
                    call_id=record.call_id,
                    raw_answer=normalized_query,
                    summary=summary,
                    status="none",
                )
                # none calls are not counted in citation system
                request_info["status"] = "none"
                request_info["summary"] = summary
                # none type indicates tool call phase is finished, but step_response must be generated by ResponseAgent
                finish_requested = True
                newly_created.append(request_info)
                # none type indicates no need to append additional tools, but won't directly write to step_response
                break

            newly_created.append(request_info)

        solve_memory.save()
        citation_memory.save()

        return {
            "step_id": current_step.step_id,
            "requested_calls": newly_created,
            "finish_requested": finish_requested,
            "raw_llm_response": response,
            "status": (
                "waiting_tools"
                if newly_created
                else ("ready_for_response" if finish_requested else "idle")
            ),
        }

    # ------------------------------------------------------------------ #
    # Prompt Building
    # ------------------------------------------------------------------ #
    def _build_context(
        self,
        question: str,
        current_step: SolveChainStep,
        solve_memory: SolveMemory,
        investigate_memory: InvestigateMemory,
    ) -> dict[str, Any]:
        return {
            "question": question,
            "current_step_id": current_step.step_id,
            "step_target": current_step.step_target,
            "available_cite_text": self._format_available_cite(current_step, investigate_memory),
            "previous_steps": self._format_previous_steps(current_step, solve_memory),
            "current_tool_history": self._format_tool_history(current_step),
        }

    def _build_system_prompt(self) -> str:
        prompt = self.get_prompt("system") if self.has_prompts() else None
        if not prompt:
            raise ValueError(
                "SolveAgent missing system prompt, please configure system in prompts/zh/solve_loop/solve_agent.yaml."
            )
        
        # If web_search is disabled, remove web_search from prompt
        if not self.enable_web_search:
            lines = prompt.split("\n")
            filtered_lines = []
            for line in lines:
                # Skip lines that describe web_search
                if "web_search" in line and (
                    "Latest Info" in line or "Extracurricular" in line or
                    "最新信息" in line or "课外知识" in line or
                    "Select `web_search`" in line
                ):
                    continue
                # Remove web_search from tool type list
                if "web_search" in line:
                    line = line.replace(" | web_search", "").replace("web_search | ", "").replace("| web_search", "")
                filtered_lines.append(line)
            prompt = "\n".join(filtered_lines)
        
        return prompt

    def _build_user_prompt(self, context: dict[str, Any]) -> str:
        template = self.get_prompt("user_template") if self.has_prompts() else None
        if not template:
            raise ValueError(
                "SolveAgent missing user_template prompt, please configure user_template in prompts/zh/solve_loop/solve_agent.yaml."
            )
        return template.format(**context)

    # ------------------------------------------------------------------ #
    # Parsing and Formatting
    # ------------------------------------------------------------------ #
    def _format_available_cite(
        self, current_step: SolveChainStep, investigate_memory: InvestigateMemory
    ) -> str:
        if not current_step.available_cite:
            return "(No available knowledge chain)"

        lines: list[str] = []
        for cite_id in current_step.available_cite:
            knowledge = next(
                (k for k in investigate_memory.knowledge_chain if k.cite_id == cite_id), None
            )
            if not knowledge:
                continue
            summary = knowledge.summary or knowledge.raw_result[:300]
            raw_preview = (
                knowledge.raw_result[:300].replace("\n", " ") if knowledge.raw_result else ""
            )
            lines.append(
                f"{cite_id} | {knowledge.tool_type}\n"
                f"  Query: {knowledge.query}\n"
                f"  Summary: {summary}\n"
                f"  Raw: {raw_preview}"
            )
        return "\n".join(lines) if lines else "(No matching knowledge)"

    def _format_previous_steps(
        self, current_step: SolveChainStep, solve_memory: SolveMemory
    ) -> str:
        snippets: list[str] = []
        for step in solve_memory.solve_chains:
            if step.step_id == current_step.step_id:
                break
            if step.step_response:
                snippets.append(
                    f"[{step.step_id}] {step.step_target}\n{step.step_response[:300]}..."
                )
        return "\n\n".join(snippets[-3:]) if snippets else "(No completed steps yet)"

    def _format_tool_history(self, current_step: SolveChainStep) -> str:
        if not current_step.tool_calls:
            return "(No tool calls have been made yet)"
        lines: list[str] = []
        for call in current_step.tool_calls:
            summary = call.summary or "(Pending)"
            lines.append(
                f"{call.tool_type} | cite_id={call.cite_id or 'N/A'} | Status={call.status}\n"
                f"Query: {call.query}\n"
                f"Summary: {summary[:200]}"
            )
        return "\n\n".join(lines)

    def _parse_tool_plan(self, response: str) -> list[dict[str, str]]:
        """
        Parse JSON plan returned by LLM
        """
        parsed_data = extract_json_from_text(response)

        if not parsed_data or not isinstance(parsed_data, dict):
            return []

        tool_calls = parsed_data.get("tool_calls", [])
        if not isinstance(tool_calls, list):
            return []

        actions: list[dict[str, str]] = []
        for item in tool_calls:
            if not isinstance(item, dict):
                continue

            tool_type = str(item.get("type", "")).strip().lower()
            query = str(item.get("query", "")).strip()

            if not tool_type:
                continue

            if tool_type not in self.SUPPORTED_TOOL_TYPES:
                self.logger.warning(f"[SolveAgent] Ignoring unknown tool type: {tool_type}")
                continue

            actions.append({"type": tool_type, "query": query})

        return actions

    # ------------------------------------------------------------------ #
    # Query preprocessing & helper
    # ------------------------------------------------------------------ #
    def _prepare_query(self, tool_type: str, query: str, current_step: SolveChainStep) -> str:
        if tool_type == "code_execution":
            return self._prepare_code_query(query)
        return query.strip()

    def _summarize_none_answer(self, text: str) -> str:
        return text.strip()

    def _prepare_code_query(self, raw_query: str | None) -> str:
        if not raw_query:
            return ""

        text = raw_query.strip()

        # In JSON format, raw_query is already a string.
        # If LLM still outputs markdown code block markers (```python ... ```), we need to remove them.
        # If LLM directly outputs code (without markdown markers), it should also be compatible.

        # Check if code fence is present
        fence_match = re.search(
            r"```(?:[A-Za-z0-9_+\-]*)?\s*\n?(?P<code>[\s\S]*?)```", text, re.DOTALL
        )

        if fence_match:
            code = fence_match.group("code").strip()
        else:
            # If no fence, assume entire text is code
            # Exclude common non-code interference (though rare in JSON format, LLM may put reasoning in query)
            code = text

        # Clean up possible leading/trailing whitespace again
        return code.strip()

    def _normalize_latex_sequences(self, text: str) -> str:
        if not text or not text.strip():
            return ""
        cleaned = text.strip()
        cleaned = cleaned.replace("\\{", "{").replace("\\}", "}").replace("$", "")
        pattern = re.compile(r"(?P<var>[A-Za-z_][A-Za-z0-9_\[\]]*)\s*=\s*\{(?P<values>[^\}]+)\}")

        def replacer(match: re.Match) -> str:
            var = match.group("var")
            values = match.group("values")
            base_var = re.sub(r"\[.*?\]", "", var).strip()
            values = values.replace(";", ",")
            items = [v.strip() for v in values.split(",") if v.strip()]
            formatted_values = ", ".join(items)
            return f"{base_var} = [{formatted_values}]"

        normalized = re.sub(pattern, replacer, cleaned)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized
