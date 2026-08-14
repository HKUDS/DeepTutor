"""MarginNote 4 loop capability -- agentic retrieval over a synced MN4 library.

Active whenever the user's selected knowledge base is a connected MarginNote 4
library (resolved by :mod:`deeptutor.capabilities.marginnote4.binding`). As a
:class:`KnowledgeCapability` it owns the turn: the chat loop runs exclusively
on the seven MarginNote tools (plus the ``ask_user`` floor), navigating the
synced study data rather than retrieving flattened RAG chunks.

The store path is injected into each tool call as ``_db_path`` server-side;
the model never supplies it.
"""

from __future__ import annotations

from importlib import resources
from typing import Any

from deeptutor.capabilities.marginnote4.binding import (
    marginnote_binding,
    marginnote_kb_refs,
)
from deeptutor.capabilities.marginnote4.tools import MARGINNOTE_TOOL_NAMES
from deeptutor.capabilities.protocol import KnowledgeCapability, PromptBlock
from deeptutor.core.context import UnifiedContext


class MarginNoteCapability(KnowledgeCapability):
    """Turn-scoped integration for a connected MarginNote 4 library."""

    name = "marginnote4"
    owned_tools = MARGINNOTE_TOOL_NAMES

    def is_active(self, context: UnifiedContext) -> bool:
        return marginnote_binding(context) is not None

    def owned_kbs(self, context: UnifiedContext) -> set[str]:
        return marginnote_kb_refs(context)

    def system_block(
        self,
        context: UnifiedContext,
        *,
        language: str,
        prompts: dict[str, Any],
    ) -> PromptBlock | None:
        binding = marginnote_binding(context)
        if binding is None:
            return None
        override = _prompt_text(prompts, ("marginnote4", "system"))
        content = override or _load_system_prompt(language)
        return PromptBlock("marginnote4", content.replace("{library_name}", binding["name"]))

    def augment_kwargs(
        self,
        tool_name: str,
        kwargs: dict[str, Any],
        context: UnifiedContext,
    ) -> dict[str, Any]:
        if tool_name not in MARGINNOTE_TOOL_NAMES:
            return kwargs
        binding = marginnote_binding(context)
        if binding is None:
            return kwargs
        updated = dict(kwargs)
        updated["_db_path"] = binding["db_path"]
        return updated

    def pre_loop_seed(self, context: UnifiedContext) -> str:
        _ = context
        return ""


def _prompt_text(prompts: dict[str, Any], path: tuple[str, ...]) -> str:
    value: Any = prompts
    for key in path:
        if not isinstance(value, dict):
            return ""
        value = value.get(key)
    return value if isinstance(value, str) and value else ""


def _load_system_prompt(language: str) -> str:
    lang = "zh" if language.lower().startswith("zh") else "en"
    prompt = resources.files(__package__).joinpath("prompts", lang, "system.md")
    return prompt.read_text(encoding="utf-8").strip()


__all__ = ["MarginNoteCapability"]
