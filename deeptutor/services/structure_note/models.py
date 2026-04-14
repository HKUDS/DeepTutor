from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class DifficultyLevel(str, Enum):
    SIMPLE = "simple"
    MEDIUM = "medium"
    DETAILED = "detailed"


class NoteLanguage(str, Enum):
    ZH = "zh"
    EN = "en"


class ExplanationStyleLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class JobStatus(str, Enum):
    QUEUED = "queued"
    NORMALIZING = "normalizing"
    INDEXING = "indexing"
    PLANNING = "planning"
    GENERATING = "generating"
    PROCESSING_IMAGES = "processing_images"
    RENDERING = "rendering"
    READY = "ready"
    FAILED = "failed"


class TextBlock(BaseModel):
    text: str
    bbox: list[float] = Field(default_factory=list)
    font_size: float | None = None


class TitleCandidate(BaseModel):
    text: str
    page_number: int
    bbox: list[float] = Field(default_factory=list)
    font_size: float | None = None
    score: float = 0.0


class ImageCandidate(BaseModel):
    candidate_id: str
    page_number: int
    bbox: list[float] = Field(default_factory=list)
    width: float | None = None
    height: float | None = None
    area_ratio: float | None = None


class PageIndexPage(BaseModel):
    page_number: int
    width: float
    height: float
    text: str
    text_blocks: list[TextBlock] = Field(default_factory=list)
    title_candidates: list[TitleCandidate] = Field(default_factory=list)
    image_candidates: list[ImageCandidate] = Field(default_factory=list)


class SectionTreeNode(BaseModel):
    section_id: str
    title: str
    level: int
    page_start: int
    page_end: int
    summary: str = ""
    parent_id: str | None = None
    child_ids: list[str] = Field(default_factory=list)
    path: list[str] = Field(default_factory=list)


class SectionEvidence(BaseModel):
    page_number: int
    excerpt: str
    title_candidates: list[str] = Field(default_factory=list)
    image_candidate_ids: list[str] = Field(default_factory=list)


class SectionPlan(BaseModel):
    section_id: str
    title: str
    level: int
    section_path: list[str] = Field(default_factory=list)
    page_start: int
    page_end: int
    page_numbers: list[int] = Field(default_factory=list)
    summary: str = ""
    writing_goal: str = ""
    dependencies: list[str] = Field(default_factory=list)
    evidence: list[SectionEvidence] = Field(default_factory=list)


class DocumentPlan(BaseModel):
    document_title: str
    document_summary: str = ""
    outline: list[SectionPlan] = Field(default_factory=list)
    section_order: list[str] = Field(default_factory=list)
    page_to_sections: dict[str, list[str]] = Field(default_factory=dict)


class CitationEntry(BaseModel):
    citation_id: str
    section_path: list[str] = Field(default_factory=list)
    page_start: int
    page_end: int
    source_file: str
    source_kind: Literal["text", "image"]
    image_page: int | None = None
    image_region: list[float] | None = None
    excerpt: str | None = None


class ImagePlaceholder(BaseModel):
    placeholder_id: str
    chunk_id: str
    page_hint: int
    purpose: str
    status: Literal["pending", "filled", "fallback_page", "fallback_text", "failed"] = "pending"
    image_path: str | None = None
    resolved_page: int | None = None
    resolved_region: list[float] | None = None
    error: str | None = None


class StructureNoteProject(BaseModel):
    name: str
    created_at: str
    updated_at: str


class GenerationChunk(BaseModel):
    chunk_id: str
    section_id: str | None = None
    section_title: str
    section_path: list[str] = Field(default_factory=list)
    section_summary: str = ""
    heading_level: int = 2
    page_start: int
    page_end: int
    page_numbers: list[int] = Field(default_factory=list)
    evidence: list[SectionEvidence] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    markdown: str = ""
    placeholder_ids: list[str] = Field(default_factory=list)


class StructureNoteArtifact(BaseModel):
    job_id: str
    file_name: str
    source_format: str
    difficulty_level: DifficultyLevel
    note_language: NoteLanguage = NoteLanguage.EN
    style_level: ExplanationStyleLevel = ExplanationStyleLevel.MEDIUM
    project_name: str | None = None
    note_title: str | None = None
    source_kind: Literal["upload", "knowledge_base"] = "upload"
    source_ref: dict[str, str] = Field(default_factory=dict)
    status: JobStatus
    source_path: str
    normalized_pdf_path: str | None = None
    page_index_path: str | None = None
    section_tree_path: str | None = None
    document_plan_path: str | None = None
    generation_chunks_path: str | None = None
    rendered_markdown_path: str | None = None
    image_fill_state_path: str | None = None
    citation_manifest_path: str | None = None
    final_pdf_path: str | None = None
    task_id: str | None = None
    retry_state: str | None = None
    error: str | None = None
    created_at: str
    updated_at: str
