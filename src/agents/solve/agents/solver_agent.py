"""
SolverAgent — ReAct agent that iteratively gathers information for each plan step.

For every step in the plan, the SolverAgent runs a think-act-observe loop:
  1. THINK  — reason about what information is still missing
  2. ACT    — choose a tool (rag_search | web_search | code_execute | done | replan)
  3. OBSERVE — the tool result is appended to the Scratchpad (outside this agent)

The agent outputs a single JSON decision per call.
"""

from __future__ import annotations

from typing import Any

from src.agents.base_agent import BaseAgent

from ..memory.scratchpad import PlanStep, Scratchpad
from ..tools import ToolRegistry
from ..utils.json_utils import extract_json_from_text


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


class SolverAgent(BaseAgent):
    """ReAct reasoning agent — one LLM call per iteration."""

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
    ) -> None:
        super().__init__(
            module_name="solve",
            agent_name="solver_agent",
            api_key=api_key,
            base_url=base_url,
            model=model,
            api_version=api_version,
            config=config or {},
            token_tracker=token_tracker,
            language=language,
        )
        self._tool_registry = tool_registry or ToolRegistry.create_default(language)

    async def process(
        self,
        question: str,
        current_step: PlanStep,
        scratchpad: Scratchpad,
        memory_context: str = "",
        image_url: str | None = None,
    ) -> dict[str, str]:
        """Run one ReAct iteration for the given plan step.

        Args:
            question: The user's original question.
            current_step: The plan step being solved.
            scratchpad: Current scratchpad state.
            memory_context: Historical memory context string.
            image_url: Optional image URL for multimodal questions.

        Returns:
            dict with keys: thought, action, action_input, self_note
        """
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(
            question=question,
            current_step=current_step,
            scratchpad=scratchpad,
            memory_context=memory_context,
        )

        llm_kwargs: dict[str, object] = {
            "user_prompt": user_prompt,
            "system_prompt": system_prompt,
            "response_format": {"type": "json_object"},
            "stage": f"solve_{current_step.id}",
        }

        if image_url:
            llm_kwargs["messages"] = _build_multimodal_messages(
                system_prompt, user_prompt, image_url,
            )

        response = await self.call_llm(**llm_kwargs)

        return self._parse_decision(response)

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_system_prompt(self) -> str:
        tools_desc = self._tool_registry.build_solver_description()

        prompt = self.get_prompt("system") if self.has_prompts() else None
        if prompt:
            try:
                return prompt.format(tools_description=tools_desc)
            except KeyError:
                return prompt

        # Fallback
        return (
            "You are a ReAct problem-solving agent. For the current step, decide what "
            "action to take next. Output strict JSON with keys: thought, action, "
            "action_input, self_note.\n\n"
            f"Available actions:\n{tools_desc}\n\n"
            "self_note: write a 1-sentence summary of what you learned this round."
        )

    def _build_user_prompt(
        self,
        question: str,
        current_step: PlanStep,
        scratchpad: Scratchpad,
        memory_context: str = "",
    ) -> str:
        template = self.get_prompt("user_template") if self.has_prompts() else None

        ctx = scratchpad.build_solver_context(current_step.id)

        current_step_text = f"[{current_step.id}] {current_step.goal}"

        if template:
            return template.format(
                question=question,
                plan=ctx["plan"],
                current_step=current_step_text,
                step_history=ctx["step_history"],
                previous_knowledge=ctx["previous_knowledge"],
                memory_context=memory_context or "(no historical memory)",
            )

        # Fallback
        return (
            f"## Original Question\n{question}\n\n"
            f"## Plan\n{ctx['plan']}\n\n"
            f"## Current Step\n{current_step_text}\n\n"
            f"## Previous Actions for This Step\n{ctx['step_history']}\n\n"
            f"## Knowledge from Previous Steps\n{ctx['previous_knowledge']}\n\n"
            f"## Historical Knowledge\n{memory_context or '(none)'}"
        )

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    def _parse_decision(self, response: str) -> dict[str, str]:
        """Parse the LLM JSON response into a decision dict."""
        data = extract_json_from_text(response)

        if not data or not isinstance(data, dict):
            # If parsing completely fails, default to done
            return {
                "thought": "Failed to parse response; ending step.",
                "action": "done",
                "action_input": "",
                "self_note": "Parse error — defaulting to done.",
            }

        action = str(data.get("action", "done")).strip().lower()
        if action not in self._tool_registry.valid_actions:
            action = "done"

        return {
            "thought": str(data.get("thought", "")),
            "action": action,
            "action_input": str(data.get("action_input", "")),
            "self_note": str(data.get("self_note", "")),
        }
