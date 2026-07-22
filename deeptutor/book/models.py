"""
Book Engine data models
=======================

Pydantic models that describe the persistent state of a Book:

- ``BookInputs`` snapshot of the four sources captured at creation.
- ``BookProposal`` LLM-generated proposal (Stage 1 output).
- ``Spine`` / ``Chapter`` chapter tree (Stage 2 output).
- ``Page`` / ``Block`` content units (Stage 3-4 output).
- ``Progress`` user progress + quiz stats (Stage 5).
- ``Book`` aggregate metadata persisted in ``manifest.json``.
"""

from __future__ import annotations

from enum import Enum
import time
from typing import Any
import uuid

from pydantic import BaseModel, ConfigDict, Field

# ─────────────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────────────


class BookStatus(str, Enum):
    DRAFT = "draft"  # ideation only, no spine yet
    SPINE_READY = "spine_ready"  # spine confirmed, compilation pending
    COMPILING = "compiling"
    READY = "ready"
    ERROR = "error"
    ARCHIVED = "archived"


class PageStatus(str, Enum):
    PENDING = "pending"
    PLANNING = "planning"
    GENERATING = "generating"
    READY = "ready"
    PARTIAL = "partial"  # some blocks ok, some failed
    ERROR = "error"


class BlockStatus(str, Enum):
    PENDING = "pending"
    GENERATING = "generating"
    READY = "ready"
    ERROR = "error"
    HIDDEN = "hidden"


class BlockType(str, Enum):
    # Phase 1
    TEXT = "text"
    CALLOUT = "callout"
    QUIZ = "quiz"
    USER_NOTE = "user_note"
    # Phase 2 — visual taxonomy: figure (svg/chartjs/mermaid) | interactive (html) | animation (video)
    FIGURE = "figure"
    INTERACTIVE = "interactive"
    ANIMATION = "animation"
    CODE = "code"
    TIMELINE = "timeline"
    FLASH_CARDS = "flash_cards"
    # Phase 3
    DEEP_DIVE = "deep_dive"
    # Phase 4 (BookEngine v2)
    SECTION = "section"  # long-form chapter section (multi-subsection)
    CONCEPT_GRAPH = "concept_graph"  # rendered overview / TOC graph
    # Guided Learning
    DIAGNOSTIC = "diagnostic"
    PRETEST = "pretest"
    RETRIEVAL_PRACTICE = "retrieval_practice"
    ERROR_DIAGNOSIS = "error_diagnosis"
    MODULE_TEST = "module_test"
    PROGRESS_DASHBOARD = "progress_dashboard"


class ContentType(str, Enum):
    """Hint that drives Page Planner template selection."""

    THEORY = "theory"  # text + figure + quiz + flash_cards
    DERIVATION = "derivation"  # text + animation + code + quiz
    HISTORY = "history"  # text + timeline + figure + quiz
    PRACTICE = "practice"  # quiz + code + text(explanation)
    CONCEPT = "concept"  # text + figure + flash_cards + quiz
    OVERVIEW = "overview"  # auto-generated TOC / concept-graph chapter


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _now() -> float:
    return time.time()


# ─────────────────────────────────────────────────────────────────────────────
# Inputs (Stage 0)
# ─────────────────────────────────────────────────────────────────────────────


class NotebookRef(BaseModel):
    """Reference to one notebook with selected record ids."""

    model_config = ConfigDict(extra="ignore")

    notebook_id: str
    record_ids: list[str] = Field(default_factory=list)


class ChatSelection(BaseModel):
    """Reference to one chat session with optional message-id filter.

    ``message_ids`` empty → use all (recent) messages of that session.
    """

    model_config = ConfigDict(extra="ignore")

    session_id: str
    message_ids: list[int] = Field(default_factory=list)


class ChatMessageSnapshot(BaseModel):
    """Lightweight snapshot of a chat message captured at book creation."""

    model_config = ConfigDict(extra="ignore")

    role: str = ""
    content: str = ""
    capability: str = ""
    created_at: float = 0.0


class BookInputs(BaseModel):
    """Four-source input snapshot captured when the book is created."""

    model_config = ConfigDict(extra="ignore")

    user_intent: str = ""
    chat_session_id: str = ""  # legacy single-session shorthand
    chat_selections: list[ChatSelection] = Field(default_factory=list)
    chat_history: list[ChatMessageSnapshot] = Field(default_factory=list)
    notebook_refs: list[NotebookRef] = Field(default_factory=list)
    knowledge_bases: list[str] = Field(default_factory=list)
    question_categories: list[int] = Field(default_factory=list)
    question_entries: list[int] = Field(default_factory=list)
    language: str = "en"
    captured_at: float = Field(default_factory=_now)


# ─────────────────────────────────────────────────────────────────────────────
# Stage 1: Proposal
# ─────────────────────────────────────────────────────────────────────────────


class BookProposal(BaseModel):
    """LLM-generated proposal returned at the end of Stage 1 (Ideation)."""

    model_config = ConfigDict(extra="allow")

    title: str = ""
    description: str = ""
    scope: str = ""
    target_level: str = ""
    estimated_chapters: int = 0
    rationale: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2: Spine
# ─────────────────────────────────────────────────────────────────────────────


class SourceAnchor(BaseModel):
    """Pointer back to the raw source(s) that anchor a chapter or block."""

    model_config = ConfigDict(extra="ignore")

    kind: str = ""  # 'kb' | 'notebook' | 'chat' | 'web' | 'manual'
    ref: str = ""  # KB doc id, notebook record id, message id…
    snippet: str = ""  # short preview (≤300 chars)


class Chapter(BaseModel):
    """A chapter in the spine. May be expanded into one or more pages."""

    model_config = ConfigDict(extra="allow")

    id: str = Field(default_factory=lambda: _new_id("ch"))
    title: str = ""
    learning_objectives: list[str] = Field(default_factory=list)
    content_type: ContentType = ContentType.THEORY
    source_anchors: list[SourceAnchor] = Field(default_factory=list)
    prerequisites: list[str] = Field(default_factory=list)  # other chapter ids
    page_ids: list[str] = Field(default_factory=list)
    summary: str = ""
    order: int = 0


# ─────────────────────────────────────────────────────────────────────────────
# Concept graph (Stage 2 — Spine companion)
# ─────────────────────────────────────────────────────────────────────────────


class ConceptNode(BaseModel):
    """One concept in the directed concept graph behind the spine."""

    model_config = ConfigDict(extra="ignore")

    id: str = ""  # short slug, e.g. "fourier_basis"
    label: str = ""  # human-readable concept name
    chapter_id: str = ""  # chapter that primarily covers this concept
    description: str = ""  # 1-sentence description (optional)
    weight: float = 1.0  # importance / centrality hint


class ConceptEdge(BaseModel):
    """Directed edge ``from`` → ``to`` in the concept graph."""

    model_config = ConfigDict(extra="ignore")

    src: str = ""  # ConceptNode.id
    dst: str = ""  # ConceptNode.id
    relation: str = "depends_on"  # 'depends_on' | 'extends' | 'related'
    rationale: str = ""


class ConceptGraph(BaseModel):
    """Directed graph of concepts that grounds the spine."""

    model_config = ConfigDict(extra="ignore")

    nodes: list[ConceptNode] = Field(default_factory=list)
    edges: list[ConceptEdge] = Field(default_factory=list)

    def node_by_id(self, node_id: str) -> ConceptNode | None:
        for n in self.nodes:
            if n.id == node_id:
                return n
        return None

    def has_edge(self, src: str, dst: str) -> bool:
        return any(e.src == src and e.dst == dst for e in self.edges)


class Spine(BaseModel):
    """Full chapter tree of a book."""

    model_config = ConfigDict(extra="allow")

    book_id: str
    chapters: list[Chapter] = Field(default_factory=list)
    version: int = 1
    updated_at: float = Field(default_factory=_now)
    # New (BookEngine v2): structural / source-grounding companions
    concept_graph: ConceptGraph = Field(default_factory=ConceptGraph)
    exploration_summary: str = ""

    def chapter_by_id(self, chapter_id: str) -> Chapter | None:
        for chapter in self.chapters:
            if chapter.id == chapter_id:
                return chapter
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Source exploration (Stage 2 prep — fed into SpineSynthesizer & compiler)
# ─────────────────────────────────────────────────────────────────────────────


class SourceChunk(BaseModel):
    """A retrieved chunk that grounds spine / block generation.

    Persisted alongside the book so subsequent stages can reuse retrievals
    without re-hitting the RAG pipeline.
    """

    model_config = ConfigDict(extra="ignore")

    chunk_id: str = ""
    kb_name: str = ""  # empty for non-KB sources (chat / notebook…)
    source: str = ""  # 'kb' | 'notebook' | 'chat' | 'questions' | 'web'
    ref: str = ""  # doc id / record id / message id …
    text: str = ""
    score: float = 0.0
    query: str = ""  # the query that surfaced this chunk
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExplorationReport(BaseModel):
    """Structured artefact produced by ``SourceExplorer``.

    Captures the multi-query parallel sweep across the user-provided sources
    (KBs, notebooks, chat selections, question entries…). Down-stream stages
    (SpineSynthesizer, SectionArchitect, BlockGenerators) read from this report
    instead of re-issuing retrievals — making generation deterministic and far
    cheaper after the first sweep.
    """

    model_config = ConfigDict(extra="ignore")

    book_id: str = ""
    queries: list[str] = Field(default_factory=list)
    chunks: list[SourceChunk] = Field(default_factory=list)
    summary: str = ""  # short LLM summary of recurring themes
    coverage: dict[str, int] = Field(default_factory=dict)  # source → chunk count
    candidate_concepts: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    created_at: float = Field(default_factory=_now)


# ─────────────────────────────────────────────────────────────────────────────
# Blocks
# ─────────────────────────────────────────────────────────────────────────────


class Block(BaseModel):
    """Atomic content unit on a page. Rendered natively by the frontend."""

    model_config = ConfigDict(extra="allow")

    id: str = Field(default_factory=lambda: _new_id("blk"))
    type: BlockType
    status: BlockStatus = BlockStatus.PENDING
    title: str = ""
    # Generator inputs (kept after generation for retry / regenerate)
    params: dict[str, Any] = Field(default_factory=dict)
    # Generated payload (shape depends on `type`)
    payload: dict[str, Any] = Field(default_factory=dict)
    # Source anchors that grounded the block
    source_anchors: list[SourceAnchor] = Field(default_factory=list)
    # Free-form metadata (timing, model, retries…)
    metadata: dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    created_at: float = Field(default_factory=_now)
    updated_at: float = Field(default_factory=_now)


# ─────────────────────────────────────────────────────────────────────────────
# Pages
# ─────────────────────────────────────────────────────────────────────────────


class PageLink(BaseModel):
    """Cross-page relationship (deepens, references, prereq…)."""

    model_config = ConfigDict(extra="ignore")

    target_page_id: str
    relation: str = "references"  # 'deepens' | 'prereq' | 'references'
    label: str = ""


class Page(BaseModel):
    """A single page = ordered sequence of Blocks + state."""

    model_config = ConfigDict(extra="allow")

    id: str = Field(default_factory=lambda: _new_id("pg"))
    book_id: str = ""
    chapter_id: str = ""
    title: str = ""
    learning_objectives: list[str] = Field(default_factory=list)
    content_type: ContentType = ContentType.THEORY
    status: PageStatus = PageStatus.PENDING
    order: int = 0
    blocks: list[Block] = Field(default_factory=list)
    links: list[PageLink] = Field(default_factory=list)
    parent_page_id: str = ""  # for deep_dive sub-pages
    error: str = ""
    created_at: float = Field(default_factory=_now)
    updated_at: float = Field(default_factory=_now)

    def block_by_id(self, block_id: str) -> Block | None:
        for block in self.blocks:
            if block.id == block_id:
                return block
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Stage 5: Progress
# ─────────────────────────────────────────────────────────────────────────────


class QuizAttempt(BaseModel):
    model_config = ConfigDict(extra="ignore")

    block_id: str
    page_id: str
    question_id: str = ""
    user_answer: str = ""
    is_correct: bool = False
    timestamp: float = Field(default_factory=_now)


class Progress(BaseModel):
    """Per-user progress through the book."""

    model_config = ConfigDict(extra="ignore")

    book_id: str
    current_page_id: str = ""
    visited_page_ids: list[str] = Field(default_factory=list)
    bookmarked_page_ids: list[str] = Field(default_factory=list)
    quiz_attempts: list[QuizAttempt] = Field(default_factory=list)
    weak_chapters: list[str] = Field(default_factory=list)
    score: int = 0
    updated_at: float = Field(default_factory=_now)


# ─────────────────────────────────────────────────────────────────────────────
# Aggregate manifest
# ─────────────────────────────────────────────────────────────────────────────


class Book(BaseModel):
    """Top-level book metadata persisted in ``manifest.json``."""

    model_config = ConfigDict(extra="allow")

    id: str = Field(default_factory=lambda: _new_id("bk"))
    title: str = ""
    description: str = ""
    status: BookStatus = BookStatus.DRAFT
    proposal: BookProposal | None = None
    knowledge_bases: list[str] = Field(default_factory=list)
    language: str = "en"
    page_count: int = 0
    chapter_count: int = 0
    created_at: float = Field(default_factory=_now)
    updated_at: float = Field(default_factory=_now)
    metadata: dict[str, Any] = Field(default_factory=dict)
    # KB fingerprints captured at compile-time. Used to detect KB drift.
    kb_fingerprints: dict[str, str] = Field(default_factory=dict)
    # Pages whose KB content has changed since they were last compiled.
    stale_page_ids: list[str] = Field(default_factory=list)


__all__ = [
    "BookStatus",
    "PageStatus",
    "BlockStatus",
    "BlockType",
    "ContentType",
    "NotebookRef",
    "ChatSelection",
    "ChatMessageSnapshot",
    "BookInputs",
    "BookProposal",
    "SourceAnchor",
    "Chapter",
    "ConceptNode",
    "ConceptEdge",
    "ConceptGraph",
    "Spine",
    "SourceChunk",
    "ExplorationReport",
    "Block",
    "Page",
    "PageLink",
    "QuizAttempt",
    "Progress",
    "Book",
]
