from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import shutil
from typing import Any

from deeptutor.services.path_service import PathService, get_path_service

from .models import StructureNoteArtifact, StructureNoteProject


def _utc_now() -> str:
    return datetime.utcnow().isoformat()


class StructureNoteStorage:
    def __init__(self, path_service: PathService | None = None):
        self.path_service = path_service or get_path_service()

    def get_root_dir(self) -> Path:
        return self.path_service.get_structure_note_dir()

    def get_job_dir(self, job_id: str) -> Path:
        return self.path_service.get_structure_note_job_dir(job_id)

    def ensure_job_dirs(self, job_id: str) -> dict[str, Path]:
        job_dir = self.get_job_dir(job_id)
        dirs = {
            "job": job_dir,
            "source": job_dir / "source",
            "normalized": job_dir / "normalized",
            "index": job_dir / "index",
            "chunks": job_dir / "chunks",
            "images": job_dir / "images",
            "final": job_dir / "final",
        }
        for directory in dirs.values():
            directory.mkdir(parents=True, exist_ok=True)
        return dirs

    def artifact_path(self, job_id: str) -> Path:
        return self.get_job_dir(job_id) / "artifact.json"

    def projects_path(self) -> Path:
        return self.get_root_dir() / "projects.json"

    def write_artifact(self, artifact: StructureNoteArtifact) -> StructureNoteArtifact:
        payload = artifact.model_dump(mode="json")
        path = self.artifact_path(artifact.job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
        return artifact

    def read_artifact(self, job_id: str) -> StructureNoteArtifact:
        with open(self.artifact_path(job_id), encoding="utf-8") as handle:
            return StructureNoteArtifact.model_validate(json.load(handle))

    def artifact_exists(self, job_id: str) -> bool:
        return self.artifact_path(job_id).exists()

    def delete_job_dir(self, job_id: str) -> None:
        shutil.rmtree(self.get_job_dir(job_id), ignore_errors=True)

    def list_artifacts(self) -> list[StructureNoteArtifact]:
        artifacts: list[StructureNoteArtifact] = []
        root = self.get_root_dir()
        if not root.exists():
            return artifacts
        for child in root.iterdir():
            if not child.is_dir():
                continue
            artifact_path = child / "artifact.json"
            if not artifact_path.exists():
                continue
            try:
                with open(artifact_path, encoding="utf-8") as handle:
                    artifacts.append(StructureNoteArtifact.model_validate(json.load(handle)))
            except Exception:
                continue
        artifacts.sort(key=lambda item: item.updated_at, reverse=True)
        return artifacts

    def read_projects(self) -> list[StructureNoteProject]:
        path = self.projects_path()
        if not path.exists():
            return []
        try:
            with open(path, encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception:
            return []
        if not isinstance(payload, list):
            return []
        projects: list[StructureNoteProject] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            try:
                projects.append(StructureNoteProject.model_validate(item))
            except Exception:
                continue
        return projects

    def write_projects(self, projects: list[StructureNoteProject]) -> list[StructureNoteProject]:
        path = self.projects_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(
                [project.model_dump(mode="json") for project in projects],
                handle,
                indent=2,
                ensure_ascii=False,
            )
        return projects

    def write_json(self, path: Path, payload: Any) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
        return path

    def read_json(self, path: Path) -> Any:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)

    def write_text(self, path: Path, content: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def output_url_for(self, path: str | Path | None) -> str | None:
        if not path:
            return None
        candidate = Path(path).resolve()
        root = self.path_service.get_user_root().resolve()
        try:
            relative = candidate.relative_to(root)
        except ValueError:
            return None
        return f"/api/outputs/{relative.as_posix()}"

    def get_retention_mode(self) -> str:
        default_mode = "full" if os.getenv("PYTEST_CURRENT_TEST") else "minimal"
        mode = os.getenv("STRUCTURE_NOTE_RETENTION_MODE", default_mode).strip().lower()
        return mode if mode in {"full", "minimal"} else default_mode

    def apply_retention_policy(self, artifact: StructureNoteArtifact) -> None:
        if self.get_retention_mode() != "minimal":
            return

        preserved: set[Path] = {self.artifact_path(artifact.job_id).resolve()}
        for candidate in (
            artifact.final_pdf_path,
            artifact.citation_manifest_path,
            artifact.rendered_markdown_path,
            artifact.page_index_path,
            artifact.section_tree_path,
            artifact.document_plan_path,
            artifact.generation_chunks_path,
            artifact.image_fill_state_path,
        ):
            if candidate:
                preserved.add(Path(candidate).resolve())

        for directory_name in ("normalized", "index", "chunks"):
            directory = self.get_job_dir(artifact.job_id) / directory_name
            if not directory.exists():
                continue
            for child in directory.rglob("*"):
                if child.is_dir():
                    continue
                if child.resolve() in preserved:
                    continue
                child.unlink(missing_ok=True)

    def touch_updated_at(self, artifact: StructureNoteArtifact) -> StructureNoteArtifact:
        artifact.updated_at = _utc_now()
        return artifact

    def new_timestamp(self) -> str:
        return _utc_now()
