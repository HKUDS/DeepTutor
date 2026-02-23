"""
Knowledge Base API Router
=========================

Handles knowledge base CRUD operations, file uploads, and initialization.
"""

import asyncio
from datetime import datetime
import json
from pathlib import Path
import re
import shutil
import sys
import traceback

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
from pydantic import BaseModel

from src.api.utils.notebook_manager import notebook_manager
from src.api.utils.progress_broadcaster import ProgressBroadcaster
from src.api.utils.task_id_manager import TaskIDManager
from src.knowledge.add_documents import DocumentAdder
from src.knowledge.initializer import KnowledgeBaseInitializer
from src.knowledge.manager import KnowledgeBaseManager
from src.knowledge.progress_tracker import ProgressStage, ProgressTracker

_project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(_project_root))
from src.logging import get_logger
from src.services.config import load_config_with_main
from src.services.llm import get_llm_config

# Initialize logger with config
project_root = Path(__file__).parent.parent.parent.parent
config = load_config_with_main("solve_config.yaml", project_root)  # Use any config to get main.yaml
log_dir = config.get("paths", {}).get("user_log_dir") or config.get("logging", {}).get("log_dir")
logger = get_logger("Knowledge", level="INFO", log_dir=log_dir)

router = APIRouter()

_kb_base_dir = _project_root / "data" / "knowledge_bases"

# Lazy initialization
kb_manager = None


def get_kb_manager():
    """Get KnowledgeBaseManager instance (lazy init)"""
    global kb_manager
    if kb_manager is None:
        kb_manager = KnowledgeBaseManager(base_dir=str(_kb_base_dir))
    return kb_manager


class KnowledgeBaseInfo(BaseModel):
    name: str
    display_name: str
    is_default: bool
    statistics: dict
    system_managed: bool = False
    owner: dict | None = None


class UpdateDisplayNameRequest(BaseModel):
    display_name: str


_NOTEBOOK_SOURCES_KB_RE = re.compile(r"^notebook_(?P<notebook_id>[^/]+)_sources$")


def _extract_notebook_id_from_sources_kb_name(kb_name: str) -> str:
    match = _NOTEBOOK_SOURCES_KB_RE.match((kb_name or "").strip())
    return match.group("notebook_id") if match else ""


def _normalize_notebook_name(name: str) -> str:
    cleaned = " ".join((name or "").split()).strip()
    return cleaned or "未命名笔记本"


def _safe_upload_filename(filename: str) -> str:
    normalized = (filename or "").replace("\\", "/").strip()
    if not normalized:
        raise ValueError("filename is empty")

    parts = [part for part in normalized.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        raise ValueError("invalid filename")

    safe_name = parts[-1].strip()
    if not safe_name or safe_name in {".", ".."} or "\x00" in safe_name:
        raise ValueError("invalid filename")

    return safe_name


def _notebook_sources_display_name(notebook_name: str) -> str:
    return f"{_normalize_notebook_name(notebook_name)} · 来源库"


def _sync_notebook_sources_kb_metadata(manager: KnowledgeBaseManager, kb_name: str) -> None:
    """
    Backfill/refresh metadata for notebook temporary source KBs.
    This keeps older KBs readable without renaming the real kb_name.
    """
    try:
        metadata = manager.get_metadata(kb_name)
    except Exception:
        return

    owner = metadata.get("owner") if isinstance(metadata.get("owner"), dict) else {}
    notebook_id = str(owner.get("notebook_id") or "").strip()
    if not notebook_id:
        notebook_id = _extract_notebook_id_from_sources_kb_name(kb_name)
    if not notebook_id:
        return

    notebook = notebook_manager.get_notebook(notebook_id) or {}
    notebook_name = _normalize_notebook_name(
        notebook.get("name") or owner.get("notebook_name") or f"笔记本 {notebook_id}"
    )
    target_display_name = _notebook_sources_display_name(notebook_name)
    target_owner = {
        "type": "notebook_sources",
        "notebook_id": notebook_id,
        "notebook_name": notebook_name,
    }

    updates = {}
    if metadata.get("display_name") != target_display_name:
        updates["display_name"] = target_display_name
    if metadata.get("system_managed") is not True:
        updates["system_managed"] = True
    if metadata.get("description") != "Notebook selected sources":
        updates["description"] = "Notebook selected sources"
    if metadata.get("owner") != target_owner:
        updates["owner"] = target_owner

    if updates:
        manager.update_metadata_fields(kb_name, updates)


def _load_source_display_name_map(kb_path: Path) -> dict[str, str]:
    manifest_path = kb_path / "sources_manifest.json"
    if not manifest_path.exists():
        return {}
    try:
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
    except Exception:
        return {}
    if not isinstance(manifest, dict):
        return {}

    mapping: dict[str, str] = {}
    sources = manifest.get("sources", [])
    if not isinstance(sources, list):
        return mapping

    for source in sources:
        if not isinstance(source, dict):
            continue
        raw_filename = source.get("raw_filename") or Path(source.get("file_path") or "").name or ""
        if not raw_filename:
            continue
        display_name = (
            source.get("source_display_name")
            or source.get("title")
            or source.get("url")
            or raw_filename
        )
        mapping[raw_filename] = display_name

    return mapping


def _extract_markdown_h1(file_path: Path) -> str:
    try:
        with open(file_path, encoding="utf-8") as f:
            for _ in range(80):
                line = f.readline()
                if not line:
                    break
                stripped = line.strip()
                if stripped.startswith("# "):
                    return stripped[2:].strip()
    except Exception:
        return ""
    return ""


async def run_initialization_task(initializer: KnowledgeBaseInitializer):
    """Background task for knowledge base initialization"""
    task_manager = TaskIDManager.get_instance()
    task_id = task_manager.generate_task_id("kb_init", initializer.kb_name)

    try:
        if not initializer.progress_tracker:
            initializer.progress_tracker = ProgressTracker(
                initializer.kb_name, initializer.base_dir
            )

        initializer.progress_tracker.task_id = task_id

        logger.info(f"[{task_id}] Initializing KB: {initializer.kb_name}")

        await initializer.process_documents()
        initializer.extract_numbered_items()

        initializer.progress_tracker.update(
            ProgressStage.COMPLETED, "Knowledge base initialization complete!", current=1, total=1
        )

        logger.success(f"[{task_id}] KB '{initializer.kb_name}' initialized")
        task_manager.update_task_status(task_id, "completed")
    except Exception as e:
        error_msg = str(e)

        logger.error(f"[{task_id}] KB '{initializer.kb_name}' init failed: {error_msg}")

        task_manager.update_task_status(task_id, "error", error=error_msg)

        if initializer.progress_tracker:
            initializer.progress_tracker.update(
                ProgressStage.ERROR, f"Initialization failed: {error_msg}", error=error_msg
            )


async def run_upload_processing_task(
    kb_name: str, base_dir: str, api_key: str, base_url: str, uploaded_file_paths: list[str]
):
    """Background task for processing uploaded files"""
    task_manager = TaskIDManager.get_instance()
    task_key = f"{kb_name}_upload_{len(uploaded_file_paths)}"
    task_id = task_manager.generate_task_id("kb_upload", task_key)

    progress_tracker = ProgressTracker(kb_name, Path(base_dir))
    progress_tracker.task_id = task_id

    try:
        logger.info(f"[{task_id}] Processing {len(uploaded_file_paths)} files to KB '{kb_name}'")
        progress_tracker.update(
            ProgressStage.PROCESSING_DOCUMENTS,
            f"Processing {len(uploaded_file_paths)} files...",
            current=0,
            total=len(uploaded_file_paths),
        )

        adder = DocumentAdder(
            kb_name=kb_name,
            base_dir=base_dir,
            api_key=api_key,
            base_url=base_url,
            progress_tracker=progress_tracker,
        )

        new_files = [Path(path) for path in uploaded_file_paths]
        processed_files = await adder.process_new_documents(new_files)

        if processed_files:
            progress_tracker.update(
                ProgressStage.EXTRACTING_ITEMS,
                "Extracting numbered items...",
                current=0,
                total=len(processed_files),
            )
            adder.extract_numbered_items_for_new_docs(processed_files, batch_size=20)

        adder.update_metadata(len(new_files))

        progress_tracker.update(
            ProgressStage.COMPLETED,
            f"Successfully processed {len(processed_files)} files!",
            current=len(processed_files),
            total=len(processed_files),
        )

        logger.success(f"[{task_id}] Processed {len(processed_files)} files to KB '{kb_name}'")
        task_manager.update_task_status(task_id, "completed")
    except Exception as e:
        error_msg = f"Upload processing failed (KB '{kb_name}'): {e}"
        logger.error(f"[{task_id}] {error_msg}")

        task_manager.update_task_status(task_id, "error", error=error_msg)

        progress_tracker.update(
            ProgressStage.ERROR, f"Processing failed: {error_msg}", error=error_msg
        )


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


@router.get("/list", response_model=list[KnowledgeBaseInfo])
async def list_knowledge_bases():
    """List all available knowledge bases with their details."""
    try:
        manager = get_kb_manager()
        kb_names = manager.list_knowledge_bases()

        logger.info(f"Found {len(kb_names)} knowledge bases: {kb_names}")

        if not kb_names:
            logger.info("No knowledge bases found, returning empty list")
            return []

        result = []
        errors = []

        for name in kb_names:
            try:
                _sync_notebook_sources_kb_metadata(manager, name)
                info = manager.get_info(name)
                logger.debug(f"Successfully got info for KB '{name}': {info.get('statistics', {})}")
                result.append(
                    KnowledgeBaseInfo(
                        name=info["name"],
                        display_name=info.get("display_name") or info["name"],
                        is_default=info["is_default"],
                        statistics=info.get("statistics", {}),
                        system_managed=bool(info.get("system_managed", False)),
                        owner=info.get("owner"),
                    )
                )
            except Exception as e:
                error_msg = f"Error getting info for KB '{name}': {e}"
                errors.append(error_msg)
                logger.warning(f"{error_msg}\n{traceback.format_exc()}")
                try:
                    kb_dir = manager.base_dir / name
                    if kb_dir.exists():
                        logger.info(f"KB '{name}' directory exists, creating fallback info")
                        result.append(
                            KnowledgeBaseInfo(
                                name=name,
                                display_name=name,
                                is_default=name == manager.get_default(),
                                statistics={
                                    "raw_documents": 0,
                                    "images": 0,
                                    "content_lists": 0,
                                    "rag_initialized": False,
                                },
                                system_managed=False,
                                owner=None,
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

        logger.info(f"Returning {len(result)} knowledge bases")
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
        manager = get_kb_manager()
        _sync_notebook_sources_kb_metadata(manager, kb_name)
        return manager.get_info(kb_name)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Knowledge base '{kb_name}' not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{kb_name}/display_name")
async def update_knowledge_base_display_name(kb_name: str, request: UpdateDisplayNameRequest):
    """Update display name without changing real kb_name."""
    try:
        manager = get_kb_manager()
        display_name = (request.display_name or "").strip()
        if not display_name:
            raise HTTPException(status_code=400, detail="display_name cannot be empty")

        _sync_notebook_sources_kb_metadata(manager, kb_name)
        info = manager.get_info(kb_name)
        if info.get("system_managed"):
            raise HTTPException(
                status_code=400,
                detail="System-managed knowledge bases cannot be renamed directly",
            )

        metadata = manager.update_display_name(kb_name, display_name)
        return {
            "success": True,
            "name": kb_name,
            "display_name": metadata.get("display_name") or kb_name,
        }
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Knowledge base '{kb_name}' not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{kb_name}")
async def delete_knowledge_base(kb_name: str):
    """Delete a knowledge base."""
    try:
        manager = get_kb_manager()
        success = manager.delete_knowledge_base(kb_name, confirm=True)
        if not success:
            raise HTTPException(status_code=400, detail="Failed to delete knowledge base")
        logger.info(f"KB '{kb_name}' deleted")
        return {"message": f"Knowledge base '{kb_name}' deleted successfully"}
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Knowledge base '{kb_name}' not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{kb_name}/upload")
async def upload_files(
    kb_name: str, background_tasks: BackgroundTasks, files: list[UploadFile] = File(...)
):
    """Upload files to a knowledge base and process them in background."""
    try:
        manager = get_kb_manager()
        kb_path = manager.get_knowledge_base_path(kb_name)
        raw_dir = kb_path / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)

        try:
            llm_config = get_llm_config()
            api_key = llm_config.api_key
            base_url = llm_config.base_url
        except ValueError as e:
            raise HTTPException(status_code=500, detail=f"LLM config error: {e!s}")

        uploaded_files = []
        uploaded_file_paths = []
        for file in files:
            try:
                safe_filename = _safe_upload_filename(file.filename or "")
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid filename: {file.filename}")

            file_path = raw_dir / safe_filename
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            uploaded_files.append(safe_filename)
            uploaded_file_paths.append(str(file_path))

        logger.info(f"Uploading {len(uploaded_files)} files to KB '{kb_name}'")

        background_tasks.add_task(
            run_upload_processing_task,
            kb_name=kb_name,
            base_dir=str(_kb_base_dir),
            api_key=api_key,
            base_url=base_url,
            uploaded_file_paths=uploaded_file_paths,
        )

        return {
            "message": f"Uploaded {len(uploaded_files)} files. Processing in background.",
            "files": uploaded_files,
        }
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Knowledge base '{kb_name}' not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/create")
async def create_knowledge_base(
    background_tasks: BackgroundTasks, name: str = Form(...), files: list[UploadFile] = File(...)
):
    """Create a new knowledge base and initialize it with files."""
    try:
        manager = get_kb_manager()
        if name in manager.list_knowledge_bases():
            raise HTTPException(status_code=400, detail=f"Knowledge base '{name}' already exists")

        try:
            llm_config = get_llm_config()
            api_key = llm_config.api_key
            base_url = llm_config.base_url
        except ValueError as e:
            raise HTTPException(status_code=500, detail=f"LLM config error: {e!s}")

        progress_tracker = ProgressTracker(name, _kb_base_dir)

        logger.info(f"Creating KB: {name}")

        progress_tracker.update(
            ProgressStage.INITIALIZING, "Initializing knowledge base...", current=0, total=0
        )

        initializer = KnowledgeBaseInitializer(
            kb_name=name,
            base_dir=str(_kb_base_dir),
            api_key=api_key,
            base_url=base_url,
            progress_tracker=progress_tracker,
        )

        initializer.create_directory_structure()

        manager = get_kb_manager()
        if name not in manager.list_knowledge_bases():
            logger.warning(f"KB {name} not found in config, registering manually")
            initializer._register_to_config()

        uploaded_files = []
        for file in files:
            try:
                safe_filename = _safe_upload_filename(file.filename or "")
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid filename: {file.filename}")

            file_path = initializer.raw_dir / safe_filename
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            uploaded_files.append(safe_filename)

        progress_tracker.update(
            ProgressStage.PROCESSING_DOCUMENTS,
            f"Saved {len(uploaded_files)} files, preparing to process...",
            current=0,
            total=len(uploaded_files),
        )

        background_tasks.add_task(run_initialization_task, initializer)

        logger.success(f"KB '{name}' created, processing {len(uploaded_files)} files in background")

        return {
            "message": f"Knowledge base '{name}' created. Processing {len(uploaded_files)} files in background.",
            "name": name,
            "files": uploaded_files,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create KB: {e}")
        logger.debug(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{kb_name}/progress")
async def get_progress(kb_name: str):
    """Get initialization progress for a knowledge base"""
    try:
        progress_tracker = ProgressTracker(kb_name, _kb_base_dir)
        progress = progress_tracker.get_progress()

        if progress is None:
            return {"status": "not_started", "message": "Initialization not started"}

        return progress
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _load_doc_status(kb_path: Path) -> dict:
    """Load per-document status from kv_store_doc_status.json in rag_storage."""
    status_file = kb_path / "rag_storage" / "kv_store_doc_status.json"
    if not status_file.exists():
        return {}
    try:
        with open(status_file, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to read kv_store_doc_status.json: {e}")
        return {}


def _match_doc_status(filename: str, doc_status_map: dict) -> dict | None:
    """Match a filename to its entry in kv_store_doc_status.json by basename."""
    for _doc_id, entry in doc_status_map.items():
        entry_path = entry.get("file_path", "")
        if Path(entry_path).name == filename:
            return entry
    return None


def _normalize_status(entry: dict | None) -> tuple[str, str | None]:
    """Return (status, error_message) for a file.

    Possible statuses: 'indexed', 'processing', 'failed', 'pending'.
    """
    if entry is None:
        return ("pending", None)

    raw_status = entry.get("status", "")
    error_msg = entry.get("error_msg") or None

    if raw_status == "processed":
        return ("indexed", None)
    elif raw_status == "processing":
        return ("processing", None)
    elif raw_status == "failed":
        return ("failed", error_msg)
    else:
        return ("pending", None)


@router.get("/{kb_name}/files")
async def list_files(kb_name: str):
    """List all files in a knowledge base with their real per-file status."""
    try:
        manager = get_kb_manager()
        _sync_notebook_sources_kb_metadata(manager, kb_name)
        kb_path = manager.get_knowledge_base_path(kb_name)
        raw_dir = kb_path / "raw"

        if not raw_dir.exists():
            return []

        kb_info = manager.get_info(kb_name)
        kb_display_name = kb_info.get("display_name") or kb_name
        source_display_name_map = _load_source_display_name_map(kb_path)
        doc_status_map = _load_doc_status(kb_path)

        files = []
        for file_path in raw_dir.iterdir():
            if not file_path.is_file() or file_path.name.startswith("."):
                continue

            stat = file_path.stat()
            entry = _match_doc_status(file_path.name, doc_status_map)
            status, error_msg = _normalize_status(entry)

            file_info = {
                "name": file_path.name,
                "size": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "status": status,
            }
            display_name = source_display_name_map.get(file_path.name)
            if not display_name and file_path.suffix.lower() in {".md", ".markdown"}:
                title = _extract_markdown_h1(file_path)
                if title:
                    display_name = f"{kb_display_name} · {title}"
            file_info["display_name"] = display_name or file_path.name
            if error_msg:
                file_info["error"] = error_msg

            files.append(file_info)

        files.sort(key=lambda x: x["modified_at"], reverse=True)
        return files

    except ValueError:
        raise HTTPException(status_code=404, detail=f"Knowledge base '{kb_name}' not found")
    except Exception as e:
        logger.error(f"Error listing files: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{kb_name}/file/{filename}")
async def get_file(kb_name: str, filename: str):
    """Get a specific file from the knowledge base."""
    from fastapi.responses import FileResponse

    try:
        manager = get_kb_manager()
        raw_path = manager.get_raw_path(kb_name)
        file_path = raw_path / filename

        if not file_path.exists():
            raise HTTPException(status_code=404, detail="File not found")

        return FileResponse(
            path=file_path, filename=filename, media_type="application/octet-stream"
        )
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Knowledge base '{kb_name}' not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{kb_name}/progress/clear")
async def clear_progress(kb_name: str):
    """Clear progress file for a knowledge base (useful for stuck states)"""
    try:
        progress_tracker = ProgressTracker(kb_name, _kb_base_dir)
        progress_tracker.clear()
        return {"status": "success", "message": f"Progress cleared for {kb_name}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.websocket("/{kb_name}/progress/ws")
async def websocket_progress(websocket: WebSocket, kb_name: str):
    """WebSocket endpoint for real-time progress updates"""
    await websocket.accept()

    broadcaster = ProgressBroadcaster.get_instance()

    try:
        await broadcaster.connect(kb_name, websocket)

        progress_tracker = ProgressTracker(kb_name, _kb_base_dir)
        initial_progress = progress_tracker.get_progress()

        # Check if KB is already ready (has rag_storage)
        kb_dir = _kb_base_dir / kb_name
        rag_storage_dir = kb_dir / "rag_storage"
        kb_is_ready = rag_storage_dir.exists() and rag_storage_dir.is_dir()

        # Only send non-completed progress if KB is not ready
        # or if progress is recent (within 5 minutes)
        if initial_progress:
            stage = initial_progress.get("stage")
            timestamp = initial_progress.get("timestamp")

            should_send = False
            if stage in ["completed", "error"] or not kb_is_ready:
                should_send = True
            elif timestamp:
                # Check if progress is recent
                try:
                    progress_time = datetime.fromisoformat(timestamp)
                    now = datetime.now()
                    age_seconds = (now - progress_time).total_seconds()
                    if age_seconds < 300:  # 5 minutes
                        should_send = True
                except:
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
        except:
            pass
    finally:
        await broadcaster.disconnect(kb_name, websocket)
        try:
            await websocket.close()
        except:
            pass
