"""PageIndex cloud-backed RAG pipeline orchestration.

Implements the same contract as :class:`LlamaIndexPipeline` (see
``..base.RAGPipeline``) but delegates indexing to the hosted PageIndex
service (tree building, no embeddings). PageIndex's REST retrieval endpoint
is deprecated: deep retrieval is agentic — the chat agent reads documents
through the PageIndex MCP server — while ``search()`` serves programmatic
callers with each document's real tree outline (titles / pages / summaries)
fetched over REST.
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
from .client import PageIndexClient
from .config import PageIndexNotConfiguredError, get_pageindex_config

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
            self.logger.warning("PageIndex skips unsupported file type: %s", Path(fp).name)
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

    # ponytail: flat per-doc cap on the formatted outline; per-consumer
    # budgets if a real need shows up.
    TREE_CHARS_PER_DOC = 6000

    async def search(self, query: str, kb_name: str, **_kwargs) -> Dict[str, Any]:
        """Return each document's tree outline (titles / pages / summaries).

        The deprecated REST retrieval endpoint is gone; deep, query-driven
        retrieval is agentic via the PageIndex MCP tools in chat. For
        programmatic callers this returns the documents' real structure as
        context — shallow but honest grounding.
        """
        docs = self.document_map(kb_name)

        if not docs:
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

        try:
            client = self._get_client()
            results = await asyncio.gather(
                *(client.get_document(doc_id, summary=True) for doc_id in docs.values()),
                return_exceptions=True,
            )
        except PageIndexNotConfiguredError as exc:
            return {
                "query": query,
                "answer": str(exc),
                "content": "",
                "sources": [],
                "provider": storage.PROVIDER,
                "error_type": "not_configured",
            }

        parts: list[str] = []
        sources: list[dict[str, Any]] = []
        errors: list[str] = []
        for (file_name, doc_id), result in zip(docs.items(), results):
            if isinstance(result, BaseException):
                errors.append(str(result))
                self.logger.warning("PageIndex tree fetch failed for %s: %s", doc_id, result)
                continue
            outline, doc_sources = self._format_tree(file_name, doc_id, result.get("result"))
            if outline:
                parts.append(f"## {file_name}\n{outline}")
            sources.extend(doc_sources)

        if not parts and errors:
            return {
                "query": query,
                "answer": "; ".join(errors[:3]),
                "content": "",
                "sources": [],
                "provider": storage.PROVIDER,
                "error_type": "retrieval_error",
            }

        content = "\n\n".join(parts)
        return {
            "query": query,
            "answer": content,
            "content": content,
            "sources": sources,
            "provider": storage.PROVIDER,
        }

    @classmethod
    def _format_tree(
        cls, file_name: str, doc_id: str, tree: Any
    ) -> tuple[str, list[dict[str, Any]]]:
        """Render a PageIndex tree as an indented outline + per-section sources."""
        lines: list[str] = []
        sources: list[dict[str, Any]] = []

        def walk(node: Any, depth: int) -> None:
            if isinstance(node, list):
                for item in node:
                    walk(item, depth)
                return
            if not isinstance(node, dict):
                return
            title = str(node.get("title") or "").strip()
            page = node.get("page_index")
            summary = str(node.get("summary") or node.get("prefix_summary") or "").strip()
            if title:
                line = f"{'  ' * depth}- {title}"
                if page not in (None, ""):
                    line += f" (p.{page})"
                if summary:
                    line += f": {summary}"
                lines.append(line)
                if depth == 0:
                    sources.append(
                        {
                            "title": title,
                            "content": summary[:200],
                            "source": file_name,
                            "page": page if page is not None else "",
                            "chunk_id": node.get("node_id") or doc_id,
                            "score": "",
                        }
                    )
            walk(node.get("nodes") or [], depth + 1)

        walk(tree, 0)
        text = "\n".join(lines)
        if len(text) > cls.TREE_CHARS_PER_DOC:
            text = text[: cls.TREE_CHARS_PER_DOC] + "\n… (outline truncated)"
        return text, sources

    def document_map(self, kb_name: str) -> dict[str, str]:
        """file name -> cloud doc_id for the KB's current manifest.

        Used by the chat layer to inject the doc list into the system prompt.
        """
        kb_dir = resolve_kb_dir(self.kb_base_dir, kb_name)
        manifest = storage.read_manifest(resolve_storage_dir_for_read(kb_dir, None))
        return {
            name: str(entry["doc_id"])
            for name, entry in storage.doc_entries(manifest).items()
            if isinstance(entry, dict) and entry.get("doc_id")
        }

    # ----- lifecycle ------------------------------------------------------

    async def delete(self, kb_name: str, **_kwargs) -> bool:
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
