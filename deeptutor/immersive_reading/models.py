"""Persistent models for the Immersive Reading workspace."""

from __future__ import annotations

import time
from typing import Any, Literal

from pydantic import BaseModel, Field


class ReadingSection(BaseModel):
    id: str
    title: str
    index: int
    char_count: int = 0
    source_start: int = 0
    source_end: int = 0
    checkpoint_kind: Literal["chapter", "chunk", "none"] = "chapter"
    source_href: str = ""


class ReadingDocument(BaseModel):
    id: str
    title: str
    author: str = ""
    source_filename: str
    source_format: str
    total_chars: int = 0
    total_words: int = 0
    reading_mode: Literal["chapters", "chunks"] = "chapters"
    sections: list[ReadingSection] = Field(default_factory=list)
    has_cover: bool = False
    experience_mode: Literal["standard", "kids"] = "standard"
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)


class ChapterSearchCard(BaseModel):
    section_id: str
    section_title: str
    section_index: int
    summary: str
    characters: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    time_markers: list[str] = Field(default_factory=list)
    timeline: list[str] = Field(default_factory=list)
    causal_links: list[str] = Field(default_factory=list)
    turning_points: list[str] = Field(default_factory=list)
    themes_and_motifs: list[str] = Field(default_factory=list)
    searchable_phrases: list[str] = Field(default_factory=list)
    content_hash: str
    model: str
    binding: str
    prompt_version: str
    generated_at: float = Field(default_factory=time.time)


class FastSearchIndex(BaseModel):
    document_id: str
    status: Literal["not_started", "building", "ready", "partial", "failed", "stale"] = (
        "not_started"
    )
    total_sections: int = 0
    completed_sections: int = 0
    failed_sections: int = 0
    cards: dict[str, ChapterSearchCard] = Field(default_factory=dict)
    errors: dict[str, str] = Field(default_factory=dict)
    model: str = ""
    binding: str = ""
    prompt_version: str = ""
    updated_at: float = Field(default_factory=time.time)


class FocusAttempt(BaseModel):
    section_id: str
    passed: bool = False
    score: int = 0
    feedback: str = ""
    attempt_count: int = 0
    updated_at: float = Field(default_factory=time.time)


class ReadingProgress(BaseModel):
    document_id: str
    current_section_id: str = ""
    current_section_index: int = 0
    scroll_percent: float = 0.0
    passed_section_ids: list[str] = Field(default_factory=list)
    focus_attempts: dict[str, FocusAttempt] = Field(default_factory=dict)
    epub_cfi: str = ""
    section_href: str = ""
    immersive_run: int = 1
    updated_at: float = Field(default_factory=time.time)


class ReadingCitation(BaseModel):
    id: str
    document_id: str
    document_title: str
    section_id: str
    section_title: str
    quote: str
    note: str = ""
    created_at: float = Field(default_factory=time.time)


class SearchHit(BaseModel):
    section_id: str
    section_title: str
    section_index: int
    excerpt: str
    score: float = 1.0
    reason: str = ""
    start_offset: int = 0
    end_offset: int = 0


class FocusCheckResult(BaseModel):
    passed: bool
    score: int
    feedback: str
    strengths: list[str] = Field(default_factory=list)
    missing_points: list[str] = Field(default_factory=list)
    progress: ReadingProgress


class SelectionQueryResult(BaseModel):
    answer: str
    citations: list[dict[str, Any]] = Field(default_factory=list)
    search_provider: str = ""


class KidsQuizQuestion(BaseModel):
    """One multiple-choice question for the child reading quiz."""

    id: str = ""
    kind: Literal["comprehension", "sight_word", "sequence"] = "comprehension"
    question: str = ""
    choices: list[str] = Field(default_factory=list)
    answer_index: int = 0
    explanation: str = ""


class KidsQuizResult(BaseModel):
    """Cached quiz for a document + section pair."""

    document_id: str
    section_id: str
    questions: list[KidsQuizQuestion] = Field(default_factory=list)
    content_hash: str = ""
    model: str = ""
    prompt_version: str = ""
    generated_at: float = Field(default_factory=time.time)


class KidsProfile(BaseModel):
    """A child profile managed by the parent (adult user)."""

    id: str
    name: str = ""
    avatar: str = "default"
    birth_date: str = ""  # ISO date string, e.g. "2018-03-15"
    help_language: Literal["en", "zh"] = "en"
    narration_rate: float = 0.8
    daily_limit_minutes: int = 30
    pin_hash: str = ""
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)

    @property
    def age(self) -> int:
        """Current age in years, computed from birth_date."""
        if not self.birth_date:
            return 7
        try:
            from datetime import date

            born = date.fromisoformat(self.birth_date)
            today = date.today()
            return today.year - born.year - ((today.month, today.day) < (born.month, born.day))
        except (ValueError, TypeError):
            return 7

    @property
    def age_band(self) -> str:
        """Auto-derived age band from birth_date. Updates as the child grows."""
        a = self.age
        if a <= 5:
            return "3-5"
        elif a <= 8:
            return "6-8"
        else:
            return "9-12"


class KidsBookAssignment(BaseModel):
    """Links a book (document) to a child profile with access controls."""

    id: str
    profile_id: str
    document_id: str
    document_title: str = ""
    status: Literal["active", "hidden"] = "active"
    available_through_section_id: str = ""
    available_through_section_index: int = 999
    # Assignments written before this safety gate did not persist the field.
    # The loader treats a missing key as confirmed to preserve those libraries.
    content_confirmed: bool = False
    content_confirmed_at: float = 0.0
    sort_order: int = 0
    is_next_read: bool = False
    assigned_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)


class KidsLearningProgress(BaseModel):
    """Per-profile per-book learning progress, isolated from adult progress."""

    profile_id: str
    document_id: str
    current_section_id: str = ""
    current_section_index: int = 0
    scroll_percent: float = 0.0
    epub_cfi: str = ""
    section_href: str = ""
    completed_section_ids: list[str] = Field(default_factory=list)
    total_stars: int = 0
    quiz_attempts: int = 0
    quiz_best_score: int = 0
    quiz_best_stars: int = 0
    time_spent_seconds: float = 0.0
    last_read_at: float = 0.0
    updated_at: float = Field(default_factory=time.time)


class KidsDeviceSession(BaseModel):
    """A revocable session issued to one child device."""

    id: str
    profile_id: str
    token_hash: str
    created_at: float = Field(default_factory=time.time)
    expires_at: float
    last_seen_at: float = Field(default_factory=time.time)
    revoked_at: float | None = None


class KidsDailyUsage(BaseModel):
    """Server-trusted reading time for one local calendar day."""

    profile_id: str
    date: str
    seconds: float = 0.0
    bonus_seconds: float = 0.0
    updated_at: float = Field(default_factory=time.time)


class KidsQuizSubmission(BaseModel):
    """A submitted quiz answer for server-side grading."""

    profile_id: str
    document_id: str
    section_id: str
    answers: list[int] = Field(default_factory=list)


class KidsQuizGradeResult(BaseModel):
    """Grading result returned to the child after submission."""

    score: int
    total: int
    stars: int
    per_question: list[dict[str, Any]] = Field(default_factory=list)
    encouragements: list[str] = Field(default_factory=list)


__all__ = [
    "ChapterSearchCard",
    "FastSearchIndex",
    "FocusAttempt",
    "FocusCheckResult",
    "KidsBookAssignment",
    "KidsDailyUsage",
    "KidsDeviceSession",
    "KidsLearningProgress",
    "KidsProfile",
    "KidsQuizGradeResult",
    "KidsQuizQuestion",
    "KidsQuizResult",
    "KidsQuizSubmission",
    "ReadingCitation",
    "ReadingDocument",
    "ReadingProgress",
    "ReadingSection",
    "SearchHit",
    "SelectionQueryResult",
]
