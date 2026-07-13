"""
Knowledge Base API Router
=========================

Handles knowledge base CRUD operations, file uploads, and initialization.
"""

import asyncio
from datetime import datetime
import json
import logging
import mimetypes
import os
from pathlib import Path
import re
import shutil
import traceback
from uuid import uuid4

from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Form,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel

from deeptutor.api.utils.progress_broadcaster import ProgressBroadcaster
from deeptutor.api.utils.task_id_manager import TaskIDManager
from deeptutor.api.utils.task_log_stream import capture_task_logs, get_task_stream_manager
from deeptutor.knowledge.add_documents import DocumentAdder, remove_raw_document
from deeptutor.knowledge.initializer import KnowledgeBaseInitializer
from deeptutor.knowledge.kb_types import is_connected_kb
from deeptutor.knowledge.manager import KnowledgeBaseManager
from deeptutor.knowledge.naming import validate_knowledge_base_name
from deeptutor.knowledge.progress_tracker import ProgressStage, ProgressTracker
from deeptutor.multi_user.context import get_current_user
from deeptutor.multi_user.knowledge_access import (
    assert_writable,
    current_kb_base_dir,
    current_kb_manager,
    manager_for_resource,
    resolve_kb,
)
from deeptutor.multi_user.knowledge_access import (
    list_visible_knowledge_bases as list_visible_kb_access,
)
from deeptutor.services.config import PROJECT_ROOT, load_config_with_main
from deeptutor.services.rag.factory import (
    DEFAULT_PROVIDER,
    GRAPHRAG_PROVIDER,
    LIGHTRAG_PROVIDER,
    PAGEINDEX_PROVIDER,
    normalize_provider_name,
    provider_uses_embedding_versions,
)
from deeptutor.services.rag.file_routing import FileTypeRouter
from deeptutor.services.rag.linked_kb import (
    LINKABLE_PROVIDERS,
    assert_path_allowed,
    probe_linked_folder,
)
from deeptutor.utils.document_extractor import (
    MAX_EXTRACTED_CHARS_PER_DOC,
    DocumentExtractionError,
    extract_text_from_path,
)
from deeptutor.utils.document_validator import DocumentValidator
from deeptutor.utils.error_utils import format_exception_message

# Initialize logger with config
config = load_config_with_main("main.yaml", PROJECT_ROOT)
log_dir = config.get("paths", {}).get("user_log_dir") or config.get("logging", {}).get("log_dir")
logger = logging.getLogger(__name__)

router = APIRouter()

# Constants for byte conversions
BYTES_PER_GB = 1024**3
BYTES_PER_MB = 1024**2


def format_bytes_human_readable(size_bytes: int) -> str:
    """Format bytes into human-readable string (GB, MB, or bytes)."""
    if size_bytes >= BYTES_PER_GB:
        return f"{size_bytes / BYTES_PER_GB:.1f} GB"
    elif size_bytes >= BYTES_PER_MB:
        return f"{size_bytes / BYTES_PER_MB:.1f} MB"
    else:
        return f"{size_bytes} bytes"


_kb_base_dir = PROJECT_ROOT / "data" / "knowledge_bases"
DEFAULT_KB_ALIASES = {"", "default", "current", "selected", "默认", "默认知识库", "当前知识库"}

# Lazy initialization
kb_manager = None


def get_kb_manager():
    """Get KnowledgeBaseManager instance (lazy init)"""
    if kb_manager is not None:
        return kb_manager
    return current_kb_manager()


def _overridden_kb_manager() -> KnowledgeBaseManager | None:
    """Return the legacy/test manager when the route-level getter is patched.

    Production multi-user access control goes through ``assert_writable`` and
    ``resolve_kb``. Older tests and single-module integrations patch
    ``get_kb_manager`` directly, so we keep that seam without weakening the
    normal write guard.
    """
    manager = get_kb_manager()
    if kb_manager is not None or manager is not current_kb_manager():
        return manager
    return None


def _current_kb_base_dir() -> Path:
    manager = _overridden_kb_manager()
    if manager is not None:
        return Path(manager.base_dir)
    return current_kb_base_dir()


def _writable_kb(kb_name: str) -> tuple[KnowledgeBaseManager, str, Path]:
    manager = _overridden_kb_manager()
    if manager is not None:
        resolved_name = _resolve_registered_kb_name(manager, kb_name)
        return manager, resolved_name, Path(manager.base_dir)
    resource = assert_writable(kb_name)
    return manager_for_resource(resource), resource.name, resource.base_dir


class KnowledgeBaseInfo(BaseModel):
    id: str | None = None
    name: str
    is_default: bool
    statistics: dict
    metadata: dict | None = None
    path: str | None = None
    status: str | None = None
    progress: dict | None = None
    source: str | None = None
    assigned: bool = False
    read_only: bool = False
    provenance_label: str | None = None
    available: bool = True


class LinkFolderRequest(BaseModel):
    """Request model for linking a local folder to a KB."""

    folder_path: str


class LinkedFolderInfo(BaseModel):
    """Response model for linked folder information."""

    id: str
    path: str
    added_at: str
    file_count: int


class SupportedFileTypesInfo(BaseModel):
    """Upload constraints exposed to the web client."""

    extensions: list[str]
    accept: str
    max_file_size_bytes: int


IMAGE_ACCEPT_MIME_TYPES = {
    ".bmp": "image/bmp",
    ".gif": "image/gif",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".webp": "image/webp",
}


def _build_unique_task_id(task_type: str, task_key_prefix: str) -> str:
    task_manager = TaskIDManager.get_instance()
    task_key = f"{task_key_prefix}_{datetime.now().isoformat()}_{uuid4().hex[:8]}"
    return task_manager.generate_task_id(task_type, task_key)


def _save_zip_archive(
    file: UploadFile,
    sanitized_filename: str,
    target_dir: Path,
    allowed_extensions: set[str] | None,
) -> list[Path]:
    """Safely expand an uploaded ``.zip`` into ``target_dir``.

    The archive itself is never persisted; each member is validated and
    extracted via :func:`safe_extract_zip` (Zip Slip / zip-bomb / extension
    guards). Returns the list of written file paths.
    """
    import tempfile
    import zipfile

    from deeptutor.utils.archive_extractor import ArchiveTooLargeError, safe_extract_zip

    file.file.seek(0)
    max_size = DocumentValidator.MAX_FILE_SIZE
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            tmp_path = Path(tmp.name)
            written = 0
            for chunk in iter(lambda: file.file.read(8192), b""):
                written += len(chunk)
                if written > max_size:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"Archive '{sanitized_filename}' exceeds maximum size limit of "
                            f"{format_bytes_human_readable(max_size)}"
                        ),
                    )
                tmp.write(chunk)

        try:
            result = safe_extract_zip(
                tmp_path, target_dir, allowed_extensions=allowed_extensions or set()
            )
        except ArchiveTooLargeError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Rejected archive '{sanitized_filename}': {exc}",
            ) from exc
        except zipfile.BadZipFile as exc:
            raise HTTPException(
                status_code=400,
                detail=f"'{sanitized_filename}' is not a valid zip archive.",
            ) from exc

        if not result.extracted:
            raise HTTPException(
                status_code=400,
                detail=f"Archive '{sanitized_filename}' contained no supported files.",
            )
        return result.extracted
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


# Folder organization is purely a human-facing layout: folders are real
# subdirectories under ``raw/`` (no manifest, no retrieval effect). These
# helpers keep user-supplied relative paths safe before they touch the FS.
_BAD_PATH_CHARS = re.compile(r'[\\:*?"<>|\x00-\x1f]')


def _sanitize_path_segment(segment: str) -> str:
    """Sanitize a single folder/file path segment for safe FS use."""
    cleaned = _BAD_PATH_CHARS.sub("", segment).strip().strip(".")
    return cleaned[:128]


def _sanitize_rel_subdir(rel_path: str | None) -> str:
    """Return a safe POSIX relative subdir (folders only, no traversal).

    A leading/trailing or interior ``..``/absolute marker raises 400 so a
    crafted directory upload can never escape ``raw/``.
    """
    if not rel_path:
        return ""
    parts: list[str] = []
    for raw_seg in str(rel_path).replace("\\", "/").split("/"):
        seg = raw_seg.strip()
        if seg in ("", "."):
            continue
        if seg == "..":
            raise HTTPException(status_code=400, detail="Invalid folder path")
        safe = _sanitize_path_segment(seg)
        if safe:
            parts.append(safe)
    return "/".join(parts)


def _safe_join_raw(raw_dir: Path, rel_path: str) -> Path:
    """Resolve ``rel_path`` under ``raw_dir``, rejecting traversal."""
    target = (raw_dir / rel_path).resolve()
    try:
        target.relative_to(raw_dir.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="Access denied") from exc
    return target


def _save_uploaded_files(
    files: list[UploadFile],
    target_dir: Path,
    allowed_extensions: set[str] | None = None,
    kb_name: str | None = None,
    rel_paths: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    """
    Save uploaded files to the local raw/ directory.

    When PocketBase is enabled and ``kb_name`` is supplied, each file is also
    uploaded to the PocketBase knowledge_bases record as a file attachment
    (best-effort — local write is always the primary path).
    """
    uploaded_files: list[str] = []
    uploaded_file_paths: list[str] = []
    written_file_paths: list[Path] = []

    from deeptutor.services.pocketbase_client import is_pocketbase_enabled

    _pb_sync = is_pocketbase_enabled() and bool(kb_name)

    try:
        for idx, file in enumerate(files):
            file_path = None
            original_filename = file.filename or "upload"
            try:
                sanitized_filename = DocumentValidator.validate_upload_safety(
                    original_filename,
                    _get_upload_file_size(file),
                    allowed_extensions=allowed_extensions,
                )
                file.filename = sanitized_filename

                # Directory uploads carry a relative path (folder/sub/file); the
                # folder portion is preserved under raw/ so nested structure is
                # kept verbatim. Single-file uploads have no rel path → root.
                rel = (
                    rel_paths[idx].replace("\\", "/")
                    if rel_paths and idx < len(rel_paths) and rel_paths[idx]
                    else ""
                )
                subdir = _sanitize_rel_subdir(rel.rsplit("/", 1)[0]) if "/" in rel else ""
                dest_dir = target_dir / subdir if subdir else target_dir
                if subdir:
                    dest_dir.mkdir(parents=True, exist_ok=True)
                rel_name = f"{subdir}/{sanitized_filename}" if subdir else sanitized_filename

                if Path(sanitized_filename).suffix.lower() == ".zip":
                    # Expand the archive in place; register each extracted
                    # member instead of the zip itself.
                    for dest in _save_zip_archive(
                        file, sanitized_filename, dest_dir, allowed_extensions
                    ):
                        written_file_paths.append(dest)
                        uploaded_files.append(dest.relative_to(target_dir).as_posix())
                        uploaded_file_paths.append(str(dest))
                        if _pb_sync and kb_name:
                            try:
                                _upload_file_to_pb(kb_name, dest.name, dest)
                            except Exception as pb_exc:
                                logger.debug(
                                    "PocketBase file upload failed for '%s': %s",
                                    dest.name,
                                    pb_exc,
                                )
                    continue

                file_path = dest_dir / sanitized_filename
                max_size = DocumentValidator.MAX_FILE_SIZE
                written_bytes = 0

                file.file.seek(0)
                with open(file_path, "wb") as buffer:
                    for chunk in iter(lambda: file.file.read(8192), b""):
                        written_bytes += len(chunk)
                        if written_bytes > max_size:
                            size_str = format_bytes_human_readable(max_size)
                            raise HTTPException(
                                status_code=400,
                                detail=(
                                    f"File '{sanitized_filename}' exceeds maximum size "
                                    f"limit of {size_str}"
                                ),
                            )
                        buffer.write(chunk)

                DocumentValidator.validate_upload_safety(
                    sanitized_filename, written_bytes, allowed_extensions=allowed_extensions
                )
                written_file_paths.append(file_path)
                uploaded_files.append(rel_name)
                uploaded_file_paths.append(str(file_path))

                # Mirror file to PocketBase when enabled (best-effort, non-blocking).
                if _pb_sync and kb_name:
                    try:
                        _upload_file_to_pb(kb_name, sanitized_filename, file_path)
                    except Exception as pb_exc:
                        logger.debug(
                            "PocketBase file upload failed for '%s': %s",
                            sanitized_filename,
                            pb_exc,
                        )
            except Exception as e:
                if file_path and file_path.exists():
                    try:
                        os.unlink(file_path)
                    except OSError:
                        pass

                error_message = f"Validation failed for file '{original_filename}': {format_exception_message(e)}"
                logger.error(error_message, exc_info=True)
                raise HTTPException(status_code=400, detail=error_message) from e
    except Exception:
        for written_path in written_file_paths:
            if written_path.exists():
                try:
                    os.unlink(written_path)
                except OSError:
                    pass
        raise

    return uploaded_files, uploaded_file_paths


def _get_upload_file_size(file: UploadFile) -> int | None:
    """Best-effort byte size detection without consuming the uploaded stream."""
    try:
        current_position = file.file.tell()
        file.file.seek(0, os.SEEK_END)
        size = file.file.tell()
        file.file.seek(current_position)
        return size
    except Exception:
        return None


def _validate_upload_batch(
    files: list[UploadFile],
    allowed_extensions: set[str] | None = None,
    rel_paths: list[str] | None = None,
) -> list[dict[str, int | str | None]]:
    """Validate upload metadata before mutating KB state or writing any files."""
    validated: list[dict[str, int | str | None]] = []
    seen_names: set[str] = set()

    for idx, file in enumerate(files):
        original_filename = file.filename or "upload"
        size_bytes = _get_upload_file_size(file)
        try:
            sanitized_filename = DocumentValidator.validate_upload_safety(
                original_filename,
                size_bytes,
                allowed_extensions=allowed_extensions,
            )
        except Exception as e:
            error_message = (
                f"Validation failed for file '{original_filename}': {format_exception_message(e)}"
            )
            raise HTTPException(status_code=400, detail=error_message) from e

        rel = (
            rel_paths[idx].replace("\\", "/")
            if rel_paths and idx < len(rel_paths) and rel_paths[idx]
            else ""
        )
        subdir = _sanitize_rel_subdir(rel.rsplit("/", 1)[0]) if "/" in rel else ""
        duplicate_key = f"{subdir}/{sanitized_filename}" if subdir else sanitized_filename

        if duplicate_key in seen_names:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Duplicate filename after sanitization: '{duplicate_key}'. "
                    "Rename one of the files and try again."
                ),
            )

        seen_names.add(duplicate_key)
        validated.append(
            {
                "original_filename": original_filename,
                "sanitized_filename": sanitized_filename,
                "path": duplicate_key,
                "size_bytes": size_bytes,
            }
        )

    return validated


def _upload_file_to_pb(kb_name: str, filename: str, file_path: Path) -> None:
    """Upload a single file to the PocketBase knowledge_bases record."""
    try:
        from deeptutor.services.pocketbase_client import get_pb_client

        pb = get_pb_client()
        records = pb.collection("knowledge_bases").get_full_list(
            query_params={"filter": f'kb_name="{kb_name}"'}
        )
        if not records:
            logger.debug(f"PocketBase KB record not found for '{kb_name}', skipping file upload")
            return
        with open(file_path, "rb") as fh:
            pb.collection("knowledge_bases").update(
                records[0].id,
                body={"kb_name": kb_name},
                files={"raw_files": (filename, fh)},
            )
        logger.debug(f"Uploaded '{filename}' to PocketBase KB '{kb_name}'")
    except Exception as exc:
        logger.debug(f"_upload_file_to_pb failed: {exc}")


def _task_log(task_id: str, message: str, level: str = "info") -> None:
    manager = get_task_stream_manager()
    manager.ensure_task(task_id)
    manager.emit_log(task_id, message)

    log_method = getattr(logger, level, None)
    if callable(log_method):
        log_method(f"[{task_id}] {message}")
    else:
        logger.info(f"[{task_id}] {message}")


def _validate_registered_provider(raw_provider: str | None) -> str:
    """Resolve a requested provider to a known engine.

    Empty / legacy / unknown strings coerce to the default (so a stale config or
    a removed engine never selects a missing pipeline). Returning the real,
    canonical provider is what makes the per-KB lock meaningful: the upload route
    compares the requested provider against the KB's bound provider, so asking to
    add to a ``pageindex`` KB with ``llamaindex`` (or vice versa) is rejected.
    """
    return normalize_provider_name(raw_provider)


def _assert_provider_ready(provider: str) -> None:
    """Block creating/using a KB whose engine isn't ready.

    PageIndex needs an API key; GraphRAG needs the optional package installed.
    """
    if provider == PAGEINDEX_PROVIDER:
        from deeptutor.services.rag.pipelines.pageindex.config import is_pageindex_configured

        if not is_pageindex_configured():
            raise HTTPException(
                status_code=400,
                detail=(
                    "PageIndex API key is not configured. Add it under "
                    "Knowledge → RAG pipeline settings before creating a PageIndex "
                    "knowledge base."
                ),
            )

    if provider == GRAPHRAG_PROVIDER:
        from deeptutor.services.rag.pipelines.graphrag.config import is_graphrag_available

        if not is_graphrag_available():
            raise HTTPException(
                status_code=400,
                detail=(
                    "GraphRAG is not installed. Run "
                    "`pip install 'deeptutor[graphrag]'` on the server before "
                    "creating a GraphRAG knowledge base."
                ),
            )

    if provider == LIGHTRAG_PROVIDER:
        from deeptutor.services.rag.pipelines.lightrag.config import is_lightrag_available

        if not is_lightrag_available():
            raise HTTPException(
                status_code=400,
                detail=(
                    "LightRAG is not installed. Run "
                    "`pip install 'deeptutor[rag-lightrag]'` on the server before "
                    "creating a LightRAG knowledge base."
                ),
            )


def _enforce_provider_formats(provider: str, files: list[UploadFile]) -> None:
    """PageIndex ingests PDF/Markdown only — reject other formats up front."""
    if provider != PAGEINDEX_PROVIDER:
        return
    from deeptutor.services.rag.pipelines.pageindex.pipeline import SUPPORTED_EXTENSIONS

    unsupported = [
        f.filename
        for f in files
        if f.filename
        and not f.filename.lower().endswith(".zip")
        and Path(f.filename).suffix.lower() not in SUPPORTED_EXTENSIONS
    ]
    if unsupported:
        raise HTTPException(
            status_code=400,
            detail=(
                "PageIndex knowledge bases accept PDF and Markdown only. "
                f"Unsupported: {', '.join(unsupported[:5])}."
            ),
        )


def _resolve_registered_kb_name(manager: KnowledgeBaseManager, kb_name: str | None) -> str:
    """Resolve route-level default aliases to the configured default KB."""
    requested = str(kb_name or "").strip()
    kb_names = manager.list_knowledge_bases()
    if requested and requested in kb_names:
        return requested

    if requested.lower() in DEFAULT_KB_ALIASES:
        default_kb = manager.get_default()
        if default_kb and default_kb in kb_names:
            return default_kb
        raise HTTPException(status_code=404, detail="No default knowledge base is configured")

    raise HTTPException(status_code=404, detail=f"Knowledge base '{requested}' not found")


def _load_kb_entry_or_404(manager: KnowledgeBaseManager, kb_name: str) -> dict:
    manager.config = manager._load_config()
    kb_entry = manager.config.get("knowledge_bases", {}).get(kb_name)
    if kb_entry is None:
        raise HTTPException(status_code=404, detail=f"Knowledge base '{kb_name}' not found")
    return kb_entry


def _assert_not_connected_kb(kb_name: str, kb_entry: dict) -> None:
    """Block writes to connected KBs (Obsidian vaults, linked indexes).

    They are read-only pointers to the user's external files — we never write
    into or re-index them.
    """
    if is_connected_kb(kb_entry):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Knowledge base '{kb_name}' is connected to an external folder and is "
                "read-only. Uploads and re-indexing are not available for it."
            ),
        )


def _assert_kb_writable_or_409(kb_name: str, kb_entry: dict) -> None:
    _assert_not_connected_kb(kb_name, kb_entry)
    if bool(kb_entry.get("needs_reindex", False)):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Knowledge base '{kb_name}' uses legacy index format and needs reindex "
                "before accepting incremental uploads."
            ),
        )


def _matching_index_is_valid(kb_name: str, matching_version: dict | None) -> bool:
    """Return whether a matching active index can safely satisfy retrieval."""
    if not matching_version:
        return False
    try:
        from deeptutor.services.rag.index_probe import inspect_provider_version
        from deeptutor.services.rag.pipelines.llamaindex.storage import (
            validate_storage_embeddings,
        )

        probe = inspect_provider_version(matching_version, DEFAULT_PROVIDER)
        if not probe.ready:
            logger.warning(
                "Matching index for KB '%s' is not provider-ready; forcing re-index: %s",
                kb_name,
                probe.failure_summary or probe.diagnostics,
            )
            return False
        validate_storage_embeddings(Path(str(matching_version["storage_path"])))
        return True
    except Exception as exc:
        logger.warning(
            "Matching index for KB '%s' is invalid; forcing re-index: %s",
            kb_name,
            exc,
        )
        return False


async def run_initialization_task(initializer: KnowledgeBaseInitializer, task_id: str):
    """Background task for knowledge base initialization"""
    task_manager = TaskIDManager.get_instance()
    task_stream_manager = get_task_stream_manager()
    task_stream_manager.ensure_task(task_id)

    with capture_task_logs(task_id):
        try:
            if not initializer.progress_tracker:
                initializer.progress_tracker = ProgressTracker(
                    initializer.kb_name, initializer.base_dir
                )

            initializer.progress_tracker.task_id = task_id

            _task_log(task_id, f"Initializing knowledge base '{initializer.kb_name}'")

            await initializer.process_documents()
            _task_log(task_id, "Document processing complete")
            _task_log(task_id, "Finalizing initialization")
            indexed_count = len(
                FileTypeRouter.collect_supported_files(initializer.raw_dir, recursive=True)
            )

            initializer.progress_tracker.update(
                ProgressStage.COMPLETED,
                "Knowledge base initialization complete!",
                current=1,
                total=1,
                indexed_count=indexed_count,
                index_changed=True,
                index_action="create",
            )

            manager = get_kb_manager()
            manager.update_kb_status(
                name=initializer.kb_name,
                status="ready",
                progress={
                    "stage": "completed",
                    "message": "Knowledge base initialization complete!",
                    "percent": 100,
                    "current": 1,
                    "total": 1,
                    "task_id": task_id,
                    "timestamp": datetime.now().isoformat(),
                    "indexed_count": indexed_count,
                    "index_changed": True,
                    "index_action": "create",
                },
            )

            _task_log(
                task_id, f"Knowledge base '{initializer.kb_name}' initialized", level="success"
            )
            task_manager.update_task_status(task_id, "completed")
            task_stream_manager.emit_complete(
                task_id, f"Knowledge base '{initializer.kb_name}' initialization complete"
            )
        except Exception as e:
            import traceback as _tb

            error_msg = str(e)
            trace = _tb.format_exc()

            _task_log(task_id, f"Initialization failed: {error_msg}", level="error")
            _task_log(task_id, f"Stack trace:\n{trace}", level="error")

            task_manager.update_task_status(task_id, "error", error=error_msg)

            manager = get_kb_manager()
            manager.update_kb_status(
                name=initializer.kb_name,
                status="error",
                progress={
                    "stage": "error",
                    "message": f"Initialization failed: {error_msg}",
                    "percent": 0,
                    "error": error_msg,
                    "task_id": task_id,
                    "timestamp": datetime.now().isoformat(),
                },
            )

            if initializer.progress_tracker:
                initializer.progress_tracker.update(
                    ProgressStage.ERROR, f"Initialization failed: {error_msg}", error=error_msg
                )
            task_stream_manager.emit_failed(task_id, error_msg, details=trace)


async def run_upload_processing_task(
    kb_name: str,
    base_dir: str,
    uploaded_file_paths: list[str],
    task_id: str,
    rag_provider: str = None,
    folder_id: str = None,
):
    """Background task for processing uploaded files.

    Args:
        kb_name: Knowledge base name
        base_dir: Base directory for knowledge bases
        uploaded_file_paths: List of file paths to process
        rag_provider: RAG provider already matched against the KB binding
        folder_id: Optional folder ID for sync state update
    """
    task_manager = TaskIDManager.get_instance()
    task_stream_manager = get_task_stream_manager()
    task_stream_manager.ensure_task(task_id)

    progress_tracker = ProgressTracker(kb_name, Path(base_dir))
    progress_tracker.task_id = task_id

    with capture_task_logs(task_id):
        try:
            _task_log(task_id, f"Processing {len(uploaded_file_paths)} file(s) for KB '{kb_name}'")
            progress_tracker.update(
                ProgressStage.PROCESSING_DOCUMENTS,
                f"Processing {len(uploaded_file_paths)} files...",
                current=0,
                total=len(uploaded_file_paths),
            )

            adder = DocumentAdder(
                kb_name=kb_name,
                base_dir=base_dir,
                progress_tracker=progress_tracker,
                rag_provider=rag_provider,
            )

            staged_files = adder.add_documents(uploaded_file_paths, allow_duplicates=False)
            _task_log(task_id, f"Staged {len(staged_files)} new file(s)")

            if not staged_files:
                _task_log(task_id, "No new files to process (all duplicates or invalid)")
                progress_tracker.update(
                    ProgressStage.COMPLETED,
                    "No new files to process (all duplicates or invalid)",
                    current=0,
                    total=0,
                )
                task_manager.update_task_status(task_id, "completed")
                task_stream_manager.emit_complete(
                    task_id, "No new files to process (all duplicates or invalid)"
                )
                return

            index_result = await adder.process_new_documents(staged_files)
            processed_files = index_result.processed_files
            _task_log(task_id, f"Indexed {index_result.processed_count} file(s)")

            if index_result.has_failures:
                failure_summary = index_result.failure_summary()
                error_msg = (
                    f"Indexed {index_result.processed_count}/{len(staged_files)} file(s); "
                    f"{index_result.failed_count} failed: {failure_summary}"
                )
                _task_log(task_id, error_msg, level="error")
                for failure in index_result.failures:
                    _task_log(
                        task_id,
                        f"Failed to index {failure.file_path.name}: {failure.error}",
                        level="error",
                    )
                progress_tracker.update(
                    ProgressStage.ERROR,
                    f"Processing failed: {error_msg}",
                    current=index_result.processed_count,
                    total=len(staged_files),
                    error=error_msg,
                    indexed_count=index_result.processed_count,
                    index_changed=index_result.processed_count > 0,
                    index_action="upload",
                )
                task_manager.update_task_status(task_id, "error", error=error_msg)
                task_stream_manager.emit_failed(
                    task_id,
                    error_msg,
                    details="\n".join(
                        f"{failure.file_path}: {failure.error}" for failure in index_result.failures
                    ),
                )
                return

            adder.update_metadata(index_result.processed_count)

            if folder_id and processed_files:
                try:
                    manager = get_kb_manager()
                    manager.update_folder_sync_state(
                        kb_name, folder_id, [str(f) for f in processed_files]
                    )
                    _task_log(task_id, f"Updated folder sync state: {folder_id}")
                except Exception as sync_err:
                    _task_log(
                        task_id, f"Folder sync state update failed: {sync_err}", level="warning"
                    )

            num_processed = index_result.processed_count
            progress_tracker.update(
                ProgressStage.COMPLETED,
                f"Successfully processed {num_processed} files!",
                current=num_processed,
                total=num_processed,
                indexed_count=num_processed,
                index_changed=num_processed > 0,
                index_action="upload",
            )

            _task_log(
                task_id, f"Processed {num_processed} file(s) for '{kb_name}'", level="success"
            )
            task_manager.update_task_status(task_id, "completed")
            task_stream_manager.emit_complete(
                task_id, f"Successfully processed {num_processed} files for '{kb_name}'"
            )
        except Exception as e:
            import traceback as _tb

            error_msg = f"Upload processing failed (KB '{kb_name}'): {e}"
            trace = _tb.format_exc()
            _task_log(task_id, error_msg, level="error")
            _task_log(task_id, f"Stack trace:\n{trace}", level="error")

            task_manager.update_task_status(task_id, "error", error=error_msg)

            progress_tracker.update(
                ProgressStage.ERROR, f"Processing failed: {error_msg}", error=error_msg
            )
            task_stream_manager.emit_failed(task_id, error_msg, details=trace)


@router.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        manager = get_kb_manager()
        config_exists = manager.config_file.exists()
        kb_count = len(manager.list_knowledge_bases())
        return {
            "status": "ok",
            "config_file": str(manager.config_file),
            "config_exists": config_exists,
            "base_dir": str(manager.base_dir),
            "base_dir_exists": manager.base_dir.exists(),
            "knowledge_bases_count": kb_count,
        }
    except Exception as e:
        return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}


@router.get("/rag-providers")
async def get_rag_providers():
    """Get list of available RAG providers (with the active per-engine mode)."""
    try:
        from deeptutor.services.config import get_kb_config_service
        from deeptutor.services.rag.service import RAGService

        providers = RAGService.list_providers()
        kb_config = get_kb_config_service()
        for provider in providers:
            modes = provider.get("modes") or []
            if modes:
                stored = kb_config.get_provider_mode(provider["id"])
                if stored in modes:
                    provider["default_mode"] = stored
            # Whether an existing index for this engine can be linked in place
            # (self-contained on disk). Drives the "link existing folder" UI.
            provider["linkable"] = provider.get("id") in LINKABLE_PROVIDERS
        return {"providers": providers}
    except Exception as e:
        logger.error(f"Error getting RAG providers: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class ProviderModeUpdate(BaseModel):
    """Set an engine's global default retrieval mode (from its engine card)."""

    mode: str


@router.put("/rag-providers/{provider}/mode")
async def set_rag_provider_mode(provider: str, payload: ProviderModeUpdate):
    """Persist the default retrieval mode for a mode-aware engine.

    The mode must be one the engine supports; a KB's own ``search_mode`` still
    overrides this per-KB default.
    """
    from deeptutor.services.config import get_kb_config_service
    from deeptutor.services.rag.service import RAGService

    entry = next((p for p in RAGService.list_providers() if p["id"] == provider), None)
    modes = (entry or {}).get("modes") or []
    if entry is None or not modes:
        raise HTTPException(status_code=404, detail=f"No retrieval modes for engine '{provider}'.")

    mode = (payload.mode or "").strip().lower()
    if mode not in modes:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid mode '{payload.mode}' for {provider}. Choose one of: {', '.join(modes)}.",
        )

    get_kb_config_service().set_provider_mode(provider, mode)
    return {"provider": provider, "mode": mode}


class PageIndexConfigUpdate(BaseModel):
    # Tri-state api_key: omit/None keeps the stored key, "" clears it, any other
    # value replaces it — so the masked UI never round-trips the real secret.
    api_key: str | None = None
    api_base_url: str | None = None


def _pageindex_config_payload() -> dict:
    """PageIndex pipeline settings for the UI, with the API key redacted."""
    from deeptutor.services.config import get_runtime_settings_service

    settings = get_runtime_settings_service().load_pageindex()
    return {
        "api_base_url": settings.get("api_base_url") or "",
        "api_key_set": bool(settings.get("api_key")),
        "configured": bool(settings.get("api_key")),
    }


@router.get("/rag-pipelines/pageindex/config")
async def get_pageindex_pipeline_config():
    """Read the PageIndex credential state (key redacted to a boolean)."""
    try:
        return _pageindex_config_payload()
    except Exception as e:
        logger.error(f"Error reading PageIndex config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/rag-pipelines/pageindex/config")
async def update_pageindex_pipeline_config(payload: PageIndexConfigUpdate):
    """Persist the PageIndex API key / base URL for this user's account."""
    try:
        from deeptutor.services.config import get_runtime_settings_service
        from deeptutor.services.rag.pipelines.pageindex.config import DEFAULT_API_BASE_URL

        service = get_runtime_settings_service()
        current = service.load_pageindex(include_process_overrides=False)

        api_key = current.get("api_key", "")
        if payload.api_key is not None:
            api_key = payload.api_key.strip()

        api_base_url = current.get("api_base_url") or DEFAULT_API_BASE_URL
        if payload.api_base_url is not None and payload.api_base_url.strip():
            api_base_url = payload.api_base_url.strip()

        service.save_pageindex({"api_key": api_key, "api_base_url": api_base_url})
        return _pageindex_config_payload()
    except Exception as e:
        logger.error(f"Error updating PageIndex config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class LlamaIndexConfigUpdate(BaseModel):
    """Partial update for the LlamaIndex engine knobs (omitted fields kept)."""

    retrieval_profile: str | None = None
    top_k: int | None = None
    vector_top_k_multiplier: int | None = None
    bm25_top_k_multiplier: int | None = None
    chunk_size: int | None = None
    chunk_overlap: int | None = None


@router.get("/rag-pipelines/llamaindex/config")
async def get_llamaindex_pipeline_config():
    """Read the LlamaIndex engine's retrieval + chunking knobs."""
    try:
        from deeptutor.services.config import get_runtime_settings_service

        return get_runtime_settings_service().load_llamaindex()
    except Exception as e:
        logger.error(f"Error reading LlamaIndex config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/rag-pipelines/llamaindex/config")
async def update_llamaindex_pipeline_config(payload: LlamaIndexConfigUpdate):
    """Persist the LlamaIndex engine knobs.

    Retrieval knobs take effect on the next query; chunk geometry only changes
    how documents indexed *after* the save are split.
    """
    try:
        from deeptutor.services.config import get_runtime_settings_service

        service = get_runtime_settings_service()
        current = service.load_llamaindex(include_process_overrides=False)
        # Merge only the provided fields so partial saves never wipe others.
        updates = payload.model_dump(exclude_none=True)
        return service.save_llamaindex({**current, **updates})
    except Exception as e:
        logger.error(f"Error updating LlamaIndex config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class GraphRagConfigUpdate(BaseModel):
    """Partial update for GraphRAG query knobs (omitted fields kept)."""

    response_type: str | None = None
    community_level: int | None = None
    dynamic_community_selection: bool | None = None


@router.get("/rag-pipelines/graphrag/config")
async def get_graphrag_pipeline_config():
    """Read GraphRAG's query knobs (response style, community granularity)."""
    try:
        from deeptutor.services.config import get_runtime_settings_service

        return get_runtime_settings_service().load_graphrag()
    except Exception as e:
        logger.error(f"Error reading GraphRAG config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/rag-pipelines/graphrag/config")
async def update_graphrag_pipeline_config(payload: GraphRagConfigUpdate):
    """Persist GraphRAG's query knobs. Takes effect on the next query."""
    try:
        from deeptutor.services.config import get_runtime_settings_service

        service = get_runtime_settings_service()
        current = service.load_graphrag()
        updates = payload.model_dump(exclude_none=True)
        return service.save_graphrag({**current, **updates})
    except Exception as e:
        logger.error(f"Error updating GraphRAG config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class LightRagConfigUpdate(BaseModel):
    """Partial update for LightRAG query knobs (omitted fields kept)."""

    top_k: int | None = None
    response_type: str | None = None


@router.get("/rag-pipelines/lightrag/config")
async def get_lightrag_pipeline_config():
    """Read LightRAG's query knobs (top_k, response style)."""
    try:
        from deeptutor.services.config import get_runtime_settings_service

        return get_runtime_settings_service().load_lightrag()
    except Exception as e:
        logger.error(f"Error reading LightRAG config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/rag-pipelines/lightrag/config")
async def update_lightrag_pipeline_config(payload: LightRagConfigUpdate):
    """Persist LightRAG's query knobs. Takes effect on the next query."""
    try:
        from deeptutor.services.config import get_runtime_settings_service

        service = get_runtime_settings_service()
        current = service.load_lightrag()
        updates = payload.model_dump(exclude_none=True)
        return service.save_lightrag({**current, **updates})
    except Exception as e:
        logger.error(f"Error updating LightRAG config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/rag-pipelines/{provider}/preflight")
async def get_rag_pipeline_preflight(provider: str):
    """Check whether ``provider`` can run in the current environment.

    Returns ``{ok, checks:[{key,label,ok,detail,optional}]}`` — package
    install, API key, and active model requirements per engine.
    """
    try:
        from deeptutor.services.rag.preflight import engine_preflight

        return engine_preflight(provider)
    except Exception as e:
        logger.error(f"Error running preflight for '{provider}': {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Model kinds an engine page is allowed to read/switch. ``vision`` is not a
# catalog service (it rides on the active chat model), so it is intentionally
# excluded here.
_ENGINE_MODEL_KINDS = ("llm", "embedding")


def _model_options_payload(kinds: list[str]) -> dict:
    """Secret-free model options per kind for the engine page picker.

    Exposes only ids / display labels / dimensions — never provider URLs or
    API keys (those stay behind the admin-only catalog endpoint).
    """
    from deeptutor.services.config import get_model_catalog_service

    catalog = get_model_catalog_service().load()
    services = catalog.get("services", {})
    out: dict = {}
    for kind in kinds:
        svc = services.get(kind) or {}
        options = []
        for profile in svc.get("profiles", []) or []:
            pid = profile.get("id")
            pname = profile.get("name") or pid
            for model in profile.get("models", []) or []:
                detail = ""
                if kind == "embedding" and model.get("dimension"):
                    detail = f"{model.get('dimension')}d"
                options.append(
                    {
                        "profile_id": pid,
                        "profile_name": pname,
                        "model_id": model.get("id"),
                        "label": model.get("name") or model.get("model") or model.get("id"),
                        "model": model.get("model") or "",
                        "detail": detail,
                    }
                )
        out[kind] = {
            "active": {
                "profile_id": svc.get("active_profile_id"),
                "model_id": svc.get("active_model_id"),
            },
            "options": options,
        }
    return out


@router.get("/rag-pipelines/model-options")
async def get_rag_model_options(kinds: str = "llm,embedding"):
    """List configured models (secret-free) for the requested model kinds."""
    try:
        requested = [
            k.strip() for k in kinds.split(",") if k.strip() in _ENGINE_MODEL_KINDS
        ] or list(_ENGINE_MODEL_KINDS)
        return _model_options_payload(requested)
    except Exception as e:
        logger.error(f"Error reading model options: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class ActiveModelUpdate(BaseModel):
    """Switch the globally-active model for a kind (llm / embedding)."""

    kind: str
    profile_id: str
    model_id: str


@router.put("/rag-pipelines/active-model")
async def set_rag_active_model(payload: ActiveModelUpdate):
    """Set the active model for an engine's required kind, applied immediately.

    This is the same active selection the model catalog manages; switching it
    here affects every engine that uses that kind (the active model is global).
    """
    if payload.kind not in _ENGINE_MODEL_KINDS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported model kind '{payload.kind}'. Choose one of: {', '.join(_ENGINE_MODEL_KINDS)}.",
        )
    try:
        from deeptutor.services.config import get_model_catalog_service

        service = get_model_catalog_service()
        catalog = service.load()
        svc = (catalog.get("services") or {}).get(payload.kind)
        if not svc:
            raise HTTPException(status_code=404, detail=f"No '{payload.kind}' models configured.")
        profile = next(
            (p for p in svc.get("profiles", []) if p.get("id") == payload.profile_id), None
        )
        if profile is None:
            raise HTTPException(status_code=400, detail="Unknown profile for this kind.")
        if not any(m.get("id") == payload.model_id for m in profile.get("models", [])):
            raise HTTPException(status_code=400, detail="Unknown model for this profile.")
        svc["active_profile_id"] = payload.profile_id
        svc["active_model_id"] = payload.model_id
        service.apply(catalog)
        return _model_options_payload([payload.kind])[payload.kind]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error setting active model: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/supported-file-types", response_model=SupportedFileTypesInfo)
async def get_supported_file_types():
    """Return the current upload policy so the web client stays in sync."""
    extensions = sorted(FileTypeRouter.get_supported_extensions())
    accept_items = extensions + [
        mime
        for extension, mime in sorted(IMAGE_ACCEPT_MIME_TYPES.items())
        if extension in FileTypeRouter.IMAGE_EXTENSIONS
    ]
    return SupportedFileTypesInfo(
        extensions=extensions,
        accept=",".join(dict.fromkeys(accept_items)),
        max_file_size_bytes=DocumentValidator.MAX_FILE_SIZE,
    )


@router.get("/configs")
async def get_all_kb_configs():
    """Get all knowledge base configurations from centralized config file."""
    try:
        from deeptutor.services.config import get_kb_config_service

        service = get_kb_config_service()
        return service.get_all_configs()
    except Exception as e:
        logger.error(f"Error getting KB configs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{kb_name}/config")
async def get_kb_config(kb_name: str):
    """Get configuration for a specific knowledge base."""
    try:
        from deeptutor.services.config import get_kb_config_service

        service = get_kb_config_service()
        config = service.get_kb_config(kb_name)
        return {"kb_name": kb_name, "config": config}
    except Exception as e:
        logger.error(f"Error getting config for KB '{kb_name}': {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{kb_name}/config")
async def update_kb_config(kb_name: str, config: dict):
    """Update configuration for a specific knowledge base."""
    try:
        from deeptutor.services.config import get_kb_config_service
        from deeptutor.services.rag.index_probe import has_ready_provider_index

        config = dict(config or {})
        if "rag_provider" in config:
            requested_provider = _validate_registered_provider(config.get("rag_provider"))
            service = get_kb_config_service()
            current_config = service.get_kb_config(kb_name)
            current_provider = _validate_registered_provider(
                current_config.get("rag_provider") or DEFAULT_PROVIDER
            )
            if requested_provider != current_provider:
                kb_dir = _current_kb_base_dir() / kb_name
                if kb_dir.exists() and has_ready_provider_index(kb_dir, current_provider):
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            f"Knowledge base '{kb_name}' already has a ready "
                            f"{current_provider} index. Provider changes require "
                            "an explicit re-index/migration instead of a silent config edit."
                        ),
                    )
                config["needs_reindex"] = True
                config.setdefault("status", "needs_reindex")
                config["progress"] = {
                    "stage": "needs_reindex",
                    "message": (
                        f"Provider changed from {current_provider} to {requested_provider}; "
                        "re-index this knowledge base before use."
                    ),
                    "percent": 0,
                    "timestamp": datetime.now().isoformat(),
                }
            config["rag_provider"] = requested_provider
        else:
            service = get_kb_config_service()

        service.set_kb_config(kb_name, config)
        return {"status": "success", "kb_name": kb_name, "config": service.get_kb_config(kb_name)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating config for KB '{kb_name}': {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/configs/sync")
async def sync_configs_from_metadata():
    """Sync all KB configurations from their metadata.json files to centralized config."""
    try:
        from deeptutor.services.config import get_kb_config_service

        service = get_kb_config_service()
        service.sync_all_from_metadata(_current_kb_base_dir())
        return {"status": "success", "message": "Configurations synced from metadata files"}
    except Exception as e:
        logger.error(f"Error syncing configs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/default")
async def get_default_kb():
    """Get the default knowledge base."""
    try:
        manager = get_kb_manager()
        default_kb = manager.get_default()
        return {"default_kb": default_kb}
    except Exception as e:
        logger.error(f"Error getting default KB: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/default/{kb_name}")
async def set_default_kb(kb_name: str):
    """Set the default knowledge base."""
    try:
        manager, kb_name, _ = _writable_kb(kb_name)

        # Verify KB exists
        if kb_name not in manager.list_knowledge_bases():
            raise HTTPException(status_code=404, detail=f"Knowledge base '{kb_name}' not found")

        manager.set_default(kb_name)
        return {"status": "success", "default_kb": kb_name}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error setting default KB: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class ConnectObsidianRequest(BaseModel):
    name: str
    vault_path: str


@router.post("/connect-obsidian")
async def connect_obsidian_vault(payload: ConnectObsidianRequest):
    """Connect an existing Obsidian vault as a knowledge base.

    Registers a pointer to the user's vault directory (``type: obsidian``) — no
    upload, no index. The vault must be a directory the server can reach (i.e. a
    local/self-hosted deployment); the Obsidian capability reads it live.
    """
    name = (payload.name or "").strip()
    vault_path = (payload.vault_path or "").strip()
    if not name or not vault_path:
        raise HTTPException(status_code=400, detail="Both name and vault_path are required.")
    try:
        folder = assert_path_allowed(vault_path)
        manager = get_kb_manager()
        entry = manager.register_obsidian_vault(name, str(folder))
        return {"status": "connected", "name": name, "vault_path": entry["vault_path"]}
    except ValueError as e:
        # Missing/invalid path, disallowed location, or a name clash → 400.
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error connecting Obsidian vault: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class ProbeFolderRequest(BaseModel):
    folder_path: str
    rag_provider: str = DEFAULT_PROVIDER


class ConnectFolderRequest(BaseModel):
    name: str
    folder_path: str
    rag_provider: str = DEFAULT_PROVIDER


@router.post("/probe-folder")
async def probe_linked_folder_route(payload: ProbeFolderRequest):
    """Inspect a local folder for a ready engine index before linking it.

    Returns the probe verdict (ready index? embedding compatible? warnings?) so
    the UI can present and confirm before any registration happens. Does not
    create a knowledge base.
    """
    folder_path = (payload.folder_path or "").strip()
    if not folder_path:
        raise HTTPException(status_code=400, detail="folder_path is required.")
    try:
        folder = assert_path_allowed(folder_path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    result = probe_linked_folder(str(folder), payload.rag_provider)
    return result.to_dict()


@router.post("/connect-folder")
async def connect_linked_folder_route(payload: ConnectFolderRequest):
    """Mount an existing engine index as a read-only ``linked`` knowledge base.

    Re-probes server-side (never trusts the client's verdict), then registers a
    pointer to the folder. Retrieval reads the index in place — no copy, no
    re-index. Embedding-mismatch warnings do not block the link (the user may
    switch embedding models later); a missing/invalid index does.
    """
    name = (payload.name or "").strip()
    folder_path = (payload.folder_path or "").strip()
    if not name or not folder_path:
        raise HTTPException(status_code=400, detail="Both name and folder_path are required.")
    try:
        folder = assert_path_allowed(folder_path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    result = probe_linked_folder(str(folder), payload.rag_provider)
    if not result.ok:
        raise HTTPException(status_code=400, detail=result.error or "Folder is not linkable.")

    stats = {
        "embedding_model": result.embedding.index_model,
        "doc_count": result.doc_count,
    }
    try:
        manager = get_kb_manager()
        entry = manager.register_linked_kb(
            name,
            str(folder),
            result.provider,
            stats=stats,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error connecting linked folder: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "status": "connected",
        "name": name,
        "external_path": entry["external_path"],
        "rag_provider": entry["rag_provider"],
        "warnings": result.warnings,
    }


class ProbeLightRagServerRequest(BaseModel):
    server_url: str
    api_key: str = ""


class ConnectLightRagServerRequest(BaseModel):
    name: str
    server_url: str
    api_key: str = ""
    search_mode: str = ""


@router.post("/probe-lightrag-server")
async def probe_lightrag_server_route(payload: ProbeLightRagServerRequest):
    """Test-connect to an external LightRAG server before binding a KB to it.

    Returns the verdict (reachable? is it a LightRAG server? API key accepted?)
    so the UI can confirm before any registration happens. Creates nothing.
    """
    from deeptutor.services.rag.pipelines.lightrag_server.probe import probe_server

    server_url = (payload.server_url or "").strip()
    if not server_url:
        raise HTTPException(status_code=400, detail="server_url is required.")
    result = await probe_server(server_url, payload.api_key or "")
    return result.to_dict()


@router.post("/connect-lightrag-server")
async def connect_lightrag_server_route(payload: ConnectLightRagServerRequest):
    """Connect an external LightRAG server as a retrieval-only knowledge base.

    Re-probes server-side (never trusts the client's verdict), then registers a
    pointer (``type: lightrag_server``). Retrieval is offloaded to the server's
    ``/query`` endpoint — no copy, no local index.
    """
    from deeptutor.services.rag.pipelines.lightrag_server.config import SUPPORTED_MODES
    from deeptutor.services.rag.pipelines.lightrag_server.probe import probe_server

    name = (payload.name or "").strip()
    server_url = (payload.server_url or "").strip()
    if not name or not server_url:
        raise HTTPException(status_code=400, detail="Both name and server_url are required.")

    result = await probe_server(server_url, payload.api_key or "")
    if not result.ok:
        raise HTTPException(
            status_code=400, detail=result.error or "Could not connect to the LightRAG server."
        )

    search_mode = (payload.search_mode or "").strip().lower()
    if search_mode and search_mode not in SUPPORTED_MODES:
        search_mode = ""

    try:
        manager = get_kb_manager()
        entry = manager.register_lightrag_server_kb(
            name,
            result.base_url,
            api_key=payload.api_key or "",
            search_mode=search_mode,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error connecting LightRAG server: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "status": "connected",
        "name": name,
        "server_url": entry["server_url"],
        "rag_provider": entry["rag_provider"],
    }


@router.get("/list", response_model=list[KnowledgeBaseInfo])
async def list_knowledge_bases():
    """List all available knowledge bases with their details."""
    try:
        manager = get_kb_manager()
        kb_names = manager.list_knowledge_bases()
        access_items = list_visible_kb_access()
        access_by_id = {str(item.get("id") or ""): item for item in access_items}
        own_prefix = "admin:kb:" if get_current_user().is_admin else "user:kb:"

        logger.debug(f"Found {len(kb_names)} knowledge bases: {kb_names}")

        result = []
        errors = []

        for name in kb_names:
            try:
                info = manager.get_info(name)
                logger.debug(f"Successfully got info for KB '{name}': {info.get('statistics', {})}")
                result.append(
                    KnowledgeBaseInfo(
                        id=f"{own_prefix}{info['name']}",
                        name=info["name"],
                        is_default=info["is_default"],
                        statistics=info.get("statistics", {}),
                        metadata=info.get("metadata"),
                        path=info.get("path"),
                        status=info.get("status"),
                        progress=info.get("progress"),
                        source="admin" if get_current_user().is_admin else "user",
                        assigned=False,
                        read_only=False,
                        provenance_label=access_by_id.get(f"{own_prefix}{info['name']}", {}).get(
                            "provenance_label"
                        ),
                    )
                )
            except Exception as e:
                error_msg = f"Error getting info for KB '{name}': {e}"
                errors.append(error_msg)
                logger.warning(f"{error_msg}\n{traceback.format_exc()}")
                try:
                    kb_dir = manager.base_dir / name
                    if kb_dir.exists():
                        logger.debug(f"KB '{name}' directory exists, creating error fallback info")
                        fallback_progress = {
                            "stage": "error",
                            "message": "Failed to load knowledge base info.",
                            "error": error_msg,
                        }
                        result.append(
                            KnowledgeBaseInfo(
                                id=f"{own_prefix}{name}",
                                name=name,
                                is_default=name == manager.get_default(),
                                statistics={
                                    "raw_documents": 0,
                                    "images": 0,
                                    "content_lists": 0,
                                    "rag_initialized": False,
                                },
                                metadata={"name": name, "last_error": error_msg},
                                path=str(kb_dir),
                                status="error",
                                progress=fallback_progress,
                                source="admin" if get_current_user().is_admin else "user",
                            )
                        )
                except Exception as fallback_err:
                    logger.error(f"Fallback also failed for KB '{name}': {fallback_err}")

        if errors and not result:
            error_detail = f"Failed to load knowledge bases. Errors: {'; '.join(errors)}"
            logger.error(error_detail)
            raise HTTPException(status_code=500, detail=error_detail)

        if errors:
            logger.warning(
                f"Some KBs had errors, returning {len(result)} results. Errors: {errors}"
            )

        logger.debug(f"Returning {len(result)} knowledge bases")
        if not get_current_user().is_admin:
            own_ids = {item.id for item in result}
            for access in access_items:
                if access.get("source") != "admin" or access.get("id") in own_ids:
                    continue
                if not access.get("available", True):
                    result.append(
                        KnowledgeBaseInfo(
                            id=str(access.get("id") or ""),
                            name=str(access.get("name") or ""),
                            is_default=False,
                            statistics={},
                            metadata={},
                            path=None,
                            status="unavailable",
                            progress=None,
                            source="admin",
                            assigned=True,
                            read_only=True,
                            provenance_label=str(access.get("provenance_label") or ""),
                            available=False,
                        )
                    )
                    continue
                resource = resolve_kb(str(access.get("id") or access.get("name") or ""))
                assigned_manager = manager_for_resource(resource)
                try:
                    info = assigned_manager.get_info(resource.name)
                    result.append(
                        KnowledgeBaseInfo(
                            id=resource.id,
                            name=info["name"],
                            is_default=False,
                            statistics=info.get("statistics", {}),
                            metadata=info.get("metadata"),
                            path=None,
                            status=info.get("status"),
                            progress=info.get("progress"),
                            source="admin",
                            assigned=True,
                            read_only=True,
                            provenance_label=str(access.get("provenance_label") or ""),
                        )
                    )
                except Exception as exc:
                    error_msg = f"Error getting assigned KB '{resource.name}': {exc}"
                    result.append(
                        KnowledgeBaseInfo(
                            id=resource.id,
                            name=resource.name,
                            is_default=False,
                            statistics={},
                            metadata={"name": resource.name, "last_error": error_msg},
                            status="error",
                            progress={
                                "stage": "error",
                                "message": "Failed to load assigned knowledge base info.",
                                "error": error_msg,
                            },
                            source="admin",
                            assigned=True,
                            read_only=True,
                            provenance_label=str(access.get("provenance_label") or ""),
                        )
                    )
        return result
    except HTTPException:
        raise
    except Exception as e:
        error_msg = f"Error listing knowledge bases: {e}"
        logger.error(f"{error_msg}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Failed to list knowledge bases: {e!s}")


@router.get("/{kb_name}")
async def get_knowledge_base_details(kb_name: str):
    """Get detailed info for a specific KB."""
    try:
        resource = resolve_kb(kb_name)
        manager = manager_for_resource(resource)
        info = manager.get_info(resource.name)
        info.update(
            {
                "id": resource.id,
                "source": resource.source,
                "assigned": resource.assigned,
                "read_only": resource.read_only,
            }
        )
        if resource.assigned:
            info.pop("path", None)
        return info
    except HTTPException:
        raise
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Knowledge base '{kb_name}' not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _resolve_kb_raw_dir(kb_name: str) -> Path:
    """Resolve the raw/ directory for a KB, validating that it exists."""
    manager = _overridden_kb_manager()
    if manager is not None:
        resolved_name = _resolve_registered_kb_name(manager, kb_name)
        return manager.get_knowledge_base_path(resolved_name) / "raw"
    resource = resolve_kb(kb_name)
    manager = manager_for_resource(resource)
    kb_path = manager.get_knowledge_base_path(resource.name)
    return kb_path / "raw"


def _resolve_kb_raw_file_or_404(kb_name: str, filename: str) -> Path:
    """Resolve a raw KB file while preventing traversal outside raw/."""
    raw_dir = _resolve_kb_raw_dir(kb_name)
    if not raw_dir.exists():
        raise HTTPException(status_code=404, detail="File not found")

    raw_resolved = raw_dir.resolve()
    target = (raw_dir / filename).resolve()
    try:
        target.relative_to(raw_resolved)
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")

    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    return target


@router.get("/{kb_name}/files")
async def list_kb_raw_files(kb_name: str):
    """List raw documents under <kb>/raw/, recursing into folders.

    ``name`` is the POSIX path relative to ``raw/`` so the web client can
    rebuild the folder tree. Folders (including empty ones) are returned as
    ``type: "folder"`` entries so user-created/uploaded structure shows even
    before it holds any files. Folders are purely organizational and have no
    effect on indexing or retrieval.
    """
    raw_dir = _resolve_kb_raw_dir(kb_name)
    if not raw_dir.exists() or not raw_dir.is_dir():
        return {"files": []}

    files = []
    for entry in sorted(raw_dir.rglob("*"), key=lambda p: str(p).lower()):
        rel = entry.relative_to(raw_dir).as_posix()
        if entry.is_dir():
            files.append({"name": rel, "type": "folder"})
            continue
        if not entry.is_file():
            continue
        try:
            stat = entry.stat()
        except OSError:
            continue
        media_type, _ = mimetypes.guess_type(entry.name)
        files.append(
            {
                "name": rel,
                "type": "file",
                "size": stat.st_size,
                "modified": stat.st_mtime,
                "mime_type": media_type,
            }
        )
    return {"files": files}


class CreateFolderPayload(BaseModel):
    path: str


class MoveFilePayload(BaseModel):
    source: str
    dest_folder: str = ""


@router.post("/{kb_name}/folders")
async def create_kb_folder(kb_name: str, payload: CreateFolderPayload):
    """Create an (organizational) folder under <kb>/raw/. No retrieval effect."""
    manager, kb_name, _ = _writable_kb(kb_name)
    _assert_kb_writable_or_409(kb_name, _load_kb_entry_or_404(manager, kb_name))
    raw_dir = manager.get_knowledge_base_path(kb_name) / "raw"
    subdir = _sanitize_rel_subdir(payload.path)
    if not subdir:
        raise HTTPException(status_code=400, detail="Folder name is required")
    target = _safe_join_raw(raw_dir, subdir)
    target.mkdir(parents=True, exist_ok=True)
    return {"status": "ok", "path": subdir}


@router.post("/{kb_name}/files/move")
async def move_kb_file(kb_name: str, payload: MoveFilePayload):
    """Move a file/folder between organizational folders (display only).

    Moving never re-indexes: folders don't affect retrieval, so this is a pure
    filesystem relocation under ``raw/``.
    """
    manager, kb_name, _ = _writable_kb(kb_name)
    _assert_kb_writable_or_409(kb_name, _load_kb_entry_or_404(manager, kb_name))
    raw_dir = manager.get_knowledge_base_path(kb_name) / "raw"

    source_rel = _sanitize_rel_subdir(payload.source)
    if not source_rel:
        raise HTTPException(status_code=400, detail="Source path is required")
    src = _safe_join_raw(raw_dir, source_rel)
    if not src.exists():
        raise HTTPException(status_code=404, detail="Source not found")

    dest_folder = _sanitize_rel_subdir(payload.dest_folder)
    dest_dir = _safe_join_raw(raw_dir, dest_folder) if dest_folder else raw_dir.resolve()
    dest = dest_dir / src.name

    if dest.resolve() == src.resolve():
        return {"status": "ok", "path": source_rel}
    if src.is_dir() and dest_dir.resolve().is_relative_to(src.resolve()):
        raise HTTPException(status_code=400, detail="Cannot move a folder into itself")
    if dest.exists():
        raise HTTPException(
            status_code=409,
            detail=f"'{src.name}' already exists in the target folder",
        )

    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    return {"status": "ok", "path": dest.relative_to(raw_dir.resolve()).as_posix()}


@router.get("/{kb_name}/file-preview-text/{filename:path}")
async def serve_kb_raw_file_text_preview(kb_name: str, filename: str):
    """Serve extracted plain text for a raw KB document preview."""
    target = _resolve_kb_raw_file_or_404(kb_name, filename)
    try:
        text = extract_text_from_path(
            target,
            max_bytes=DocumentValidator.MAX_FILE_SIZE,
            max_chars=MAX_EXTRACTED_CHARS_PER_DOC,
        )
    except DocumentExtractionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=404, detail="File not found") from exc

    return PlainTextResponse(text, media_type="text/plain; charset=utf-8")


@router.get("/{kb_name}/files/{filename:path}")
async def serve_kb_raw_file(kb_name: str, filename: str):
    """Serve a single raw document for inline preview / download.

    Resolution is sandboxed to the KB's raw/ directory; any path that
    escapes via traversal yields 403.
    """
    target = _resolve_kb_raw_file_or_404(kb_name, filename)
    media_type, _ = mimetypes.guess_type(target.name)
    return FileResponse(
        target,
        media_type=media_type or "application/octet-stream",
        filename=target.name,
        content_disposition_type="inline",
    )


@router.delete("/{kb_name}/files/{filename:path}")
async def delete_kb_file(kb_name: str, filename: str):
    """Remove a single raw document from a knowledge base.

    Unlike deleting the whole KB, this works while the KB is in an *error*
    state — that is the point: a file that failed to parse (e.g. one that
    exceeds the cloud parser's page limit) can be dropped without deleting and
    rebuilding everything. Connected (read-only) and legacy KBs are still
    rejected. Vectors are not pruned here; ``was_indexed`` tells the caller
    whether a re-index is needed to purge the file from retrieval.
    """
    manager, kb_name, _ = _writable_kb(kb_name)
    _assert_kb_writable_or_409(kb_name, _load_kb_entry_or_404(manager, kb_name))
    target = _resolve_kb_raw_file_or_404(kb_name, filename)

    kb_dir = manager.get_knowledge_base_path(kb_name)
    removal = remove_raw_document(Path(kb_dir), target)
    return {
        "status": "ok",
        "path": removal.rel_path,
        "was_indexed": removal.was_indexed,
    }


@router.delete("/{kb_name}")
async def delete_knowledge_base(kb_name: str):
    """Delete a knowledge base."""
    try:
        manager, resolved_name, _ = _writable_kb(kb_name)
        success = manager.delete_knowledge_base(resolved_name, confirm=True)
        if not success:
            raise HTTPException(status_code=400, detail="Failed to delete knowledge base")
        logger.info(f"KB '{kb_name}' deleted")
        return {"message": f"Knowledge base '{kb_name}' deleted successfully"}
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Knowledge base '{kb_name}' not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks/{task_id}/stream")
async def stream_task_logs(task_id: str):
    """Stream task-specific logs for knowledge-base operations."""
    manager = get_task_stream_manager()
    manager.ensure_task(task_id)
    return StreamingResponse(
        manager.stream(task_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{kb_name}/upload")
async def upload_files(
    kb_name: str,
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    rag_provider: str = Form(None),
    rel_paths: list[str] = Form(None),
):
    """Upload files to a knowledge base and process them in background."""
    try:
        manager, kb_name, kb_base_dir = _writable_kb(kb_name)
        kb_path = manager.get_knowledge_base_path(kb_name)
        raw_dir = kb_path / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)

        requested_provider = None
        if rag_provider is not None and str(rag_provider).strip():
            requested_provider = _validate_registered_provider(rag_provider)

        kb_entry = _load_kb_entry_or_404(manager, kb_name)
        _assert_kb_writable_or_409(kb_name, kb_entry)
        kb_provider = _validate_registered_provider(
            kb_entry.get("rag_provider") or DEFAULT_PROVIDER
        )
        if requested_provider and requested_provider != kb_provider:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Requested provider '{requested_provider}' does not match KB provider '{kb_provider}'. "
                    "A knowledge base is locked to the engine it was created with."
                ),
            )
        _assert_provider_ready(kb_provider)
        _enforce_provider_formats(kb_provider, files)
        allowed_extensions = FileTypeRouter.get_supported_extensions()
        # ``.zip`` is accepted as an upload container; its members are
        # validated against ``allowed_extensions`` during extraction and the
        # archive itself is never indexed (``safe_extract_zip`` skips ``.zip``).
        upload_extensions = allowed_extensions | {".zip"}
        _validate_upload_batch(files, allowed_extensions=upload_extensions, rel_paths=rel_paths)
        uploaded_files, uploaded_file_paths = _save_uploaded_files(
            files, raw_dir, allowed_extensions=upload_extensions, rel_paths=rel_paths
        )
        task_id = _build_unique_task_id("kb_upload", kb_name)
        get_task_stream_manager().ensure_task(task_id)

        logger.info(f"Uploading {len(uploaded_files)} files to KB '{kb_name}'")

        background_tasks.add_task(
            run_upload_processing_task,
            kb_name=kb_name,
            base_dir=str(kb_base_dir),
            uploaded_file_paths=uploaded_file_paths,
            task_id=task_id,
            rag_provider=kb_provider,
        )

        return {
            "message": f"Uploaded {len(uploaded_files)} files. Processing in background.",
            "files": uploaded_files,
            "task_id": task_id,
        }
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Knowledge base '{kb_name}' not found")
    except Exception as e:
        # Unexpected failure (Server error)
        formatted_error = format_exception_message(e)
        raise HTTPException(status_code=500, detail=formatted_error) from e


@router.post("/create")
async def create_knowledge_base(
    background_tasks: BackgroundTasks,
    name: str = Form(...),
    files: list[UploadFile] = File(...),
    rag_provider: str = Form(DEFAULT_PROVIDER),
    rel_paths: list[str] = Form(None),
):
    """Create a new knowledge base and initialize it with files."""
    try:
        try:
            name = validate_knowledge_base_name(name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        manager = get_kb_manager()
        kb_base_dir = _current_kb_base_dir()
        if name in manager.list_knowledge_bases():
            raise HTTPException(status_code=400, detail=f"Knowledge base '{name}' already exists")

        rag_provider = _validate_registered_provider(rag_provider)
        _assert_provider_ready(rag_provider)
        _enforce_provider_formats(rag_provider, files)
        allowed_extensions = FileTypeRouter.get_supported_extensions()
        _validate_upload_batch(files, allowed_extensions=allowed_extensions, rel_paths=rel_paths)

        logger.info(f"Creating KB: {name} (provider={rag_provider})")
        task_id = _build_unique_task_id("kb_init", name)
        get_task_stream_manager().ensure_task(task_id)

        # Register KB to kb_config.json immediately with "initializing" status
        # This ensures the KB appears in the list right away
        manager.update_kb_status(
            name=name,
            status="initializing",
            progress={
                "stage": "initializing",
                "message": "Initializing knowledge base...",
                "percent": 0,
                "current": 0,
                "total": len(files),
                "task_id": task_id,
            },
        )
        # Also store rag_provider in config (reload and update)
        manager.config = manager._load_config()
        if name in manager.config.get("knowledge_bases", {}):
            manager.config["knowledge_bases"][name]["rag_provider"] = rag_provider
            manager.config["knowledge_bases"][name]["needs_reindex"] = False
            manager._save_config()

        progress_tracker = ProgressTracker(name, kb_base_dir)

        initializer = KnowledgeBaseInitializer(
            kb_name=name,
            base_dir=str(kb_base_dir),
            progress_tracker=progress_tracker,
            rag_provider=rag_provider,
        )

        initializer.create_directory_structure()
        progress_tracker.task_id = task_id

        manager = get_kb_manager()
        if name not in manager.list_knowledge_bases():
            logger.warning(f"KB {name} not found in config, registering manually")
            initializer._register_to_config()

        uploaded_files, _ = _save_uploaded_files(
            files, initializer.raw_dir, allowed_extensions=allowed_extensions, rel_paths=rel_paths
        )

        progress_tracker.update(
            ProgressStage.PROCESSING_DOCUMENTS,
            f"Saved {len(uploaded_files)} files, preparing to process...",
            current=0,
            total=len(uploaded_files),
        )

        background_tasks.add_task(run_initialization_task, initializer, task_id)

        logger.info(f"KB '{name}' created, processing {len(uploaded_files)} files in background")

        return {
            "message": f"Knowledge base '{name}' created. Processing {len(uploaded_files)} files in background.",
            "name": name,
            "files": uploaded_files,
            "task_id": task_id,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create KB: {e}")
        logger.debug(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


async def run_reindex_task(kb_name: str, base_dir: str, task_id: str, signature_hash: str) -> None:
    """Re-index a KB's raw documents against the currently-active embedding config.

    Each ``(profile, model, dimension, base_url)`` combination gets its own
    flat ``<kb>/version-N/`` storage directory. Prior versions are preserved
    untouched so switching the active embedding model back to a
    previously-indexed one reuses the existing version with no extra work.
    """
    task_manager = TaskIDManager.get_instance()
    task_stream_manager = get_task_stream_manager()
    task_stream_manager.ensure_task(task_id)

    with capture_task_logs(task_id):
        try:
            base_path = Path(base_dir)
            kb_dir = base_path / kb_name
            raw_dir = kb_dir / "raw"
            if not raw_dir.is_dir():
                raise FileNotFoundError(f"KB '{kb_name}' has no `raw/` directory; cannot reindex.")
            file_paths = [
                str(path)
                for path in FileTypeRouter.collect_supported_files(raw_dir, recursive=True)
            ]
            if not file_paths:
                raise ValueError(f"KB '{kb_name}' has no source files in `raw/` to reindex.")

            _task_log(
                task_id,
                f"Re-indexing '{kb_name}' ({len(file_paths)} files) against signature {signature_hash}",
            )

            progress_tracker = ProgressTracker(kb_name, base_path)
            progress_tracker.task_id = task_id
            progress_tracker.update(
                ProgressStage.PROCESSING_DOCUMENTS,
                f"Re-indexing {len(file_paths)} document(s) with the active embedding model...",
                current=0,
                total=len(file_paths),
            )

            from deeptutor.services.rag.service import RAGService

            # provider=None → RAGService resolves the KB's DeepTutor-bound
            # engine, so re-indexing a PageIndex/LightRAG/GraphRAG KB stays on
            # that provider rather than forcing the default pipeline.
            rag_service = RAGService(kb_base_dir=str(base_path), provider=None)

            def _on_progress(batch_num: int, total_batches: int) -> None:
                progress_tracker.update(
                    ProgressStage.PROCESSING_DOCUMENTS,
                    f"Embedding batches: {batch_num}/{total_batches}",
                    current=batch_num,
                    total=total_batches,
                )

            # The pipeline now raises the underlying error (embedding API
            # failure, parse error, etc.) so it surfaces in the task log
            # rather than being swallowed into a generic wrapper. A False
            # return is reserved for "no documents to index" — surface that
            # specifically too.
            success = await rag_service.initialize(
                kb_name=kb_name,
                file_paths=file_paths,
                progress_callback=_on_progress,
            )
            if not success:
                raise RuntimeError(f"Re-index found no valid documents to index in '{kb_name}'.")

            completed_at = datetime.now().isoformat()
            metadata_file = kb_dir / "metadata.json"
            try:
                metadata = {}
                if metadata_file.exists():
                    with open(metadata_file, encoding="utf-8") as handle:
                        loaded_metadata = json.load(handle)
                    if isinstance(loaded_metadata, dict):
                        metadata = loaded_metadata
                metadata["last_updated"] = completed_at
                metadata["last_indexed_at"] = completed_at
                metadata["last_indexed_count"] = len(file_paths)
                metadata["last_indexed_action"] = "reindex"
                with open(metadata_file, "w", encoding="utf-8") as handle:
                    json.dump(metadata, handle, indent=2, ensure_ascii=False)
            except Exception as meta_err:
                logger.warning(
                    "Failed to update re-index metadata for '%s': %s",
                    kb_name,
                    meta_err,
                )

            manager = get_kb_manager()
            manager.update_kb_status(
                name=kb_name,
                status="ready",
                progress={
                    "stage": "completed",
                    "message": "Re-index complete",
                    "percent": 100,
                    "current": len(file_paths),
                    "total": len(file_paths),
                    "task_id": task_id,
                    "timestamp": completed_at,
                    "indexed_count": len(file_paths),
                    "index_changed": True,
                    "index_action": "reindex",
                },
            )
            # Clear the legacy mismatch / needs_reindex flags now that an
            # index version matching the active config exists on disk.
            kb_entry = manager.config.get("knowledge_bases", {}).get(kb_name) or {}
            mutated = False
            if kb_entry.get("needs_reindex"):
                kb_entry["needs_reindex"] = False
                mutated = True
            if kb_entry.get("embedding_mismatch"):
                kb_entry.pop("embedding_mismatch", None)
                mutated = True
            if mutated:
                manager._save_config()

            _task_log(task_id, f"Re-index of '{kb_name}' complete", level="success")
            task_manager.update_task_status(task_id, "completed")
            task_stream_manager.emit_complete(task_id, f"Re-index of '{kb_name}' complete")
        except Exception as e:
            import traceback as _tb

            error_msg = str(e)
            trace = _tb.format_exc()
            _task_log(task_id, f"Re-index failed: {error_msg}", level="error")
            _task_log(task_id, f"Stack trace:\n{trace}", level="error")
            task_manager.update_task_status(task_id, "error", error=error_msg)
            try:
                ProgressTracker(kb_name, Path(base_dir)).update(
                    ProgressStage.ERROR,
                    f"Re-index failed: {error_msg}",
                    error=error_msg,
                )
            except Exception:
                pass
            task_stream_manager.emit_failed(task_id, error_msg, details=trace)


@router.post("/{kb_name}/reindex")
async def reindex_knowledge_base(
    kb_name: str,
    background_tasks: BackgroundTasks,
):
    """Re-index ``kb_name`` through its bound RAG provider.

    LlamaIndex still keys versions by the active embedding model. The other
    providers keep synthetic provider-keyed versions, so they should rebuild
    without requiring an embedding-signature precheck.
    """
    try:
        manager, kb_name, kb_base_dir = _writable_kb(kb_name)
        kb_entry = _load_kb_entry_or_404(manager, kb_name)
        _assert_not_connected_kb(kb_name, kb_entry)
        force_reindex = str(kb_entry.get("status") or "").lower() == "error"
        kb_provider = _validate_registered_provider(
            kb_entry.get("rag_provider") or DEFAULT_PROVIDER
        )
        _assert_provider_ready(kb_provider)

        kb_dir = kb_base_dir / kb_name
        signature_hash = kb_provider
        if provider_uses_embedding_versions(kb_provider):
            from deeptutor.services.rag.embedding_signature import signature_from_embedding_config
            from deeptutor.services.rag.index_versioning import (
                find_matching_version,
            )

            signature = signature_from_embedding_config()
            if signature is None:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "No embedding model is configured. Set up the embedding "
                        "profile in Settings before re-indexing."
                    ),
                )

            signature_hash = signature.hash()
            matching_version = find_matching_version(kb_dir, signature)
            matching_valid = _matching_index_is_valid(kb_name, matching_version)
            if (
                matching_version
                and matching_version.get("layout") == "flat"
                and matching_valid
                and not force_reindex
            ):
                return {
                    "message": (
                        f"Knowledge base '{kb_name}' already has an index for the "
                        "active embedding configuration; no reindex needed."
                    ),
                    "task_id": None,
                    "signature": signature_hash,
                    "noop": True,
                }

        task_id = _build_unique_task_id("kb_reindex", kb_name)
        get_task_stream_manager().ensure_task(task_id)

        manager.update_kb_status(
            name=kb_name,
            status="initializing",
            progress={
                "stage": "starting",
                "message": "Queueing re-index...",
                "percent": 0,
                "task_id": task_id,
                "timestamp": datetime.now().isoformat(),
            },
        )

        background_tasks.add_task(
            run_reindex_task,
            kb_name=kb_name,
            base_dir=str(kb_base_dir),
            task_id=task_id,
            signature_hash=signature_hash,
        )

        return {
            "message": f"Re-indexing '{kb_name}' in the background.",
            "task_id": task_id,
            "signature": signature_hash,
            "noop": False,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start reindex for '{kb_name}': {e}")
        raise HTTPException(status_code=500, detail=format_exception_message(e))


@router.post("/{kb_name}/retry")
async def retry_knowledge_base(
    kb_name: str,
    background_tasks: BackgroundTasks,
):
    """Retry a failed KB initialization/indexing run from its stored raw files."""
    try:
        manager, resolved_name, _ = _writable_kb(kb_name)
        kb_entry = _load_kb_entry_or_404(manager, resolved_name)
        status = str(kb_entry.get("status") or "").lower()
        progress = kb_entry.get("progress") if isinstance(kb_entry.get("progress"), dict) else {}
        progress_stage = str(progress.get("stage") or "").lower()
        if status != "error" and progress_stage != "error":
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Knowledge base '{resolved_name}' is not in an error state. "
                    "Use re-index when you want to rebuild a healthy knowledge base."
                ),
            )
        return await reindex_knowledge_base(resolved_name, background_tasks)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to retry KB '{kb_name}': {e}")
        raise HTTPException(status_code=500, detail=format_exception_message(e))


@router.get("/{kb_name}/progress")
async def get_progress(kb_name: str):
    """Get initialization progress for a knowledge base"""
    try:
        resource = resolve_kb(kb_name)
        progress_tracker = ProgressTracker(resource.name, resource.base_dir)
        progress = progress_tracker.get_progress()

        if progress is None:
            return {"status": "not_started", "message": "Initialization not started"}

        return progress
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{kb_name}/progress/clear")
async def clear_progress(kb_name: str):
    """Clear progress file for a knowledge base (useful for stuck states)"""
    try:
        _, resolved_name, base_dir = _writable_kb(kb_name)
        progress_tracker = ProgressTracker(resolved_name, base_dir)
        progress_tracker.clear()
        return {"status": "success", "message": f"Progress cleared for {kb_name}"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.websocket("/{kb_name}/progress/ws")
async def websocket_progress(websocket: WebSocket, kb_name: str):
    """WebSocket endpoint for real-time progress updates"""
    from deeptutor.api.routers.auth import ws_auth_failed, ws_require_auth
    from deeptutor.multi_user.context import reset_current_user

    user_token = await ws_require_auth(websocket)
    if user_token is ws_auth_failed:
        return

    await websocket.accept()

    broadcaster = ProgressBroadcaster.get_instance()

    try:
        await broadcaster.connect(kb_name, websocket)

        base_dir = _current_kb_base_dir()
        progress_tracker = ProgressTracker(kb_name, base_dir)
        initial_progress = progress_tracker.get_progress()
        expected_task_id = websocket.query_params.get("task_id")

        try:
            kb_info = KnowledgeBaseManager(base_dir=str(base_dir)).get_info(kb_name)
            kb_is_ready = bool(kb_info.get("statistics", {}).get("rag_initialized"))
        except Exception:
            kb_is_ready = False

        # Fast path: no active task — send current state and close immediately
        # This prevents infinite polling loops for ready or legacy KBs.
        has_active_task = False
        if initial_progress:
            stage = initial_progress.get("stage")
            if stage not in ("completed", "error", None):
                ts = initial_progress.get("timestamp")
                if ts:
                    try:
                        age = (datetime.now() - datetime.fromisoformat(ts)).total_seconds()
                        has_active_task = age < 120
                    except Exception:
                        pass

        if not has_active_task and not expected_task_id:
            if kb_is_ready:
                await websocket.send_json(
                    {
                        "type": "progress",
                        "data": {
                            "stage": "completed",
                            "message": "Knowledge base is ready.",
                            "percent": 100,
                            "current": 1,
                            "total": 1,
                        },
                    }
                )
            else:
                await websocket.send_json(
                    {
                        "type": "progress",
                        "data": initial_progress
                        or {
                            "stage": "error",
                            "message": "Knowledge base needs reindex or initialization.",
                        },
                    }
                )
            return

        if initial_progress:
            stage = initial_progress.get("stage")
            timestamp = initial_progress.get("timestamp")
            progress_task_id = initial_progress.get("task_id")

            should_send = False
            if expected_task_id and progress_task_id and progress_task_id != expected_task_id:
                should_send = False
            elif stage == "error" or not kb_is_ready:
                should_send = True
            elif stage != "completed" and timestamp:
                try:
                    progress_time = datetime.fromisoformat(timestamp)
                    now = datetime.now()
                    age_seconds = (now - progress_time).total_seconds()
                    if age_seconds < 300:
                        should_send = True
                except Exception:
                    pass

            if should_send:
                await websocket.send_json({"type": "progress", "data": initial_progress})

        last_progress = initial_progress
        last_timestamp = initial_progress.get("timestamp") if initial_progress else None

        while True:
            try:
                try:
                    await asyncio.wait_for(websocket.receive_text(), timeout=1.0)
                except asyncio.TimeoutError:
                    current_progress = progress_tracker.get_progress()
                    if current_progress:
                        progress_task_id = current_progress.get("task_id")
                        if (
                            expected_task_id
                            and progress_task_id
                            and progress_task_id != expected_task_id
                        ):
                            continue
                        current_timestamp = current_progress.get("timestamp")
                        if current_timestamp != last_timestamp:
                            await websocket.send_json(
                                {"type": "progress", "data": current_progress}
                            )
                            last_progress = current_progress
                            last_timestamp = current_timestamp

                            if current_progress.get("stage") in ["completed", "error"]:
                                await asyncio.sleep(3)
                                break
                    continue

            except WebSocketDisconnect:
                break
            except Exception:
                break

    except Exception as e:
        logger.debug(f"Progress WS error: {e}")
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        await broadcaster.disconnect(kb_name, websocket)
        try:
            await websocket.close()
        except Exception:
            pass
        if user_token is not None:
            try:
                reset_current_user(user_token)
            except Exception:
                pass


@router.post("/{kb_name}/link-folder", response_model=LinkedFolderInfo)
async def link_folder(kb_name: str, request: LinkFolderRequest):
    """
    Link a local folder to a knowledge base.

    This allows syncing documents from a local folder (which can be
    synced with SharePoint, Google Drive, OneLake, etc.) to the KB.

    The folder path supports:
    - Absolute paths: /Users/name/Documents or C:\\Users\\name\\Documents
    - Home directory: ~/Documents
    - Relative paths (resolved from server working directory)
    """
    try:
        manager, resolved_name, _ = _writable_kb(kb_name)
        _assert_not_connected_kb(resolved_name, _load_kb_entry_or_404(manager, resolved_name))
        folder_info = manager.link_folder(resolved_name, request.folder_path)
        logger.info(f"Linked folder '{request.folder_path}' to KB '{kb_name}'")
        return LinkedFolderInfo(**folder_info)
    except HTTPException:
        raise
    except ValueError as e:
        error_msg = str(e)
        if "not found" in error_msg.lower():
            raise HTTPException(status_code=404, detail=error_msg)
        raise HTTPException(status_code=400, detail=error_msg)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{kb_name}/linked-folders", response_model=list[LinkedFolderInfo])
async def get_linked_folders(kb_name: str):
    """Get list of linked folders for a knowledge base."""
    try:
        resource = resolve_kb(kb_name)
        manager = manager_for_resource(resource)
        folders = manager.get_linked_folders(resource.name)
        return [LinkedFolderInfo(**f) for f in folders]
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Knowledge base '{kb_name}' not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{kb_name}/linked-folders/{folder_id}")
async def unlink_folder(kb_name: str, folder_id: str):
    """Unlink a folder from a knowledge base."""
    try:
        manager, resolved_name, _ = _writable_kb(kb_name)
        success = manager.unlink_folder(resolved_name, folder_id)
        if not success:
            raise HTTPException(status_code=404, detail=f"Folder '{folder_id}' not found")
        logger.info(f"Unlinked folder '{folder_id}' from KB '{kb_name}'")
        return {"message": "Folder unlinked successfully", "folder_id": folder_id}
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Knowledge base '{kb_name}' not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{kb_name}/sync-folder/{folder_id}")
async def sync_folder(kb_name: str, folder_id: str, background_tasks: BackgroundTasks):
    """
    Sync files from a linked folder to the knowledge base.

    This scans the linked folder for supported documents and processes
    any new files that haven't been added yet.
    """
    try:
        manager, kb_name, kb_base_dir = _writable_kb(kb_name)
        kb_entry = _load_kb_entry_or_404(manager, kb_name)
        _assert_kb_writable_or_409(kb_name, kb_entry)
        kb_provider = _validate_registered_provider(
            kb_entry.get("rag_provider") or DEFAULT_PROVIDER
        )

        # Get linked folders and find the one with matching ID
        folders = manager.get_linked_folders(kb_name)
        folder_info = next((f for f in folders if f["id"] == folder_id), None)

        if not folder_info:
            raise HTTPException(status_code=404, detail=f"Linked folder '{folder_id}' not found")

        folder_path = folder_info["path"]

        # Check for changes (new or modified files)
        changes = manager.detect_folder_changes(kb_name, folder_id)
        files_to_process = changes["new_files"] + changes["modified_files"]

        if not files_to_process:
            return {"message": "No new or modified files to sync", "files": [], "file_count": 0}

        logger.info(
            f"Syncing {len(files_to_process)} files from folder '{folder_path}' to KB '{kb_name}'"
        )
        task_id = _build_unique_task_id("kb_upload", f"{kb_name}_folder_{folder_id}")
        get_task_stream_manager().ensure_task(task_id)

        # NOTE: We DO NOT update sync state here anymore.
        # It is updated in run_upload_processing_task only after successful processing.
        # This prevents marking files as synced if processing fails (race condition fix).

        # Add background task to process files
        background_tasks.add_task(
            run_upload_processing_task,
            kb_name=kb_name,
            base_dir=str(kb_base_dir),
            uploaded_file_paths=files_to_process,
            task_id=task_id,
            rag_provider=kb_provider,
            folder_id=folder_id,  # Pass folder_id to update state on success
        )

        return {
            "message": f"Syncing {len(files_to_process)} files from linked folder",
            "folder_path": folder_path,
            "new_files": changes["new_count"],
            "modified_files": changes["modified_count"],
            "file_count": len(files_to_process),
            "task_id": task_id,
        }
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Knowledge base '{kb_name}' not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
