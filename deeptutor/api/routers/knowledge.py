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
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from deeptutor.api.utils.progress_broadcaster import ProgressBroadcaster
from deeptutor.api.utils.task_id_manager import TaskIDManager
from deeptutor.api.utils.task_log_stream import capture_task_logs, get_task_stream_manager
from deeptutor.knowledge.add_documents import DocumentAdder
from deeptutor.knowledge.initializer import KnowledgeBaseInitializer
from deeptutor.knowledge.manager import KnowledgeBaseManager
from deeptutor.knowledge.naming import validate_knowledge_base_name
from deeptutor.knowledge.progress_tracker import ProgressStage, ProgressTracker
from deeptutor.services.config import PROJECT_ROOT, load_config_with_main
from deeptutor.services.rag.factory import DEFAULT_PROVIDER
from deeptutor.services.rag.file_routing import FileTypeRouter
from deeptutor.multi_user.context import get_current_user
from deeptutor.multi_user.knowledge_access import (
    assert_writable,
    current_kb_base_dir,
    current_kb_manager,
    list_visible_knowledge_bases as list_visible_kb_access,
    manager_for_resource,
    resolve_kb,
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
    max_pdf_size_bytes: int


def _build_unique_task_id(task_type: str, task_key_prefix: str) -> str:
    task_manager = TaskIDManager.get_instance()
    task_key = f"{task_key_prefix}_{datetime.now().isoformat()}_{uuid4().hex[:8]}"
    return task_manager.generate_task_id(task_type, task_key)


def _save_uploaded_files(
    files: list[UploadFile],
    target_dir: Path,
    allowed_extensions: set[str] | None = None,
    kb_name: str | None = None,
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
        for file in files:
            file_path = None
            original_filename = file.filename or "upload"
            try:
                sanitized_filename = DocumentValidator.validate_upload_safety(
                    original_filename,
                    _get_upload_file_size(file),
                    allowed_extensions=allowed_extensions,
                )
                file.filename = sanitized_filename

                file_path = target_dir / sanitized_filename
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
                uploaded_files.append(sanitized_filename)
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
) -> list[dict[str, int | str | None]]:
    """Validate upload metadata before mutating KB state or writing any files."""
    validated: list[dict[str, int | str | None]] = []
    seen_names: set[str] = set()

    for file in files:
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

        if sanitized_filename in seen_names:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Duplicate filename after sanitization: '{sanitized_filename}'. "
                    "Rename one of the files and try again."
                ),
            )

        seen_names.add(sanitized_filename)
        validated.append(
            {
                "original_filename": original_filename,
                "sanitized_filename": sanitized_filename,
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
    """Always return the canonical provider; field is kept as a stub."""
    return DEFAULT_PROVIDER


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


def _assert_kb_writable_or_409(kb_name: str, kb_entry: dict) -> None:
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
        from deeptutor.services.rag.pipelines.llamaindex.storage import (
            validate_storage_embeddings,
        )

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
            initializer.extract_numbered_items()
            _task_log(task_id, "Finalizing initialization")
            indexed_count = len(FileTypeRouter.collect_supported_files(initializer.raw_dir))

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
        rag_provider: RAG provider (ignored - we use the one from KB metadata)
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

            processed_files = await adder.process_new_documents(staged_files)
            _task_log(task_id, f"Indexed {len(processed_files)} file(s)")

            if processed_files:
                progress_tracker.update(
                    ProgressStage.EXTRACTING_ITEMS,
                    "Extracting numbered items...",
                    current=0,
                    total=len(processed_files),
                )
                adder.extract_numbered_items_for_new_docs(processed_files, batch_size=20)

            adder.update_metadata(len(processed_files) if processed_files else 0)

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

            num_processed = len(processed_files) if processed_files else 0
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
    """Get list of available RAG providers."""
    try:
        from deeptutor.services.rag.service import RAGService

        providers = RAGService.list_providers()
        return {"providers": providers}
    except Exception as e:
        logger.error(f"Error getting RAG providers: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/supported-file-types", response_model=SupportedFileTypesInfo)
async def get_supported_file_types():
    """Return the current upload policy so the web client stays in sync."""
    extensions = sorted(FileTypeRouter.get_supported_extensions())
    return SupportedFileTypesInfo(
        extensions=extensions,
        accept=",".join(extensions),
        max_file_size_bytes=DocumentValidator.MAX_FILE_SIZE,
        max_pdf_size_bytes=DocumentValidator.MAX_PDF_SIZE,
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

        if "rag_provider" in config:
            config["rag_provider"] = _validate_registered_provider(config.get("rag_provider"))

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
                        provenance_label=access_by_id.get(
                            f"{own_prefix}{info['name']}", {}
                        ).get("provenance_label"),
                    )
                )
            except Exception as e:
                error_msg = f"Error getting info for KB '{name}': {e}"
                errors.append(error_msg)
                logger.warning(f"{error_msg}\n{traceback.format_exc()}")
                try:
                    kb_dir = manager.base_dir / name
                    if kb_dir.exists():
                        logger.debug(f"KB '{name}' directory exists, creating fallback info")
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
                                metadata=None,
                                path=str(kb_dir),
                                status="unknown",
                                progress=None,
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
                except Exception:
                    result.append(
                        KnowledgeBaseInfo(
                            id=resource.id,
                            name=resource.name,
                            is_default=False,
                            statistics={},
                            metadata={},
                            status="unknown",
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


@router.get("/{kb_name}/files")
async def list_kb_raw_files(kb_name: str):
    """List raw documents stored under data/knowledge_bases/<kb>/raw/."""
    raw_dir = _resolve_kb_raw_dir(kb_name)
    if not raw_dir.exists() or not raw_dir.is_dir():
        return {"files": []}

    files = []
    for entry in sorted(raw_dir.iterdir(), key=lambda p: p.name.lower()):
        if not entry.is_file():
            continue
        try:
            stat = entry.stat()
        except OSError:
            continue
        media_type, _ = mimetypes.guess_type(entry.name)
        files.append(
            {
                "name": entry.name,
                "size": stat.st_size,
                "modified": stat.st_mtime,
                "mime_type": media_type,
            }
        )
    return {"files": files}


@router.get("/{kb_name}/files/{filename:path}")
async def serve_kb_raw_file(kb_name: str, filename: str):
    """Serve a single raw document for inline preview / download.

    Resolution is sandboxed to the KB's raw/ directory; any path that
    escapes via traversal yields 403.
    """
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

    media_type, _ = mimetypes.guess_type(target.name)
    return FileResponse(
        target,
        media_type=media_type or "application/octet-stream",
        filename=target.name,
        content_disposition_type="inline",
    )


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
                    "Update KB config first."
                ),
            )
        allowed_extensions = FileTypeRouter.get_supported_extensions()
        _validate_upload_batch(files, allowed_extensions=allowed_extensions)
        uploaded_files, uploaded_file_paths = _save_uploaded_files(
            files, raw_dir, allowed_extensions=allowed_extensions
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
        allowed_extensions = FileTypeRouter.get_supported_extensions()
        _validate_upload_batch(files, allowed_extensions=allowed_extensions)

        logger.info(f"Creating KB: {name}")
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
            files, initializer.raw_dir, allowed_extensions=allowed_extensions
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
            file_paths = [str(path) for path in FileTypeRouter.collect_supported_files(raw_dir)]
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

            rag_service = RAGService(kb_base_dir=str(base_path), provider=DEFAULT_PROVIDER)

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
    """Re-index ``kb_name`` against the currently-active embedding model.

    The new index lands in a flat ``<kb>/version-N/`` directory so prior
    versions stay intact. Legacy nested versions remain readable, but a
    manual re-index will converge them onto the flat layout.
    """
    try:
        manager, kb_name, kb_base_dir = _writable_kb(kb_name)
        kb_entry = _load_kb_entry_or_404(manager, kb_name)
        force_reindex = str(kb_entry.get("status") or "").lower() == "error"

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

        kb_dir = kb_base_dir / kb_name
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
                "signature": signature.hash(),
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
            signature_hash=signature.hash(),
        )

        return {
            "message": f"Re-indexing '{kb_name}' in the background.",
            "task_id": task_id,
            "signature": signature.hash(),
            "noop": False,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start reindex for '{kb_name}': {e}")
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
    await websocket.accept()

    broadcaster = ProgressBroadcaster.get_instance()

    try:
        await broadcaster.connect(kb_name, websocket)

        base_dir = _current_kb_base_dir()
        progress_tracker = ProgressTracker(kb_name, base_dir)
        initial_progress = progress_tracker.get_progress()
        expected_task_id = websocket.query_params.get("task_id")

        kb_dir = base_dir / kb_name
        from deeptutor.services.rag.index_versioning import list_kb_versions

        kb_is_ready = any(bool(version.get("ready")) for version in list_kb_versions(kb_dir))

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
