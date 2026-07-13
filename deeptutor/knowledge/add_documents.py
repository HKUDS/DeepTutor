#!/usr/bin/env python
"""Incrementally add documents to an existing knowledge base."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import logging
from pathlib import Path
import shutil
from typing import List, Optional

from deeptutor.services.config import resolve_llm_runtime_config
from deeptutor.services.rag.factory import (
    DEFAULT_PROVIDER,
    has_ready_provider_index,
    normalize_provider_name,
)
from deeptutor.services.rag.file_routing import FileTypeRouter
from deeptutor.services.rag.provider_binding import resolve_bound_provider
from deeptutor.services.rag.service import RAGService

logger = logging.getLogger(__name__)

DEFAULT_BASE_DIR = "./data/knowledge_bases"


@dataclass(frozen=True)
class DocumentIndexFailure:
    """One file that could not be added to the provider index."""

    file_path: Path
    error: str


@dataclass(frozen=True)
class DocumentIndexResult:
    """Structured incremental-index result.

    A task can no longer infer success from "no exception": every staged file is
    explicitly accounted for as either processed or failed.
    """

    processed_files: list[Path]
    failures: list[DocumentIndexFailure]

    @property
    def processed_count(self) -> int:
        return len(self.processed_files)

    @property
    def failed_count(self) -> int:
        return len(self.failures)

    @property
    def has_failures(self) -> bool:
        return bool(self.failures)

    def failure_summary(self, *, limit: int = 3) -> str:
        if not self.failures:
            return ""
        shown = [f"{failure.file_path.name}: {failure.error}" for failure in self.failures[:limit]]
        remaining = len(self.failures) - len(shown)
        if remaining > 0:
            shown.append(f"... and {remaining} more file(s)")
        return "; ".join(shown)


@dataclass(frozen=True)
class RawDocumentRemoval:
    """Outcome of removing one raw document from a knowledge base."""

    rel_path: str
    was_indexed: bool


def _read_metadata(metadata_file: Path) -> dict:
    """Load a KB's metadata.json, returning {} when absent or unreadable."""
    if not metadata_file.exists():
        return {}
    try:
        with open(metadata_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _write_metadata(metadata_file: Path, metadata: dict) -> None:
    """Persist a KB's metadata.json (pretty-printed, non-ASCII preserved)."""
    with open(metadata_file, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)


def _raw_hash_key(file_path: Path, raw_dir: Path) -> str:
    """Stable ``file_hashes`` key for a staged file.

    The key is the POSIX path relative to ``raw/`` (so folder uploads keep
    distinct entries), falling back to the basename for anything that resolves
    outside ``raw/``. Indexing and removal MUST share this rule, otherwise a
    removed file's hash record would leak and silently skip a later re-add.
    """
    try:
        return file_path.resolve().relative_to(raw_dir.resolve()).as_posix()
    except ValueError:
        return file_path.name


def remove_raw_document(kb_dir: Path, file_path: Path) -> RawDocumentRemoval:
    """Delete one staged raw file and drop its indexed-hash record.

    Deliberately decoupled from :class:`DocumentAdder` (whose constructor
    requires a ready provider index): a KB stuck in an *error* state often has
    no index at all, yet its raw/ files must still be removable so the user can
    drop an unparseable document instead of deleting and rebuilding the whole
    KB. Vectors are not touched here — the providers index whole KBs, so any
    vectors from an already-indexed file are cleared by a subsequent re-index,
    which the returned ``was_indexed`` flag lets the caller surface.

    ``file_path`` must already be sandbox-resolved under the KB's raw/ dir.
    """
    raw_dir = kb_dir / "raw"
    hash_key = _raw_hash_key(file_path, raw_dir)

    target = file_path.resolve()
    if target.exists():
        target.unlink()

    metadata_file = kb_dir / "metadata.json"
    metadata = _read_metadata(metadata_file)
    hashes = metadata.get("file_hashes")
    was_indexed = isinstance(hashes, dict) and hash_key in hashes
    if was_indexed:
        del hashes[hash_key]
        _write_metadata(metadata_file, metadata)

    return RawDocumentRemoval(rel_path=hash_key, was_indexed=was_indexed)


class DocumentAdder:
    """Stage and index new files through a KB's bound RAG provider."""

    def __init__(
        self,
        kb_name: str,
        base_dir: str = DEFAULT_BASE_DIR,
        api_key: str | None = None,
        base_url: str | None = None,
        progress_tracker=None,
        rag_provider: str | None = None,
    ):
        self.kb_name = kb_name
        self.base_dir = Path(base_dir)
        self.kb_dir = self.base_dir / kb_name

        if not self.kb_dir.exists():
            raise ValueError(f"Knowledge base does not exist: {kb_name}")

        self.raw_dir = self.kb_dir / "raw"
        self.llamaindex_storage_dir = self.kb_dir / "llamaindex_storage"
        self.legacy_rag_storage_dir = self.kb_dir / "rag_storage"
        self.metadata_file = self.kb_dir / "metadata.json"

        # Incremental adds must use the engine DeepTutor has bound to this KB. An
        # explicit rag_provider (from the API, already matched against the KB)
        # wins; otherwise use the shared binding resolver.
        if rag_provider:
            self.rag_provider = normalize_provider_name(rag_provider)
        else:
            self.rag_provider = self._provider_from_binding()

        has_provider_index = has_ready_provider_index(self.kb_dir, self.rag_provider)

        if (
            self.rag_provider == DEFAULT_PROVIDER
            and not has_provider_index
            and self.legacy_rag_storage_dir.exists()
        ):
            raise ValueError(
                f"Knowledge base '{kb_name}' uses legacy index format and requires reindex before incremental add"
            )

        if not has_provider_index:
            raise ValueError(f"Knowledge base not initialized ({self.rag_provider}): {kb_name}")

        self.api_key = api_key
        self.base_url = base_url
        self.progress_tracker = progress_tracker

        self.raw_dir.mkdir(parents=True, exist_ok=True)

    def _provider_from_binding(self) -> str:
        return resolve_bound_provider(self.base_dir, self.kb_name)

    def _get_file_hash(self, file_path: Path) -> str:
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(65536), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def get_ingested_hashes(self) -> dict[str, str]:
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return data.get("file_hashes", {})
            except Exception:
                return {}
        return {}

    def add_documents(self, source_files: List[str], allow_duplicates: bool = False) -> List[Path]:
        """Validate and stage files into raw/ before indexing."""
        logger.info(f"Validating documents for '{self.kb_name}'...")

        ingested_hashes = self.get_ingested_hashes()
        files_to_process: list[Path] = []

        for source in source_files:
            source_path = Path(source)
            if not source_path.exists() or not source_path.is_file():
                logger.warning(f"Missing file: {source}")
                continue

            current_hash = self._get_file_hash(source_path)
            if current_hash in ingested_hashes.values() and not allow_duplicates:
                logger.info(f"Skipped (content already indexed): {source_path.name}")
                continue

            # Files already saved under raw/ (e.g. by the upload route, possibly
            # inside a folder) are indexed in place — never flattened to the
            # basename — so the uploaded folder structure is preserved verbatim.
            if source_path.resolve().is_relative_to(self.raw_dir.resolve()):
                files_to_process.append(source_path)
                continue

            dest_path = self.raw_dir / source_path.name
            if dest_path.exists():
                dest_hash = self._get_file_hash(dest_path)
                if dest_hash == current_hash:
                    logger.info(f"Recovering staged file: {source_path.name}")
                    files_to_process.append(dest_path)
                    continue
                if not allow_duplicates:
                    logger.info(f"Skipped (filename collision): {source_path.name}")
                    continue

            shutil.copy2(source_path, dest_path)
            logger.info(f"Staged to raw: {source_path.name}")
            files_to_process.append(dest_path)

        return files_to_process

    async def process_new_documents(self, new_files: List[Path]) -> DocumentIndexResult:
        """Index staged files via the KB's bound provider."""
        if not new_files:
            return DocumentIndexResult(processed_files=[], failures=[])

        rag_service = RAGService(kb_base_dir=str(self.base_dir), provider=self.rag_provider)
        processed_files: list[Path] = []
        failures: list[DocumentIndexFailure] = []
        total_files = len(new_files)

        for idx, doc_file in enumerate(new_files, 1):
            try:
                if self.progress_tracker is not None:
                    from deeptutor.knowledge.progress_tracker import ProgressStage

                    self.progress_tracker.update(
                        ProgressStage.PROCESSING_FILE,
                        f"Indexing {doc_file.name}",
                        current=idx,
                        total=total_files,
                    )

                success = await rag_service.add_documents(self.kb_name, [str(doc_file)])
                if success:
                    processed_files.append(doc_file)
                    self._record_successful_hash(doc_file)
                    logger.info(f"Processed: {doc_file.name}")
                else:
                    error = "Provider returned failure without details."
                    failures.append(DocumentIndexFailure(doc_file, error))
                    logger.error(f"Failed to index: {doc_file.name}")
            except Exception as e:
                logger.exception(f"Failed {doc_file.name}: {e}")
                failures.append(DocumentIndexFailure(doc_file, str(e)))

        return DocumentIndexResult(processed_files=processed_files, failures=failures)

    def _record_successful_hash(self, file_path: Path) -> None:
        file_hash = self._get_file_hash(file_path)
        metadata = _read_metadata(self.metadata_file)
        hash_key = _raw_hash_key(file_path, self.raw_dir)
        metadata.setdefault("file_hashes", {})[hash_key] = file_hash
        _write_metadata(self.metadata_file, metadata)

    def update_metadata(self, added_count: int) -> None:
        """Update metadata after incremental add."""
        metadata: dict = {}
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, "r", encoding="utf-8") as f:
                    metadata = json.load(f)
            except Exception:
                metadata = {}

        metadata["rag_provider"] = self.rag_provider
        metadata["needs_reindex"] = False
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        metadata["last_updated"] = timestamp
        if added_count > 0:
            metadata["last_indexed_at"] = timestamp
            metadata["last_indexed_count"] = added_count
            metadata["last_indexed_action"] = "upload"

        history = metadata.get("update_history", [])
        history.append(
            {
                "timestamp": metadata["last_updated"],
                "action": "incremental_add",
                "count": added_count,
                "provider": self.rag_provider,
            }
        )
        metadata["update_history"] = history

        with open(self.metadata_file, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)


async def add_documents(
    kb_name: str,
    source_files: list[str],
    base_dir: str = DEFAULT_BASE_DIR,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    allow_duplicates: bool = False,
) -> int:
    """Convenience function used by CLI wrappers."""
    from deeptutor.knowledge.manager import KnowledgeBaseManager

    manager = KnowledgeBaseManager(base_dir=base_dir)
    try:
        manager.update_kb_status(
            name=kb_name,
            status="processing",
            progress={
                "stage": "processing_documents",
                "message": "Processing uploaded documents...",
                "percent": 0,
                "current": 0,
                "total": max(len(source_files), 1),
                "file_name": "",
                "error": None,
                "timestamp": datetime.now().isoformat(),
            },
        )

        adder = DocumentAdder(
            kb_name=kb_name,
            base_dir=base_dir,
            api_key=api_key,
            base_url=base_url,
        )
        new_files = adder.add_documents(source_files, allow_duplicates=allow_duplicates)
        if not new_files:
            manager.update_kb_status(
                name=kb_name,
                status="ready",
                progress={
                    "stage": "completed",
                    "message": "No new unique documents to process.",
                    "percent": 100,
                    "current": 1,
                    "total": 1,
                    "file_name": "",
                    "error": None,
                    "timestamp": datetime.now().isoformat(),
                },
            )
            return 0
        result = await adder.process_new_documents(new_files)
        if result.has_failures:
            raise RuntimeError(
                f"Failed to index {result.failed_count}/{len(new_files)} file(s): "
                f"{result.failure_summary()}"
            )
        adder.update_metadata(result.processed_count)

        manager.update_kb_status(
            name=kb_name,
            status="ready",
            progress={
                "stage": "completed",
                "message": f"Successfully processed {result.processed_count} files!",
                "percent": 100,
                "current": result.processed_count,
                "total": max(len(new_files), 1),
                "file_name": "",
                "error": None,
                "timestamp": datetime.now().isoformat(),
                "indexed_count": result.processed_count,
                "index_changed": result.processed_count > 0,
                "index_action": "upload",
            },
        )
        return result.processed_count
    except Exception as exc:
        manager.update_kb_status(
            name=kb_name,
            status="error",
            progress={
                "stage": "error",
                "message": "Document upload failed",
                "percent": 0,
                "current": 0,
                "total": max(len(source_files), 1),
                "file_name": "",
                "error": str(exc),
                "timestamp": datetime.now().isoformat(),
            },
        )
        raise


async def main() -> None:
    try:
        llm_config = resolve_llm_runtime_config()
        default_api_key = llm_config.api_key
        default_base_url = llm_config.effective_url
    except Exception:
        default_api_key = ""
        default_base_url = ""

    parser = argparse.ArgumentParser(description="Incrementally add documents to a KB")
    parser.add_argument("kb_name", help="KB Name")
    parser.add_argument("--docs", nargs="+", help="Files")
    parser.add_argument("--docs-dir", help="Directory")
    parser.add_argument("--base-dir", default=DEFAULT_BASE_DIR)
    parser.add_argument("--api-key", default=default_api_key)
    parser.add_argument("--base-url", default=default_base_url)
    parser.add_argument("--allow-duplicates", action="store_true")

    args = parser.parse_args()
    doc_files: list[str] = []
    if args.docs:
        doc_files.extend(args.docs)
    if args.docs_dir:
        p = Path(args.docs_dir)
        doc_files.extend(str(f) for f in FileTypeRouter.collect_supported_files(p))

    if not doc_files:
        logger.error("No documents provided.")
        return

    processed_count = await add_documents(
        kb_name=args.kb_name,
        source_files=doc_files,
        base_dir=args.base_dir,
        api_key=args.api_key,
        base_url=args.base_url,
        allow_duplicates=args.allow_duplicates,
    )

    if processed_count:
        logger.info(f"Done! Successfully added {processed_count} documents.")
    else:
        logger.info("No new unique documents to add.")


if __name__ == "__main__":
    asyncio.run(main())
