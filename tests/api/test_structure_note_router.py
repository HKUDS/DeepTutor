from __future__ import annotations

import json
from pathlib import Path

import pytest

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except Exception:  # pragma: no cover
    FastAPI = None
    TestClient = None

pytestmark = pytest.mark.skipif(
    FastAPI is None or TestClient is None, reason="fastapi not installed"
)

if FastAPI is not None and TestClient is not None:
    from deeptutor.api.routers import structure_note as structure_note_router_module
    from deeptutor.agents.structure_note import (
        DifficultyLevel,
        ExplanationStyleLevel,
        JobStatus,
        NoteLanguage,
        StructureNoteManager,
        StructureNoteStorage,
    )

    router = structure_note_router_module.router
else:  # pragma: no cover
    structure_note_router_module = None
    router = None


def _build_app() -> FastAPI:
    if FastAPI is None or router is None:  # pragma: no cover
        raise RuntimeError("fastapi is not installed")
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/structure-note")
    return app


def _write_kb_raw_file(
    tmp_path: Path,
    kb_name: str,
    file_name: str,
    content: bytes = b"%PDF-1.4\n%%EOF",
) -> Path:
    kb_base = tmp_path / "data" / "knowledge_bases"
    raw_dir = kb_base / kb_name / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (kb_base / kb_name / "llamaindex_storage").mkdir(parents=True, exist_ok=True)
    config_path = kb_base / "kb_config.json"
    config = (
        json.loads(config_path.read_text(encoding="utf-8"))
        if config_path.exists()
        else {"knowledge_bases": {}}
    )
    config.setdefault("knowledge_bases", {})[kb_name] = {
        "path": kb_name,
        "status": "ready",
        "rag_provider": "llamaindex",
    }
    config_path.write_text(json.dumps(config), encoding="utf-8")
    source_path = raw_dir / file_name
    source_path.write_bytes(content)
    return source_path


@pytest.fixture
def manager(tmp_path: Path):
    storage = StructureNoteStorage()
    original_root = storage.path_service._project_root
    original_user_dir = storage.path_service._user_data_dir
    try:
        storage.path_service._project_root = tmp_path
        storage.path_service._user_data_dir = tmp_path / "data" / "user"
        storage.path_service.ensure_all_directories()
        yield StructureNoteManager(storage=storage)
    finally:
        storage.path_service._project_root = original_root
        storage.path_service._user_data_dir = original_user_dir


def test_create_job_returns_contract(monkeypatch, manager) -> None:
    monkeypatch.setattr(structure_note_router_module, "_structure_note_manager", manager)

    async def _noop_run(*_args, **_kwargs):
        return None

    monkeypatch.setattr(structure_note_router_module, "_run_structure_note_job", _noop_run)

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/v1/structure-note/jobs",
            data={
                "difficulty_level": DifficultyLevel.MEDIUM.value,
                "note_language": NoteLanguage.EN.value,
                "style_level": ExplanationStyleLevel.HIGH.value,
                "project_name": "Course A",
            },
            files={
                "file": (
                    "chapter.pdf",
                    b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF",
                    "application/pdf",
                )
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["file_name"] == "chapter.pdf"
    assert body["difficulty_level"] == "medium"
    assert body["note_language"] == "en"
    assert body["style_level"] == "high"
    assert body["project_name"] == "Course A"
    assert body["note_title"] == "chapter"
    assert body["source_kind"] == "upload"
    assert body["status"] == "queued"
    assert isinstance(body["task_id"], str) and body["task_id"]


def test_create_and_rename_project_updates_jobs(monkeypatch, manager) -> None:
    monkeypatch.setattr(structure_note_router_module, "_structure_note_manager", manager)

    async def _noop_run(*_args, **_kwargs):
        return None

    monkeypatch.setattr(structure_note_router_module, "_run_structure_note_job", _noop_run)

    with TestClient(_build_app()) as client:
        create_project_response = client.post(
            "/api/v1/structure-note/projects",
            data={"name": "Course A"},
        )
        create_job_response = client.post(
            "/api/v1/structure-note/jobs",
            data={
                "difficulty_level": DifficultyLevel.MEDIUM.value,
                "note_language": NoteLanguage.EN.value,
                "style_level": ExplanationStyleLevel.MEDIUM.value,
                "project_name": "Course A",
            },
            files={
                "file": (
                    "chapter.pdf",
                    b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF",
                    "application/pdf",
                )
            },
        )
        rename_response = client.post(
            "/api/v1/structure-note/projects/Course%20A/rename",
            data={"new_name": "Course B"},
        )
        list_response = client.get("/api/v1/structure-note/projects")
        detail_response = client.get(
            f"/api/v1/structure-note/jobs/{create_job_response.json()['job_id']}"
        )

    assert create_project_response.status_code == 200
    assert create_project_response.json()["name"] == "Course A"
    assert create_job_response.status_code == 200
    assert rename_response.status_code == 200
    assert rename_response.json()["name"] == "Course B"
    project_names = [project["name"] for project in list_response.json()["projects"]]
    assert "Course B" in project_names
    assert "Course A" not in project_names
    assert detail_response.json()["project_name"] == "Course B"


def test_delete_project_removes_jobs(monkeypatch, manager) -> None:
    monkeypatch.setattr(structure_note_router_module, "_structure_note_manager", manager)
    job_dirs = manager.storage.ensure_job_dirs("job_project_delete")
    source_path = job_dirs["source"] / "demo.pdf"
    source_path.write_text("pdf", encoding="utf-8")
    artifact = manager.create_job(
        file_name="demo.pdf",
        source_format="pdf",
        difficulty_level=DifficultyLevel.SIMPLE,
        note_language=NoteLanguage.ZH,
        style_level=ExplanationStyleLevel.LOW,
        source_path=source_path,
        task_id="task_1",
        job_id="job_project_delete",
        project_name="Course A",
    )
    assert manager.storage.get_job_dir(artifact.job_id).exists()

    with TestClient(_build_app()) as client:
        response = client.delete("/api/v1/structure-note/projects/Course%20A")
        list_response = client.get("/api/v1/structure-note/jobs")

    assert response.status_code == 200
    assert response.json()["deleted_job_ids"] == ["job_project_delete"]
    assert not manager.storage.get_job_dir(artifact.job_id).exists()
    assert list_response.json()["jobs"] == []


def test_list_and_detail_jobs(monkeypatch, manager) -> None:
    monkeypatch.setattr(structure_note_router_module, "_structure_note_manager", manager)
    job_dirs = manager.storage.ensure_job_dirs("job_1")
    source_path = job_dirs["source"] / "demo.pdf"
    source_path.write_text("pdf", encoding="utf-8")
    artifact = manager.create_job(
        file_name="demo.pdf",
        source_format="pdf",
        difficulty_level=DifficultyLevel.SIMPLE,
        note_language=NoteLanguage.ZH,
        style_level=ExplanationStyleLevel.LOW,
        source_path=source_path,
        task_id="task_1",
        job_id="job_1",
    )
    manager.update_status(artifact, JobStatus.FAILED, error="boom", task_id="task_1")

    with TestClient(_build_app()) as client:
        list_response = client.get("/api/v1/structure-note/jobs")
        detail_response = client.get("/api/v1/structure-note/jobs/job_1")

    assert list_response.status_code == 200
    jobs = list_response.json()["jobs"]
    assert jobs[0]["job_id"] == "job_1"
    assert detail_response.status_code == 200
    assert detail_response.json()["retry_available"] is True
    assert detail_response.json()["note_language"] == "zh"
    assert detail_response.json()["style_level"] == "low"


def test_retry_failed_job(monkeypatch, manager) -> None:
    monkeypatch.setattr(structure_note_router_module, "_structure_note_manager", manager)

    async def _noop_run(*_args, **_kwargs):
        return None

    monkeypatch.setattr(structure_note_router_module, "_run_structure_note_job", _noop_run)

    job_dirs = manager.storage.ensure_job_dirs("job_retry")
    source_path = job_dirs["source"] / "deck.pdf"
    source_path.write_text("pdf", encoding="utf-8")
    artifact = manager.create_job(
        file_name="deck.pdf",
        source_format="pdf",
        difficulty_level=DifficultyLevel.MEDIUM,
        note_language=NoteLanguage.EN,
        style_level=ExplanationStyleLevel.MEDIUM,
        source_path=source_path,
        task_id="task_old",
        job_id="job_retry",
    )
    manager.update_status(artifact, JobStatus.FAILED, error="old error", task_id="task_old")

    with TestClient(_build_app()) as client:
        response = client.post("/api/v1/structure-note/jobs/job_retry/retry")

    assert response.status_code == 200
    body = response.json()
    assert body["job_id"] == "job_retry"
    assert body["status"] == "queued"
    assert body["task_id"] != "task_old"


def test_list_knowledge_base_source_files(monkeypatch, tmp_path: Path, manager) -> None:
    monkeypatch.setattr(structure_note_router_module, "_structure_note_manager", manager)
    monkeypatch.setattr(
        structure_note_router_module,
        "_kb_base_dir",
        tmp_path / "data" / "knowledge_bases",
    )
    _write_kb_raw_file(tmp_path, "Math", "lesson.pdf")
    _write_kb_raw_file(tmp_path, "Ignored", "notes.txt")

    with TestClient(_build_app()) as client:
        response = client.get("/api/v1/structure-note/kb/files")

    assert response.status_code == 200
    groups = response.json()["knowledge_bases"]
    math_group = next(group for group in groups if group["kb_name"] == "Math")
    assert math_group["files"][0]["file_id"] == "lesson.pdf"
    assert math_group["files"][0]["file_name"] == "lesson.pdf"
    ignored_group = next(group for group in groups if group["kb_name"] == "Ignored")
    assert ignored_group["files"] == []


def test_create_job_from_knowledge_base_file(monkeypatch, tmp_path: Path, manager) -> None:
    monkeypatch.setattr(structure_note_router_module, "_structure_note_manager", manager)
    monkeypatch.setattr(
        structure_note_router_module,
        "_kb_base_dir",
        tmp_path / "data" / "knowledge_bases",
    )

    async def _noop_run(*_args, **_kwargs):
        return None

    monkeypatch.setattr(structure_note_router_module, "_run_structure_note_job", _noop_run)
    _write_kb_raw_file(tmp_path, "Math", "lesson.pdf")

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/v1/structure-note/jobs/from-kb",
            data={
                "kb_name": "Math",
                "file_id": "lesson.pdf",
                "difficulty_level": DifficultyLevel.SIMPLE.value,
                "note_language": NoteLanguage.ZH.value,
                "style_level": ExplanationStyleLevel.MEDIUM.value,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["file_name"] == "lesson.pdf"
    assert body["project_name"] == "Math"
    assert body["note_title"] == "lesson"
    assert body["source_kind"] == "knowledge_base"
    assert body["source_ref"] == {
        "kb_name": "Math",
        "file_id": "lesson.pdf",
        "file_name": "lesson.pdf",
    }
    artifact = manager.get_job(body["job_id"])
    assert Path(artifact.source_path).exists()
