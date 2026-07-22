"""Obsidian loop capability — agentic retrieval & authoring over a live vault.

Active whenever the user's selected knowledge base is a connected Obsidian
vault (resolved by :mod:`deeptutor.capabilities.obsidian.binding`). As a
:class:`KnowledgeCapability` it owns the turn: the chat loop runs exclusively
on the nine Obsidian tools (plus the ``ask_user`` floor), navigating and
editing the vault's Markdown directly rather than retrieving flattened chunks.

The vault root is injected into each tool call as ``_vault_path`` server-side;
the model never supplies it.
"""

from __future__ import annotations

from importlib import resources
from typing import Any

from deeptutor.capabilities.obsidian.binding import vault_for_turn
from deeptutor.capabilities.obsidian.tools import OBSIDIAN_TOOL_NAMES
from deeptutor.capabilities.protocol import KnowledgeCapability, PromptBlock
from deeptutor.core.context import UnifiedContext


class ObsidianCapability(KnowledgeCapability):
    """Turn-scoped integration for a connected Obsidian vault."""

    name = "obsidian"
    owned_tools = OBSIDIAN_TOOL_NAMES

    def is_active(self, context: UnifiedContext) -> bool:
        return vault_for_turn(context) is not None

    def system_block(
        self,
        context: UnifiedContext,
        *,
        language: str,
        prompts: dict[str, Any],
    ) -> PromptBlock | None:
        binding = vault_for_turn(context)
        if binding is None:
            return None
        override = _prompt_text(prompts, ("obsidian", "system"))
        content = override or _load_system_prompt(language)
        return PromptBlock("obsidian", content.replace("{vault_name}", binding["name"]))

    def augment_kwargs(
        self,
        tool_name: str,
        kwargs: dict[str, Any],
        context: UnifiedContext,
    ) -> dict[str, Any]:
        if tool_name not in OBSIDIAN_TOOL_NAMES:
            return kwargs
        binding = vault_for_turn(context)
        if binding is None:
            return kwargs
        # Server-owned: overwrite any model-supplied value so the path can't be
        # forged to read/write outside the connected vault.
        updated = dict(kwargs)
        updated["_vault_path"] = binding["path"]
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


__all__ = ["ObsidianCapability"]
