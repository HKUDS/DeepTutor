"""Unified assessment adapter for the Question Notebook review layer.

Mastery Path, Book Focus-Check, and Immersive Reading persist graded attempts
through :func:`record_assessment`. Identity is the existing
``(session_id, turn_id, question_id)`` notebook unique key — there is no
second question bank. Objective linkage is written only for
``source="mastery_path"``.
"""

from __future__ import annotations

from hashlib import sha1
import logging
import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

logger = logging.getLogger(__name__)

AssessmentSource = Literal["deep_question", "mastery_path", "immersive_reading", "book"]
AssessmentType = Literal["quiz", "focus_check", "qualitative", "review"]
AssessmentResult = Literal["correct", "incorrect", "partial", "ungraded"]

ASSESSMENT_SOURCES: frozenset[str] = frozenset(
    {"deep_question", "mastery_path", "immersive_reading", "book"}
)
ASSESSMENT_TYPES: frozenset[str] = frozenset({"quiz", "focus_check", "qualitative", "review"})
ASSESSMENT_RESULTS: frozenset[str] = frozenset({"correct", "incorrect", "partial", "ungraded"})


class RecordAssessmentError(RuntimeError):
    """Raised when a review record cannot be persisted consistently."""


class AssessmentOutcome(BaseModel):
    model_config = ConfigDict(extra="ignore")

    entry_id: int | None = None
    upserted: bool = False
    diagnostics: list[str] = Field(default_factory=list)


def result_to_is_correct(result: str) -> bool:
    """Bool compatibility: only a fully correct result is true."""
    return str(result or "").strip() == "correct"


def is_correct_to_result(is_correct: bool | None) -> AssessmentResult:
    """Map the legacy bool onto a graded result; unknown stays ungraded."""
    if is_correct is True:
        return "correct"
    if is_correct is False:
        return "incorrect"
    return "ungraded"


def build_grade_result(
    *,
    result: str = "",
    is_correct: bool | None = None,
) -> AssessmentResult:
    """Canonical result string; an explicit result wins over the bool."""
    value = str(result or "").strip()
    if value in ASSESSMENT_RESULTS:
        return value  # type: ignore[return-value]
    return is_correct_to_result(is_correct)


class AssessmentRecord(BaseModel):
    """Normalized payload for one review upsert."""

    model_config = ConfigDict(extra="ignore")

    session_id: str
    turn_id: str = ""
    question_id: str
    source: AssessmentSource = "deep_question"
    assessment_type: AssessmentType = "quiz"
    result: str = ""
    is_correct: bool | None = None
    question: str = ""
    question_type: str = ""
    options: dict[str, str] = Field(default_factory=dict)
    user_answer: str = ""
    correct_answer: str = ""
    explanation: str = ""
    difficulty: str = ""
    material_id: str = ""
    material_title: str = ""
    section_id: str = ""
    section_title: str = ""
    mastery_path_id: str = ""
    knowledge_point_id: str = ""
    attempt_count: int = 1
    hints_used: int = 0
    confidence: float | None = None
    response_time: float | None = None
    quality: float | None = None
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    bookmarked: bool = False
    resolved: bool | None = None

    @field_validator("source", mode="before")
    @classmethod
    def _normalize_source(cls, value: object) -> str:
        raw = str(value or "").strip()
        return raw if raw in ASSESSMENT_SOURCES else "deep_question"

    @field_validator("assessment_type", mode="before")
    @classmethod
    def _normalize_type(cls, value: object) -> str:
        raw = str(value or "").strip()
        return raw if raw in ASSESSMENT_TYPES else "quiz"

    @field_validator("result", mode="before")
    @classmethod
    def _normalize_result_field(cls, value: object) -> str:
        raw = str(value or "").strip()
        return raw if raw in ASSESSMENT_RESULTS else ""

    @field_validator(
        "session_id",
        "turn_id",
        "question_id",
        "question",
        "question_type",
        "user_answer",
        "correct_answer",
        "explanation",
        "difficulty",
        "material_id",
        "material_title",
        "section_id",
        "section_title",
        "mastery_path_id",
        "knowledge_point_id",
        mode="before",
    )
    @classmethod
    def _strip_text(cls, value: object) -> str:
        return str(value or "").strip()

    @field_validator("options", mode="before")
    @classmethod
    def _options(cls, value: object) -> dict[str, str]:
        if not isinstance(value, dict):
            return {}
        return {str(key): str(body) for key, body in value.items()}

    @field_validator("attempt_count", mode="before")
    @classmethod
    def _attempt_count(cls, value: object) -> int:
        try:
            return max(1, int(value))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 1

    @field_validator("hints_used", mode="before")
    @classmethod
    def _hints_used(cls, value: object) -> int:
        try:
            return max(0, int(value))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0

    @model_validator(mode="after")
    def _require_identity(self) -> "AssessmentRecord":
        if not self.session_id or not self.question_id:
            raise ValueError("session_id and question_id are required")
        if not self.question:
            raise ValueError("question is required")
        return self

    @property
    def assessment_id(self) -> str:
        """Audit id derived from the notebook unique key — not a second identity."""
        raw = f"{self.session_id}|{self.turn_id}|{self.question_id}"
        return sha1(raw.encode("utf-8")).hexdigest()


def _resolve_result(record: AssessmentRecord, diagnostics: list[str]) -> AssessmentResult:
    result = build_grade_result(result=record.result, is_correct=record.is_correct)
    if record.result and record.is_correct is not None:
        if record.result in {"partial", "ungraded"}:
            if record.is_correct:
                logger.warning(
                    "is_correct=%s conflicts with result=%s; using result",
                    record.is_correct,
                    record.result,
                )
                diagnostics.append("is_correct_result_conflict")
        elif result_to_is_correct(record.result) != record.is_correct:
            logger.warning(
                "is_correct=%s conflicts with result=%s; using result",
                record.is_correct,
                record.result,
            )
            diagnostics.append("is_correct_result_conflict")
    return result


def _apply_linkage(record: AssessmentRecord, diagnostics: list[str]) -> tuple[str, str]:
    if record.source == "mastery_path":
        return record.mastery_path_id, record.knowledge_point_id
    if record.mastery_path_id or record.knowledge_point_id:
        logger.warning(
            "Dropping mastery linkage on non-mastery assessment source=%s "
            "mastery_path_id=%s knowledge_point_id=%s",
            record.source,
            record.mastery_path_id,
            record.knowledge_point_id,
        )
        diagnostics.append("dropped_non_mastery_linkage")
    return "", ""


def to_notebook_item(record: AssessmentRecord, diagnostics: list[str]) -> dict[str, Any]:
    """Build the dict ``upsert_notebook_entries`` expects."""
    result = _resolve_result(record, diagnostics)
    mastery_path_id, knowledge_point_id = _apply_linkage(record, diagnostics)
    is_correct = result_to_is_correct(result)
    item: dict[str, Any] = {
        "turn_id": record.turn_id,
        "question_id": record.question_id,
        "question": record.question,
        "question_type": record.question_type,
        "options": record.options,
        "correct_answer": record.correct_answer,
        "explanation": record.explanation,
        "difficulty": record.difficulty,
        "user_answer": record.user_answer,
        "is_correct": is_correct,
        "source": record.source,
        "material_id": record.material_id,
        "material_title": record.material_title,
        "section_id": record.section_id,
        "section_title": record.section_title,
        "assessment_type": record.assessment_type,
        "result": result,
        "mastery_path_id": mastery_path_id,
        "knowledge_point_id": knowledge_point_id,
        "attempt_count": record.attempt_count,
        "hints_used": record.hints_used,
        "confidence": record.confidence,
        "response_time": record.response_time,
        "quality": record.quality,
    }
    return item


async def record_assessment(record: AssessmentRecord) -> AssessmentOutcome:
    """Persist one assessment into the unified Question Notebook."""
    diagnostics: list[str] = []
    item = to_notebook_item(record, diagnostics)
    try:
        from deeptutor.services.session import get_sqlite_session_store

        store = get_sqlite_session_store()
        upserted = await store.upsert_notebook_entries(record.session_id, [item])
        entry = await store.find_notebook_entry(
            record.session_id, record.question_id, turn_id=record.turn_id
        )
    except Exception as exc:
        logger.exception(
            "Failed to record assessment %s for session %s",
            record.question_id,
            record.session_id,
        )
        raise RecordAssessmentError(
            f"Failed to record assessment {record.question_id!r} for session {record.session_id!r}"
        ) from exc
    entry_id = int(entry["id"]) if isinstance(entry, dict) and entry.get("id") is not None else None
    return AssessmentOutcome(
        entry_id=entry_id,
        upserted=bool(upserted),
        diagnostics=diagnostics,
    )


__all__ = [
    "ASSESSMENT_RESULTS",
    "ASSESSMENT_SOURCES",
    "ASSESSMENT_TYPES",
    "AssessmentOutcome",
    "AssessmentRecord",
    "AssessmentResult",
    "AssessmentSource",
    "AssessmentType",
    "RecordAssessmentError",
    "build_grade_result",
    "is_correct_to_result",
    "record_assessment",
    "result_to_is_correct",
    "to_notebook_item",
]
