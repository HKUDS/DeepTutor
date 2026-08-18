"""PageIndex Cloud and OSS knowledge-base lifecycle orchestration.

Implements the same contract as :class:`LlamaIndexPipeline` (see
``..base.RAGPipeline``) but delegates document lifecycle to the PageIndex SDK.
Answering is intentionally unavailable through ``search()``: PageIndex
knowledge bases are read inside an agent loop with their provider tools.
"""

from __future__ import annotations

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
from .client import PageIndexClient
from .config import get_pageindex_config

logger = logging.getLogger(__name__)

DEFAULT_KB_BASE_DIR = str(get_runtime_data_root() / "knowledge_bases")

# Mirrors what PageIndex ``POST /doc/`` accepts (ZIP is handled upstream as a
# container: members are extracted and validated individually). Other formats
# are rejected upstream and skipped defensively here.
SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".md",
    ".markdown",
    ".txt",
    ".docx",
    ".doc",
    ".pptx",
    ".ppt",
    ".xlsx",
    ".xls",
    ".csv",
}
OSS_SUPPORTED_EXTENSIONS = {".pdf"}


def is_supported_file(path: str | Path, provider: str = storage.CLOUD_PROVIDER) -> bool:
    extensions = (
        OSS_SUPPORTED_EXTENSIONS if provider == storage.OSS_PROVIDER else SUPPORTED_EXTENSIONS
    )
    return Path(path).suffix.lower() in extensions


class PageIndexPipeline:
    """Manage one PageIndex provider while preserving DeepTutor's RAG contract."""

    def __init__(
        self,
        kb_base_dir: Optional[str] = None,
        *,
        client: Optional[PageIndexClient] = None,
        config_provider=None,
        provider: str = storage.CLOUD_PROVIDER,
    ) -> None:
        self.logger = logging.getLogger(__name__)
        self.kb_base_dir = kb_base_dir or DEFAULT_KB_BASE_DIR
        self._client = client
        self._config_provider = config_provider or get_pageindex_config
        self.provider = (
            storage.OSS_PROVIDER if provider == storage.OSS_PROVIDER else storage.CLOUD_PROVIDER
        )

    def _get_client(self, storage_dir: Path | None = None) -> PageIndexClient:
        if self._client is not None:
            return self._client
        if self.provider == storage.OSS_PROVIDER:
            if storage_dir is None:
                raise RuntimeError("PageIndex OSS requires a resolved Local Library path")
            return PageIndexClient.local(storage.sdk_storage_path(storage_dir))
        return PageIndexClient.cloud(self._config_provider())

    def _processing_mode(self, kb_name: str) -> str | None:
        if self.provider != storage.OSS_PROVIDER:
            return None
        try:
            from deeptutor.services.config.knowledge_base_config import KnowledgeBaseConfigService

            mode = (
                str(
                    KnowledgeBaseConfigService.get_instance(
                        Path(self.kb_base_dir) / "kb_config.json"
                    )
                    .get_kb_config(kb_name)
                    .get("pageindex_mode")
                    or ""
                )
                .strip()
                .lower()
            )
        except Exception:
            mode = ""
        return mode if mode in {"flash", "standard"} else None

    # ----- indexing -------------------------------------------------------

    async def initialize(self, kb_name: str, file_paths: List[str], **kwargs) -> bool:
        progress_callback = kwargs.get("progress_callback")
        kb_dir = resolve_kb_dir(self.kb_base_dir, kb_name)
        storage_dir = resolve_storage_dir_for_rebuild(kb_dir, None)
        self.logger.info(
            "Initializing KB '%s' with %d file(s) using PageIndex", kb_name, len(file_paths)
        )
        try:
            manifest = storage._empty_manifest(self.provider)
            count = await self._ingest(
                file_paths,
                manifest,
                progress_callback,
                storage_dir=storage_dir,
                mode=self._processing_mode(kb_name),
            )
            if count == 0:
                self.logger.error("PageIndex: no supported documents to index for '%s'", kb_name)
                self._cleanup_failed_version_dir(storage_dir)
                return False
            storage.write_manifest(storage_dir, manifest)
            storage.write_meta(storage_dir, provider=self.provider)
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
            manifest = storage.read_manifest(existing, provider=self.provider)
        else:
            storage_dir = resolve_storage_dir_for_rebuild(kb_dir, None)
            manifest = storage._empty_manifest(self.provider)

        self.logger.info("Adding %d document(s) to PageIndex KB '%s'", len(file_paths), kb_name)
        try:
            count = await self._ingest(
                file_paths,
                manifest,
                progress_callback,
                storage_dir=storage_dir,
                mode=self._processing_mode(kb_name),
            )
            if count == 0:
                self.logger.warning("PageIndex: no supported documents to add for '%s'", kb_name)
                return False
            storage_dir.mkdir(parents=True, exist_ok=True)
            storage.write_manifest(storage_dir, manifest)
            storage.write_meta(storage_dir, provider=self.provider)
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
        *,
        storage_dir: Path,
        mode: str | None,
    ) -> int:
        supported = [fp for fp in file_paths if is_supported_file(fp, self.provider)]
        skipped = [fp for fp in file_paths if not is_supported_file(fp, self.provider)]
        for fp in skipped:
            self.logger.warning("PageIndex skips unsupported file type: %s", Path(fp).name)
        if not supported:
            return 0

        client = self._get_client(storage_dir)
        total = len(supported)
        for idx, fp in enumerate(supported, 1):
            path = Path(fp)
            self.logger.info("PageIndex: submitting %s (%d/%d)", path.name, idx, total)
            doc_id = await client.submit_document(path, mode=mode)
            size = path.stat().st_size if path.exists() else None
            storage.upsert_doc(manifest, path.name, doc_id, size=size)
            if progress_callback:
                progress_callback(idx, total)
        return total

    # ----- retrieval ------------------------------------------------------

    async def search(self, query: str, kb_name: str, **_kwargs) -> Dict[str, Any]:
        """Fail closed: PageIndex answering must happen inside an agent loop."""
        message = (
            "PageIndex uses Reasoning as Retrieval. Read this knowledge base with "
            "its PageIndex tools inside an agent loop instead of calling rag search."
        )
        return {
            "query": query,
            "answer": message,
            "content": "",
            "sources": [],
            "provider": self.provider,
            "error_type": "reasoning_as_retrieval_required",
        }

    def document_map(self, kb_name: str) -> dict[str, str]:
        """file name -> cloud doc_id for the KB's current manifest.

        Used by the chat layer to inject the doc list into the system prompt.
        """
        kb_dir = resolve_kb_dir(self.kb_base_dir, kb_name)
        manifest = storage.read_manifest(
            resolve_storage_dir_for_read(kb_dir, None), provider=self.provider
        )
        return {
            name: str(entry["doc_id"])
            for name, entry in storage.doc_entries(manifest).items()
            if isinstance(entry, dict) and entry.get("doc_id")
        }

    # ----- lifecycle ------------------------------------------------------

    async def delete(self, kb_name: str, **_kwargs) -> bool:
        import shutil

        kb_dir = resolve_kb_dir(self.kb_base_dir, kb_name)
        # Preserve the existing Cloud behavior. OSS data is already inside kb_dir.
        if self.provider == storage.CLOUD_PROVIDER:
            try:
                storage_dir = resolve_storage_dir_for_read(kb_dir, None)
                ids = storage.doc_ids(storage.read_manifest(storage_dir, provider=self.provider))
                if ids:
                    client = self._get_client(storage_dir)
                    for doc_id in ids:
                        await client.delete_document(doc_id)
            except Exception as exc:  # pragma: no cover - best-effort
                self.logger.warning("PageIndex cloud cleanup skipped for '%s': %s", kb_name, exc)

        if kb_dir.exists():
            shutil.rmtree(kb_dir)
            self.logger.info("Deleted PageIndex KB '%s'", kb_name)
            return True
        return False

    async def remove_document(self, kb_name: str, file_name: str) -> bool:
        """Delete one indexed document and update the active manifest."""
        kb_dir = resolve_kb_dir(self.kb_base_dir, kb_name)
        storage_dir = resolve_storage_dir_for_read(kb_dir, None)
        if storage_dir is None:
            return False
        manifest = storage.read_manifest(storage_dir, provider=self.provider)
        docs = storage.doc_entries(manifest)
        key = file_name if file_name in docs else Path(file_name).name
        entry = docs.get(key)
        if not isinstance(entry, dict) or not entry.get("doc_id"):
            return False
        client = (
            PageIndexClient.local_read(storage.sdk_storage_path(storage_dir))
            if self.provider == storage.OSS_PROVIDER and self._client is None
            else self._get_client(storage_dir)
        )
        await client.delete_document(str(entry["doc_id"]))
        storage.remove_doc(manifest, key)
        storage.write_manifest(storage_dir, manifest)
        storage.write_meta(storage_dir, provider=self.provider)
        return True

    def sdk_client_for_read(self, kb_name: str) -> Any:
        """Return the SDK client bound to this KB's active Local Library."""
        kb_dir = resolve_kb_dir(self.kb_base_dir, kb_name)
        storage_dir = resolve_storage_dir_for_read(kb_dir, None)
        if storage_dir is None:
            raise RuntimeError(f"PageIndex knowledge base '{kb_name}' has no ready index")
        if self.provider == storage.OSS_PROVIDER and self._client is None:
            return PageIndexClient.local_read(storage.sdk_storage_path(storage_dir)).sdk_client
        return self._get_client(storage_dir).sdk_client

    def _cleanup_failed_version_dir(self, storage_dir: Path) -> None:
        try:
            if storage_dir.is_dir() and not (storage_dir / storage.META_FILENAME).exists():
                import shutil

                shutil.rmtree(storage_dir)
        except Exception as exc:  # pragma: no cover - best-effort
            self.logger.warning("Could not clean up failed version dir %s: %s", storage_dir, exc)


__all__ = [
    "OSS_SUPPORTED_EXTENSIONS",
    "PageIndexPipeline",
    "SUPPORTED_EXTENSIONS",
    "is_supported_file",
]
