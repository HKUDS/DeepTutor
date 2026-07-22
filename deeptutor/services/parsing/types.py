"""Canonical, engine-agnostic document-parse result (the bridge IR).

The parse layer sits between *input material* and its consumers (question
extraction, RAG indexing, future LightRAG). Every engine — MinerU, Docling,
markitdown — produces the same :class:`ParsedDocument` so consumers never branch
on which engine ran.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


class ParserError(RuntimeError):
    """Raised when a parse fails or is gated (engine missing, models not ready,
    misconfiguration). Carries a user-facing message; the capability/stream
    layers surface it as a stream error. Engine-specific errors (e.g.
    ``MinerUError``) subclass this so callers can catch a single type."""


@dataclass(frozen=True)
class ParsedDocument:
    """The bridge IR.

    ``markdown`` is always present — the lowest common denominator every engine
    produces (MinerU writes ``.md``, Docling exports markdown, markitdown and
    text-only produce markdown/plain text). ``blocks`` is the richer MinerU
    ``content_list``-shaped structure: native for MinerU, mapped for Docling,
    ``None`` for text-only/markitdown. Consumers that only need text read
    ``markdown``; consumers wanting multimodal structure prefer ``blocks`` and
    fall back to chunking ``markdown`` when it is absent.
    """

    markdown: str
    blocks: Optional[list[dict[str, Any]]] = None
    asset_dir: Optional[Path] = None
    source_hash: str = ""
    parser_signature: str = ""
    engine: str = ""
    # The on-disk cache dir holding the raw engine artifacts. Consumers that
    # still operate on a directory (e.g. the question extractor's glob loader)
    # use this; pure-IR consumers ignore it.
    workdir: Optional[Path] = None

    @property
    def has_structure(self) -> bool:
        return bool(self.blocks)


__all__ = ["ParsedDocument", "ParserError"]
