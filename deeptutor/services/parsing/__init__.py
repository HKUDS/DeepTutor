"""Shared, engine-pluggable document-parsing layer (the "bridge").

Sits between input material and its consumers (question extraction, RAG
indexing, future LightRAG): one canonical IR (:class:`ParsedDocument`), one
content-addressed cache, a registry of pluggable engines (text-only, MinerU,
Docling, markitdown). Parsing is upstream of and independent from retrieval.

``ParseService`` / ``get_parse_service`` are the public entry; they are imported
lazily here to keep this package importable before the service module lands and
to avoid pulling engine deps at import time.
"""

from __future__ import annotations

from .base import Parser, ReadinessReport
from .signature import ParserSignature
from .types import ParsedDocument, ParserError


def get_parse_service():
    """Return the process-wide :class:`ParseService` singleton."""
    from .service import get_parse_service as _get

    return _get()


__all__ = [
    "ParsedDocument",
    "ParserError",
    "Parser",
    "ReadinessReport",
    "ParserSignature",
    "get_parse_service",
]
