"""Structural contract every document-parsing engine implements.

Parsing is deliberately kept OFF the ``RAGPipeline`` protocol
(``services/rag/pipelines/base.py``): it is an upstream, shared, *optional*
stage. An engine turns bytes/path into a :class:`~deeptutor.services.parsing.types.ParsedDocument`
and declares its availability + model readiness so the UI can gate local model
downloads (default: no silent multi-GB pull).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional, Protocol, runtime_checkable

from .signature import ParserSignature


@dataclass(frozen=True)
class ReadinessReport:
    """Whether an engine can run a parse right now."""

    ready: bool
    # Machine code: "ready" | "models_missing" | "cli_missing" | "not_configured"
    reason: str = "ready"
    # User-facing guidance shown when not ready (which escape hatch to take).
    message: str = ""


@runtime_checkable
class Parser(Protocol):
    """A document-parsing engine: ``source_path`` in → ``ParsedDocument`` out.

    Concrete engines also expose a ``classmethod is_available() -> bool`` (probed
    by the factory before instantiation); it is intentionally not part of the
    instance Protocol.
    """

    name: str
    # True when the engine downloads/needs local model weights (MinerU local,
    # Docling). text-only, markitdown, and cloud backends are False.
    needs_local_models: bool

    def resolve_config(self) -> Any:
        """Load this engine's effective config slice from runtime settings."""
        ...

    def supported_formats(self) -> frozenset[str]:
        """Lower-case file suffixes (including the dot) this engine can parse."""
        ...

    def signature(self, config: Any) -> ParserSignature:
        """Stable identity of ``(engine, version, output-affecting config)``."""
        ...

    def is_ready(self, config: Any) -> ReadinessReport:
        """Whether a parse can run now (models present / cloud configured)."""
        ...

    def parse(
        self,
        source_path: Path,
        workdir: Path,
        *,
        config: Any,
        on_output: Optional[Callable[[str], None]] = None,
    ) -> None:
        """Write canonical artifacts for ``source_path`` into ``workdir``.

        Engines emit ``<stem>.md`` (always) and may add
        ``<stem>_content_list.json`` and an ``images/`` dir. The caller
        (``ParseService``) assembles the :class:`ParsedDocument` from the
        workdir via :func:`deeptutor.services.parsing.cache.load_ir` and writes
        the cache manifest. Raises :class:`ParserError` on failure.
        """
        ...


__all__ = ["Parser", "ReadinessReport"]
