"""Solve tools — the seam between the chat-loop solver and the SolveSession.

Three tools auto-mounted only when a solve turn is active (via the solve loop
capability). The chat agent loop IS the solver; these tools give it a deterministic
spine — a plan it commits to, a per-step "done" gate, and a bounded replan —
while the reasoning (how to actually solve each step) stays the model's job in
the loop, using the shared built-in tools (rag / code_execution / geogebra / …).

The active session id is injected server-side by the pipeline as
``_solve_session_id``; the model never supplies it. ``solve_finish_step`` emits
a ``_context_checkpoint`` so the loop folds the just-finished step's tool
chatter into a one-line summary — the loop-native equivalent of the old
pipeline's per-step message reset.
"""

from __future__ import annotations

import json
from typing import Any

from deeptutor.capabilities.solve.session import get_session
from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolParameter, ToolResult

# Tool names the pipeline mounts together when a solve turn is active. Kept
# here so the mount policy and the registration list can't disagree.
SOLVE_TOOL_NAMES: tuple[str, ...] = (
    "solve_plan",
    "solve_finish_step",
    "solve_replan",
)


def _resolve_session_id(kwargs: dict[str, Any]) -> str:
    return str(kwargs.get("_solve_session_id") or "").strip()


def _json_result(
    payload: dict[str, Any], *, meta_key: str, extra_meta: dict[str, Any] | None = None
) -> ToolResult:
    metadata: dict[str, Any] = {meta_key: payload}
    if extra_meta:
        metadata.update(extra_meta)
    return ToolResult(
        content=json.dumps(payload, ensure_ascii=False),
        success=True,
        metadata=metadata,
    )


def _no_session_result() -> ToolResult:
    return ToolResult(
        content="No solve session is active on this turn; solve tools are unavailable.",
        success=False,
    )


def _parse_steps(raw_steps: Any) -> list[tuple[str, str]]:
    """Validate the model-authored step list into ``(id, goal)`` pairs.

    Ids are server-generated (``S1``, ``S2``, …) so the model never controls
    storage keys; steps without a goal are dropped.
    """
    if not isinstance(raw_steps, list):
        return []
    steps: list[tuple[str, str]] = []
    for i, raw in enumerate(raw_steps):
        if isinstance(raw, dict):
            goal = str(raw.get("goal") or "").strip()
        else:
            goal = str(raw or "").strip()
        if not goal:
            continue
        steps.append((f"S{len(steps) + 1}", goal))
    return steps


class SolvePlanTool(BaseTool):
    """Commit to a step plan for the problem. Call FIRST on a solve turn."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="solve_plan",
            description=(
                "Lay out your plan for solving the problem: a short analysis plus "
                "an ordered list of steps. Call this FIRST, before doing any work. "
                "Then work the steps one at a time with the available tools, "
                "calling solve_finish_step after each. Keep the plan tight (2-6 "
                "steps); for a trivial problem a single step is fine."
            ),
            parameters=[
                ToolParameter(
                    name="analysis",
                    type="string",
                    description="One or two sentences: what the problem asks and your approach.",
                ),
                ToolParameter(
                    name="steps",
                    type="array",
                    description="Ordered steps, each {goal}. Goals are short imperative phrases.",
                    items={
                        "type": "object",
                        "properties": {"goal": {"type": "string"}},
                        "required": ["goal"],
                    },
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        session_id = _resolve_session_id(kwargs)
        if not session_id:
            return _no_session_result()
        steps = _parse_steps(kwargs.get("steps"))
        if not steps:
            return ToolResult(
                content="solve_plan needs a non-empty 'steps' array, each with a 'goal'.",
                success=False,
            )
        analysis = str(kwargs.get("analysis") or "").strip()
        session = get_session(session_id)
        session.set_plan(analysis, steps)
        first = session.next_step()
        return _json_result(
            {
                "status": "planned",
                "analysis": analysis,
                "steps": session.map(),
                "next": first.to_dict() if first else None,
                "instruction": (
                    "Work the first step now using the available tools, then call "
                    "solve_finish_step with a short summary of its result. Do not "
                    "skip steps."
                ),
            },
            meta_key="solve_plan",
        )


class SolveFinishStepTool(BaseTool):
    """Record a step as done and advance; folds the step's chatter to a summary."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="solve_finish_step",
            description=(
                "Mark the current step done and move on. Pass a short summary of "
                "what the step established (the key result / value / conclusion) — "
                "this is kept as the step's record while its intermediate tool "
                "output is folded away to save context. Returns the next step to "
                "work on, or signals that all steps are done."
            ),
            parameters=[
                ToolParameter(
                    name="step_id",
                    type="string",
                    description="The step id from solve_plan (e.g. 'S1').",
                ),
                ToolParameter(
                    name="summary",
                    type="string",
                    description="Short summary of the step's result, kept as its record.",
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        session_id = _resolve_session_id(kwargs)
        if not session_id:
            return _no_session_result()
        step_id = str(kwargs.get("step_id") or "").strip()
        summary = str(kwargs.get("summary") or "").strip()
        session = get_session(session_id)
        if not session.steps:
            return ToolResult(
                content="No plan yet. Call solve_plan before solve_finish_step.",
                success=False,
            )
        step = session.mark_done(step_id, summary)
        if step is None:
            return ToolResult(
                content=f"Unknown step {step_id!r}; valid ids: {[s.id for s in session.steps]}.",
                success=False,
            )
        nxt = session.next_step()
        payload = {
            "status": "step_done",
            "completed": step_id,
            "next": nxt.to_dict() if nxt else None,
            "all_done": session.all_done(),
            "instruction": (
                "Write the final answer now."
                if nxt is None
                else "Work the next step, then call solve_finish_step again."
            ),
        }
        # The checkpoint summary persists this step's outcome while the loop
        # folds its intermediate tool messages away (see AgentLoop).
        checkpoint = f"[{step.id}] {step.goal} — done. {summary}".strip()
        return _json_result(
            payload,
            meta_key="solve_finish_step",
            extra_meta={"_context_checkpoint": {"summary": checkpoint}},
        )


class SolveReplanTool(BaseTool):
    """Discard the current plan for a new one when the approach is stuck."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="solve_replan",
            description=(
                "Replace the plan when the current approach has stalled or proved "
                "wrong. Give the reason and a fresh ordered list of steps. This is "
                "budget-limited — use it only for a genuine course correction, not "
                "minor tweaks. If the budget is spent, finish with what you have."
            ),
            parameters=[
                ToolParameter(
                    name="reason",
                    type="string",
                    description="Why the current plan failed and what changes.",
                ),
                ToolParameter(
                    name="steps",
                    type="array",
                    description="The new ordered steps, each {goal}.",
                    items={
                        "type": "object",
                        "properties": {"goal": {"type": "string"}},
                        "required": ["goal"],
                    },
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        session_id = _resolve_session_id(kwargs)
        if not session_id:
            return _no_session_result()
        steps = _parse_steps(kwargs.get("steps"))
        if not steps:
            return ToolResult(
                content="solve_replan needs a non-empty 'steps' array, each with a 'goal'.",
                success=False,
            )
        reason = str(kwargs.get("reason") or "").strip()
        session = get_session(session_id)
        if not session.replan(reason, steps):
            return ToolResult(
                content=json.dumps(
                    {
                        "status": "budget_exhausted",
                        "instruction": (
                            "Replan budget is spent. Do not replan again — finish "
                            "the problem with the best of what you have."
                        ),
                    },
                    ensure_ascii=False,
                ),
                success=False,
                metadata={"solve_replan": {"status": "budget_exhausted"}},
            )
        first = session.next_step()
        return _json_result(
            {
                "status": "replanned",
                "reason": reason,
                "replans_used": session.replans,
                "replans_max": session.max_replans,
                "steps": session.map(),
                "next": first.to_dict() if first else None,
            },
            meta_key="solve_replan",
        )


SOLVE_TOOL_TYPES: tuple[type[BaseTool], ...] = (
    SolvePlanTool,
    SolveFinishStepTool,
    SolveReplanTool,
)


__all__ = [
    "SOLVE_TOOL_NAMES",
    "SOLVE_TOOL_TYPES",
    "SolveFinishStepTool",
    "SolvePlanTool",
    "SolveReplanTool",
]
