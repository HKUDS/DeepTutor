"""Immersive-reading loop capability.

Active whenever the turn carries an open reading material. It augments the
normal chat surface (it is not a :class:`KnowledgeCapability` — the user keeps
web search, code execution and everything else) with the five reading tools, and
tells the model three things it cannot infer: what document is open, where the
user is currently looking, and how to cite.

**The locate pre-pass.** The capability implements the optional async
``pre_loop`` hook, but *without* a second LLM loop: it runs the same
deterministic search the model would have run, on the user's own question, and
folds the hits into the turn's seed. That choice is deliberate —

* it costs no tokens and adds no latency before the first token,
* it is fully deterministic, so it can be tested rather than sampled, and
* it fixes the real failure it exists for: weak models under native tool calling
  often never call a read tool at all (the same observation
  :mod:`deeptutor.capabilities.explore_context` was built around). Handing the
  model "your question matches page 12 and page 17" up front means grounding
  happens even when the model would not have asked for it.

**Why materials do not enter ``source_index``.** Reading material is addressed by
locator through this capability's own store, never flattened into the per-turn
attached-sources map. That keeps ``ExploreContextCapability`` inactive on reading
turns (it activates on a non-empty ``source_index``), so the two pre-passes can
never both read the same document — no coordination code required in either.
"""

from __future__ import annotations

import asyncio
from importlib import resources
import logging
from typing import Any

import yaml

from deeptutor.capabilities.protocol import PromptBlock
from deeptutor.capabilities.reading.tools import (
    MATERIAL_KWARG,
    READING_TOOL_NAMES,
)
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream_bus import StreamBus

logger = logging.getLogger(__name__)

# Metadata keys the frontend sets on a reading turn.
MATERIAL_ID_KEY = "reading_material_id"
VIEWPORT_KEY = "reading_viewport"
# Set by the mode shell. Distinguishes "the user is in reading mode with nothing
# open yet" from "this is an ordinary chat turn" — the two need different prompts
# and only one of them may answer a document question.
MODE_KEY = "immersive_reading_mode"

# Hits the locate pre-pass folds into the seed. Enough to point at the right
# part of a document, few enough that it cannot crowd out the conversation.
LOCATE_HITS = 4
LOCATE_SNIPPET_CHARS = 260

_PROMPT_CACHE: dict[str, dict[str, Any]] = {}


def _load_prompts(language: str) -> dict[str, Any]:
    lang = "zh" if str(language or "en").lower().startswith("zh") else "en"
    cached = _PROMPT_CACHE.get(lang)
    if cached is not None:
        return cached
    try:
        text = (
            resources.files(__package__)
            .joinpath("prompts", lang, "reading.yaml")
            .read_text(encoding="utf-8")
        )
        data = yaml.safe_load(text)
    except Exception:
        logger.warning("failed to load reading prompts (%s)", lang, exc_info=True)
        data = None
    result = data if isinstance(data, dict) else {}
    _PROMPT_CACHE[lang] = result
    return result


def resolve_material_id(context: UnifiedContext) -> str:
    """The material the turn is reading, or "" when none is open."""
    return str((context.metadata or {}).get(MATERIAL_ID_KEY) or "").strip()


def resolve_viewport(context: UnifiedContext) -> dict[str, Any]:
    """What the user is looking at right now, as reported by the reader."""
    raw = (context.metadata or {}).get(VIEWPORT_KEY)
    return raw if isinstance(raw, dict) else {}


class ReadingCapability:
    """Turn-scoped integration for immersive reading."""

    name = "immersive_reading"
    owned_tools: tuple[str, ...] = READING_TOOL_NAMES

    def is_active(self, context: UnifiedContext) -> bool:
        """Active with a document open, and also with the mode merely selected.

        The second half is not cosmetic. Without it, a turn taken in reading mode
        before any document is open was an ordinary chat turn — so a question
        like "what does the section on positional encoding say?" was answered
        from the model's memory of a similar paper, complete with a confident
        section number and a verbatim-looking quote, and nothing in the answer
        revealed that no document had been read. Activating here lets the prompt
        say the reader is empty, and mounts tools whose guard says the same.
        """
        if resolve_material_id(context):
            return True
        return bool((context.metadata or {}).get(MODE_KEY))

    # -- prompt -----------------------------------------------------------

    def system_block(
        self,
        context: UnifiedContext,
        *,
        language: str,
        prompts: dict[str, Any],
    ) -> PromptBlock | None:
        del prompts  # the capability owns its own prompt file
        own = _load_prompts(language)
        material_id = resolve_material_id(context)
        if not material_id:
            # Mode selected, nothing open. The one thing the model must not do is
            # answer a document question from memory. With neither a material nor
            # the mode there is nothing to say — this is a plain chat turn.
            if not (context.metadata or {}).get(MODE_KEY):
                return None
            empty = str(own.get("no_material") or "").strip()
            return PromptBlock(name="immersive_reading", content=empty) if empty else None

        playbook = str(own.get("playbook") or "").strip()
        if not playbook:
            return None

        facts = self._material_facts(material_id, language=language)
        if not facts:
            # The material vanished (deleted in another tab). Say so rather than
            # promising the model a document it cannot read.
            return PromptBlock(
                name="immersive_reading",
                content=str(own.get("material_missing") or "").strip()
                or "The reading material is unavailable.",
            )
        return PromptBlock(name="immersive_reading", content=f"{playbook}\n\n{facts}")

    def _material_facts(self, material_id: str, *, language: str) -> str:
        """Describe the open document: identity, size, unit word, viewport."""
        try:
            from deeptutor.reading import ReadingStore, material_summary

            store = ReadingStore()
            manifest = store.manifest(material_id)
            annotation_count = len(store.annotations(material_id))
        except Exception:
            logger.info("reading material %s unavailable for prompt", material_id, exc_info=True)
            return ""

        own = _load_prompts(language)
        template = str(own.get("material_facts") or "").strip()
        if not template:
            return ""
        return template.format(
            summary=material_summary(manifest),
            unit=manifest.unit,
            unit_count=manifest.unit_count,
            annotations=annotation_count,
        )

    # -- tool kwargs ------------------------------------------------------

    def augment_kwargs(
        self,
        tool_name: str,
        kwargs: dict[str, Any],
        context: UnifiedContext,
    ) -> dict[str, Any]:
        """Bind the open material to this capability's tools, server-side.

        The model never names a material, so it can neither read a document the
        user has not opened nor mistype an id.
        """
        if tool_name not in READING_TOOL_NAMES:
            return kwargs
        material_id = resolve_material_id(context)
        if not material_id:
            return kwargs
        return {**kwargs, MATERIAL_KWARG: material_id}

    # -- seeds ------------------------------------------------------------

    def pre_loop_seed(self, context: UnifiedContext) -> str:
        """Report the viewport — cheap, synchronous, no I/O.

        Kept separate from the locate pre-pass so that "the user is looking at
        page 12" reaches the model even when the search finds nothing.
        """
        if not resolve_material_id(context):
            return ""
        viewport = resolve_viewport(context)
        locator = _as_int(viewport.get("locator"))
        selection = str(viewport.get("selection") or "").strip()
        parts: list[str] = []
        if locator:
            parts.append(f"The reader is currently showing locator {locator}.")
        if selection:
            parts.append(f'The user has selected this text: "{_clip(selection, 600)}"')
        return " ".join(parts)

    async def pre_loop(
        self,
        context: UnifiedContext,
        stream: StreamBus,
        *,
        usage: Any | None = None,
    ) -> PromptBlock | None:
        """Deterministically locate the user's question in the document.

        No LLM call, so ``usage`` is untouched and the turn's first token is not
        delayed. ``stream`` is accepted to satisfy the hook's signature; there is
        no progress worth narrating for a few milliseconds of local search.
        """
        del stream, usage
        material_id = resolve_material_id(context)
        question = (context.user_message or "").strip()
        if not material_id or len(question) < 3:
            return None

        try:
            hits = await asyncio.to_thread(self._locate, material_id, question)
        except Exception:
            logger.info("reading locate pre-pass failed", exc_info=True)
            return None
        if not hits:
            return None

        own = _load_prompts(context.language or "en")
        header = str(own.get("locate_header") or "").strip() or (
            "Search of the open document for the user's question found:"
        )
        lines = [header]
        lines.extend(hits)
        return PromptBlock(name="immersive_reading_locate", content="\n".join(lines))

    @staticmethod
    def _locate(material_id: str, question: str) -> list[str]:
        from deeptutor.reading import ReadingStore, search_material

        store = ReadingStore()
        manifest = store.manifest(material_id)
        result = search_material(store, material_id, question, limit=LOCATE_HITS)
        if result.is_empty:
            return []
        confidence = "verbatim" if result.mode in ("exact", "normalised") else "loose"
        return [
            f"- {manifest.unit} {hit.locator} ({confidence}): "
            f"{_clip(hit.snippet, LOCATE_SNIPPET_CHARS)}"
            for hit in result.hits
        ]


def _as_int(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


def _clip(text: str, limit: int) -> str:
    flat = " ".join((text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


__all__ = [
    "LOCATE_HITS",
    "MATERIAL_ID_KEY",
    "MODE_KEY",
    "VIEWPORT_KEY",
    "ReadingCapability",
    "resolve_material_id",
    "resolve_viewport",
]
