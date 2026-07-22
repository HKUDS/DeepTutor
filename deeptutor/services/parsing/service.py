"""ParseService — the public entry to the document-parse bridge.

Resolves the active (or requested) engine, computes the content-addressed cache
key, returns a cached :class:`ParsedDocument` on hit, and on miss runs the
engine behind the model-download readiness gate, then caches and returns the IR.
Consumption is pull-based: callers ask for a parse when they need structured
content; nothing is parsed implicitly.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional

from deeptutor.services.config.runtime_settings import (
    _DEFAULT_DOCUMENT_PARSING_ENGINE,
    load_document_parsing_settings,
)

from . import cache
from .engines.factory import get_parser
from .types import ParsedDocument, ParserError

logger = logging.getLogger(__name__)


class ParseService:
    """Cache-aware, engine-pluggable document parsing."""

    def __init__(self, cache_root: Optional[Path] = None) -> None:
        self._cache_root_override = Path(cache_root) if cache_root else None

    def _cache_root(self) -> Path:
        if self._cache_root_override is not None:
            return self._cache_root_override
        # Resolve lazily per call so the cache root tracks the active
        # user/workspace (multi-user safety), like get_path_service().
        from deeptutor.services.path_service import get_path_service

        return get_path_service().get_parse_cache_root()

    def active_engine(self) -> str:
        return str(
            load_document_parsing_settings().get("engine") or _DEFAULT_DOCUMENT_PARSING_ENGINE
        )

    def parse(
        self,
        source_path: str | Path,
        *,
        engine: Optional[str] = None,
        on_output: Optional[Callable[[str], None]] = None,
    ) -> ParsedDocument:
        """Parse ``source_path`` with the active (or requested) engine.

        Returns a cached result when one exists for the same bytes + engine
        signature. Raises :class:`ParserError` when the engine is not ready
        (e.g. local models not downloaded and auto-download disabled) or the
        file type is unsupported.
        """
        source_path = Path(source_path)
        if not source_path.is_file():
            raise ParserError(f"File to parse not found: {source_path}")

        engine_name = (engine or self.active_engine()).strip().lower()
        parser = get_parser(engine_name)
        config = parser.resolve_config()

        suffix = source_path.suffix.lower()
        supported = parser.supported_formats()
        if supported and suffix not in supported:
            raise ParserError(
                f"The '{engine_name}' parsing engine doesn't support {suffix or 'this'} "
                f"files. Choose a different engine in Settings → Document Parsing."
            )

        sig = parser.signature(config).hash()
        source_hash = cache.source_hash_from_path(source_path)
        cache_root = self._cache_root()

        hit = cache.lookup(cache_root, source_hash, sig)
        if hit is not None:
            logger.info("Parse cache hit for %s (%s/%s)", source_path.name, engine_name, sig)
            markdown, blocks, asset_dir = cache.load_ir(hit)
            return ParsedDocument(
                markdown=markdown,
                blocks=blocks,
                asset_dir=asset_dir,
                source_hash=source_hash,
                parser_signature=sig,
                engine=engine_name,
                workdir=hit,
            )

        report = parser.is_ready(config)
        if not report.ready:
            raise ParserError(report.message or f"The '{engine_name}' engine is not ready.")

        workdir = cache.reserve(cache_root, source_hash, sig)
        logger.info("Parsing %s with %s (signature %s)", source_path.name, engine_name, sig)
        try:
            parser.parse(source_path, workdir, config=config, on_output=on_output)
            markdown, blocks, asset_dir = cache.load_ir(workdir)
            if not markdown and not blocks:
                raise ParserError(
                    f"The '{engine_name}' engine produced no content for {source_path.name}."
                )
            cache.write_manifest(
                workdir,
                {
                    "engine": engine_name,
                    "signature": sig,
                    "source_hash": source_hash,
                    "source_name": source_path.name,
                },
            )
            return ParsedDocument(
                markdown=markdown,
                blocks=blocks,
                asset_dir=asset_dir,
                source_hash=source_hash,
                parser_signature=sig,
                engine=engine_name,
                workdir=workdir,
            )
        except Exception:
            cache.cleanup_failed(workdir)
            raise


_service: Optional[ParseService] = None


def get_parse_service() -> ParseService:
    """Return the process-wide :class:`ParseService` singleton."""
    global _service
    if _service is None:
        _service = ParseService()
    return _service


__all__ = ["ParseService", "get_parse_service"]
