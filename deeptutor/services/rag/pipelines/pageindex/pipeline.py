"""PageIndex cloud-backed RAG pipeline orchestration.

Implements the same contract as :class:`LlamaIndexPipeline` (see
``..base.RAGPipeline``) but delegates indexing and retrieval to the hosted
PageIndex service. Documents are uploaded for tree building; retrieval is
doc-scoped and reasoning-based (no embeddings). DeepTutor's own chat LLM still
writes the final answer from the returned context.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
import traceback
from typing import Any, Dict, List, Optional

from deeptutor.runtime.home import get_runtime_data_root
from deeptutor.services.rag.index_versioning import (
    resolve_storage_dir_for_read,
    resolve_storage_dir_for_rebuild,
)
from deeptutor.services.rag.kb_paths import resolve_kb_dir

from . import storage
from .client import PageIndexAPIError, PageIndexClient
from .config import get_pageindex_config

logger = logging.getLogger(__name__)

DEFAULT_KB_BASE_DIR = str(get_runtime_data_root() / "knowledge_bases")

# PageIndex ingests PDFs and Markdown; other formats are rejected upstream and
# skipped defensively here.
SUPPORTED_EXTENSIONS = {".pdf", ".md", ".markdown"}


def is_supported_file(path: str | Path) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_EXTENSIONS


class PageIndexPipeline:
    """Index/retrieve KB content via the hosted PageIndex service."""

    def __init__(
        self,
        kb_base_dir: Optional[str] = None,
        *,
        client: Optional[PageIndexClient] = None,
        config_provider=None,
    ) -> None:
        self.logger = logging.getLogger(__name__)
        self.kb_base_dir = kb_base_dir or DEFAULT_KB_BASE_DIR
        self._client = client
        self._config_provider = config_provider or get_pageindex_config

    def _get_client(self) -> PageIndexClient:
        if self._client is not None:
            return self._client
        return PageIndexClient(self._config_provider())

    # ----- indexing -------------------------------------------------------

    async def initialize(self, kb_name: str, file_paths: List[str], **kwargs) -> bool:
        progress_callback = kwargs.get("progress_callback")
        kb_dir = resolve_kb_dir(self.kb_base_dir, kb_name)
        storage_dir = resolve_storage_dir_for_rebuild(kb_dir, None)
        self.logger.info(
            "Initializing KB '%s' with %d file(s) using PageIndex", kb_name, len(file_paths)
        )
        try:
            manifest = storage._empty_manifest()
            count = await self._ingest(file_paths, manifest, progress_callback)
            if count == 0:
                self.logger.error("PageIndex: no supported documents to index for '%s'", kb_name)
                self._cleanup_failed_version_dir(storage_dir)
                return False
            storage.write_manifest(storage_dir, manifest)
            storage.write_meta(storage_dir)
            self.logger.info("KB '%s' initialized with PageIndex (%d docs)", kb_name, count)
            return True
        except Exception as exc:
            self.logger.error("Failed to initialize PageIndex KB: %s", exc)
            self.logger.error(traceback.format_exc())
            self._cleanup_failed_version_dir(storage_dir)
            raise

    async def add_documents(self, kb_name: str, file_paths: List[str], **kwargs) -> bool:
        progress_callback = kwargs.get("progress_callback")
        kb_dir = resolve_kb_dir(self.kb_base_dir, kb_name)
        existing = resolve_storage_dir_for_read(kb_dir, None)
        if existing is not None:
            storage_dir = existing
            manifest = storage.read_manifest(existing)
        else:
            storage_dir = resolve_storage_dir_for_rebuild(kb_dir, None)
            manifest = storage._empty_manifest()

        self.logger.info("Adding %d document(s) to PageIndex KB '%s'", len(file_paths), kb_name)
        try:
            count = await self._ingest(file_paths, manifest, progress_callback)
            if count == 0:
                self.logger.warning("PageIndex: no supported documents to add for '%s'", kb_name)
                return False
            storage_dir.mkdir(parents=True, exist_ok=True)
            storage.write_manifest(storage_dir, manifest)
            storage.write_meta(storage_dir)
            self.logger.info("Added %d doc(s) to PageIndex KB '%s'", count, kb_name)
            return True
        except Exception as exc:
            self.logger.error("Failed to add documents to PageIndex KB: %s", exc)
            self.logger.error(traceback.format_exc())
            raise

    async def _ingest(
        self,
        file_paths: List[str],
        manifest: dict[str, Any],
        progress_callback,
    ) -> int:
        supported = [fp for fp in file_paths if is_supported_file(fp)]
        skipped = [fp for fp in file_paths if not is_supported_file(fp)]
        for fp in skipped:
            self.logger.warning(
                "PageIndex skips unsupported file (PDF/Markdown only): %s", Path(fp).name
            )
        if not supported:
            return 0

        client = self._get_client()
        total = len(supported)
        for idx, fp in enumerate(supported, 1):
            path = Path(fp)
            self.logger.info("PageIndex: submitting %s (%d/%d)", path.name, idx, total)
            doc_id = await client.submit_document(path)
            await client.wait_until_ready(doc_id)
            size = path.stat().st_size if path.exists() else None
            storage.upsert_doc(manifest, path.name, doc_id, size=size)
            if progress_callback:
                progress_callback(idx, total)
        return total

    # ----- retrieval ------------------------------------------------------

    async def search(self, query: str, kb_name: str, **kwargs) -> Dict[str, Any]:
        kwargs.pop("mode", None)
        top_k = int(kwargs.get("top_k", 5) or 5)
        kb_dir = resolve_kb_dir(self.kb_base_dir, kb_name)
        storage_dir = resolve_storage_dir_for_read(kb_dir, None)
        manifest = storage.read_manifest(storage_dir)
        ids = storage.doc_ids(manifest)

        if storage_dir is None or not ids:
            return {
                "query": query,
                "answer": (
                    "This PageIndex knowledge base has no indexed documents yet. "
                    "Add documents before querying."
                ),
                "content": "",
                "sources": [],
                "provider": storage.PROVIDER,
                "needs_reindex": True,
            }

        # doc_id -> file_name for provenance labelling.
        id_to_name = {
            str(entry["doc_id"]): name
            for name, entry in storage.doc_entries(manifest).items()
            if isinstance(entry, dict) and entry.get("doc_id")
        }

        client = self._get_client()
        try:
            results = await asyncio.gather(
                *(client.retrieve(doc_id, query) for doc_id in ids),
                return_exceptions=True,
            )
        except Exception as exc:  # pragma: no cover - gather itself rarely raises
            return self._error_result(query, exc)

        sources: list[dict[str, Any]] = []
        context_parts: list[str] = []
        errors: list[str] = []
        for doc_id, result in zip(ids, results):
            if isinstance(result, Exception):
                errors.append(str(result))
                self.logger.warning("PageIndex retrieval failed for %s: %s", doc_id, result)
                continue
            doc_name = id_to_name.get(doc_id, doc_id)
            for node in result[:top_k]:
                text, source = self._node_to_source(doc_name, node)
                if text:
                    context_parts.append(text)
                sources.append(source)

        if not sources and errors:
            return self._error_result(query, PageIndexAPIError("; ".join(errors[:3])))

        content = "\n\n".join(context_parts)
        return {
            "query": query,
            "answer": content,
            "content": content,
            "sources": sources,
            "provider": storage.PROVIDER,
        }

    @staticmethod
    def _node_to_source(doc_name: str, node: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        if not isinstance(node, dict):
            text = str(node)
            return text, {
                "title": doc_name,
                "content": text[:200],
                "source": doc_name,
                "page": "",
                "chunk_id": "",
                "score": "",
            }
        title = node.get("title") or doc_name
        texts: list[str] = []
        pages: list[Any] = []
        for chunk in node.get("relevant_contents") or []:
            if isinstance(chunk, dict):
                piece = chunk.get("content") or chunk.get("text") or ""
                if piece:
                    texts.append(str(piece))
                if chunk.get("page_index") is not None:
                    pages.append(chunk.get("page_index"))
            elif chunk:
                texts.append(str(chunk))
        text = "\n".join(texts) or str(node.get("text") or node.get("content") or "")
        page = pages[0] if pages else node.get("page_index", "")
        source = {
            "title": title,
            "content": text[:200],
            "source": doc_name,
            "page": page if page is not None else "",
            "chunk_id": node.get("node_id") or "",
            "score": node.get("score", ""),
        }
        return text, source

    def _error_result(self, query: str, exc: Exception) -> Dict[str, Any]:
        from deeptutor.services.rag.pipelines.pageindex.config import (
            PageIndexNotConfiguredError,
        )

        needs_config = isinstance(exc, PageIndexNotConfiguredError)
        return {
            "query": query,
            "answer": str(exc),
            "content": "",
            "sources": [],
            "provider": storage.PROVIDER,
            "error_type": "not_configured" if needs_config else "retrieval_error",
        }

    # ----- lifecycle ------------------------------------------------------

    async def delete(self, kb_name: str, **kwargs) -> bool:
        import shutil

        kb_dir = resolve_kb_dir(self.kb_base_dir, kb_name)
        # Best-effort: drop hosted documents so they don't linger on the account.
        try:
            storage_dir = resolve_storage_dir_for_read(kb_dir, None)
            ids = storage.doc_ids(storage.read_manifest(storage_dir))
            if ids:
                client = self._get_client()
                await asyncio.gather(
                    *(client.delete_document(doc_id) for doc_id in ids),
                    return_exceptions=True,
                )
        except Exception as exc:  # pragma: no cover - best-effort
            self.logger.warning("PageIndex cloud cleanup skipped for '%s': %s", kb_name, exc)

        if kb_dir.exists():
            shutil.rmtree(kb_dir)
            self.logger.info("Deleted PageIndex KB '%s'", kb_name)
            return True
        return False

    def _cleanup_failed_version_dir(self, storage_dir: Path) -> None:
        try:
            if storage_dir.is_dir() and not any(
                child.name != storage.META_FILENAME for child in storage_dir.iterdir()
            ):
                import shutil

                shutil.rmtree(storage_dir)
        except Exception as exc:  # pragma: no cover - best-effort
            self.logger.warning("Could not clean up failed version dir %s: %s", storage_dir, exc)


__all__ = ["PageIndexPipeline", "is_supported_file", "SUPPORTED_EXTENSIONS"]
