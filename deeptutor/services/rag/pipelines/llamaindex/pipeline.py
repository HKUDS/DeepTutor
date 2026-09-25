"""LlamaIndex-backed RAG pipeline orchestration."""

from __future__ import annotations

import asyncio
from contextvars import copy_context
import json
import logging
from pathlib import Path
import threading
import time
import traceback
from typing import Any, Callable, Dict, List, Optional

from deeptutor.runtime.home import get_runtime_data_root
from deeptutor.services.embedding import get_embedding_config
from deeptutor.services.rag.embedding_signature import signature_from_embedding_config
from deeptutor.services.rag.index_versioning import (
    EmbeddingSignature,
    resolve_storage_dir_for_read,
    resolve_storage_dir_for_rebuild,
    write_version_meta,
)
from deeptutor.services.rag.kb_paths import resolve_kb_dir

from . import storage
from .config import default_top_k, should_show_progress
from .document_loader import LlamaIndexDocumentLoader
from .embedding_adapter import (
    configure_llamaindex_settings,
    set_progress_callback,
    verify_embedding_connectivity,
)
from .errors import search_error_result

DEFAULT_KB_BASE_DIR = str(get_runtime_data_root() / "knowledge_bases")

# How long an indexing step may run without reporting any progress before it
# is treated as stalled (see _run_with_stall_guard).
_INDEX_STALL_TIMEOUT_SECONDS = 600.0
# How often the stall guard checks the progress heartbeat.
_INDEX_STALL_POLL_SECONDS = 5.0
_INDEX_WORKERS: dict[str, threading.Event] = {}
_INDEX_WORKERS_LOCK = threading.Lock()

SignatureProvider = Callable[[], EmbeddingSignature | None]


class IndexingStallError(RuntimeError):
    """Raised when an indexing operation makes no progress for too long."""


def _worker_busy_error() -> IndexingStallError:
    return IndexingStallError(
        "A previous indexing worker for this knowledge base is still running. "
        "Wait for it to finish or restart DeepTutor before retrying."
    )


def _ensure_index_worker_available(key: str) -> None:
    with _INDEX_WORKERS_LOCK:
        marker = _INDEX_WORKERS.get(key)
        if marker is not None and not marker.is_set():
            raise _worker_busy_error()


def _claim_index_worker(key: str | None) -> threading.Event | None:
    if key is None:
        return None
    with _INDEX_WORKERS_LOCK:
        previous = _INDEX_WORKERS.get(key)
        if previous is not None and not previous.is_set():
            raise _worker_busy_error()
        marker = threading.Event()
        _INDEX_WORKERS[key] = marker
        return marker


def _release_index_worker(key: str | None, marker: threading.Event | None) -> None:
    if key is None or marker is None:
        return
    marker.set()
    with _INDEX_WORKERS_LOCK:
        if _INDEX_WORKERS.get(key) is marker:
            _INDEX_WORKERS.pop(key, None)


async def _run_with_stall_guard(
    fn: Callable[[], Any],
    *,
    progress_callback: Optional[Callable[..., Any]] = None,
    stall_timeout: Optional[float] = None,
    worker_key: str | None = None,
) -> Any:
    """Run a synchronous indexing step in the executor, failing if it stalls.

    Indexing steps (chunking + embedding) run in a worker thread via
    ``run_in_executor``. A provider that accepts a request but never
    completes it (e.g. a blackholed keep-alive connection) can block that
    thread indefinitely: per-request HTTP timeouts only bound a single
    attempt, and provider retries extend the wait far beyond any reasonable
    budget. Instead of hanging forever, watch the embedding progress
    heartbeat and fail with a clear error once no progress has been reported
    for ``stall_timeout`` seconds.

    The sync function keeps running in its thread after a stall is raised —
    Python cannot interrupt arbitrary synchronous code. Its callback becomes
    silent and a same-KB retry is rejected until that thread actually exits.
    """
    if stall_timeout is None:
        stall_timeout = _INDEX_STALL_TIMEOUT_SECONDS

    worker_marker = _claim_index_worker(worker_key)
    progress_live = threading.Event()
    progress_live.set()
    last_progress = {"at": time.monotonic()}

    def _heartbeat(*args: Any, **kwargs: Any) -> None:
        if not progress_live.is_set():
            return
        last_progress["at"] = time.monotonic()
        if progress_callback is not None:
            progress_callback(*args, **kwargs)

    def _work() -> Any:
        try:
            return fn()
        finally:
            _release_index_worker(worker_key, worker_marker)

    set_progress_callback(_heartbeat)
    try:
        future = asyncio.get_running_loop().run_in_executor(None, copy_context().run, _work)
    except BaseException:
        progress_live.clear()
        _release_index_worker(worker_key, worker_marker)
        raise

    def _consume_terminal_exception(fut: "asyncio.Future[Any]") -> None:
        # The stalled thread may finish after we raise; retrieve its exception
        # so it is not reported as "exception was never retrieved".
        if not fut.cancelled():
            fut.exception()

    try:
        while True:
            done, _ = await asyncio.wait({future}, timeout=_INDEX_STALL_POLL_SECONDS)
            if done:
                return future.result()
            stalled_for = time.monotonic() - last_progress["at"]
            if stalled_for > stall_timeout:
                raise IndexingStallError(
                    f"Indexing made no progress for {stalled_for:.0f}s while "
                    "embedding documents. Check the embedding endpoint; wait "
                    "for the worker to finish or restart DeepTutor before retrying."
                )
    finally:
        progress_live.clear()
        if not future.done():
            future.add_done_callback(_consume_terminal_exception)


class LlamaIndexPipeline:
    """Pipeline that indexes and retrieves KB content via LlamaIndex."""

    def __init__(
        self,
        kb_base_dir: Optional[str] = None,
        *,
        signature_provider: SignatureProvider | None = None,
        document_loader: LlamaIndexDocumentLoader | None = None,
    ):
        self.logger = logging.getLogger(__name__)
        self.kb_base_dir = kb_base_dir or DEFAULT_KB_BASE_DIR
        self._signature_provider = signature_provider or signature_from_embedding_config
        self.document_loader = document_loader or LlamaIndexDocumentLoader(self.logger)

    def _configure_settings(self) -> None:
        configure_llamaindex_settings(self.logger)

    async def _verify_embedding_connectivity(self) -> None:
        await verify_embedding_connectivity(self.logger)

    def _current_signature(self) -> EmbeddingSignature | None:
        return self._signature_provider()

    def _cleanup_failed_version_dir(self, storage_dir: Path, signature: Optional[Any]) -> None:
        _ = signature
        try:
            if storage.cleanup_failed_version_dir(storage_dir):
                self.logger.info(
                    f"Removed empty version dir after failed pipeline run: {storage_dir}"
                )
        except Exception as cleanup_exc:  # pragma: no cover - best-effort
            self.logger.warning(
                f"Could not clean up failed version dir for {storage_dir}: {cleanup_exc}"
            )

    async def initialize(self, kb_name: str, file_paths: List[str], **kwargs) -> bool:
        progress_callback = kwargs.get("progress_callback")
        image_progress_callback = kwargs.get("image_progress_callback")
        kb_dir = resolve_kb_dir(self.kb_base_dir, kb_name)
        _ensure_index_worker_available(str(kb_dir.resolve()))
        self._configure_settings()

        self.logger.info(
            f"Initializing KB '{kb_name}' with {len(file_paths)} files using LlamaIndex"
        )

        signature = self._current_signature()
        storage_dir = resolve_storage_dir_for_rebuild(kb_dir, signature)

        try:
            await self._verify_embedding_connectivity()
            documents = await self.document_loader.load(
                file_paths, image_progress_callback=image_progress_callback
            )
            if not documents:
                self.logger.error("No valid documents found")
                return False

            self.logger.info(
                f"Creating VectorStoreIndex with {len(documents)} documents "
                f"(chunking + embedding)..."
            )

            await _run_with_stall_guard(
                lambda: storage.create_index(
                    documents, storage_dir, show_progress=should_show_progress()
                ),
                progress_callback=progress_callback,
                worker_key=str(kb_dir.resolve()),
            )

            self.logger.info(f"Index persisted to {storage_dir}")
            if signature is not None:
                write_version_meta(kb_dir, signature, storage_dir=storage_dir)

            indexed_file_callback = kwargs.get("indexed_file_callback")
            if indexed_file_callback is not None:
                indexed_paths: set[str] = set()
                for document in documents:
                    metadata = getattr(document, "metadata", None)
                    if isinstance(metadata, dict):
                        path = metadata.get("file_path")
                        if isinstance(path, str) and path:
                            indexed_paths.add(path)
                indexed_file_callback(sorted(indexed_paths))

            self.logger.info(f"KB '{kb_name}' initialized successfully with LlamaIndex")
            return True

        except Exception as exc:
            self.logger.error(f"Failed to initialize KB: {exc}")
            self.logger.error(traceback.format_exc())
            # A timed-out executor can still be writing to this directory.
            if not isinstance(exc, IndexingStallError):
                self._cleanup_failed_version_dir(storage_dir, signature)
            raise
        finally:
            set_progress_callback(None)

    async def search(
        self,
        query: str,
        kb_name: str,
        **kwargs,
    ) -> Dict[str, Any]:
        kwargs.pop("mode", None)
        self._configure_settings()
        self.logger.info(f"Searching KB '{kb_name}' with query: {query[:50]}...")

        kb_dir = resolve_kb_dir(self.kb_base_dir, kb_name)
        signature = self._current_signature()
        storage_dir = resolve_storage_dir_for_read(kb_dir, signature)

        if storage_dir is None or not (storage_dir / "docstore.json").exists():
            self.logger.warning(
                f"No matching index found for KB '{kb_name}' at signature "
                f"{signature.hash() if signature else 'n/a'}"
            )
            return {
                "query": query,
                "answer": (
                    "This knowledge base has no index for its selected embedding "
                    "model. Re-index it (or switch back to a previously-used "
                    "embedding model) before querying."
                ),
                "content": "",
                "provider": "llamaindex",
                "needs_reindex": True,
            }

        embedding_mismatch_warning = self._embedding_mismatch_warning(kb_name)

        try:
            loop = asyncio.get_running_loop()
            top_k = kwargs.get("top_k") or default_top_k()
            nodes = await loop.run_in_executor(
                None,
                copy_context().run,
                lambda: storage.retrieve_nodes(storage_dir, query, top_k=top_k),
            )

            result = self._nodes_to_result(query, nodes)
            if embedding_mismatch_warning:
                result["warning"] = embedding_mismatch_warning
            return result

        except Exception as exc:
            result = search_error_result(query, exc)
            if result.get("error_type"):
                log_message = result.get("log_message") or str(exc)
                self.logger.warning(f"Search failed ({result['error_type']}): {log_message}")
            else:
                self.logger.error(f"Search failed: {exc}")
                self.logger.error(traceback.format_exc())
            return result

    def _embedding_mismatch_warning(self, kb_name: str) -> str:
        try:
            cfg_path = Path(self.kb_base_dir) / "kb_config.json"
            if not cfg_path.exists():
                return ""
            with open(cfg_path, encoding="utf-8") as handle:
                kb_entry = json.load(handle).get("knowledge_bases", {}).get(kb_name, {})
            if not kb_entry.get("embedding_mismatch"):
                return ""
            stored = kb_entry.get("embedding_model", "unknown")
            current = get_embedding_config().model
            warning = (
                f"Warning: KB '{kb_name}' was indexed with '{stored}' "
                f"but current model is '{current}'. Re-index recommended."
            )
            self.logger.warning(warning)
            return warning
        except Exception:
            return ""

    def _nodes_to_result(self, query: str, nodes: list[Any]) -> Dict[str, Any]:
        context_parts: list[str] = []
        sources: list[dict[str, Any]] = []
        for i, node in enumerate(nodes):
            context_parts.append(node.node.text)
            meta = node.node.metadata or {}
            sources.append(
                {
                    "title": meta.get("file_name", meta.get("title", f"Document {i + 1}")),
                    "content": node.node.text[:200],
                    "source": meta.get("file_path", meta.get("file_name", "")),
                    "page": meta.get("page_label", meta.get("page", "")),
                    "chunk_id": node.node.node_id or str(i),
                    "score": round(node.score, 4) if node.score is not None else "",
                }
            )

        content = "\n\n".join(context_parts) if context_parts else ""
        return {
            "query": query,
            "answer": content,
            "content": content,
            "sources": sources,
            "provider": "llamaindex",
        }

    async def add_documents(self, kb_name: str, file_paths: List[str], **kwargs) -> bool:
        progress_callback = kwargs.get("progress_callback")
        image_progress_callback = kwargs.get("image_progress_callback")
        kb_dir = resolve_kb_dir(self.kb_base_dir, kb_name)
        _ensure_index_worker_available(str(kb_dir.resolve()))
        self._configure_settings()

        self.logger.info(f"Adding {len(file_paths)} documents to KB '{kb_name}' using LlamaIndex")

        signature = self._current_signature()
        plan = storage.resolve_add_storage_plan(kb_dir, signature)

        try:
            await self._verify_embedding_connectivity()

            documents = await self.document_loader.load(
                file_paths, image_progress_callback=image_progress_callback
            )
            if not documents:
                self.logger.warning("No valid documents to add")
                return False

            if plan.existing_storage is not None:
                self.logger.info(f"Loading existing index from {plan.existing_storage}...")
                num_added = await _run_with_stall_guard(
                    lambda: storage.insert_documents(
                        plan.existing_storage, plan.storage_dir, documents
                    ),
                    progress_callback=progress_callback,
                    worker_key=str(kb_dir.resolve()),
                )
                self.logger.info(f"Added {num_added} documents to existing index")
                if signature is not None and plan.storage_dir != plan.existing_storage:
                    write_version_meta(kb_dir, signature, storage_dir=plan.storage_dir)
            else:
                self.logger.info(f"Creating new index with {len(documents)} documents...")
                plan.storage_dir.mkdir(parents=True, exist_ok=True)
                num_added = await _run_with_stall_guard(
                    lambda: storage.create_index(
                        documents, plan.storage_dir, show_progress=should_show_progress()
                    ),
                    progress_callback=progress_callback,
                    worker_key=str(kb_dir.resolve()),
                )
                self.logger.info(f"Created new index with {num_added} documents")
                if signature is not None:
                    write_version_meta(kb_dir, signature, storage_dir=plan.storage_dir)

            self.logger.info(f"Successfully added documents to KB '{kb_name}'")
            return True

        except Exception as exc:
            self.logger.error(f"Failed to add documents: {exc}")
            self.logger.error(traceback.format_exc())
            if not isinstance(exc, IndexingStallError) and (
                plan.existing_storage is None or plan.storage_dir != plan.existing_storage
            ):
                self._cleanup_failed_version_dir(plan.storage_dir, signature)
            raise
        finally:
            set_progress_callback(None)

    async def delete(self, kb_name: str) -> bool:
        kb_dir = resolve_kb_dir(self.kb_base_dir, kb_name)
        deleted = storage.delete_kb_dir(kb_dir)
        if deleted:
            self.logger.info(f"Deleted KB '{kb_name}'")
        return deleted
