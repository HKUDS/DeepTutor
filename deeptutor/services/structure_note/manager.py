from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal
import uuid

from deeptutor.logging import get_logger

from .difficulty import get_difficulty_preset
from .generator import (
    build_generation_chunks,
    generate_chunk_markdown,
    generate_transition_markdown,
    inject_image_placeholders,
)
from .image_pipeline import process_images
from .markdown_postprocessor import normalize_structure_note_markdown
from .models import (
    CitationEntry,
    DifficultyLevel,
    DocumentPlan,
    ExplanationStyleLevel,
    GenerationChunk,
    JobStatus,
    NoteLanguage,
    PageIndexPage,
    SectionTreeNode,
    StructureNoteArtifact,
    StructureNoteProject,
)
from .normalizer import normalize_to_pdf
from .page_index import build_page_index
from .planner import build_document_plan
from .renderer import render_pdf
from .storage import StructureNoteStorage
from .tree_builder import build_section_tree


class StructureNoteManager:
    def __init__(self, storage: StructureNoteStorage | None = None):
        self.storage = storage or StructureNoteStorage()
        self.logger = get_logger("StructureNote")

    def _normalize_project_name(self, project_name: str | None) -> str:
        normalized = (project_name or "").strip()
        if not normalized:
            raise ValueError("Project name is required.")
        if "/" in normalized or "\\" in normalized:
            raise ValueError("Project name cannot contain path separators.")
        return normalized

    def _artifact_project_name(self, artifact: StructureNoteArtifact) -> str:
        return artifact.project_name or artifact.source_ref.get("kb_name") or "Local Uploads"

    def list_projects(self) -> list[StructureNoteProject]:
        projects_by_name: dict[str, StructureNoteProject] = {
            self._normalize_project_name(project.name): project
            for project in self.storage.read_projects()
        }
        for artifact in self.list_jobs():
            project_name = self._artifact_project_name(artifact)
            existing = projects_by_name.get(project_name)
            if existing is None:
                projects_by_name[project_name] = StructureNoteProject(
                    name=project_name,
                    created_at=artifact.created_at,
                    updated_at=artifact.updated_at,
                )
            elif artifact.updated_at > existing.updated_at:
                existing.updated_at = artifact.updated_at
        return sorted(projects_by_name.values(), key=lambda item: item.name.lower())

    def create_project(self, project_name: str) -> StructureNoteProject:
        name = self._normalize_project_name(project_name)
        projects = {project.name: project for project in self.list_projects()}
        if name in projects:
            raise ValueError(f"Project already exists: {name}")
        timestamp = self.storage.new_timestamp()
        project = StructureNoteProject(name=name, created_at=timestamp, updated_at=timestamp)
        projects[name] = project
        self.storage.write_projects(sorted(projects.values(), key=lambda item: item.name.lower()))
        return project

    def ensure_project(self, project_name: str) -> StructureNoteProject:
        name = self._normalize_project_name(project_name)
        for project in self.list_projects():
            if project.name == name:
                return project
        return self.create_project(name)

    def rename_project(self, old_name: str, new_name: str) -> StructureNoteProject:
        old_project_name = self._normalize_project_name(old_name)
        new_project_name = self._normalize_project_name(new_name)
        if old_project_name == new_project_name:
            self.ensure_project(new_project_name)
            return next(
                project for project in self.list_projects() if project.name == new_project_name
            )

        projects = {project.name: project for project in self.list_projects()}
        if old_project_name not in projects:
            raise FileNotFoundError(f"Project not found: {old_project_name}")
        if new_project_name in projects:
            raise ValueError(f"Project already exists: {new_project_name}")

        renamed = projects.pop(old_project_name)
        renamed.name = new_project_name
        renamed.updated_at = self.storage.new_timestamp()
        projects[new_project_name] = renamed

        for artifact in self.list_jobs():
            if self._artifact_project_name(artifact) != old_project_name:
                continue
            artifact.project_name = new_project_name
            self.storage.touch_updated_at(artifact)
            self.storage.write_artifact(artifact)

        self.storage.write_projects(sorted(projects.values(), key=lambda item: item.name.lower()))
        return renamed

    def delete_project(self, project_name: str) -> list[str]:
        name = self._normalize_project_name(project_name)
        projects = {project.name: project for project in self.list_projects()}
        if name not in projects:
            raise FileNotFoundError(f"Project not found: {name}")

        deleted_job_ids: list[str] = []
        for artifact in self.list_jobs():
            if self._artifact_project_name(artifact) != name:
                continue
            deleted_job_ids.append(artifact.job_id)
            self.storage.delete_job_dir(artifact.job_id)

        projects.pop(name, None)
        self.storage.write_projects(sorted(projects.values(), key=lambda item: item.name.lower()))
        return deleted_job_ids

    def create_job(
        self,
        file_name: str,
        source_format: str,
        difficulty_level: DifficultyLevel,
        note_language: NoteLanguage,
        style_level: ExplanationStyleLevel,
        source_path: Path,
        task_id: str,
        job_id: str | None = None,
        project_name: str | None = None,
        note_title: str | None = None,
        source_kind: Literal["upload", "knowledge_base"] = "upload",
        source_ref: dict[str, str] | None = None,
    ) -> StructureNoteArtifact:
        job_id = job_id or (
            f"structure_note_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        )
        self.storage.ensure_job_dirs(job_id)
        inferred_title = Path(file_name).stem or file_name
        if project_name:
            project_name = self.ensure_project(project_name).name
        artifact = StructureNoteArtifact(
            job_id=job_id,
            file_name=file_name,
            source_format=source_format,
            difficulty_level=difficulty_level,
            note_language=note_language,
            style_level=style_level,
            project_name=project_name,
            note_title=note_title or inferred_title,
            source_kind=source_kind,
            source_ref=source_ref or {},
            status=JobStatus.QUEUED,
            source_path=str(source_path),
            task_id=task_id,
            retry_state=None,
            error=None,
            created_at=self.storage.new_timestamp(),
            updated_at=self.storage.new_timestamp(),
        )
        return self.storage.write_artifact(artifact)

    def list_jobs(self) -> list[StructureNoteArtifact]:
        return self.storage.list_artifacts()

    def get_job(self, job_id: str) -> StructureNoteArtifact:
        return self.storage.read_artifact(job_id)

    def update_status(
        self,
        artifact: StructureNoteArtifact,
        status: JobStatus,
        *,
        error: str | None = None,
        retry_state: str | None = None,
        task_id: str | None = None,
    ) -> StructureNoteArtifact:
        artifact.status = status
        artifact.error = error
        artifact.retry_state = retry_state
        if task_id is not None:
            artifact.task_id = task_id
        self.storage.touch_updated_at(artifact)
        return self.storage.write_artifact(artifact)

    def serialize_job(self, artifact: StructureNoteArtifact) -> dict[str, Any]:
        citations: list[dict[str, Any]] = []
        if artifact.citation_manifest_path and Path(artifact.citation_manifest_path).exists():
            citations = self.storage.read_json(Path(artifact.citation_manifest_path))
        section_tree = self._load_section_tree_payload(artifact.section_tree_path)
        return {
            "job_id": artifact.job_id,
            "file_name": artifact.file_name,
            "status": artifact.status.value,
            "source_format": artifact.source_format,
            "difficulty_level": artifact.difficulty_level.value,
            "note_language": artifact.note_language.value,
            "style_level": artifact.style_level.value,
            "project_name": artifact.project_name,
            "note_title": artifact.note_title,
            "source_kind": artifact.source_kind,
            "source_ref": artifact.source_ref,
            "final_pdf_url": self.storage.output_url_for(artifact.final_pdf_path),
            "rendered_markdown_url": self.storage.output_url_for(artifact.rendered_markdown_path),
            "asset_base_url": self.storage.output_url_for(
                self.storage.get_job_dir(artifact.job_id)
            ),
            "sections": section_tree,
            "citations": citations,
            "retry_available": artifact.status == JobStatus.FAILED,
            "error": artifact.error,
            "task_id": artifact.task_id,
            "created_at": artifact.created_at,
            "updated_at": artifact.updated_at,
        }

    async def run_job(self, job_id: str, task_id: str, emit_log) -> StructureNoteArtifact:
        artifact = self.get_job(job_id)
        artifact = self.update_status(artifact, JobStatus.QUEUED, error=None, task_id=task_id)
        job_dirs = self.storage.ensure_job_dirs(job_id)
        language = artifact.note_language.value
        preset = get_difficulty_preset(artifact.difficulty_level)
        style_level = artifact.style_level

        try:
            emit_log(task_id, "Preparing Structure Note job.")

            normalized_pdf_path = job_dirs["normalized"] / "normalized.pdf"
            artifact = self.update_status(
                artifact, JobStatus.NORMALIZING, retry_state=JobStatus.NORMALIZING.value
            )
            if artifact.normalized_pdf_path and Path(artifact.normalized_pdf_path).exists():
                normalized_pdf_path = Path(artifact.normalized_pdf_path)
                emit_log(task_id, "Reusing normalized PDF.")
            else:
                emit_log(task_id, "Normalizing source file to PDF.")
                normalized_pdf_path = normalize_to_pdf(
                    Path(artifact.source_path), job_dirs["normalized"]
                )
                artifact.normalized_pdf_path = str(normalized_pdf_path)
                self.storage.write_artifact(artifact)

            page_index_path = job_dirs["index"] / "page_index.json"
            artifact = self.update_status(
                artifact, JobStatus.INDEXING, retry_state=JobStatus.INDEXING.value
            )
            if artifact.page_index_path and Path(artifact.page_index_path).exists():
                emit_log(task_id, "Reusing existing page index.")
                page_index = [
                    PageIndexPage.model_validate(item)
                    for item in self.storage.read_json(Path(artifact.page_index_path))
                ]
            else:
                emit_log(task_id, "Building page-level index.")
                page_index = build_page_index(normalized_pdf_path)
                artifact.page_index_path = str(
                    self.storage.write_json(
                        page_index_path,
                        [page.model_dump(mode="json") for page in page_index],
                    )
                )
                self.storage.write_artifact(artifact)

            section_tree_path = job_dirs["index"] / "section_tree.json"
            artifact = self.update_status(
                artifact, JobStatus.PLANNING, retry_state=JobStatus.PLANNING.value
            )
            if artifact.section_tree_path and Path(artifact.section_tree_path).exists():
                emit_log(task_id, "Reusing section tree.")
                section_tree = [
                    SectionTreeNode.model_validate(item)
                    for item in self.storage.read_json(Path(artifact.section_tree_path))
                ]
            else:
                emit_log(task_id, "Deriving section tree.")
                section_tree = await build_section_tree(
                    page_index, preset.page_window, language=language
                )
                artifact.section_tree_path = str(
                    self.storage.write_json(
                        section_tree_path,
                        [node.model_dump(mode="json") for node in section_tree],
                    )
                )
                self.storage.write_artifact(artifact)

            document_plan_path = job_dirs["index"] / "document_plan.json"
            if artifact.document_plan_path and Path(artifact.document_plan_path).exists():
                emit_log(task_id, "Reusing document-level plan.")
                document_plan = DocumentPlan.model_validate(
                    self.storage.read_json(Path(artifact.document_plan_path))
                )
            else:
                emit_log(task_id, "Building document-level section plan.")
                document_plan = build_document_plan(
                    page_index,
                    section_tree,
                    document_title=artifact.file_name,
                    language=language,
                )
                artifact.document_plan_path = str(
                    self.storage.write_json(
                        document_plan_path,
                        document_plan.model_dump(mode="json"),
                    )
                )
                self.storage.write_artifact(artifact)

            chunks_path = job_dirs["chunks"] / "generation_chunks.json"
            artifact = self.update_status(
                artifact, JobStatus.GENERATING, retry_state=JobStatus.GENERATING.value
            )
            if artifact.generation_chunks_path and Path(artifact.generation_chunks_path).exists():
                emit_log(task_id, "Reusing generated chunks.")
                chunks = [
                    GenerationChunk.model_validate(item)
                    for item in self.storage.read_json(Path(artifact.generation_chunks_path))
                ]
            else:
                emit_log(task_id, "Generating section-level Markdown notes.")
                chunks = build_generation_chunks(
                    page_index,
                    section_tree,
                    preset,
                    document_plan=document_plan,
                )
                for chunk in chunks:
                    chunk.markdown = await generate_chunk_markdown(
                        chunk,
                        page_index,
                        preset,
                        language=language,
                        style_level=style_level,
                        document_plan=document_plan,
                    )
                chunks = inject_image_placeholders(chunks, page_index, preset.placeholder_purpose)
                artifact.generation_chunks_path = str(
                    self.storage.write_json(
                        chunks_path,
                        [chunk.model_dump(mode="json") for chunk in chunks],
                    )
                )
                self.storage.write_artifact(artifact)

            image_state_path = job_dirs["chunks"] / "image_fill_state.json"
            artifact = self.update_status(
                artifact,
                JobStatus.PROCESSING_IMAGES,
                retry_state=JobStatus.PROCESSING_IMAGES.value,
            )
            if artifact.rendered_markdown_path and Path(artifact.rendered_markdown_path).exists():
                emit_log(task_id, "Reusing rendered markdown after image processing.")
                rendered_path = Path(artifact.rendered_markdown_path)
                markdown_text = normalize_structure_note_markdown(
                    rendered_path.read_text(encoding="utf-8")
                )
                rendered_path.write_text(markdown_text, encoding="utf-8")
                image_citations = self._load_image_citations(artifact.image_fill_state_path)
            else:
                emit_log(task_id, "Resolving figure placeholders.")
                chunks, placeholders, image_citations = process_images(
                    chunks,
                    page_index,
                    normalized_pdf_path,
                    job_dirs["images"],
                    artifact.file_name,
                    language=language,
                )
                self.storage.write_json(
                    chunks_path,
                    [chunk.model_dump(mode="json") for chunk in chunks],
                )
                artifact.image_fill_state_path = str(
                    self.storage.write_json(
                        image_state_path,
                        {
                            "placeholders": [item.model_dump(mode="json") for item in placeholders],
                            "image_citations": [
                                item.model_dump(mode="json") for item in image_citations
                            ],
                        },
                    )
                )
                transition_map = await self._build_transition_map(
                    chunks,
                    language=language,
                    style_level=style_level,
                    document_plan=document_plan,
                )
                markdown_text = normalize_structure_note_markdown(
                    self._compose_markdown(
                        artifact,
                        chunks,
                        language,
                        transition_map=transition_map,
                    )
                )
                artifact.rendered_markdown_path = str(
                    self.storage.write_text(job_dirs["final"] / "rendered.md", markdown_text)
                )
                self.storage.write_artifact(artifact)

            artifact = self.update_status(
                artifact, JobStatus.RENDERING, retry_state=JobStatus.RENDERING.value
            )
            citations = self._build_text_citations(chunks, artifact.file_name)
            citations.extend(image_citations)
            emit_log(task_id, "Rendering final PDF.")
            final_pdf_path, citation_path = render_pdf(
                markdown_text,
                title=artifact.file_name,
                citation_entries=citations,
                job_dir=job_dirs["job"],
                final_dir=job_dirs["final"],
            )
            artifact.final_pdf_path = str(final_pdf_path)
            artifact.citation_manifest_path = str(citation_path)
            artifact = self.update_status(
                artifact, JobStatus.READY, retry_state=JobStatus.READY.value
            )
            self.storage.apply_retention_policy(artifact)
            emit_log(task_id, "Structure Note is ready.")
            return artifact
        except Exception as exc:
            self.logger.error(f"Structure Note job failed: {exc}", exc_info=True)
            emit_log(task_id, f"Structure Note failed: {exc}")
            return self.update_status(
                artifact,
                JobStatus.FAILED,
                error=str(exc),
                retry_state=artifact.status.value,
            )

    def _compose_markdown(
        self,
        artifact: StructureNoteArtifact,
        chunks: list[GenerationChunk],
        language: str,
        *,
        transition_map: dict[str, str] | None = None,
    ) -> str:
        heading = self._compose_markdown_heading(artifact, chunks, language)
        sections: list[str] = []
        previous_major: GenerationChunk | None = None
        for chunk in chunks:
            if not chunk.markdown.strip():
                continue
            if chunk.heading_level <= 2:
                if previous_major is not None:
                    transition = (transition_map or {}).get(chunk.section_id or chunk.chunk_id, "")
                    if transition.strip():
                        sections.append(transition.strip())
                previous_major = chunk
            sections.append(
                f'<a id="{chunk.section_id or chunk.chunk_id}"></a>\n\n{chunk.markdown.strip()}'
            )
        return f"{heading}\n\n" + "\n\n".join(sections)

    async def _build_transition_map(
        self,
        chunks: list[GenerationChunk],
        *,
        language: str,
        style_level: ExplanationStyleLevel,
        document_plan: DocumentPlan | None,
    ) -> dict[str, str]:
        transition_map: dict[str, str] = {}
        previous_major: GenerationChunk | None = None
        for chunk in chunks:
            if not chunk.markdown.strip() or chunk.heading_level > 2:
                continue
            if previous_major is not None:
                key = chunk.section_id or chunk.chunk_id
                transition_map[key] = await generate_transition_markdown(
                    previous_major,
                    chunk,
                    language=language,
                    style_level=style_level,
                    document_plan=document_plan,
                )
            previous_major = chunk
        return transition_map

    def _compose_markdown_heading(
        self,
        artifact: StructureNoteArtifact,
        chunks: list[GenerationChunk],
        language: str,
    ) -> str:
        if language == "zh":
            lines = [
                f"# {artifact.file_name}",
                "",
                f"> 结构化讲义。难度：`{artifact.difficulty_level.value}`。",
                "",
                "## 讲义目录",
            ]
            for chunk in chunks:
                page_range = (
                    f"第 {chunk.page_start}-{chunk.page_end} 页"
                    if chunk.page_start != chunk.page_end
                    else f"第 {chunk.page_start} 页"
                )
                indent = "  " * max(0, chunk.heading_level - 2)
                lines.append(f"{indent}- {chunk.section_title}（{page_range}）")
            lines.append("")
            return "\n".join(lines)

        lines = [
            f"# {artifact.file_name}",
            "",
            f"> Structured lecture note. Difficulty: `{artifact.difficulty_level.value}`.",
            "",
            "## Lecture Outline",
        ]
        for chunk in chunks:
            page_range = (
                f"pages {chunk.page_start}-{chunk.page_end}"
                if chunk.page_start != chunk.page_end
                else f"page {chunk.page_start}"
            )
            indent = "  " * max(0, chunk.heading_level - 2)
            lines.append(f"{indent}- {chunk.section_title} ({page_range})")
        lines.append("")
        return "\n".join(lines)

    def _build_text_citations(
        self, chunks: list[GenerationChunk], source_file: str
    ) -> list[CitationEntry]:
        citations: list[CitationEntry] = []
        for chunk in chunks:
            evidence_excerpt = " ".join(
                item.excerpt for item in chunk.evidence if item.excerpt
            ).strip()
            excerpt = evidence_excerpt or chunk.markdown.replace("\n", " ").strip()
            if len(excerpt) > 240:
                excerpt = f"{excerpt[:240]}..."
            citations.append(
                CitationEntry(
                    citation_id=f"cite-{chunk.chunk_id}",
                    section_path=chunk.section_path,
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    source_file=source_file,
                    source_kind="text",
                    excerpt=excerpt or None,
                )
            )
        return citations

    def _load_section_tree_payload(self, section_tree_path: str | None) -> list[dict[str, Any]]:
        if not section_tree_path:
            return []
        path = Path(section_tree_path)
        if not path.exists():
            return []
        payload = self.storage.read_json(path)
        if not isinstance(payload, list):
            return []
        return [item for item in payload if isinstance(item, dict)]

    def _load_image_citations(self, image_fill_state_path: str | None) -> list[CitationEntry]:
        if not image_fill_state_path:
            return []
        state_path = Path(image_fill_state_path)
        if not state_path.exists():
            return []
        payload = self.storage.read_json(state_path)
        return [
            CitationEntry.model_validate(item)
            for item in payload.get("image_citations", [])
            if isinstance(item, dict)
        ]
