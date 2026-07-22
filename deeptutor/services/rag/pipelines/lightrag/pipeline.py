"""LightRAG-backed RAG pipeline orchestration.

Implements the same contract as :class:`LlamaIndexPipeline` (see
``..base.RAGPipeline``) but delegates indexing/retrieval to RAG-Anything /
LightRAG. Each KB owns a self-contained LightRAG store under its ``version-N``
directory (see ``storage``).

Documents are turned into a MinerU-style ``content_list`` by DeepTutor's shared
parse layer (``deeptutor/services/parsing``) — the same bridge the question
extractor uses — so multimodal parsing stays a decoupled, cached, engine-
pluggable concern and this pipeline only ever feeds LightRAG ready content.

LightRAG is an optional dependency: every method fails with a clear, actionable
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

from . import config as lr_config
from . import engine, storage

logger = logging.getLogger(__name__)

DEFAULT_KB_BASE_DIR = str(get_runtime_data_root() / "knowledge_bases")


class LightRagPipeline:
    """Index/retrieve KB content via RAG-Anything / LightRAG."""

    def __init__(self, kb_base_dir: Optional[str] = None, **_: Any) -> None:
        self.logger = logging.getLogger(__name__)
        self.kb_base_dir = kb_base_dir or DEFAULT_KB_BASE_DIR

    # ----- helpers --------------------------------------------------------

    def _ensure_available(self) -> None:
        if not lr_config.is_lightrag_available():
            raise lr_config.LightRagNotAvailableError(
                "LightRAG is not installed. Install it with "
                "`pip install 'deeptutor[rag-lightrag]'` to use LightRAG knowledge bases."
            )

    def _resolve_mode(self, kb_name: str, kwargs: dict[str, Any]) -> str:
        from ..modes import resolve_kb_mode

        return resolve_kb_mode(
            self.kb_base_dir,
            kb_name,
            storage.PROVIDER,
            explicit=kwargs.get("mode"),
            supported=lr_config.SUPPORTED_MODES,
            default=lr_config.DEFAULT_MODE,
        )

    def _cleanup_failed_version_dir(self, root_dir: Path) -> None:
        try:
            if root_dir.is_dir() and not (root_dir / storage.META_FILENAME).exists():
                shutil.rmtree(root_dir)
        except Exception as exc:  # pragma: no cover - best-effort
            self.logger.warning("Could not clean up failed version dir %s: %s", root_dir, exc)

    async def _ingest(self, rag: Any, file_paths: List[str]) -> int:
        """Parse each file via the shared parse layer and insert it into LightRAG.

        Returns the number of documents successfully inserted. Per-file failures
        are logged and skipped so one bad document doesn't abort the batch.
        """
        from deeptutor.services.parsing import ParserError, get_parse_service

        parse_service = get_parse_service()
        inserted = 0
        for file_path in file_paths:
            path = Path(file_path)
            try:
                doc = parse_service.parse(path)
            except ParserError as exc:
                self.logger.warning("LightRAG: parse failed for %s: %s", path.name, exc)
                continue

            content_list = doc.blocks or (
                [{"type": "text", "text": doc.markdown, "page_idx": 0}] if doc.markdown else []
            )
            if not content_list:
                self.logger.warning("LightRAG: empty document skipped: %s", path.name)
                continue

            await engine.insert(
                rag,
                content_list,
                file_name=path.name,
                doc_id=doc.source_hash or path.stem,
            )
            doc_error = storage.document_error(Path(rag.working_dir), doc.source_hash or path.stem)
            if doc_error:
                raise RuntimeError(f"{path.name}: {doc_error}")
            inserted += 1
            self.logger.info("LightRAG: inserted %s", path.name)
        return inserted

    # ----- indexing -------------------------------------------------------

    async def initialize(self, kb_name: str, file_paths: List[str], **kwargs) -> bool:
        self._ensure_available()
        kb_dir = resolve_kb_dir(self.kb_base_dir, kb_name)
        root_dir = resolve_storage_dir_for_rebuild(kb_dir, None)
        self.logger.info(
            "Initializing KB '%s' with %d file(s) using LightRAG", kb_name, len(file_paths)
        )
        try:
            rag = engine.build_rag(storage.working_dir(root_dir))
            count = await self._ingest(rag, file_paths)
            if count == 0:
                self.logger.error("LightRAG: no extractable documents for '%s'", kb_name)
                self._cleanup_failed_version_dir(root_dir)
                return False
            if not storage.has_output(root_dir):
                details = storage.failure_summary(root_dir)
                message = f"LightRAG did not produce a ready index for '{kb_name}'"
                if details:
                    message = f"{message}: {details}"
                self.logger.error(message)
                self._cleanup_failed_version_dir(root_dir)
                raise RuntimeError(message)
            storage.write_meta(root_dir)
            self.logger.info("KB '%s' initialized with LightRAG (%d docs)", kb_name, count)
            return True
        except Exception as exc:
            self.logger.error("Failed to initialize LightRAG KB: %s", exc)
            self.logger.error(traceback.format_exc())
            self._cleanup_failed_version_dir(root_dir)
            raise

    async def add_documents(self, kb_name: str, file_paths: List[str], **kwargs) -> bool:
        self._ensure_available()
        kb_dir = resolve_kb_dir(self.kb_base_dir, kb_name)
        existing = resolve_storage_dir_for_read(kb_dir, None)
        is_update = existing is not None and storage.has_output(existing)
        root_dir = existing if is_update else resolve_storage_dir_for_rebuild(kb_dir, None)

        self.logger.info(
            "Adding %d document(s) to LightRAG KB '%s' (update=%s)",
            len(file_paths),
            kb_name,
            is_update,
        )
        try:
            rag = engine.build_rag(storage.working_dir(root_dir))
            count = await self._ingest(rag, file_paths)
            if count == 0:
                self.logger.warning("LightRAG: no extractable documents to add for '%s'", kb_name)
                return False
            if not storage.has_output(root_dir):
                details = storage.failure_summary(root_dir)
                message = f"LightRAG did not produce a ready index for '{kb_name}'"
                if details:
                    message = f"{message}: {details}"
                self.logger.error(message)
                if not is_update:
                    self._cleanup_failed_version_dir(root_dir)
                raise RuntimeError(message)
            storage.write_meta(root_dir)
            self.logger.info("Added %d doc(s) to LightRAG KB '%s'", count, kb_name)
            return True
        except Exception as exc:
            self.logger.error("Failed to add documents to LightRAG KB: %s", exc)
            self.logger.error(traceback.format_exc())
            if not is_update:
                self._cleanup_failed_version_dir(root_dir)
            raise

    # ----- retrieval ------------------------------------------------------

    async def search(self, query: str, kb_name: str, **kwargs) -> Dict[str, Any]:
        kb_dir = resolve_kb_dir(self.kb_base_dir, kb_name)
        root_dir = resolve_storage_dir_for_read(kb_dir, None)

        if root_dir is None or not storage.has_output(root_dir):
            return {
                "query": query,
                "answer": (
                    "This LightRAG knowledge base has no index yet. Add documents before querying."
                ),
                "content": "",
                "sources": [],
                "provider": storage.PROVIDER,
                "needs_reindex": True,
            }

        mode = self._resolve_mode(kb_name, kwargs)
        try:
            self._ensure_available()
            rag = engine.build_rag(storage.working_dir(root_dir))
            answer = await engine.query(rag, query, mode)
        except lr_config.LightRagNotAvailableError as exc:
            return self._error_result(query, exc, error_type="not_configured")
        except Exception as exc:
            self.logger.error("LightRAG search failed: %s", exc)
            self.logger.error(traceback.format_exc())
            return self._error_result(query, exc, error_type="retrieval_error")

        return {
            "query": query,
            "answer": answer,
            "content": answer,
            "sources": [],
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
            self.logger.info("Deleted LightRAG KB '%s'", kb_name)
            return True
        return False


__all__ = ["LightRagPipeline"]
