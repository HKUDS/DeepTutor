"""
Structure Note API Router
=========================

Independent workspace for turning PDF/PPT/PPTX course materials into structured notes.
"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path, PurePosixPath
import shutil
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from deeptutor.api.utils.task_id_manager import TaskIDManager
from deeptutor.api.utils.task_log_stream import get_task_stream_manager
from deeptutor.logging import get_logger
from deeptutor.services.config import PROJECT_ROOT, load_config_with_main
from deeptutor.services.structure_note import (
    DifficultyLevel,
    ExplanationStyleLevel,
    JobStatus,
    NoteLanguage,
    StructureNoteManager,
)
from deeptutor.utils.document_validator import DocumentValidator

router = APIRouter()
_structure_note_manager: StructureNoteManager | None = None
_kb_base_dir = PROJECT_ROOT / "data" / "knowledge_bases"
_accepted_source_extensions = {".pdf", ".ppt", ".pptx"}

try:
    config = load_config_with_main("main.yaml", PROJECT_ROOT)
except FileNotFoundError:
    config = {}
log_dir = config.get("paths", {}).get("user_log_dir") or config.get("logging", {}).get("log_dir")
logger = get_logger("StructureNote", level="INFO", log_dir=log_dir)


def get_structure_note_manager() -> StructureNoteManager:
    global _structure_note_manager
    if _structure_note_manager is None:
        _structure_note_manager = StructureNoteManager()
    return _structure_note_manager


def _build_unique_task_id(task_type: str, task_key_prefix: str) -> str:
    task_manager = TaskIDManager.get_instance()
    task_key = f"{task_key_prefix}_{datetime.now().isoformat()}_{uuid4().hex[:8]}"
    return task_manager.generate_task_id(task_type, task_key)


def _emit_log(task_id: str, message: str) -> None:
    manager = get_task_stream_manager()
    manager.ensure_task(task_id)
    manager.emit_log(task_id, message)
    logger.info(f"[{task_id}] {message}")


def _save_upload(file: UploadFile, target_dir: Path) -> tuple[Path, str, int]:
    safe_name = DocumentValidator.validate_upload_safety(
        file.filename or "upload",
        None,
        allowed_extensions={".pdf", ".ppt", ".pptx"},
    )
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / safe_name
    written_bytes = 0
    with open(target_path, "wb") as handle:
        for chunk in iter(lambda: file.file.read(8192), b""):
            written_bytes += len(chunk)
            if written_bytes > DocumentValidator.MAX_FILE_SIZE:
                raise HTTPException(status_code=400, detail="Uploaded file exceeds the size limit.")
            handle.write(chunk)

    DocumentValidator.validate_upload_safety(
        safe_name,
        written_bytes,
        allowed_extensions={".pdf", ".ppt", ".pptx"},
    )
    return target_path, safe_name, written_bytes


def _validate_kb_file_id(file_id: str) -> PurePosixPath:
    relative_path = PurePosixPath(file_id)
    if (
        relative_path.is_absolute()
        or not relative_path.parts
        or any(part in {"", ".", ".."} for part in relative_path.parts)
    ):
        raise HTTPException(status_code=400, detail="Invalid Knowledge Base file id.")
    return relative_path


def _is_safe_kb_name(kb_name: str) -> bool:
    relative_name = PurePosixPath(kb_name)
    return (
        not relative_name.is_absolute()
        and len(relative_name.parts) == 1
        and all(part not in {"", ".", ".."} for part in relative_name.parts)
    )


def _validate_kb_name(kb_name: str) -> str:
    if not _is_safe_kb_name(kb_name):
        raise HTTPException(status_code=400, detail="Invalid Knowledge Base name.")
    return PurePosixPath(kb_name).name


def _list_kb_names_readonly() -> list[str]:
    kb_names: set[str] = set()
    config_path = _kb_base_dir / "kb_config.json"
    if config_path.exists():
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            knowledge_bases = payload.get("knowledge_bases", {})
            if isinstance(knowledge_bases, dict):
                kb_names.update(
                    str(name) for name in knowledge_bases.keys() if _is_safe_kb_name(str(name))
                )
        except Exception as exc:
            logger.warning(f"Failed to read Knowledge Base config for Structure Note: {exc}")

    if _kb_base_dir.exists():
        for item in _kb_base_dir.iterdir():
            if not item.is_dir() or item.name.startswith(("__", ".")):
                continue
            if (
                (item / "raw").exists()
                or (item / "llamaindex_storage").exists()
                or (item / "rag_storage").exists()
            ):
                kb_names.add(item.name)

    return sorted(kb_names)


def _kb_raw_dir(kb_name: str) -> Path:
    safe_kb_name = _validate_kb_name(kb_name)
    if safe_kb_name not in _list_kb_names_readonly():
        raise HTTPException(status_code=404, detail="Knowledge Base not found.")

    base_dir = _kb_base_dir.resolve()
    kb_dir = (base_dir / safe_kb_name).resolve()
    try:
        kb_dir.relative_to(base_dir)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid Knowledge Base name.")
    return kb_dir / "raw"


def _resolve_kb_source_file(kb_name: str, file_id: str) -> Path:
    relative_path = _validate_kb_file_id(file_id)
    raw_dir = _kb_raw_dir(kb_name).resolve()
    source_path = (raw_dir / Path(*relative_path.parts)).resolve()
    try:
        source_path.relative_to(raw_dir)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid Knowledge Base file id.")

    if not source_path.exists() or not source_path.is_file():
        raise HTTPException(status_code=404, detail="Knowledge Base file not found.")
    if source_path.suffix.lower() not in _accepted_source_extensions:
        raise HTTPException(
            status_code=400, detail="Structure Note accepts PDF, PPT, or PPTX only."
        )
    return source_path


def _list_kb_source_files() -> list[dict]:
    groups: list[dict] = []
    for kb_name in _list_kb_names_readonly():
        raw_dir = _kb_raw_dir(kb_name)
        files: list[dict] = []
        if raw_dir.exists():
            for source_path in sorted(raw_dir.rglob("*"), key=lambda item: item.as_posix()):
                if not source_path.is_file():
                    continue
                if source_path.suffix.lower() not in _accepted_source_extensions:
                    continue
                stat = source_path.stat()
                file_id = source_path.relative_to(raw_dir).as_posix()
                files.append(
                    {
                        "file_id": file_id,
                        "file_name": source_path.name,
                        "display_path": file_id,
                        "size_bytes": stat.st_size,
                        "updated_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    }
                )

        groups.append({"kb_name": kb_name, "files": files})
    return groups


async def _run_structure_note_job(job_id: str, task_id: str) -> None:
    stream_manager = get_task_stream_manager()
    stream_manager.ensure_task(task_id)
    manager = get_structure_note_manager()
    artifact = await manager.run_job(job_id, task_id, _emit_log)
    if artifact.status == JobStatus.READY:
        stream_manager.emit_complete(task_id, "Structure Note completed")
    else:
        stream_manager.emit_failed(task_id, artifact.error or "Structure Note failed")


@router.post("/jobs")
async def create_job(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    difficulty_level: DifficultyLevel = Form(DifficultyLevel.MEDIUM),
    note_language: NoteLanguage = Form(NoteLanguage.ZH),
    style_level: ExplanationStyleLevel = Form(ExplanationStyleLevel.MEDIUM),
    project_name: str | None = Form(None),
):
    manager = get_structure_note_manager()
    task_id = _build_unique_task_id("structure_note", file.filename or "upload")
    get_task_stream_manager().ensure_task(task_id)

    source_format = Path(file.filename or "").suffix.lower().lstrip(".")
    if source_format not in {"pdf", "ppt", "pptx"}:
        raise HTTPException(
            status_code=400, detail="Structure Note accepts PDF, PPT, or PPTX only."
        )

    job_id = f"structure_note_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"
    job_dirs = manager.storage.ensure_job_dirs(job_id)
    source_path, safe_name, _ = _save_upload(file, job_dirs["source"])

    target_project_name = (
        project_name.strip() if project_name and project_name.strip() else "Local Uploads"
    )
    try:
        artifact = manager.create_job(
            file_name=safe_name,
            source_format=source_format,
            difficulty_level=difficulty_level,
            note_language=note_language,
            style_level=style_level,
            source_path=source_path,
            task_id=task_id,
            job_id=job_id,
            project_name=target_project_name,
            note_title=Path(safe_name).stem,
            source_kind="upload",
            source_ref={"file_name": safe_name},
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _emit_log(task_id, f"Created Structure Note job for `{safe_name}`.")
    background_tasks.add_task(_run_structure_note_job, artifact.job_id, task_id)
    return manager.serialize_job(artifact)


@router.get("/jobs")
async def list_jobs():
    manager = get_structure_note_manager()
    return {"jobs": [manager.serialize_job(job) for job in manager.list_jobs()]}


@router.get("/projects")
async def list_projects():
    manager = get_structure_note_manager()
    return {"projects": [project.model_dump(mode="json") for project in manager.list_projects()]}


@router.post("/projects")
async def create_project(name: str = Form(...)):
    manager = get_structure_note_manager()
    try:
        project = manager.create_project(name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return project.model_dump(mode="json")


@router.post("/projects/{project_name}/rename")
async def rename_project(project_name: str, new_name: str = Form(...)):
    manager = get_structure_note_manager()
    try:
        project = manager.rename_project(project_name, new_name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found.")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return project.model_dump(mode="json")


@router.delete("/projects/{project_name}")
async def delete_project(project_name: str):
    manager = get_structure_note_manager()
    try:
        deleted_job_ids = manager.delete_project(project_name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found.")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"deleted_job_ids": deleted_job_ids}


@router.get("/kb/files")
async def list_knowledge_base_source_files():
    return {"knowledge_bases": _list_kb_source_files()}


@router.post("/jobs/from-kb")
async def create_job_from_knowledge_base(
    background_tasks: BackgroundTasks,
    kb_name: str = Form(...),
    file_id: str = Form(...),
    difficulty_level: DifficultyLevel = Form(DifficultyLevel.MEDIUM),
    note_language: NoteLanguage = Form(NoteLanguage.ZH),
    style_level: ExplanationStyleLevel = Form(ExplanationStyleLevel.MEDIUM),
    project_name: str | None = Form(None),
):
    source_file = _resolve_kb_source_file(kb_name, file_id)
    safe_name = DocumentValidator.validate_upload_safety(
        source_file.name,
        source_file.stat().st_size,
        allowed_extensions=_accepted_source_extensions,
    )
    source_format = source_file.suffix.lower().lstrip(".")

    manager = get_structure_note_manager()
    task_id = _build_unique_task_id("structure_note", f"{kb_name}_{safe_name}")
    get_task_stream_manager().ensure_task(task_id)

    job_id = f"structure_note_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"
    job_dirs = manager.storage.ensure_job_dirs(job_id)
    snapshot_path = job_dirs["source"] / safe_name
    shutil.copy2(source_file, snapshot_path)

    target_project_name = project_name.strip() if project_name and project_name.strip() else kb_name
    try:
        artifact = manager.create_job(
            file_name=safe_name,
            source_format=source_format,
            difficulty_level=difficulty_level,
            note_language=note_language,
            style_level=style_level,
            source_path=snapshot_path,
            task_id=task_id,
            job_id=job_id,
            project_name=target_project_name,
            note_title=Path(file_id).stem,
            source_kind="knowledge_base",
            source_ref={
                "kb_name": kb_name,
                "file_id": file_id,
                "file_name": source_file.name,
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _emit_log(
        task_id, f"Created Structure Note job for `{safe_name}` from Knowledge Base `{kb_name}`."
    )
    background_tasks.add_task(_run_structure_note_job, artifact.job_id, task_id)
    return manager.serialize_job(artifact)


@router.get("/jobs/{job_id}")
async def get_job(job_id: str):
    manager = get_structure_note_manager()
    try:
        return manager.serialize_job(manager.get_job(job_id))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Structure Note job not found")


@router.post("/jobs/{job_id}/retry")
async def retry_job(job_id: str, background_tasks: BackgroundTasks):
    manager = get_structure_note_manager()
    try:
        artifact = manager.get_job(job_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Structure Note job not found")

    if artifact.status != JobStatus.FAILED:
        raise HTTPException(status_code=409, detail="Only failed jobs can be retried.")

    task_id = _build_unique_task_id("structure_note_retry", job_id)
    get_task_stream_manager().ensure_task(task_id)
    artifact = manager.update_status(artifact, JobStatus.QUEUED, error=None, task_id=task_id)
    _emit_log(task_id, f"Retrying Structure Note job `{artifact.file_name}`.")
    background_tasks.add_task(_run_structure_note_job, artifact.job_id, task_id)
    return manager.serialize_job(artifact)


@router.get("/tasks/{task_id}/stream")
async def stream_task(task_id: str):
    manager = get_task_stream_manager()
    manager.ensure_task(task_id)
    return StreamingResponse(
        manager.stream(task_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
