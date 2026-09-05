"""Chat tools for the soft learning journal (#740)."""

from __future__ import annotations

from typing import Any

from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolParameter, ToolResult
from deeptutor.tools.prompting import load_prompt_hints


class _PromptHintsMixin:
    def get_prompt_hints(self, language: str = "en"):
        return load_prompt_hints(self.name, language=language)


class LearningStatusTool(_PromptHintsMixin, BaseTool):
    """Read the learner's mission / last-session handoff / recent records."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="learning_status",
            description=(
                "Read the soft learning journal: mission (topic + why + level), "
                "last-session handoff, and recent learning records. The mission "
                "and handoff are already in your context when a journal exists "
                "— call this for the record history, or when the user asks to "
                "continue learning and nothing was carried over. Not a "
                "substitute for Mastery Path progress (use mastery_status for "
                "scored curriculum)."
            ),
            parameters=[],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        from deeptutor.services.learning_journal import get_learning_journal_store

        text = get_learning_journal_store().status_markdown()
        return ToolResult(content=text, metadata={"char_count": len(text)})


class LearningUpdateTool(_PromptHintsMixin, BaseTool):
    """Write mission / session notes / learning records into the journal."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="learning_update",
            description=(
                "Update the soft learning journal across sessions. "
                "op=set_mission pins topic/why/level; op=note_session records "
                "what happened and the next focus; op=add_record stores one "
                "durable insight (ADR-style). Use for free-form multi-session "
                "study; do not dump preferences here (use write_memory) and do "
                "not replace Mastery Path gates."
            ),
            parameters=[
                ToolParameter(
                    name="op",
                    type="string",
                    description=(
                        "set_mission | note_session | add_record. "
                        "set_mission needs topic (+ optional why/level); "
                        "note_session needs summary and/or next_focus; "
                        "add_record needs insight (+ optional title)."
                    ),
                    enum=["set_mission", "note_session", "add_record"],
                    required=True,
                ),
                ToolParameter(
                    name="topic",
                    type="string",
                    description="set_mission: what they are learning.",
                    required=False,
                ),
                ToolParameter(
                    name="why",
                    type="string",
                    description="set_mission: why it matters to them.",
                    required=False,
                ),
                ToolParameter(
                    name="level",
                    type="string",
                    description="set_mission: beginner | intermediate | advanced | short free text.",
                    required=False,
                ),
                ToolParameter(
                    name="summary",
                    type="string",
                    description="note_session: what was covered this session.",
                    required=False,
                ),
                ToolParameter(
                    name="next_focus",
                    type="string",
                    description="note_session: what to pick up next time.",
                    required=False,
                ),
                ToolParameter(
                    name="title",
                    type="string",
                    description="add_record: short label for the insight.",
                    required=False,
                ),
                ToolParameter(
                    name="insight",
                    type="string",
                    description="add_record: the durable takeaway (non-obvious lesson).",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        from deeptutor.services.learning_journal import get_learning_journal_store

        op = str(kwargs.get("op") or "").strip().lower()
        store = get_learning_journal_store()

        if op == "set_mission":
            result = store.set_mission(
                topic=str(kwargs.get("topic") or ""),
                why=str(kwargs.get("why") or ""),
                level=str(kwargs.get("level") or ""),
            )
        elif op == "note_session":
            result = store.note_session(
                summary=str(kwargs.get("summary") or ""),
                next_focus=str(kwargs.get("next_focus") or ""),
            )
        elif op == "add_record":
            result = store.add_record(
                title=str(kwargs.get("title") or ""),
                insight=str(kwargs.get("insight") or ""),
            )
        else:
            return ToolResult(
                content=(
                    f"Error: op must be set_mission, note_session, or add_record; got {op!r}."
                ),
                success=False,
            )

        return ToolResult(
            content=result.message,
            success=result.accepted,
            metadata={
                "op": op,
                "record_id": result.record_id,
                "deduplicated": result.deduplicated,
            },
        )


__all__ = [
    "LearningStatusTool",
    "LearningUpdateTool",
]
