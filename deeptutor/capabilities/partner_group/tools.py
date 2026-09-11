"""Tool that records, but never executes, a Partner-to-Partner proposal."""

from __future__ import annotations

import json
from typing import Any

from deeptutor.core.context import UnifiedContext
from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolResult

PARTNER_GROUP_TOOL_NAMES: tuple[str, ...] = ("invoke_other",)


class InvokeOtherTool(BaseTool):
    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="invoke_other",
            description=(
                "After your complete formal answer has been saved, propose asking exactly one "
                "other Partner one focused follow-up question. This only creates a user approval "
                "request; it never invokes the target by itself. Use selectively and at most once."
            ),
            raw_parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "target_partner_id": {
                        "type": "string",
                        "description": "Exact @id of one eligible peer Partner.",
                    },
                    "question": {
                        "type": "string",
                        "description": (
                            "A standalone, specific question for the target. Do not include an "
                            "answer on the target's behalf."
                        ),
                    },
                },
                "required": ["target_partner_id", "question"],
            },
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        context = kwargs.pop("_partner_group_context", None)
        if not isinstance(context, UnifiedContext):
            return ToolResult(
                content="invoke_other is available only inside a Partner Group.", success=False
            )

        group = context.metadata.get("partner_group")
        if not isinstance(group, dict):
            return ToolResult(
                content="This Group turn cannot propose another Partner.", success=False
            )
        state = context.extension("partner_group")
        if not group.get("allow_invoke_other"):
            repeated = bool(state.get("disallowed_invocation_attempted"))
            state["disallowed_invocation_attempted"] = True
            state["invocation_decided"] = True
            has_answer = bool(state.get("formal_answer"))
            return ToolResult(
                content=(
                    "This invoked reply cannot create another Partner proposal. Complete the "
                    "current user-facing answer once and end the turn; do not call invoke_other."
                ),
                success=False,
                terminate_turn=has_answer or repeated,
            )
        if not state.get("formal_answer"):
            if state.get("invocation_decided"):
                return self._terminal_result(
                    "The collaboration decision was already consumed. End this turn immediately; "
                    "do not call invoke_other or rewrite an answer.",
                    success=False,
                )
            state["invocation_decided"] = True
            return ToolResult(
                content=(
                    "This collaboration decision is consumed. Write the complete user-facing "
                    "answer exactly once, then end the turn. Do not call invoke_other again."
                ),
                success=False,
            )
        # Reaching the tool consumes the capability's single private decision
        # round. Every outcome terminates so malformed or duplicate proposals
        # cannot send the model back through another full-answer generation.
        if state.get("invocation_decided"):
            return self._terminal_result(
                "The collaboration decision was already consumed. End this turn immediately; "
                "do not rewrite the answer.",
                success=False,
            )
        state["invocation_decided"] = True
        if state.get("invocation_proposal"):
            return self._terminal_result(
                "A proposal is already recorded. End this turn immediately; do not rewrite the answer.",
                success=False,
            )

        target_id = str(kwargs.get("target_partner_id") or "").strip().lstrip("@")
        question = str(kwargs.get("question") or "").strip()
        self_id = str(group.get("self_id") or "")
        members = {
            str(item.get("partner_id") or ""): str(item.get("name") or item.get("partner_id") or "")
            for item in (group.get("members") or [])
            if isinstance(item, dict) and item.get("partner_id")
        }
        if not target_id or target_id not in members:
            return self._terminal_result(
                "No proposal was recorded because the target is not eligible. End this turn "
                "immediately; do not rewrite the answer.",
                success=False,
            )
        if target_id == self_id:
            return self._terminal_result(
                "No proposal was recorded because you cannot invoke yourself. End this turn "
                "immediately; do not rewrite the answer.",
                success=False,
            )
        if not question:
            return self._terminal_result(
                "No proposal was recorded because the question is empty. End this turn "
                "immediately; do not rewrite the answer.",
                success=False,
            )
        if len(question) > 2_000:
            return self._terminal_result(
                "No proposal was recorded because the question is too long. End this turn "
                "immediately; do not rewrite the answer.",
                success=False,
            )

        proposal = {
            "target_partner_id": target_id,
            "target_partner_name": members[target_id],
            "question": question,
        }
        state["invocation_proposal"] = proposal
        return ToolResult(
            content=json.dumps(
                {
                    "status": "pending_user_approval",
                    "target_partner_id": target_id,
                    "message": (
                        "The proposal is recorded. End this turn immediately and do not rewrite "
                        "the saved answer."
                    ),
                },
                ensure_ascii=False,
            ),
            metadata={"partner_invocation": proposal},
            terminate_turn=True,
        )

    @staticmethod
    def _terminal_result(content: str, *, success: bool) -> ToolResult:
        return ToolResult(content=content, success=success, terminate_turn=True)


PARTNER_GROUP_TOOL_TYPES: tuple[type[BaseTool], ...] = (InvokeOtherTool,)

__all__ = ["PARTNER_GROUP_TOOL_NAMES", "PARTNER_GROUP_TOOL_TYPES", "InvokeOtherTool"]
