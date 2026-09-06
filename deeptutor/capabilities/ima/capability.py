"""IMA loop capability — inventory, source reading and authoring over a live library.

Active whenever one of the turn's selected knowledge bases is a connected Tencent
IMA library (resolved by :mod:`deeptutor.capabilities.ima.binding`).

Unlike the Obsidian and subagent capabilities this is a *plain*
:class:`~deeptutor.capabilities.protocol.LoopExtension`, not a
:class:`~deeptutor.capabilities.protocol.KnowledgeCapability`: it **adds** its
tools to chat's normal surface instead of replacing it. That difference is not
stylistic — it follows from what the KB actually is. An Obsidian vault has no
index at all, so ``rag`` is useless against it and the capability must own the
turn. An IMA library is genuinely searchable over HTTP: the ``ima`` RAG provider
answers ``rag`` calls for it. Retrieval therefore stays where it belongs, and
these tools add only what retrieval cannot do — enumerate the library, read a
whole source, search notes by recency, and write back.

Keeping the surface additive also means a turn that attaches an IMA library
alongside other knowledge bases (or that needs web search) does not lose those
abilities, which an exclusive capability would strip.
"""

from __future__ import annotations

from importlib import resources
from typing import Any

from deeptutor.capabilities.ima.binding import ima_bindings
from deeptutor.capabilities.ima.tools import BINDINGS_KWARG, IMA_TOOL_NAMES
from deeptutor.capabilities.protocol import PromptBlock
from deeptutor.core.context import UnifiedContext
from deeptutor.services.prompt.language import is_chinese as _is_zh
from deeptutor.services.prompt.lookup import prompt_text as _prompt_text


class ImaCapability:
    """Turn-scoped integration for connected Tencent IMA knowledge bases."""

    name = "ima"
    owned_tools = IMA_TOOL_NAMES

    def is_active(self, context: UnifiedContext) -> bool:
        return bool(ima_bindings(context))

    def system_block(
        self,
        context: UnifiedContext,
        *,
        language: str,
        prompts: dict[str, Any],
    ) -> PromptBlock | None:
        bindings = ima_bindings(context)
        if not bindings:
            return None
        override = _prompt_text(prompts, ("ima", "system"))
        content = override or _load_system_prompt(language)
        names = (
            "、".join(binding.name for binding in bindings)
            if _is_zh(language)
            else ", ".join(binding.name for binding in bindings)
        )
        return PromptBlock("ima", content.replace("{kb_names}", names))

    def augment_kwargs(
        self,
        tool_name: str,
        kwargs: dict[str, Any],
        context: UnifiedContext,
    ) -> dict[str, Any]:
        if tool_name not in IMA_TOOL_NAMES:
            return kwargs
        bindings = ima_bindings(context)
        if not bindings:
            return kwargs
        # Server-owned: overwrite any model-supplied value so a turn can only
        # reach the libraries the user actually attached. Credentials are not
        # part of this payload — the tools load them per call.
        updated = dict(kwargs)
        updated[BINDINGS_KWARG] = bindings
        return updated

    def pre_loop_seed(self, context: UnifiedContext) -> str:
        _ = context
        return ""


def _load_system_prompt(language: str) -> str:
    lang = "zh" if _is_zh(language) else "en"
    prompt = resources.files(__package__).joinpath("prompts", lang, "system.md")
    return prompt.read_text(encoding="utf-8").strip()


__all__ = ["ImaCapability"]
