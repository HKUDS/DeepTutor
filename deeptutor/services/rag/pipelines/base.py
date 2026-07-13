"""Structural contract every RAG pipeline implements.

The RAG service and factory have always relied on duck typing across pipelines
(``initialize`` / ``add_documents`` / ``search`` / ``delete``). This Protocol
makes that contract explicit so a new engine — e.g. the PageIndex cloud
pipeline — can be type-checked against the same shape the LlamaIndex pipeline
already satisfies. It is intentionally minimal: ``RAGService`` still probes for
optional methods with ``hasattr`` to stay tolerant of partial implementations.
"""

from __future__ import annotations

from typing import Any, Dict, List, Protocol, runtime_checkable


@runtime_checkable
class RAGPipeline(Protocol):
    """A knowledge-base index/retrieve engine bound to a KB by its provider."""

    async def initialize(self, kb_name: str, file_paths: List[str], **kwargs: Any) -> bool:
        """Build a fresh index for ``kb_name`` from ``file_paths``."""
        ...

    async def add_documents(self, kb_name: str, file_paths: List[str], **kwargs: Any) -> bool:
        """Incrementally add ``file_paths`` to ``kb_name``'s existing index."""
        ...

    async def search(self, query: str, kb_name: str, **kwargs: Any) -> Dict[str, Any]:
        """Retrieve grounded context for ``query`` from ``kb_name``.

        Returns a dict with at least ``query``, ``content``/``answer``,
        ``sources`` and ``provider`` keys.
        """
        ...

    async def delete(self, kb_name: str, **kwargs: Any) -> bool:
        """Delete ``kb_name`` and any engine-side resources."""
        ...


__all__ = ["RAGPipeline"]
