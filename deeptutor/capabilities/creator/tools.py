"""Tool that publishes a reviewable Skill/Persona draft from the chat loop."""

from __future__ import annotations

import json
from typing import Any

from deeptutor.core.context import UnifiedContext
from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolResult

CREATOR_TOOL_NAMES: tuple[str, ...] = ("propose_creation",)


class ProposeCreationTool(BaseTool):
    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="propose_creation",
            description=(
                "Publish a complete, editable draft of the Skill or Persona being authored in "
                "this conversation, shown to the user as a review card. This never writes the "
                "Skill/Persona itself — only the user's Approve does that. Call it again with the "
                "full revised package (same name) after each round of changes the user asks for."
            ),
            raw_parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Lowercase slug (letters, digits, hyphens).",
                    },
                    "description": {
                        "type": "string",
                        "description": "One-line summary: what it does and when to use it.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Complete Markdown body. Do not include frontmatter.",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Up to 6 short tags. Skills only; ignored for personas.",
                    },
                    "references": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "path": {
                                    "type": "string",
                                    "description": "Relative path starting with references/.",
                                },
                                "content": {"type": "string"},
                            },
                            "required": ["path", "content"],
                        },
                        "description": (
                            "Up to 12 supporting files under references/. Skills only; ignored "
                            "for personas."
                        ),
                    },
                },
                "required": ["name", "description", "content"],
            },
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        # Lazy by design: importing ``deeptutor.services`` initializes the
        # runtime/tool registry, which is itself importing this built-in type
        # (see ProposePartnerTool's identical comment).
        from deeptutor.services.creations import CreationDraftStore, get_creation_kind

        context = kwargs.pop("_creation_context", None)
        if not isinstance(context, UnifiedContext):
            return ToolResult(content="No active creation context for this turn.", success=False)

        kind = get_creation_kind(context.metadata.get("create_target"))
        if kind is None:
            return ToolResult(content="Create mode is not active for this turn.", success=False)

        try:
            normalized = kind.normalize(kwargs)
        except ValueError as exc:
            return ToolResult(content=str(exc), success=False)

        store = CreationDraftStore()
        session_id = str(context.session_id or "")
        name = normalized["name"]
        if kind.name_in_use(name) and not store.created_by_session(session_id, kind.key, name):
            return ToolResult(
                content=(
                    f"A {kind.label.lower()} named `{name}` already exists. "
                    "Choose a different name, or reuse the name of a draft this "
                    "conversation already created to update it."
                ),
                success=False,
            )

        draft = store.create(
            kind=kind.key,
            session_id=session_id,
            name=name,
            description=normalized["description"],
            content=normalized["content"],
            tags=normalized.get("tags") or [],
            references=normalized.get("references") or [],
        )
        context.extension("creator")["draft_id"] = draft.draft_id
        return ToolResult(
            content=json.dumps(
                {
                    "status": "draft_ready",
                    "draft_id": draft.draft_id,
                    "kind": kind.key,
                    "name": draft.name,
                    "message": (
                        "Shown to the user as a draft card. Nothing is saved until they approve it."
                    ),
                },
                ensure_ascii=False,
            ),
            success=True,
            metadata={"creation_draft": draft.to_dict()},
        )


CREATOR_TOOL_TYPES: tuple[type[BaseTool], ...] = (ProposeCreationTool,)

__all__ = ["CREATOR_TOOL_NAMES", "CREATOR_TOOL_TYPES", "ProposeCreationTool"]
