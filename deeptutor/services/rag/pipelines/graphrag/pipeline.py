"""GraphRAG-backed RAG pipeline orchestration.

Implements the same contract as :class:`LlamaIndexPipeline` (see
``..base.RAGPipeline``) but delegates indexing and retrieval to a local
microsoft/graphrag project. Each KB owns a self-contained GraphRAG project under
its ``version-N`` directory (see ``storage``); documents are parsed to text by
DeepTutor first (see ``ingestion``) so GraphRAG only ever sees ``.txt`` input.

GraphRAG is an optional dependency: every method fails with a clear, actionable
message when it is not installed instead of an opaque ``ImportError``.
"""

from __future__ import annotations

import logging
from pathlib import Path
import shutil
import traceback
from typing import Any, Dict, List, Optional

from deeptutor.runtime.home import get_runtime_data_root
from deeptutor.services.rag.index_versioning import (
    resolve_storage_dir_for_read,
    resolve_storage_dir_for_rebuild,
)
from deeptutor.services.rag.kb_paths import resolve_kb_dir

from . import config as gr_config
from . import ingestion, storage

logger = logging.getLogger(__name__)

DEFAULT_KB_BASE_DIR = str(get_runtime_data_root() / "knowledge_bases")


class GraphRagPipeline:
    """Index/retrieve KB content via a local microsoft/graphrag project."""

    def __init__(self, kb_base_dir: Optional[str] = None, **_: Any) -> None:
        self.logger = logging.getLogger(__name__)
        self.kb_base_dir = kb_base_dir or DEFAULT_KB_BASE_DIR

    # ----- helpers --------------------------------------------------------

    def _ensure_available(self) -> None:
        if not gr_config.is_graphrag_available():
            raise gr_config.GraphRagNotAvailableError(
                "GraphRAG is not installed. Install it with "
                "`pip install 'deeptutor[graphrag]'` to use GraphRAG knowledge bases."
            )

    def _resolve_mode(self, kb_name: str, kwargs: dict[str, Any]) -> str:
        from ..modes import resolve_kb_mode

        return resolve_kb_mode(
            self.kb_base_dir,
            kb_name,
            storage.PROVIDER,
            explicit=kwargs.get("mode"),
            supported=gr_config.SUPPORTED_MODES,
            default=gr_config.DEFAULT_MODE,
        )

    def _cleanup_failed_version_dir(self, root_dir: Path) -> None:
        try:
            if root_dir.is_dir() and not (root_dir / storage.META_FILENAME).exists():
                shutil.rmtree(root_dir)
        except Exception as exc:  # pragma: no cover - best-effort
            self.logger.warning("Could not clean up failed version dir %s: %s", root_dir, exc)

    # ----- indexing -------------------------------------------------------

    async def initialize(self, kb_name: str, file_paths: List[str], **kwargs) -> bool:
        self._ensure_available()
        kb_dir = resolve_kb_dir(self.kb_base_dir, kb_name)
        root_dir = resolve_storage_dir_for_rebuild(kb_dir, None)
        self.logger.info(
            "Initializing KB '%s' with %d file(s) using GraphRAG", kb_name, len(file_paths)
        )
        try:
            gr_config.write_settings(root_dir)
            count = await ingestion.prepare_input(file_paths, root_dir)
            if count == 0:
                self.logger.error("GraphRAG: no extractable documents for '%s'", kb_name)
                self._cleanup_failed_version_dir(root_dir)
                return False
            await self._build(root_dir, is_update=False)
            storage.write_meta(root_dir)
            self.logger.info("KB '%s' initialized with GraphRAG (%d docs)", kb_name, count)
            return True
        except Exception as exc:
            self.logger.error("Failed to initialize GraphRAG KB: %s", exc)
            self.logger.error(traceback.format_exc())
            self._cleanup_failed_version_dir(root_dir)
            raise

    async def add_documents(self, kb_name: str, file_paths: List[str], **kwargs) -> bool:
        self._ensure_available()
        kb_dir = resolve_kb_dir(self.kb_base_dir, kb_name)
        existing = resolve_storage_dir_for_read(kb_dir, None)
        is_update = existing is not None and storage.has_output(existing)
        root_dir = (
            existing if existing is not None else resolve_storage_dir_for_rebuild(kb_dir, None)
        )

        self.logger.info(
            "Adding %d document(s) to GraphRAG KB '%s' (update=%s)",
            len(file_paths),
            kb_name,
            is_update,
        )
        try:
            # Refresh settings so a changed model/endpoint is picked up.
            gr_config.write_settings(root_dir)
            count = await ingestion.prepare_input(file_paths, root_dir)
            if count == 0:
                self.logger.warning("GraphRAG: no extractable documents to add for '%s'", kb_name)
                return False
            await self._build(root_dir, is_update=is_update)
            storage.write_meta(root_dir)
            self.logger.info("Added %d doc(s) to GraphRAG KB '%s'", count, kb_name)
            return True
        except Exception as exc:
            self.logger.error("Failed to add documents to GraphRAG KB: %s", exc)
            self.logger.error(traceback.format_exc())
            if not is_update:
                self._cleanup_failed_version_dir(root_dir)
            raise

    async def _build(self, root_dir: Path, *, is_update: bool) -> None:
        from . import engine

        await engine.build(root_dir, is_update=is_update)

    # ----- retrieval ------------------------------------------------------

    async def search(self, query: str, kb_name: str, **kwargs) -> Dict[str, Any]:
        kb_dir = resolve_kb_dir(self.kb_base_dir, kb_name)
        root_dir = resolve_storage_dir_for_read(kb_dir, None)

        if root_dir is None or not storage.has_output(root_dir):
            return {
                "query": query,
                "answer": (
                    "This GraphRAG knowledge base has no index yet. Add documents before querying."
                ),
                "content": "",
                "sources": [],
                "provider": storage.PROVIDER,
                "needs_reindex": True,
            }

        mode = self._resolve_mode(kb_name, kwargs)
        try:
            self._ensure_available()
            from . import engine

            response, context_data = await engine.search(root_dir, query, mode)
        except gr_config.GraphRagNotAvailableError as exc:
            return self._error_result(query, exc, error_type="not_configured")
        except Exception as exc:
            self.logger.error("GraphRAG search failed: %s", exc)
            self.logger.error(traceback.format_exc())
            return self._error_result(query, exc, error_type="retrieval_error")

        return {
            "query": query,
            "answer": response,
            "content": response,
            "sources": _context_to_sources(context_data),
            "provider": storage.PROVIDER,
            "mode": mode,
        }

    def _error_result(self, query: str, exc: Exception, *, error_type: str) -> Dict[str, Any]:
        return {
            "query": query,
            "answer": str(exc),
            "content": "",
            "sources": [],
            "provider": storage.PROVIDER,
            "error_type": error_type,
        }

    # ----- lifecycle ------------------------------------------------------

    async def delete(self, kb_name: str, **kwargs) -> bool:
        kb_dir = resolve_kb_dir(self.kb_base_dir, kb_name)
        if kb_dir.exists():
            shutil.rmtree(kb_dir)
            self.logger.info("Deleted GraphRAG KB '%s'", kb_name)
            return True
        return False


def _context_to_sources(context_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Map GraphRAG context records into DeepTutor's source-citation shape."""
    sources: list[dict[str, Any]] = []
    if not isinstance(context_data, dict):
        return sources
    # ``sources`` are the text units; ``reports`` are community summaries. Prefer
    # the most concrete provenance available.
    for key in ("sources", "reports", "entities"):
        records = context_data.get(key)
        if not isinstance(records, list):
            continue
        for rec in records:
            if not isinstance(rec, dict):
                continue
            text = str(rec.get("text") or rec.get("content") or rec.get("description") or "")
            sources.append(
                {
                    "title": str(rec.get("title") or rec.get("name") or f"GraphRAG {key}"),
                    "content": text[:200],
                    "source": str(rec.get("source") or ""),
                    "page": "",
                    "chunk_id": str(rec.get("id") or ""),
                    "score": rec.get("rank") or rec.get("score") or "",
                }
            )
        if sources:
            break
    return sources


__all__ = ["GraphRagPipeline"]
