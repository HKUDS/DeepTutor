"""
BlockGenerator base class
=========================

A BlockGenerator turns a ``Block`` (with ``params``) plus some shared context
(book / chapter / page / KB) into a populated ``Block`` (``payload`` filled,
``status`` set to READY/ERROR).

Generators are stateless and are looked up by ``BlockType`` via
``get_block_registry()``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import asyncio
from dataclasses import dataclass, field
import logging
from typing import Any

from ..models import (
    Block,
    BlockStatus,
    BlockType,
    Chapter,
    ExplorationReport,
    Page,
    SourceAnchor,
)

logger = logging.getLogger(__name__)


class GenerationFailure(Exception):
    """Raised by a generator to mark the block as ERROR."""


def _classify_failure(message: str) -> str:
    """Bucket a generator failure so the UI can say whether a retry is worth it.

    Substring matching on an error string is crude, and the ordering is what
    keeps it honest: a provider's own rejection must be recognised as one
    before the heuristics that look for the *model's* misbehaviour get a turn.
    """
    lower = (message or "").lower()
    # First, because a provider's rejection quotes the field it objected to.
    # DeepSeek's "the reasoning_content in the thinking mode must be passed
    # back to the API" was landing in `prompt_leak` — permanently un-retryable,
    # and blaming the model for what was a bug in how we replayed its history.
    if "invalid_request_error" in lower or "must be passed back" in lower:
        return "provider_error"
    if "json" in lower or "object found" in lower or "parse" in lower:
        return "json_parse"
    if "empty" in lower or "did not return" in lower or "returned no" in lower:
        return "empty_response"
    if "timeout" in lower or "timed out" in lower or "stalled" in lower:
        return "timeout"
    if "rate limit" in lower or "429" in lower:
        return "rate_limit"
    # `"prompt" in lower` deliberately dropped: it also matches "prompt_tokens",
    # which appears in ordinary usage payloads.
    if "<think" in lower or "reasoning_content" in lower or "system prompt" in lower:
        return "prompt_leak"
    if "api" in lower or "llm" in lower or "provider" in lower:
        return "provider_error"
    return "generator_error"


def _failure_metadata(exc: Exception, source: str) -> dict[str, Any]:
    message = str(exc)
    kind = _classify_failure(message)
    return {
        "kind": kind,
        "message": message,
        "retryable": kind
        in {
            "json_parse",
            "empty_response",
            "timeout",
            "rate_limit",
            "provider_error",
            "generator_error",
        },
        "source": source,
    }


@dataclass
class BlockContext:
    """Everything a generator might need outside the block itself."""

    book_id: str
    chapter: Chapter
    page: Page
    block: Block
    language: str = "en"
    knowledge_bases: list[str] = field(default_factory=list)
    rag_enabled: bool = True
    extra: dict[str, Any] = field(default_factory=dict)
    # BookEngine v2 — fed in by ``BookCompiler`` so generators can reuse the
    # exploration sweep instead of re-issuing RAG calls.
    exploration: ExplorationReport | None = None

    @property
    def primary_kb(self) -> str | None:
        return self.knowledge_bases[0] if self.knowledge_bases else None

    def relevant_chunks(self, query: str, *, limit: int = 6) -> list:
        """Return ``SourceChunk`` objects from ``self.exploration`` that look
        relevant to *query* (cheap keyword overlap heuristic). Empty list when
        no exploration is attached."""
        if self.exploration is None or not self.exploration.chunks:
            return []
        tokens = {t for t in (query or "").lower().split() if len(t) > 2}
        if not tokens:
            return self.exploration.chunks[:limit]

        scored: list[tuple[float, Any]] = []
        for ch in self.exploration.chunks:
            text = (ch.text or "").lower()
            q = (ch.query or "").lower()
            hits = sum(1 for tok in tokens if tok in text or tok in q)
            if hits == 0:
                continue
            scored.append((hits + 0.01 * (ch.score or 0.0), ch))
        scored.sort(key=lambda pair: -pair[0])
        return [ch for _, ch in scored[:limit]]


class BlockGenerator(ABC):
    """Base class for all block generators."""

    block_type: BlockType  # subclasses MUST override

    async def generate(self, ctx: BlockContext) -> Block:
        """Public entry point. Wraps ``_generate`` with status book-keeping."""
        block = ctx.block
        block.status = BlockStatus.GENERATING
        block.error = ""
        try:
            payload, anchors, metadata = await self._generate(ctx)
        except GenerationFailure as exc:
            block.status = BlockStatus.ERROR
            block.error = str(exc)
            block.metadata = {
                **block.metadata,
                "failure": _failure_metadata(exc, self.__class__.__name__),
            }
            return block
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(f"Generator {self.__class__.__name__} raised: {exc}", exc_info=True)
            block.status = BlockStatus.ERROR
            block.error = str(exc)
            block.metadata = {
                **block.metadata,
                "failure": _failure_metadata(exc, self.__class__.__name__),
            }
            return block

        block.payload = payload or {}
        if anchors:
            block.source_anchors = anchors
        if metadata:
            block.metadata = {**block.metadata, **metadata}
        block.metadata.pop("failure", None)
        block.status = BlockStatus.READY
        return block

    @abstractmethod
    async def _generate(
        self, ctx: BlockContext
    ) -> tuple[dict[str, Any], list[SourceAnchor], dict[str, Any]]:
        """Subclasses return (payload, source_anchors, metadata)."""


class BlockGeneratorRegistry:
    """In-memory registry mapping ``BlockType`` → generator instance."""

    def __init__(self) -> None:
        self._registry: dict[BlockType, BlockGenerator] = {}

    def register(self, generator: BlockGenerator) -> None:
        self._registry[generator.block_type] = generator

    def get(self, block_type: BlockType) -> BlockGenerator | None:
        return self._registry.get(block_type)

    def types(self) -> list[BlockType]:
        return list(self._registry.keys())


_REGISTRY: BlockGeneratorRegistry | None = None


def get_block_registry() -> BlockGeneratorRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = _build_default_registry()
    return _REGISTRY


def _build_default_registry() -> BlockGeneratorRegistry:
    registry = BlockGeneratorRegistry()
    # Lazy imports to avoid circular deps
    from .animation import AnimationGenerator
    from .callout import CalloutGenerator
    from .code import CodeGenerator
    from .concept_graph import ConceptGraphGenerator
    from .deep_dive import DeepDiveGenerator
    from .figure import FigureGenerator
    from .flash_cards import FlashCardsGenerator
    from .interactive import InteractiveGenerator
    from .quiz import QuizGenerator
    from .section import SectionGenerator
    from .text import TextGenerator
    from .timeline import TimelineGenerator
    from .user_note import UserNoteGenerator

    for cls in (
        TextGenerator,
        CalloutGenerator,
        QuizGenerator,
        UserNoteGenerator,
        FigureGenerator,
        InteractiveGenerator,
        AnimationGenerator,
        CodeGenerator,
        TimelineGenerator,
        FlashCardsGenerator,
        DeepDiveGenerator,
        ConceptGraphGenerator,
        SectionGenerator,
    ):
        registry.register(cls())
    return registry


__all__ = [
    "BlockContext",
    "BlockGenerator",
    "BlockGeneratorRegistry",
    "GenerationFailure",
    "get_block_registry",
]
