"""Tool that publishes a complete, editable Partner profile draft."""

from __future__ import annotations

import json
from typing import Any

from deeptutor.core.context import UnifiedContext
from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolResult

PARTNER_AUTHORING_TOOL_NAMES: tuple[str, ...] = ("propose_partner",)


class ProposePartnerTool(BaseTool):
    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="propose_partner",
            description=(
                "Create a complete but non-binding Partner profile draft for the user to "
                "review and confirm in the UI. Infer sensible details from the request. "
                "This never creates or starts a Partner by itself."
            ),
            raw_parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string", "description": "Short memorable display name."},
                    "description": {
                        "type": "string",
                        "description": "One-sentence learner-facing summary.",
                    },
                    "soul": {
                        "type": "string",
                        "description": (
                            "Complete Markdown system profile: identity, educational role, "
                            "goals, teaching style, interaction rules, boundaries, and routines."
                        ),
                    },
                    "language": {
                        "type": "string",
                        "description": "Preferred response language, normally en or zh.",
                    },
                    "emoji": {"type": "string", "description": "One representative emoji."},
                    "color": {
                        "type": "string",
                        "pattern": "^#[0-9A-Fa-f]{6}$",
                        "description": "Accessible six-digit hex accent color.",
                    },
                },
                "required": ["name", "description", "soul", "language", "emoji", "color"],
            },
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        # Lazy by design: importing ``deeptutor.services`` initializes the
        # runtime/tool registry, which is itself importing this built-in type.
        from deeptutor.services.partners.drafts import PartnerDraftStore

        context = kwargs.pop("_partner_authoring_context", None)
        try:
            draft = PartnerDraftStore().create(kwargs)
        except ValueError as exc:
            return ToolResult(content=str(exc), success=False)
        if isinstance(context, UnifiedContext):
            context.extension("partner_authoring")["draft_created"] = draft.draft_id
        payload = draft.to_dict()
        return ToolResult(
            content=json.dumps(
                {
                    "status": "draft_ready",
                    "draft_id": draft.draft_id,
                    "message": "The profile is ready for the user to review and confirm.",
                },
                ensure_ascii=False,
            ),
            success=True,
            metadata={"partner_draft": payload},
        )


PARTNER_AUTHORING_TOOL_TYPES: tuple[type[BaseTool], ...] = (ProposePartnerTool,)

__all__ = ["PARTNER_AUTHORING_TOOL_NAMES", "PARTNER_AUTHORING_TOOL_TYPES"]
