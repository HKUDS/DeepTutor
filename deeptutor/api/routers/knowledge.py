"""
Knowledge Base API Router
=========================

Handles knowledge base CRUD operations, file uploads, and initialization.
"""

import asyncio
from contextlib import contextmanager
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
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from deeptutor.api.routers.auth import require_admin
from deeptutor.api.utils.progress_broadcaster import ProgressBroadcaster
from deeptutor.api.utils.task_id_manager import TaskIDManager
from deeptutor.api.utils.task_log_stream import capture_task_logs, get_task_stream_manager
from deeptutor.knowledge.add_documents import DocumentAdder, remove_raw_document
from deeptutor.knowledge.initializer import KnowledgeBaseInitializer
from deeptutor.knowledge.kb_types import is_connected_kb, supports_local_raw_files
from deeptutor.knowledge.manager import KnowledgeBaseManager
from deeptutor.knowledge.naming import validate_knowledge_base_name
from deeptutor.knowledge.progress_tracker import ProgressStage, ProgressTracker
from deeptutor.logging import PROCESS_LOG_PRIVATE_ATTR
from deeptutor.multi_user.context import (
    get_current_user,
    get_current_user_or_none,
    reset_current_user,
    set_current_user,
)
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
from deeptutor.services.file_io import atomic_write_json
from deeptutor.services.rag.factory import (
    DEFAULT_PROVIDER,
    GRAPHRAG_PROVIDER,
    LIGHTRAG_PROVIDER,
    PAGEINDEX_OSS_PROVIDER,
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
from deeptutor.services.rag.pipelines.ima.client import (
    MAX_PAGE_LIMIT,
    ImaAPIError,
    ImaAuthError,
    ImaClient,
    ImaRateLimitError,
)
from deeptutor.services.rag.pipelines.ima.config import (
    ImaConfig,
    ImaCredentials,
    get_account_credentials,
)
from deeptutor.utils.document_extractor import (
    MAX_EXTRACTED_CHARS_PER_DOC,
    DocumentExtractionError,
    extract_text_from_path,
    extract_text_from_path_isolated,
)
from deeptutor.utils.document_validator import DocumentValidator
from deeptutor.utils.error_utils import format_exception_message

# Initialize logger with config
config = load_config_with_main("main.yaml", PROJECT_ROOT)
log_dir = config.get("paths", {}).get("user_log_dir") or config.get("logging", {}).get("log_dir")
logger = logging.getLogger(__name__)

router = APIRouter()
ws_router = APIRouter()

_DEFAULT_EXTRACT_TEXT_FROM_PATH = extract_text_from_path

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
    allow_any_extension: bool = False


class IndexingLLMSelectionRequest(BaseModel):
    """Secret-free catalog identity for an empty LightRAG knowledge base."""

    profile_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    reasoning_effort: str | None = None


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


def _mark_kb_queued_for_processing(
    manager: KnowledgeBaseManager,
    kb_name: str,
    task_id: str,
    message: str,
    *,
    status: str = "processing",
) -> None:
    """Flip an existing KB to a live processing status before its background task is dispatched.

    ``run_upload_processing_task`` only writes status once it starts running;
    without this pre-dispatch update the KB keeps reporting ``ready`` between
    the accepted upload/sync response and the task's first progress write.
    Mirrors the pre-dispatch update ``create_knowledge_base`` already does.
    ``stage`` must be a member of the frontend's ``LIVE_PROGRESS_STAGES`` set
    (web/lib/knowledge-helpers.ts).
    """
    manager.update_kb_status(
        name=kb_name,
        status=status,
        progress={
            "stage": "starting",
            "message": message,
            "percent": 0,
            "task_id": task_id,
            "timestamp": datetime.now().isoformat(),
        },
    )


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
    dest_subdir: str = "",
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
                own_subdir = _sanitize_rel_subdir(rel.rsplit("/", 1)[0]) if "/" in rel else ""
                # A browser folder pick reports paths relative to the chosen
                # directory, so its ancestors are simply not in the payload.
                # dest_subdir is how the caller re-attaches the batch to the
                # place it belongs inside the KB (#866).
                subdir = "/".join(part for part in (dest_subdir, own_subdir) if part)
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


async def _save_uploaded_files_off_loop(
    files: list[UploadFile],
    target_dir: Path,
    allowed_extensions: set[str] | None = None,
    kb_name: str | None = None,
    rel_paths: list[str] | None = None,
    dest_subdir: str = "",
) -> tuple[list[str], list[str]]:
    """:func:`_save_uploaded_files` on a worker thread.

    That function blocks end to end — a chunked write of every uploaded byte,
    zip extraction for archive members, and (when PocketBase is enabled) one
    synchronous HTTP upload per file. Called inline from an ``async def``
    route it held the event loop for the whole batch, so every other request
    — chat WebSockets included — stalled until the upload finished (#777).

    Safe to hand to a thread: it only touches ``UploadFile.file``, the plain
    ``SpooledTemporaryFile`` underneath, never the async ``UploadFile`` API.
    """
    return await asyncio.to_thread(
        _save_uploaded_files,
        files,
        target_dir,
        allowed_extensions=allowed_extensions,
        kb_name=kb_name,
        rel_paths=rel_paths,
        dest_subdir=dest_subdir,
    )


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
        log_method(f"[{task_id}] {message}", extra={PROCESS_LOG_PRIVATE_ATTR: True})
    else:
        logger.info(f"[{task_id}] {message}", extra={PROCESS_LOG_PRIVATE_ATTR: True})


def _server_task_trace(task_id: str, trace: str) -> None:
    """Keep a traceback in server logs while excluding it from browser streams."""
    logger.error(
        "[%s] Stack trace:\n%s",
        task_id,
        trace,
        extra={PROCESS_LOG_PRIVATE_ATTR: True},
    )


def _exception_failure_metadata(exc: Exception) -> dict:
    """Extract stable, user-facing failure metadata from a typed exception."""
    metadata = {}
    error_code = getattr(exc, "code", None)
    retryable = getattr(exc, "retryable", None)
    if isinstance(error_code, str) and error_code:
        metadata["error_code"] = error_code
    if isinstance(retryable, bool):
        metadata["retryable"] = retryable
    return metadata


def _validate_registered_provider(raw_provider: str | None) -> str:
    """Resolve a requested provider to a known engine.

    Empty / legacy / unknown strings coerce to the default (so a stale config or
    a removed engine never selects a missing pipeline). Returning the real,
    canonical provider is what makes the per-KB lock meaningful: the upload route
    compares the requested provider against the KB's bound provider, so asking to
    add to a ``pageindex`` KB with ``llamaindex`` (or vice versa) is rejected.
    """
    return normalize_provider_name(raw_provider)


def _freeze_indexing_llm_form(raw: str):
    """Parse and resolve the optional LightRAG selection exactly once."""
    from deeptutor.services.rag.pipelines.lightrag.indexing_policy import (
        IndexingPolicyError,
        freeze_snapshot,
    )

    try:
        selection = json.loads(raw)
        if not isinstance(selection, dict) or not selection:
            raise ValueError("indexing_llm must be a non-empty JSON object.")
        return selection, freeze_snapshot(selection)
    except (json.JSONDecodeError, ValueError, PermissionError, IndexingPolicyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _freeze_default_indexing_llm():
    """Freeze the released LightRAG model default for one create or rebuild."""
    from deeptutor.services.rag.pipelines.lightrag.indexing_policy import (
        IndexingPolicyError,
        freeze_default_snapshot,
    )

    try:
        return freeze_default_snapshot()
    except (ValueError, PermissionError, IndexingPolicyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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

    if provider == PAGEINDEX_OSS_PROVIDER:
        from deeptutor.services.rag.preflight import engine_preflight

        report = engine_preflight(provider)
        failed_checks = [
            check
            for check in report.get("checks", [])
            if not check.get("optional") and not check.get("ok")
        ]
        if failed_checks:
            details = "; ".join(
                str(check.get("detail") or check.get("label") or "Requirement not met")
                for check in failed_checks
            )
            raise HTTPException(
                status_code=409, detail=f"PageIndex OSS preflight failed: {details}"
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

        from deeptutor.services.rag.preflight import engine_preflight

        report = engine_preflight(provider)
        failed_checks = [
            check
            for check in report.get("checks", [])
            if not check.get("optional") and not check.get("ok")
        ]
        if failed_checks:
            failure_details = "; ".join(
                str(check.get("detail") or check.get("label") or "Requirement not met")
                for check in failed_checks
            )
            raise HTTPException(
                status_code=409,
                detail=f"GraphRAG preflight failed: {failure_details}",
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
    """Reject files PageIndex's document endpoint does not accept, up front."""
    if provider not in {PAGEINDEX_PROVIDER, PAGEINDEX_OSS_PROVIDER}:
        return
    from deeptutor.services.rag.pipelines.pageindex.pipeline import (
        OSS_SUPPORTED_EXTENSIONS,
        SUPPORTED_EXTENSIONS,
    )

    extensions = (
        OSS_SUPPORTED_EXTENSIONS if provider == PAGEINDEX_OSS_PROVIDER else SUPPORTED_EXTENSIONS
    )

    unsupported = [
        f.filename
        for f in files
        if f.filename
        and not (provider == PAGEINDEX_PROVIDER and f.filename.lower().endswith(".zip"))
        and Path(f.filename).suffix.lower() not in extensions
    ]
    if unsupported:
        supported = ", ".join(sorted(extensions))
        raise HTTPException(
            status_code=400,
            detail=(
                f"PageIndex knowledge bases accept: {supported}. "
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
                f"Knowledge base '{kb_name}' is connected to an external resource and is "
                "read-only. Local file operations and re-indexing are not available for it."
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
    owner = getattr(initializer, "owner", None)
    if owner is not None and get_current_user_or_none() != owner:
        token = set_current_user(owner)
        try:
            return await run_initialization_task(initializer, task_id)
        finally:
            reset_current_user(token)

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
                message_key="Knowledge base initialization complete!",
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
            if getattr(initializer, "index_published", False):
                _task_log(
                    task_id,
                    "LightRAG index was published; final status bookkeeping will be reconciled.",
                    level="warning",
                )
                _server_task_trace(task_id, trace)
                task_manager.update_task_status(task_id, "completed")
                task_stream_manager.emit_complete(
                    task_id,
                    f"Knowledge base '{initializer.kb_name}' index published",
                )
                return
            failure_metadata = _exception_failure_metadata(e)

            _task_log(task_id, f"Initialization failed: {error_msg}", level="error")
            _server_task_trace(task_id, trace)

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
                    **failure_metadata,
                    "task_id": task_id,
                    "timestamp": datetime.now().isoformat(),
                },
            )

            if initializer.progress_tracker:
                initializer.progress_tracker.update(
                    ProgressStage.ERROR,
                    message_key="Initialization failed: {{error}}",
                    message_params={"error": error_msg},
                    error=error_msg,
                    **failure_metadata,
                )
            task_stream_manager.emit_failed(task_id, error_msg, **failure_metadata)


async def run_upload_processing_task(
    kb_name: str,
    base_dir: str,
    uploaded_file_paths: list[str],
    task_id: str,
    rag_provider: str = None,
    folder_id: str = None,
    folder_root: str = None,
    owner=None,
):
    """Background task for processing uploaded files.

    Args:
        kb_name: Knowledge base name
        base_dir: Base directory for knowledge bases
        uploaded_file_paths: List of file paths to process
        rag_provider: RAG provider already matched against the KB binding
        folder_id: Optional folder ID for sync state update
        folder_root: Linked folder's own root path, when these files came
            from a folder sync. Preserves each file's path relative to it
            instead of flattening to the bare filename.
    """
    if owner is not None and get_current_user_or_none() != owner:
        token = set_current_user(owner)
        try:
            return await run_upload_processing_task(
                kb_name=kb_name,
                base_dir=base_dir,
                uploaded_file_paths=uploaded_file_paths,
                task_id=task_id,
                rag_provider=rag_provider,
                folder_id=folder_id,
                folder_root=folder_root,
            )
        finally:
            reset_current_user(token)

    task_manager = TaskIDManager.get_instance()
    task_stream_manager = get_task_stream_manager()
    task_stream_manager.ensure_task(task_id)
    index_published = False

    progress_tracker = ProgressTracker(kb_name, Path(base_dir))
    progress_tracker.task_id = task_id

    with capture_task_logs(task_id):
        try:
            _task_log(task_id, f"Processing {len(uploaded_file_paths)} file(s) for KB '{kb_name}'")
            progress_tracker.update(
                ProgressStage.PROCESSING_DOCUMENTS,
                message_key="Validating {{count}} file(s)...",
                message_params={"count": len(uploaded_file_paths)},
                current=0,
                total=len(uploaded_file_paths),
            )

            adder = DocumentAdder(
                kb_name=kb_name,
                base_dir=base_dir,
                progress_tracker=progress_tracker,
                rag_provider=rag_provider,
            )

            # Staging blocks: a full-content hash per file, plus a copy for
            # anything not already under raw/. A BackgroundTasks entry declared
            # ``async def`` is awaited ON the event loop — starlette only routes
            # *sync* callables to its threadpool — so doing this inline stalled
            # every other request for the length of the batch (#777).
            staged_files = await asyncio.to_thread(
                adder.add_documents,
                uploaded_file_paths,
                allow_duplicates=False,
                source_root=folder_root,
            )
            _task_log(task_id, f"Staged {len(staged_files)} new file(s)")
            progress_tracker.update(
                ProgressStage.PROCESSING_DOCUMENTS,
                message_key="Staged {{count}} new file(s)",
                message_params={"count": len(staged_files)},
                current=0,
                total=len(staged_files),
            )

            if not staged_files:
                _task_log(task_id, "No new files to process (all duplicates or invalid)")
                progress_tracker.update(
                    ProgressStage.COMPLETED,
                    message_key="No new files to process (all duplicates or invalid)",
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
                    message_key="Processing failed: {{error}}",
                    message_params={"error": error_msg},
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

            index_published = rag_provider == LIGHTRAG_PROVIDER and bool(
                index_result.processed_count
            )

            progress_tracker.update(
                ProgressStage.PROCESSING_DOCUMENTS,
                message_key="Saving metadata...",
                current=index_result.processed_count,
                total=len(staged_files),
            )
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
                message_key="Successfully processed {{count}} files!",
                message_params={"count": num_processed},
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
            if index_published:
                _task_log(
                    task_id,
                    "LightRAG index changes were published; final upload bookkeeping "
                    "will be reconciled.",
                    level="warning",
                )
                _server_task_trace(task_id, trace)
                task_manager.update_task_status(task_id, "completed")
                task_stream_manager.emit_complete(
                    task_id, f"LightRAG changes for '{kb_name}' published"
                )
                return
            failure_metadata = _exception_failure_metadata(e)
            _task_log(task_id, error_msg, level="error")
            _server_task_trace(task_id, trace)

            task_manager.update_task_status(task_id, "error", error=error_msg)

            progress_tracker.update(
                ProgressStage.ERROR,
                message_key="Processing failed: {{error}}",
                message_params={"error": error_msg},
                error=error_msg,
                **failure_metadata,
            )
            task_stream_manager.emit_failed(task_id, error_msg, **failure_metadata)


@router.get("/knowledge-bases/health")
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


@router.get("/knowledge-bases/rag-providers")
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


@router.put("/knowledge-bases/rag-providers/{provider}/mode")
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


def _pageindex_config_payload() -> dict:
    """PageIndex pipeline settings for the UI, with the API key redacted."""
    from deeptutor.services.config import get_runtime_settings_service

    settings = get_runtime_settings_service().load_pageindex()
    return {
        "api_key_set": bool(settings.get("api_key")),
        "configured": bool(settings.get("api_key")),
    }


@router.get("/knowledge-bases/rag-pipelines/pageindex/config")
async def get_pageindex_pipeline_config():
    """Read the PageIndex credential state (key redacted to a boolean)."""
    try:
        return _pageindex_config_payload()
    except Exception as e:
        logger.error(f"Error reading PageIndex config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/knowledge-bases/rag-pipelines/pageindex/config")
async def update_pageindex_pipeline_config(payload: PageIndexConfigUpdate):
    """Persist the deployment-level PageIndex Cloud credential."""
    try:
        from deeptutor.services.config import get_runtime_settings_service

        service = get_runtime_settings_service()
        current = service.load_pageindex(include_process_overrides=False)

        api_key = current.get("api_key", "")
        if payload.api_key is not None:
            api_key = payload.api_key.strip()

        service.save_pageindex({"api_key": api_key})

        return _pageindex_config_payload()
    except Exception as e:
        logger.error(f"Error updating PageIndex config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class ImaConfigUpdate(BaseModel):
    # Same tri-state as PageIndex for the secret half of the pair: omit/None
    # keeps the stored key, "" clears it, any other value replaces it. The
    # Client ID is not a secret and round-trips in the clear.
    client_id: str | None = None
    api_key: str | None = None


def _ima_config_payload() -> dict:
    """Account-level IMA credential state for the UI, with the key redacted."""
    from deeptutor.services.config import get_runtime_settings_service

    settings = get_runtime_settings_service().load_ima()
    client_id = str(settings.get("client_id") or "")
    api_key_set = bool(settings.get("api_key"))
    return {
        "client_id": client_id,
        "api_key_set": api_key_set,
        "configured": bool(client_id) and api_key_set,
    }


@router.get("/knowledge-bases/rag-pipelines/ima/config")
async def get_ima_pipeline_config():
    """Read the account-level IMA credentials (key redacted to a boolean)."""
    try:
        return _ima_config_payload()
    except Exception as e:
        logger.error(f"Error reading IMA config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/knowledge-bases/rag-pipelines/ima/config")
async def update_ima_pipeline_config(payload: ImaConfigUpdate):
    """Persist the account-level IMA Client ID / API key."""
    try:
        from deeptutor.services.config import get_runtime_settings_service

        service = get_runtime_settings_service()
        current = service.load_ima(include_process_overrides=False)

        client_id = current.get("client_id", "")
        if payload.client_id is not None:
            client_id = payload.client_id.strip()

        api_key = current.get("api_key", "")
        if payload.api_key is not None:
            api_key = payload.api_key.strip()

        service.save_ima({"client_id": client_id, "api_key": api_key})
        return _ima_config_payload()
    except Exception as e:
        logger.error(f"Error updating IMA config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class LlamaIndexConfigUpdate(BaseModel):
    """Partial update for the LlamaIndex engine knobs (omitted fields kept)."""

    retrieval_profile: str | None = None
    top_k: int | None = None
    vector_top_k_multiplier: int | None = None
    bm25_top_k_multiplier: int | None = None
    reranker_model: str | None = None
    rerank_top_k: int | None = None
    vector_index_type: str | None = None
    hnsw_m: int | None = None
    hnsw_ef_construction: int | None = None
    hnsw_ef_search: int | None = None
    chunk_size: int | None = None
    chunk_overlap: int | None = None
    image_description_concurrency: int | None = None
    image_description_timeout_seconds: int | None = None


@router.get("/knowledge-bases/rag-pipelines/llamaindex/config")
async def get_llamaindex_pipeline_config():
    """Read the LlamaIndex engine's retrieval + chunking knobs."""
    try:
        from deeptutor.services.config import get_runtime_settings_service

        return get_runtime_settings_service().load_llamaindex()
    except Exception as e:
        logger.error(f"Error reading LlamaIndex config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/knowledge-bases/rag-pipelines/llamaindex/config")
async def update_llamaindex_pipeline_config(payload: LlamaIndexConfigUpdate):
    """Persist the LlamaIndex engine knobs.

    Retrieval knobs take effect on the next query; indexing knobs only affect
    documents processed after the save.
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


@router.get("/knowledge-bases/rag-pipelines/graphrag/config")
async def get_graphrag_pipeline_config():
    """Read GraphRAG's query knobs (response style, community granularity)."""
    try:
        from deeptutor.services.config import get_runtime_settings_service

        return get_runtime_settings_service().load_graphrag()
    except Exception as e:
        logger.error(f"Error reading GraphRAG config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/knowledge-bases/rag-pipelines/graphrag/config")
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
    """Partial update for LightRAG query + indexing knobs (omitted fields kept)."""

    top_k: int | None = None
    response_type: str | None = None
    max_concurrent_files: int | None = None
    llm_model_max_async: int | None = None
    entity_extract_max_gleaning: int | None = None
    llm_profile_id: str | None = None
    llm_model_id: str | None = None


def _validate_lightrag_llm_selection(profile_id: str, model_id: str) -> None:
    """Keep stored LightRAG references inside the configured model catalog."""
    if bool(profile_id) != bool(model_id):
        raise HTTPException(
            status_code=422,
            detail="LightRAG model selection requires both profile_id and model_id.",
        )
    if not profile_id:
        return
    try:
        from deeptutor.services.config import get_model_catalog_service
        from deeptutor.services.model_selection import (
            LLMSelection,
            apply_llm_selection_to_catalog,
        )

        selection = LLMSelection.from_payload({"profile_id": profile_id, "model_id": model_id})
        apply_llm_selection_to_catalog(get_model_catalog_service().load(), selection)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.get("/knowledge-bases/rag-pipelines/lightrag/config")
async def get_lightrag_pipeline_config():
    """Read LightRAG's query knobs plus its indexing concurrency/extraction knobs."""
    try:
        from deeptutor.services.config import get_runtime_settings_service

        return get_runtime_settings_service().load_lightrag()
    except Exception as e:
        logger.error(f"Error reading LightRAG config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/knowledge-bases/rag-pipelines/lightrag/config")
async def update_lightrag_pipeline_config(payload: LightRagConfigUpdate):
    """Persist LightRAG's knobs.

    Query knobs (``top_k``, ``response_type``) take effect on the next query;
    the indexing knobs shape how a KB is built, so they apply to the next
    build or rebuild.
    """
    try:
        from deeptutor.services.config import get_runtime_settings_service

        service = get_runtime_settings_service()
        current = service.load_lightrag()
        updates = payload.model_dump(exclude_none=True)
        candidate = {**current, **updates}
        _validate_lightrag_llm_selection(
            str(candidate.get("llm_profile_id") or ""),
            str(candidate.get("llm_model_id") or ""),
        )
        return service.save_lightrag({**current, **updates})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating LightRAG config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class LightRagServerConfigUpdate(BaseModel):
    """Reusable LightRAG Server defaults (individual KBs may override them)."""

    server_url: str | None = None
    api_key: str | None = None


def _lightrag_server_config_payload() -> dict:
    from deeptutor.services.config import get_runtime_settings_service

    settings = get_runtime_settings_service().load_lightrag_server()
    server_url = str(settings.get("server_url") or "")
    api_key_set = bool(settings.get("api_key"))
    return {
        "server_url": server_url,
        "api_key_set": api_key_set,
        "configured": bool(server_url),
    }


@router.get("/knowledge-bases/rag-pipelines/lightrag-server/config")
async def get_lightrag_server_pipeline_config():
    """Read reusable server defaults with the API key redacted."""
    try:
        return _lightrag_server_config_payload()
    except Exception as e:
        logger.error(f"Error reading LightRAG Server config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/knowledge-bases/rag-pipelines/lightrag-server/config")
async def update_lightrag_server_pipeline_config(payload: LightRagServerConfigUpdate):
    """Persist reusable defaults without changing existing KB bindings."""
    try:
        from deeptutor.services.config import get_runtime_settings_service
        from deeptutor.services.rag.pipelines.lightrag_server.config import normalize_base_url

        service = get_runtime_settings_service()
        current = service.load_lightrag_server()
        server_url = current.get("server_url", "")
        if payload.server_url is not None:
            server_url = normalize_base_url(payload.server_url)
        api_key = current.get("api_key", "")
        if payload.api_key is not None:
            api_key = payload.api_key.strip()
        service.save_lightrag_server({"server_url": server_url, "api_key": api_key})
        return _lightrag_server_config_payload()
    except Exception as e:
        logger.error(f"Error updating LightRAG Server config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/knowledge-bases/rag-pipelines/{provider}/preflight")
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


@router.get("/knowledge-bases/rag-pipelines/model-options")
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


class GraphRagModelCompatibilityRequest(BaseModel):
    """Configured chat-model candidate to test without activating it."""

    profile_id: str
    model_id: str


async def _probe_graphrag_model_compatibility(profile_id: str, model_id: str) -> dict:
    """Resolve and probe a configured GraphRAG chat-model candidate."""
    from deeptutor.services.rag.pipelines.graphrag.compatibility import (
        probe_configured_completion_model,
    )

    return await probe_configured_completion_model(profile_id, model_id)


@router.post("/knowledge-bases/rag-pipelines/graphrag/model-compatibility")
async def test_graphrag_model_compatibility(payload: GraphRagModelCompatibilityRequest):
    """Test GraphRAG structured output without changing the active chat model."""
    try:
        return await _probe_graphrag_model_compatibility(payload.profile_id, payload.model_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("Unexpected error testing GraphRAG model compatibility")
        raise HTTPException(
            status_code=500,
            detail="GraphRAG compatibility could not be tested because of an internal error.",
        ) from e


class ActiveModelUpdate(BaseModel):
    """Switch the globally-active model for a kind (llm / embedding)."""

    kind: str
    profile_id: str
    model_id: str


@router.put("/knowledge-bases/rag-pipelines/active-model")
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


@router.get("/knowledge-bases/supported-file-types", response_model=SupportedFileTypesInfo)
async def get_supported_file_types():
    """Return the current upload policy so the web client stays in sync."""
    allow_any_extension = FileTypeRouter.active_parser_accepts_any_format()
    extensions = [] if allow_any_extension else sorted(FileTypeRouter.get_supported_extensions())
    accept_items = (
        []
        if allow_any_extension
        else extensions
        + [
            mime
            for extension, mime in sorted(IMAGE_ACCEPT_MIME_TYPES.items())
            if extension in FileTypeRouter.IMAGE_EXTENSIONS
        ]
    )
    return SupportedFileTypesInfo(
        extensions=extensions,
        accept=",".join(dict.fromkeys(accept_items)),
        max_file_size_bytes=DocumentValidator.MAX_FILE_SIZE,
        allow_any_extension=allow_any_extension,
    )


@router.get("/knowledge-bases/configs")
async def get_all_kb_configs():
    """Get all knowledge base configurations from centralized config file."""
    try:
        from deeptutor.services.config import get_kb_config_service

        service = get_kb_config_service()
        return service.get_all_configs()
    except Exception as e:
        logger.error(f"Error getting KB configs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/knowledge-bases/{kb_name}/config")
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


@router.put("/knowledge-bases/{kb_name}/config")
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


@router.post("/knowledge-bases/configs/sync")
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


@router.get("/knowledge-bases/default")
async def get_default_kb():
    """Get the default knowledge base."""
    try:
        manager = get_kb_manager()
        default_kb = manager.get_default()
        return {"default_kb": default_kb}
    except Exception as e:
        logger.error(f"Error getting default KB: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/knowledge-bases/default/{kb_name}")
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


@router.post("/knowledge-bases/connect-obsidian")
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


class ConnectMarginNote4Request(BaseModel):
    name: str
    db_path: str = ""
    description: str = ""


@router.post("/knowledge-bases/connect-marginnote4")
async def connect_marginnote4(payload: ConnectMarginNote4Request):
    """Register a connected MarginNote 4 library as a knowledge base.

    Creates a ``type: marginnote4`` pointer so the MarginNote capability can
    bind to it on turns where the user selects this KB. When ``db_path`` is
    omitted the capability derives a default SQLite path from the KB name.
    """
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required.")
    try:
        manager = get_kb_manager()
        entry = manager.register_marginnote4_kb(
            name,
            db_path=(payload.db_path or "").strip(),
            description=(payload.description or "").strip(),
        )
        result = {"status": "connected", "name": name}
        if entry.get("db_path"):
            result["db_path"] = entry["db_path"]
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error connecting MarginNote 4 library: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class ProbeFolderRequest(BaseModel):
    folder_path: str
    rag_provider: str = DEFAULT_PROVIDER


class ConnectFolderRequest(BaseModel):
    name: str
    folder_path: str
    rag_provider: str = DEFAULT_PROVIDER


@router.post("/knowledge-bases/probe-folder")
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


@router.post("/knowledge-bases/connect-folder")
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
    use_saved_api_key: bool = False


class ConnectLightRagServerRequest(BaseModel):
    name: str
    server_url: str
    api_key: str = ""
    search_mode: str = ""


class ProbeWeKnoraRequest(BaseModel):
    server_url: str
    api_key: str
    knowledge_base_id: str


class ConnectWeKnoraRequest(BaseModel):
    name: str
    server_url: str
    api_key: str
    knowledge_base_id: str


@router.post("/knowledge-bases/probe-lightrag-server")
async def probe_lightrag_server_route(payload: ProbeLightRagServerRequest):
    """Test-connect to an external LightRAG server before binding a KB to it.

    Returns the verdict (reachable? is it a LightRAG server? API key accepted?)
    so the UI can confirm before any registration happens. Creates nothing.
    """
    from deeptutor.services.rag.pipelines.lightrag_server.probe import probe_server

    server_url = (payload.server_url or "").strip()
    if not server_url:
        raise HTTPException(status_code=400, detail="server_url is required.")
    api_key = payload.api_key or ""
    if payload.use_saved_api_key and not api_key:
        from deeptutor.services.config import load_lightrag_server_settings
        from deeptutor.services.rag.pipelines.lightrag_server.config import normalize_base_url

        defaults = load_lightrag_server_settings()
        if normalize_base_url(defaults.get("server_url")) == normalize_base_url(server_url):
            api_key = str(defaults.get("api_key") or "")
    result = await probe_server(server_url, api_key)
    return result.to_dict()


@router.post("/knowledge-bases/connect-lightrag-server")
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

    api_key = payload.api_key or ""
    if not api_key:
        from deeptutor.services.config import load_lightrag_server_settings
        from deeptutor.services.rag.pipelines.lightrag_server.config import normalize_base_url

        defaults = load_lightrag_server_settings()
        if normalize_base_url(defaults.get("server_url")) == normalize_base_url(server_url):
            api_key = str(defaults.get("api_key") or "")

    result = await probe_server(server_url, api_key)
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
            api_key=api_key,
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


@router.post("/knowledge-bases/probe-weknora", dependencies=[Depends(require_admin)])
async def probe_weknora_route(payload: ProbeWeKnoraRequest):
    """Validate a WeKnora server and knowledge-base binding without registering."""
    from deeptutor.services.rag.pipelines.weknora.probe import probe_weknora

    server_url = (payload.server_url or "").strip()
    knowledge_base_id = (payload.knowledge_base_id or "").strip()
    if not server_url or not knowledge_base_id:
        raise HTTPException(
            status_code=400,
            detail="Both server_url and knowledge_base_id are required.",
        )
    result = await probe_weknora(
        server_url,
        payload.api_key or "",
        knowledge_base_id,
    )
    return result.to_dict()


@router.post("/knowledge-bases/connect-weknora", dependencies=[Depends(require_admin)])
async def connect_weknora_route(payload: ConnectWeKnoraRequest):
    """Connect a self-hosted WeKnora knowledge base for retrieval only."""
    from deeptutor.services.rag.pipelines.weknora.probe import probe_weknora

    name = (payload.name or "").strip()
    server_url = (payload.server_url or "").strip()
    knowledge_base_id = (payload.knowledge_base_id or "").strip()
    if not name or not server_url or not knowledge_base_id:
        raise HTTPException(
            status_code=400,
            detail="name, server_url, and knowledge_base_id are required.",
        )

    result = await probe_weknora(
        server_url,
        payload.api_key or "",
        knowledge_base_id,
    )
    if not result.ok:
        raise HTTPException(
            status_code=400,
            detail=result.error or "Could not connect to the WeKnora knowledge base.",
        )

    try:
        manager = get_kb_manager()
        entry = manager.register_weknora_kb(
            name,
            result.base_url,
            payload.api_key or "",
            result.knowledge_base_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error connecting WeKnora knowledge base: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "status": "connected",
        "name": name,
        "server_url": entry["server_url"],
        "knowledge_base_id": entry["knowledge_base_id"],
        "rag_provider": entry["rag_provider"],
    }


class ListImaRequest(BaseModel):
    # Empty means "use the account-level credentials from the engine settings",
    # so the connect flow never has to re-send what is already stored.
    client_id: str = ""
    api_key: str = ""
    cursor: str = ""
    # IMA documents this call's page size as 1..50; the picker asks for one
    # screenful and pages for the rest.
    limit: int = Field(default=20, ge=1, le=MAX_PAGE_LIMIT)


class ImaKnowledgeBaseSummary(BaseModel):
    id: str
    name: str
    description: str | None = None


class ListImaResponse(BaseModel):
    knowledge_bases: list[ImaKnowledgeBaseSummary]
    next_cursor: str
    is_end: bool


def _resolve_ima_credentials(client_id: str, api_key: str) -> ImaCredentials:
    """A request's credentials, falling back to the account-level pair.

    A request that supplies only one half is not silently completed from the
    account pair: mixing two accounts' halves would fail at IMA with a confusing
    verdict.
    """
    supplied = ImaCredentials(client_id=(client_id or "").strip(), api_key=(api_key or "").strip())
    if supplied.client_id or supplied.api_key:
        return supplied
    return get_account_credentials()


@router.post("/knowledge-bases/list-ima", response_model=ListImaResponse)
async def list_ima_route(payload: ListImaRequest):
    """List IMA knowledge bases without storing or echoing credentials."""
    credentials = _resolve_ima_credentials(payload.client_id, payload.api_key)
    if not credentials.complete:
        raise HTTPException(status_code=400, detail="Client ID and API key are required.")

    client = ImaClient(
        ImaConfig(
            client_id=credentials.client_id,
            api_key=credentials.api_key,
            knowledge_base_id="",
        )
    )
    try:
        return await client.search_knowledge_bases(
            query="",
            cursor=payload.cursor.strip(),
            limit=payload.limit,
        )
    except ImaAuthError:
        raise HTTPException(status_code=401, detail="IMA rejected the supplied credentials.")
    except ImaRateLimitError:
        raise HTTPException(status_code=429, detail="IMA rate limit reached. Try again shortly.")
    except ImaAPIError:
        raise HTTPException(status_code=502, detail="IMA returned an invalid response.")
    except Exception:
        raise HTTPException(status_code=502, detail="Could not reach Tencent IMA.")


class ProbeImaRequest(BaseModel):
    client_id: str = ""
    api_key: str = ""
    knowledge_base_id: str


class ConnectImaRequest(BaseModel):
    name: str
    client_id: str = ""
    api_key: str = ""
    knowledge_base_id: str


@router.post("/knowledge-bases/probe-ima")
async def probe_ima_route(payload: ProbeImaRequest):
    """Test-connect to a Tencent IMA knowledge base before binding a KB to it.

    Returns the verdict (credentials accepted? does the library id resolve, and
    what is it called?) so the UI can confirm before any registration happens.
    Creates nothing.
    """
    from deeptutor.services.rag.pipelines.ima.probe import probe_knowledge_base

    credentials = _resolve_ima_credentials(payload.client_id, payload.api_key)
    result = await probe_knowledge_base(
        credentials.client_id,
        credentials.api_key,
        payload.knowledge_base_id,
    )
    return result.to_dict()


@router.post("/knowledge-bases/connect-ima")
async def connect_ima_route(payload: ConnectImaRequest):
    """Connect a Tencent IMA knowledge base as a retrieval-only knowledge base.

    Re-probes server-side (never trusts the client's verdict), then registers a
    pointer (``type: ima``). Retrieval is offloaded to IMA's ``search_knowledge``
    OpenAPI — no copy, no local index.

    Credentials the request omits come from the account-level settings and are
    *not* copied onto the KB, so rotating them there keeps this KB working.
    """
    from deeptutor.services.rag.pipelines.ima.probe import probe_knowledge_base

    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Knowledge base name is required.")

    overrides = ImaCredentials(
        client_id=payload.client_id.strip(),
        api_key=payload.api_key.strip(),
    )
    credentials = _resolve_ima_credentials(payload.client_id, payload.api_key)
    result = await probe_knowledge_base(
        credentials.client_id,
        credentials.api_key,
        payload.knowledge_base_id,
    )
    if not result.ok:
        raise HTTPException(
            status_code=400,
            detail=result.error or "Could not connect to the IMA knowledge base.",
        )

    try:
        manager = get_kb_manager()
        entry = manager.register_ima_kb(
            name,
            overrides.client_id,
            overrides.api_key,
            payload.knowledge_base_id,
            description=result.description or "",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as exc:
        # Never echo or log an upstream message from this credential-bearing
        # flow. The exception class is enough for server-side diagnosis.
        logger.error("Error connecting IMA knowledge base (%s)", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Could not connect the IMA knowledge base.")

    return {
        "status": "connected",
        "name": name,
        "knowledge_base_id": entry["knowledge_base_id"],
        "rag_provider": entry["rag_provider"],
    }


@router.get("/knowledge-bases", response_model=list[KnowledgeBaseInfo])
async def list_knowledge_bases():
    """List all available knowledge bases with their details."""
    try:
        manager = get_kb_manager()
        kb_names = manager.list_knowledge_bases()
        default_name = manager.get_default(available_names=kb_names)
        access_items = list_visible_kb_access()
        access_by_id = {str(item.get("id") or ""): item for item in access_items}
        own_prefix = "admin:kb:" if get_current_user().is_admin else "user:kb:"

        logger.debug(f"Found {len(kb_names)} knowledge bases: {kb_names}")

        result = []
        errors = []

        for name in kb_names:
            try:
                info = manager.get_info(
                    name,
                    refresh_config=False,
                    default_name=default_name,
                )
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
                                is_default=name == default_name,
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
            assigned_snapshots: dict[str, str | None] = {}
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
                    manager_key = str(assigned_manager.base_dir.resolve())
                    if manager_key not in assigned_snapshots:
                        assigned_names = assigned_manager.list_knowledge_bases()
                        assigned_snapshots[manager_key] = assigned_manager.get_default(
                            available_names=assigned_names
                        )
                    info = assigned_manager.get_info(
                        resource.name,
                        refresh_config=False,
                        default_name=assigned_snapshots[manager_key],
                    )
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


@router.get("/knowledge-bases/{kb_name}")
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


def _resolve_kb_raw_dir(kb_name: str, *, allow_unsupported: bool = False) -> Path | None:
    """Resolve a KB's managed ``raw/`` directory without inventing one.

    Connected KBs are external-resource pointers and intentionally have no
    DeepTutor-managed raw directory.  File listing treats that as an empty
    collection for backwards compatibility; endpoints that require a local
    file receive an explicit conflict response.
    """
    manager = _overridden_kb_manager()
    if manager is not None:
        resolved_name = _resolve_registered_kb_name(manager, kb_name)
    else:
        resource = resolve_kb(kb_name)
        manager = manager_for_resource(resource)
        resolved_name = resource.name

    kb_entry = _load_kb_entry_or_404(manager, resolved_name)
    if not supports_local_raw_files(kb_entry):
        if allow_unsupported:
            return None
        raise HTTPException(
            status_code=409,
            detail=(
                f"Knowledge base '{resolved_name}' is connected to an external resource "
                "and has no local files."
            ),
        )

    kb_path = manager.get_knowledge_base_path(resolved_name)
    return kb_path / "raw"


def _resolve_kb_raw_file_or_404(kb_name: str, filename: str) -> Path:
    """Resolve a raw KB file while preventing traversal outside raw/."""
    raw_dir = _resolve_kb_raw_dir(kb_name)
    assert raw_dir is not None  # allow_unsupported=False guarantees a path
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


@router.get("/knowledge-bases/{kb_name}/files")
async def list_kb_raw_files(kb_name: str):
    """List raw documents under <kb>/raw/, recursing into folders.

    ``name`` is the POSIX path relative to ``raw/`` so the web client can
    rebuild the folder tree. Folders (including empty ones) are returned as
    ``type: "folder"`` entries so user-created/uploaded structure shows even
    before it holds any files. Folders are purely organizational and have no
    effect on indexing or retrieval.
    """
    raw_dir = _resolve_kb_raw_dir(kb_name, allow_unsupported=True)
    if raw_dir is None:
        return {"files": []}
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


@router.post("/knowledge-bases/{kb_name}/folders")
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


@router.post("/knowledge-bases/{kb_name}/files/move")
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


@router.get("/knowledge-bases/{kb_name}/file-preview-text/{filename:path}")
async def serve_kb_raw_file_text_preview(kb_name: str, filename: str):
    """Serve extracted plain text for a raw KB document preview."""
    target = _resolve_kb_raw_file_or_404(kb_name, filename)
    try:
        extraction_kwargs = {
            "max_bytes": DocumentValidator.MAX_FILE_SIZE,
            "max_chars": MAX_EXTRACTED_CHARS_PER_DOC,
        }
        if extract_text_from_path is _DEFAULT_EXTRACT_TEXT_FROM_PATH:
            text = await extract_text_from_path_isolated(target, **extraction_kwargs)
        else:
            # Preserve the router's long-standing monkeypatch/integration seam.
            text = await asyncio.to_thread(extract_text_from_path, target, **extraction_kwargs)
    except DocumentExtractionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=404, detail="File not found") from exc

    return PlainTextResponse(text, media_type="text/plain; charset=utf-8")


@router.get("/knowledge-bases/{kb_name}/files/{filename:path}")
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


@router.delete("/knowledge-bases/{kb_name}/files/{filename:path}")
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
    kb_entry = _load_kb_entry_or_404(manager, kb_name)
    _assert_kb_writable_or_409(kb_name, kb_entry)
    target = _resolve_kb_raw_file_or_404(kb_name, filename)

    kb_dir = manager.get_knowledge_base_path(kb_name)
    provider = _validate_registered_provider(kb_entry.get("rag_provider") or DEFAULT_PROVIDER)
    if provider in {PAGEINDEX_PROVIDER, PAGEINDEX_OSS_PROVIDER}:
        from deeptutor.services.rag.factory import get_pipeline

        await get_pipeline(provider, kb_base_dir=str(manager.base_dir)).remove_document(
            kb_name,
            target.name,
        )
    removal = remove_raw_document(Path(kb_dir), target)
    return {
        "status": "ok",
        "path": removal.rel_path,
        "was_indexed": removal.was_indexed,
    }


def _delete_kb(kb_name: str) -> dict[str, str]:
    """Delete ``kb_name``, whichever route addressed it."""
    try:
        manager, resolved_name, _ = _writable_kb(kb_name)
        success = manager.delete_knowledge_base(resolved_name, confirm=True)
    except HTTPException:
        # Re-raised before the catch-all below, which used to turn a 404 from
        # ``_writable_kb`` into a 500 whose detail read "404: ... not found".
        raise
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Knowledge base '{kb_name}' not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    if not success:
        raise HTTPException(status_code=400, detail="Failed to delete knowledge base")
    logger.info(f"KB '{kb_name}' deleted")
    return {"message": f"Knowledge base '{kb_name}' deleted successfully"}


class DeleteKnowledgeBaseRequest(BaseModel):
    name: str


@router.post("/knowledge-bases/delete")
async def delete_knowledge_base_by_name(payload: DeleteKnowledgeBaseRequest):
    """Delete a knowledge base named in the body rather than in the path.

    The path route below cannot reach every registered name. A name is a
    ``kb_config.json`` key, and until the ``register_*`` methods validated it
    the connect-* endpoints wrote whatever the user typed — including a ``/``.
    uvicorn percent-decodes the path before routing, so ``%2F`` becomes a real
    separator and ``{kb_name}`` (compiled to ``[^/]+``) cannot span it: every
    per-KB route 404s and the KB is visible in the list but unreachable.

    A body is never split into path segments, so this reaches those entries.
    Widening the path route to ``{kb_name:path}`` would not do — it is
    declared ahead of the DELETE routes for linked folders, GitHub sources and
    web sources, and a greedy converter would silently swallow all three.
    """
    return _delete_kb(payload.name)


@router.delete("/knowledge-bases/{kb_name}")
async def delete_knowledge_base(kb_name: str):
    """Delete a knowledge base."""
    return _delete_kb(kb_name)


@router.get("/knowledge-bases/tasks/{task_id}/stream")
async def stream_task_logs(task_id: str):
    """Stream task-specific logs for knowledge-base operations."""
    manager = get_task_stream_manager()
    manager.ensure_task(task_id)
    return StreamingResponse(
        manager.stream(task_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/knowledge-bases/{kb_name}/upload")
async def upload_files(
    kb_name: str,
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    rag_provider: str = Form(None),
    rel_paths: list[str] = Form(None),
    dest_subdir: str = Form(None),
):
    """Upload files to a knowledge base and process them in background.

    ``dest_subdir`` places the whole batch under that folder inside the KB.
    A browser folder pick reports each file's path relative to the chosen
    directory, so the directory's own ancestors never reach the server; this
    is how a caller adding one subtree at a time re-attaches it where it
    belongs instead of piling every batch at the root (#866).
    """
    try:
        manager, kb_name, kb_base_dir = _writable_kb(kb_name)
        requested_provider = None
        if rag_provider is not None and str(rag_provider).strip():
            requested_provider = _validate_registered_provider(rag_provider)

        kb_entry = _load_kb_entry_or_404(manager, kb_name)
        _assert_kb_writable_or_409(kb_name, kb_entry)
        kb_path = manager.get_knowledge_base_path(kb_name)
        raw_dir = kb_path / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
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
        allowed_extensions = (
            set()
            if FileTypeRouter.active_parser_accepts_any_format()
            else FileTypeRouter.get_supported_extensions()
        )
        # ``.zip`` is accepted as an upload container; its members are
        # validated against ``allowed_extensions`` during extraction and the
        # archive itself is never indexed (``safe_extract_zip`` skips ``.zip``).
        upload_extensions = allowed_extensions | {".zip"} if allowed_extensions else set()
        _validate_upload_batch(files, allowed_extensions=upload_extensions, rel_paths=rel_paths)
        uploaded_files, uploaded_file_paths = await _save_uploaded_files_off_loop(
            files,
            raw_dir,
            allowed_extensions=upload_extensions,
            rel_paths=rel_paths,
            dest_subdir=_sanitize_rel_subdir(dest_subdir),
        )
        task_id = _build_unique_task_id("kb_upload", kb_name)
        get_task_stream_manager().ensure_task(task_id)

        logger.info(f"Uploading {len(uploaded_files)} files to KB '{kb_name}'")

        _mark_kb_queued_for_processing(
            manager,
            kb_name,
            task_id,
            f"Processing {len(uploaded_files)} uploaded file(s)...",
        )

        background_tasks.add_task(
            run_upload_processing_task,
            kb_name=kb_name,
            base_dir=str(kb_base_dir),
            uploaded_file_paths=uploaded_file_paths,
            task_id=task_id,
            rag_provider=kb_provider,
            owner=get_current_user(),
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


@router.post("/knowledge-bases")
async def create_knowledge_base(
    background_tasks: BackgroundTasks,
    name: str = Form(...),
    files: list[UploadFile] = File(default=[]),
    rag_provider: str = Form(DEFAULT_PROVIDER),
    pageindex_mode: str = Form(""),
    search_mode: str = Form(""),
    rel_paths: list[str] = Form(None),
    indexing_llm: str = Form(""),
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
        indexing_snapshot = None
        if rag_provider == LIGHTRAG_PROVIDER:
            if indexing_llm:
                _, indexing_snapshot = _freeze_indexing_llm_form(indexing_llm)
            else:
                indexing_snapshot = _freeze_default_indexing_llm()
        elif indexing_llm:
            raise HTTPException(
                status_code=400,
                detail="indexing_llm is supported only for built-in LightRAG.",
            )
        pageindex_mode = str(pageindex_mode or "").strip().lower()
        if rag_provider == PAGEINDEX_OSS_PROVIDER and pageindex_mode not in {
            "",
            "flash",
            "standard",
        }:
            raise HTTPException(
                status_code=400,
                detail="PageIndex OSS mode must be 'flash', 'standard', or omitted.",
            )
        _assert_provider_ready(rag_provider)
        search_mode = str(search_mode or "").strip().lower()
        if search_mode:
            from deeptutor.services.rag.service import RAGService

            provider_entry = next(
                (item for item in RAGService.list_providers() if item["id"] == rag_provider),
                None,
            )
            supported_modes = (provider_entry or {}).get("modes") or []
            if search_mode not in supported_modes:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Invalid search mode '{search_mode}' for {rag_provider}. "
                        f"Choose one of: {', '.join(supported_modes)}."
                    ),
                )
        _enforce_provider_formats(rag_provider, files)
        allowed_extensions = (
            set()
            if FileTypeRouter.active_parser_accepts_any_format()
            else FileTypeRouter.get_supported_extensions()
        )
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
            if rag_provider == PAGEINDEX_OSS_PROVIDER and pageindex_mode:
                manager.config["knowledge_bases"][name]["pageindex_mode"] = pageindex_mode
            if search_mode:
                manager.config["knowledge_bases"][name]["search_mode"] = search_mode
            if indexing_snapshot is not None:
                pending_policy = indexing_snapshot.persisted_policy()
                pending_policy["policy"] = "pending_pinned"
                manager.config["knowledge_bases"][name]["pending_indexing_policy"] = pending_policy
            manager._save_config()

        progress_tracker = ProgressTracker(name, kb_base_dir)

        initializer = KnowledgeBaseInitializer(
            kb_name=name,
            base_dir=str(kb_base_dir),
            progress_tracker=progress_tracker,
            rag_provider=rag_provider,
            indexing_snapshot=indexing_snapshot,
            owner=get_current_user(),
        )

        initializer.create_directory_structure()
        progress_tracker.task_id = task_id

        manager = get_kb_manager()
        if name not in manager.list_knowledge_bases():
            logger.warning(f"KB {name} not found in config, registering manually")
            initializer._register_to_config()

        # Fast path: no files uploaded — create an empty KB ready for web
        # sources, GitHub sources, or later document uploads.
        if not files:
            progress_tracker.update(
                ProgressStage.COMPLETED,
                "Knowledge base created (no documents yet).",
                current=0,
                total=0,
            )
            manager.update_kb_status(
                name=name,
                status="ready",
                progress={
                    "stage": "completed",
                    "message": "Knowledge base created (no documents yet).",
                    "percent": 100,
                    "current": 0,
                    "total": 0,
                    "timestamp": datetime.now().isoformat(),
                    "index_changed": True,
                    "index_action": "create",
                },
            )
            logger.info(f"KB '{name}' created (no documents yet)")
            return {
                "message": f"Knowledge base '{name}' created (no documents yet).",
                "name": name,
                "files": [],
                "task_id": None,
            }

        uploaded_files, _ = await _save_uploaded_files_off_loop(
            files, initializer.raw_dir, allowed_extensions=allowed_extensions, rel_paths=rel_paths
        )

        progress_tracker.update(
            ProgressStage.PROCESSING_DOCUMENTS,
            message_key="Saved {{count}} files, preparing to process...",
            message_params={"count": len(uploaded_files)},
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


async def run_reindex_task(
    kb_name: str,
    base_dir: str,
    task_id: str,
    signature_hash: str,
    indexing_snapshot=None,
    owner=None,
) -> None:
    """Re-index a KB's raw documents against the currently-active embedding config.

    Each ``(profile, model, dimension, base_url)`` combination gets its own
    flat ``<kb>/version-N/`` storage directory. Prior versions are preserved
    untouched so switching the active embedding model back to a
    previously-indexed one reuses the existing version with no extra work.
    """
    if owner is not None and get_current_user_or_none() != owner:
        token = set_current_user(owner)
        try:
            return await run_reindex_task(
                kb_name=kb_name,
                base_dir=base_dir,
                task_id=task_id,
                signature_hash=signature_hash,
                indexing_snapshot=indexing_snapshot,
            )
        finally:
            reset_current_user(token)

    task_manager = TaskIDManager.get_instance()
    task_stream_manager = get_task_stream_manager()
    task_stream_manager.ensure_task(task_id)
    index_published = False

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
                message_key="Re-indexing {{count}} document(s) with the active embedding model...",
                message_params={"count": len(file_paths)},
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
                    message_key="Embedding batches: {{current}}/{{total}}",
                    message_params={"current": batch_num, "total": total_batches},
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
                indexing_snapshot=indexing_snapshot,
            )
            if not success:
                raise RuntimeError(f"Re-index found no valid documents to index in '{kb_name}'.")
            index_published = signature_hash == LIGHTRAG_PROVIDER

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
                atomic_write_json(metadata_file, metadata)
            except Exception as meta_err:
                logger.warning(
                    "Failed to update re-index metadata for '%s': %s",
                    kb_name,
                    meta_err,
                )

            progress_tracker.update(
                ProgressStage.COMPLETED,
                "Re-index complete",
                current=len(file_paths),
                total=len(file_paths),
                indexed_count=len(file_paths),
                index_changed=True,
                index_action="reindex",
            )
            try:
                with open(progress_tracker.progress_file, encoding="utf-8") as handle:
                    persisted_progress = json.load(handle)
            except Exception as progress_err:
                raise RuntimeError(
                    f"Re-index terminal state was not persisted for '{kb_name}'."
                ) from progress_err
            expected_terminal_progress = {
                "stage": ProgressStage.COMPLETED.value,
                "task_id": task_id,
                "progress_percent": 100,
                "current": len(file_paths),
                "total": len(file_paths),
                "indexed_count": len(file_paths),
                "index_changed": True,
                "index_action": "reindex",
            }
            if not isinstance(persisted_progress, dict) or any(
                persisted_progress.get(key) != value
                for key, value in expected_terminal_progress.items()
            ):
                raise RuntimeError(f"Re-index terminal state was not persisted for '{kb_name}'.")
            manager = get_kb_manager()
            # ProgressTracker persists through its own manager instance. Refresh
            # this cached instance before clearing flags so stale processing
            # state cannot overwrite the completed status it just wrote.
            manager.config = manager._load_config()
            # Clear the legacy mismatch / needs_reindex flags now that an
            # index version matching the active config exists on disk.
            kb_entry = manager.config.get("knowledge_bases", {}).get(kb_name) or {}
            if kb_entry.get("status") != "ready":
                raise RuntimeError(f"Re-index terminal state was not persisted for '{kb_name}'.")
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
            if index_published:
                _task_log(
                    task_id,
                    "LightRAG version was published; final status bookkeeping will be reconciled.",
                    level="warning",
                )
                _server_task_trace(task_id, trace)
                task_manager.update_task_status(task_id, "completed")
                task_stream_manager.emit_complete(task_id, f"Re-index of '{kb_name}' published")
                return
            failure_metadata = _exception_failure_metadata(e)
            _task_log(task_id, f"Re-index failed: {error_msg}", level="error")
            _server_task_trace(task_id, trace)
            task_manager.update_task_status(task_id, "error", error=error_msg)
            try:
                ProgressTracker(kb_name, Path(base_dir)).update(
                    ProgressStage.ERROR,
                    f"Re-index failed: {error_msg}",
                    error=error_msg,
                    **failure_metadata,
                )
            except Exception:
                pass
            task_stream_manager.emit_failed(task_id, error_msg, **failure_metadata)


@router.post("/knowledge-bases/{kb_name}/reindex")
async def reindex_knowledge_base(
    kb_name: str,
    background_tasks: BackgroundTasks,
    indexing_llm: str = Form(""),
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
        indexing_snapshot = None
        if kb_provider == LIGHTRAG_PROVIDER:
            if indexing_llm:
                _, indexing_snapshot = _freeze_indexing_llm_form(indexing_llm)
            else:
                indexing_snapshot = _freeze_default_indexing_llm()
        elif indexing_llm:
            raise HTTPException(
                status_code=400,
                detail="indexing_llm is supported only for built-in LightRAG.",
            )

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

        _mark_kb_queued_for_processing(
            manager, kb_name, task_id, "Queueing re-index...", status="initializing"
        )

        background_tasks.add_task(
            run_reindex_task,
            kb_name=kb_name,
            base_dir=str(kb_base_dir),
            task_id=task_id,
            signature_hash=signature_hash,
            indexing_snapshot=indexing_snapshot,
            owner=get_current_user(),
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


@router.put("/knowledge-bases/{kb_name}/indexing-policy")
async def update_pending_indexing_policy(
    kb_name: str,
    payload: IndexingLLMSelectionRequest,
):
    """Change the pending model of an empty, unpublished LightRAG KB."""
    manager, kb_name, kb_base_dir = _writable_kb(kb_name)
    kb_entry = _load_kb_entry_or_404(manager, kb_name)
    _assert_not_connected_kb(kb_name, kb_entry)
    provider = _validate_registered_provider(kb_entry.get("rag_provider"))
    if provider != LIGHTRAG_PROVIDER:
        raise HTTPException(
            status_code=400,
            detail="Indexing-model policy is supported only for built-in LightRAG.",
        )

    def assert_no_active_task(entry: dict) -> None:
        status = str(entry.get("status") or "").lower()
        progress = entry.get("progress")
        stage = str(progress.get("stage") or "").lower() if isinstance(progress, dict) else ""
        if status in {"initializing", "processing"} and stage not in {
            "completed",
            "error",
        }:
            raise HTTPException(
                status_code=409,
                detail=(
                    "The pending indexing model cannot change while an indexing task is active."
                ),
            )

    assert_no_active_task(kb_entry)
    kb_dir = kb_base_dir / kb_name
    from deeptutor.services.rag.pipelines.lightrag.storage import latest_published_root

    if latest_published_root(kb_dir) is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                "This knowledge base already has a published index; run a full re-index "
                "to change its model."
            ),
        )
    raw_dir = kb_dir / "raw"
    if raw_dir.is_dir() and any(path.is_file() for path in raw_dir.rglob("*")):
        raise HTTPException(
            status_code=409,
            detail=(
                "The pending indexing model can change only while the knowledge base is empty."
            ),
        )

    from deeptutor.services.rag.pipelines.lightrag.indexing_policy import (
        IndexingPolicyError,
        pending_policy_for_selection,
    )

    try:
        policy = pending_policy_for_selection(payload.model_dump(exclude_none=True))
    except (ValueError, PermissionError, IndexingPolicyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Re-read immediately before saving so a task queued during model
    # resolution cannot be overwritten through a stale entry reference.
    kb_entry = _load_kb_entry_or_404(manager, kb_name)
    assert_no_active_task(kb_entry)
    if latest_published_root(kb_dir) is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                "This knowledge base already has a published index; run a full re-index "
                "to change its model."
            ),
        )
    if raw_dir.is_dir() and any(path.is_file() for path in raw_dir.rglob("*")):
        raise HTTPException(
            status_code=409,
            detail=(
                "The pending indexing model can change only while the knowledge base is empty."
            ),
        )
    kb_entry["pending_indexing_policy"] = policy
    manager._save_config()
    return {"indexing_policy": policy}


@router.post("/knowledge-bases/{kb_name}/retry")
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
        return await reindex_knowledge_base(resolved_name, background_tasks, indexing_llm="")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to retry KB '{kb_name}': {e}")
        raise HTTPException(status_code=500, detail=format_exception_message(e))


@router.get("/knowledge-bases/{kb_name}/progress")
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


@router.post("/knowledge-bases/{kb_name}/progress/clear")
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


@ws_router.websocket("/knowledge-bases/{kb_name}/progress")
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
        task_manager = TaskIDManager.get_instance()

        try:
            kb_info = KnowledgeBaseManager(base_dir=str(base_dir)).get_info(kb_name)
            kb_is_ready = bool(kb_info.get("statistics", {}).get("rag_initialized"))
        except Exception:
            kb_is_ready = False

        if expected_task_id:
            progress_task_id = initial_progress.get("task_id") if initial_progress else None
            stage = initial_progress.get("stage") if initial_progress else None
            task_metadata = task_manager.get_task_metadata(expected_task_id)

            # A terminal snapshot is durable and authoritative. Always replay
            # it, including completed snapshots for already-ready KBs.
            if progress_task_id == expected_task_id and stage in {"completed", "error"}:
                await websocket.send_json({"type": "progress", "data": initial_progress})
                return

            if not task_metadata:
                # Task IDs and background asyncio tasks are process-local. If
                # the browser reconnects with an expected id that this process
                # does not know, the server was restarted (or the task was
                # evicted) and it cannot ever produce another event. Convert
                # that orphan into a durable, retryable terminal state so both
                # SSE and WebSocket consumers settle immediately.
                error_message = (
                    "Knowledge-base processing was interrupted by a server restart. "
                    "Retry the operation to continue."
                )
                if progress_task_id == expected_task_id and stage not in {
                    "completed",
                    "error",
                }:
                    progress_tracker.task_id = expected_task_id
                    progress_tracker.update(
                        ProgressStage.ERROR,
                        message=error_message,
                        error=error_message,
                        error_code="knowledge_task_interrupted",
                        retryable=True,
                    )
                    initial_progress = progress_tracker.get_progress()
                else:
                    initial_progress = {
                        "kb_name": kb_name,
                        "task_id": expected_task_id,
                        "stage": "error",
                        "message": error_message,
                        "error": error_message,
                        "error_code": "knowledge_task_interrupted",
                        "retryable": True,
                        "progress_percent": 0,
                        "timestamp": datetime.now().isoformat(),
                    }
                get_task_stream_manager().emit_failed(
                    expected_task_id,
                    error_message,
                    error_code="knowledge_task_interrupted",
                    retryable=True,
                )
                await websocket.send_json({"type": "progress", "data": initial_progress})
                return

            task_status = str(task_metadata.get("status") or "")
            if task_status in {"completed", "error", "cancelled"}:
                is_completed = task_status == "completed"
                message = (
                    "Knowledge-base processing completed."
                    if is_completed
                    else str(task_metadata.get("error") or "Knowledge-base processing failed.")
                )
                terminal_progress = {
                    "kb_name": kb_name,
                    "task_id": expected_task_id,
                    "stage": "completed" if is_completed else "error",
                    "message": message,
                    "progress_percent": 100 if is_completed else 0,
                    "timestamp": str(
                        task_metadata.get("finished_at") or datetime.now().isoformat()
                    ),
                }
                if not is_completed:
                    terminal_progress.update(
                        {
                            "error": message,
                            "error_code": "knowledge_task_failed",
                            "retryable": True,
                        }
                    )
                await websocket.send_json({"type": "progress", "data": terminal_progress})
                return

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
            elif expected_task_id and progress_task_id == expected_task_id:
                should_send = True
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
                            last_timestamp = current_timestamp

                            if current_progress.get("stage") in ["completed", "error"]:
                                await asyncio.sleep(3)
                                break
                    if expected_task_id:
                        task_metadata = task_manager.get_task_metadata(expected_task_id)
                        task_status = str((task_metadata or {}).get("status") or "")
                        if task_status in {"completed", "error", "cancelled"}:
                            is_completed = task_status == "completed"
                            message = (
                                "Knowledge-base processing completed."
                                if is_completed
                                else str(
                                    (task_metadata or {}).get("error")
                                    or "Knowledge-base processing failed."
                                )
                            )
                            await websocket.send_json(
                                {
                                    "type": "progress",
                                    "data": {
                                        "kb_name": kb_name,
                                        "task_id": expected_task_id,
                                        "stage": "completed" if is_completed else "error",
                                        "message": message,
                                        "error": None if is_completed else message,
                                        "error_code": (
                                            None if is_completed else "knowledge_task_failed"
                                        ),
                                        "retryable": False if is_completed else True,
                                        "progress_percent": 100 if is_completed else 0,
                                        "timestamp": str(
                                            (task_metadata or {}).get("finished_at")
                                            or datetime.now().isoformat()
                                        ),
                                    },
                                }
                            )
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


@router.post("/knowledge-bases/{kb_name}/link-folder", response_model=LinkedFolderInfo)
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


@router.get("/knowledge-bases/{kb_name}/linked-folders", response_model=list[LinkedFolderInfo])
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


@router.delete("/knowledge-bases/{kb_name}/linked-folders/{folder_id}")
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


@router.post("/knowledge-bases/{kb_name}/sync-folder/{folder_id}")
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

        _mark_kb_queued_for_processing(
            manager,
            kb_name,
            task_id,
            f"Syncing {len(files_to_process)} file(s) from linked folder...",
        )

        # Add background task to process files
        background_tasks.add_task(
            run_upload_processing_task,
            kb_name=kb_name,
            base_dir=str(kb_base_dir),
            uploaded_file_paths=files_to_process,
            task_id=task_id,
            rag_provider=kb_provider,
            folder_id=folder_id,  # Pass folder_id to update state on success
            folder_root=folder_path,  # Preserve each file's path relative to this root
            owner=get_current_user(),
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


class AddGitHubSourceRequest(BaseModel):
    repo: str
    branch: str = "main"
    path: str = ""
    glob: str = "*.md"


class GitHubSourceInfo(BaseModel):
    id: str
    repo: str
    branch: str
    path: str
    glob: str
    enabled: bool = True
    last_synced_sha: str = ""
    last_synced_at: str = ""
    last_sync_status: str = "pending"
    last_sync_error: str | None = None
    files_synced: int = 0
    added_at: str = ""


class AddWebSourceRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    max_depth: int = Field(default=3, ge=1, le=5)
    max_pages: int = Field(default=200, ge=1, le=200)


class WebSourceInfo(BaseModel):
    id: str
    url: str
    max_depth: int = 3
    max_pages: int = 200
    enabled: bool = True
    page_count: int = 0
    last_synced_at: str = ""
    last_sync_status: str = "pending"
    last_sync_error: str | None = None
    added_at: str = ""
    navigation: dict | None = None


@contextmanager
def _knowledge_source_errors(kb_name: str, *, validation_status: int = 404):
    """Translate source-service failures without duplicating route ladders."""
    try:
        yield
    except HTTPException:
        raise
    except ValueError as exc:
        detail = str(exc)
        status_code = (
            404 if validation_status == 404 or "not found" in detail.lower() else validation_status
        )
        if validation_status == 404:
            detail = f"KB '{kb_name}' not found"
        raise HTTPException(status_code=status_code, detail=detail) from exc
    except Exception as exc:
        logger.exception("Knowledge source operation failed for %s", kb_name)
        raise HTTPException(status_code=500, detail="Knowledge source operation failed") from exc


@router.post("/knowledge-bases/{kb_name}/github-source", response_model=GitHubSourceInfo)
async def add_github_source(kb_name: str, request: AddGitHubSourceRequest):
    with _knowledge_source_errors(kb_name, validation_status=400):
        manager, resolved_name, _ = _writable_kb(kb_name)
        info = manager.add_github_source(
            resolved_name, request.repo, request.branch, request.path, request.glob
        )
        return GitHubSourceInfo(**info)


@router.get("/knowledge-bases/{kb_name}/github-sources", response_model=list[GitHubSourceInfo])
async def get_github_sources(kb_name: str):
    with _knowledge_source_errors(kb_name):
        manager, resolved_name, _ = _writable_kb(kb_name)
        return [GitHubSourceInfo(**s) for s in manager.get_github_sources(resolved_name)]


@router.delete("/knowledge-bases/{kb_name}/github-source/{source_id}")
async def remove_github_source(kb_name: str, source_id: str):
    with _knowledge_source_errors(kb_name):
        manager, resolved_name, _ = _writable_kb(kb_name)
        if not manager.remove_github_source(resolved_name, source_id):
            raise HTTPException(status_code=404, detail=f"Source '{source_id}' not found")
        return {"message": "Removed", "source_id": source_id}


@router.post("/knowledge-bases/{kb_name}/sync-github")
async def sync_github_sources(kb_name: str):
    with _knowledge_source_errors(kb_name):
        manager, resolved_name, kb_base_dir = _writable_kb(kb_name)
        sources = manager.get_github_sources(resolved_name)
        if not sources:
            return {"message": "No GitHub sources", "results": []}
        from deeptutor.services.github_source.sync import sync_source

        results = []
        for src in sources:
            if not src.get("enabled", True):
                continue
            r = await sync_source(kb_name=resolved_name, source=src, base_dir=str(kb_base_dir))
            results.append(
                {
                    "source_id": src.get("id"),
                    "repo": src.get("repo"),
                    "ok": r.ok,
                    "skipped": r.skipped,
                    "files_added": r.files_added,
                    "files_updated": r.files_updated,
                    "files_removed": r.files_removed,
                    "error": r.error or None,
                }
            )
        return {"message": f"Synced {len(results)} source(s)", "results": results}


@router.post("/knowledge-bases/{kb_name}/web-source", response_model=WebSourceInfo)
async def add_web_source(kb_name: str, request: AddWebSourceRequest):
    with _knowledge_source_errors(kb_name, validation_status=400):
        manager, resolved_name, _ = _writable_kb(kb_name)
        info = manager.add_web_source(
            resolved_name, request.url, request.max_depth, request.max_pages
        )
        return WebSourceInfo(**info)


@router.get("/knowledge-bases/{kb_name}/web-sources", response_model=list[WebSourceInfo])
async def get_web_sources(kb_name: str):
    with _knowledge_source_errors(kb_name):
        manager, resolved_name, _ = _writable_kb(kb_name)
        return [WebSourceInfo(**s) for s in manager.get_web_sources(resolved_name)]


@router.delete("/knowledge-bases/{kb_name}/web-source/{source_id}")
async def remove_web_source(kb_name: str, source_id: str):
    with _knowledge_source_errors(kb_name):
        manager, resolved_name, _ = _writable_kb(kb_name)
        if not manager.remove_web_source(resolved_name, source_id):
            raise HTTPException(status_code=404, detail=f"Source '{source_id}' not found")
        return {"message": "Removed", "source_id": source_id}


@router.post("/knowledge-bases/{kb_name}/sync-web")
async def sync_web_sources(kb_name: str):
    """Run one bounded crawl-and-sync pass for every enabled web source."""
    with _knowledge_source_errors(kb_name):
        manager, resolved_name, kb_base_dir = _writable_kb(kb_name)
        sources = manager.get_web_sources(resolved_name)
        if not sources:
            return {"message": "No web sources", "results": []}
        from deeptutor.services.web_source.sync import sync_source

        enabled = [s for s in sources if s.get("enabled", True)]
        if not enabled:
            return {"message": "No enabled web sources", "results": []}

        results = []
        for source in enabled:
            result = await sync_source(
                kb_name=resolved_name,
                source=source,
                base_dir=str(kb_base_dir),
                max_depth=source.get("max_depth"),
                max_pages=source.get("max_pages"),
            )
            refreshed = manager.get_web_sources(resolved_name)
            page_count = next(
                (
                    item.get("page_count", 0)
                    for item in refreshed
                    if item.get("id") == source.get("id")
                ),
                source.get("page_count", 0),
            )
            results.append(
                {
                    "source_id": source.get("id"),
                    "url": source.get("url"),
                    "ok": result.ok,
                    "page_count": page_count,
                    "pages_added": result.pages_added,
                    "pages_updated": result.pages_updated,
                    "pages_removed": result.pages_removed,
                    "pages_unchanged": result.pages_unchanged,
                    "error": result.error or None,
                }
            )

        return {
            "message": f"Synced {len(results)} source(s)",
            "ok": all(result["ok"] for result in results),
            "results": results,
        }
