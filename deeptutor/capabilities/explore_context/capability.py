"""Explore-context loop capability.

A near-invisible loop capability that activates whenever the chat turn carries
any readable (non-image) attached source — a document, a notebook record, a
book section, a question-bank entry, or — the motivating case — a referenced
conversation history. When active it runs a read-only pre-pass
(:class:`ContextExplorer`) *before* the answer loop's first LLM call: an
agentic investigation that uses ``read_source`` to read the attached sources
the user's request actually needs, then folds an objective, third-person
investigation into the loop's user-message seed.

Why it exists:

* The chat loop fuses "understand the attached material" with "answer the
  user" in a single loop. When the material is a transcript of the user
  talking to another AI agent, the model reads those ``## Assistant`` turns in
  the same context it answers from and adopts that agent's first-person voice.
  Separating comprehension into an objective pre-pass removes that confusion
  structurally.
* Weak models under native tool calling routinely never call ``read_source``
  themselves. Owning source-reading in a dedicated pre-pass — and dropping the
  tool from the answer loop entirely — forces the investigation to happen up
  front instead of being skipped.

The capability owns no answer-loop tools and contributes no system block — it
works purely through the optional async ``pre_loop`` hook (see
:class:`LoopCapability`). ``read_source`` lives inside the pre-pass's own tool
loop, not on the answer loop's surface.
"""

from __future__ import annotations

from importlib import resources
import logging
from typing import Any

import yaml

from deeptutor.capabilities.protocol import PromptBlock
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream_bus import StreamBus

logger = logging.getLogger(__name__)

_PROMPT_CACHE: dict[str, dict[str, Any]] = {}


def _load_prompts(language: str) -> dict[str, Any]:
    lang = "zh" if str(language or "en").lower().startswith("zh") else "en"
    cached = _PROMPT_CACHE.get(lang)
    if cached is not None:
        return cached
    try:
        text = (
            resources.files(__package__)
            .joinpath("prompts", lang, "explore_context.yaml")
            .read_text(encoding="utf-8")
        )
        data = yaml.safe_load(text)
    except Exception:
        logger.warning("failed to load explore_context prompts (%s)", lang, exc_info=True)
        data = None
    result = data if isinstance(data, dict) else {}
    _PROMPT_CACHE[lang] = result
    return result


def _has_readable_sources(context: UnifiedContext) -> bool:
    """Whether the turn has any readable (non-image) attached source.

    ``source_index`` is the per-turn ``{source_id: full_text}`` map the chat
    pipeline builds from the (session-cumulative) Attached Sources manifest. It
    is non-empty whenever the turn carries any textual source — whether
    attached this turn or carried over from an earlier turn on the branch — so
    the investigation runs query-driven on every turn that has sources to read,
    not just the turn they were first attached.
    """
    idx = context.metadata.get("source_index")
    return isinstance(idx, dict) and bool(idx)


class ExploreContextCapability:
    """Pre-pass capability that investigates the turn's attached context."""

    name = "explore_context"
    # Owns no answer-loop tools: ``read_source`` is mounted inside the pre-pass's
    # own tool loop (:class:`ContextExplorer`), never on the answer surface.
    owned_tools: tuple[str, ...] = ()

    def is_active(self, context: UnifiedContext) -> bool:
        return _has_readable_sources(context)

    def system_block(
        self,
        context: UnifiedContext,
        *,
        language: str,
        prompts: dict[str, Any],
    ) -> PromptBlock | None:
        # The investigation is delivered via ``pre_loop`` (user-message seed),
        # not as a static system block.
        _ = (context, language, prompts)
        return None

    def augment_kwargs(
        self,
        tool_name: str,
        kwargs: dict[str, Any],
        context: UnifiedContext,
    ) -> dict[str, Any]:
        _ = (tool_name, context)
        return kwargs

    def pre_loop_seed(self, context: UnifiedContext) -> str:
        _ = context
        return ""

    async def pre_loop(
        self,
        context: UnifiedContext,
        stream: StreamBus,
        *,
        usage: Any | None = None,
    ) -> PromptBlock | None:
        if not self.is_active(context):
            return None
        # Imported lazily: ``explorer`` pulls in ``services.llm`` /
        # ``core.agentic``, and this capability is constructed at
        # ``capabilities`` package-import time — importing it eagerly would form
        # a circular import through the LLM config stack. By ``pre_loop`` call
        # time everything is initialised.
        from deeptutor.capabilities.explore_context.explorer import ContextExplorer

        explorer = ContextExplorer(
            language=context.language,
            prompts=_load_prompts(context.language),
        )
        investigation = await explorer.investigate(context=context, stream=stream, usage=usage)
        if not investigation.strip():
            return None
        return PromptBlock("explore_context", investigation)


__all__ = ["ExploreContextCapability"]
