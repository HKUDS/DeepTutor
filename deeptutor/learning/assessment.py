"""Unified assessment adapter for the Question Notebook review layer.

Mastery Path, Book Focus-Check, and Immersive Reading persist graded attempts
through :func:`record_assessment`. Identity is
``(origin_type, origin_ref, turn_id, question_id)``; conversation-backed
records use their session id as ``origin_ref`` for backward compatibility.
Every graded submission is also appended to the immutable shared attempt log,
and explicit objective linkage can update the same retention state from any
learning surface.
"""

from __future__ import annotations

import asyncio
from hashlib import sha1
import logging
import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from deeptutor.core.assessment import (
    ASSESSMENT_RESULTS,
    ASSESSMENT_SOURCES,
    ASSESSMENT_TYPES,
    QUESTION_ORIGIN_TYPES,
    AssessmentResult,
    AssessmentSource,
    AssessmentType,
    QuestionOriginType,
)

logger = logging.getLogger(__name__)


class RecordAssessmentError(RuntimeError):
    """Raised when a review record cannot be persisted consistently."""


class AssessmentOutcome(BaseModel):
    model_config = ConfigDict(extra="ignore")

    entry_id: int | None = None
    upserted: bool = False
    attempt_id: str = ""
    attempt_recorded: bool = False
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

    session_id: str = ""
    origin_type: QuestionOriginType = "conversation"
    origin_ref: str = ""
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
    attempt_id: str = ""

    @field_validator("source", mode="before")
    @classmethod
    def _normalize_source(cls, value: object) -> str:
        raw = str(value or "").strip()
        return raw if raw in ASSESSMENT_SOURCES else "deep_question"

    @field_validator("origin_type", mode="before")
    @classmethod
    def _normalize_origin_type(cls, value: object) -> str:
        raw = str(value or "").strip()
        return raw if raw in QUESTION_ORIGIN_TYPES else "conversation"

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
        "origin_ref",
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
        "attempt_id",
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
            return max(1, int(value))  # type: ignore[arg-type,call-overload]
        except (TypeError, ValueError):
            return 1

    @field_validator("hints_used", mode="before")
    @classmethod
    def _hints_used(cls, value: object) -> int:
        try:
            return max(0, int(value))  # type: ignore[arg-type,call-overload]
        except (TypeError, ValueError):
            return 0

    @model_validator(mode="after")
    def _require_identity(self) -> "AssessmentRecord":
        if self.origin_type == "conversation":
            if not self.session_id:
                raise ValueError("conversation assessments require session_id")
            if self.origin_ref and self.origin_ref != self.session_id:
                raise ValueError("conversation origin_ref must match session_id")
            self.origin_ref = self.session_id
        elif not self.origin_ref:
            raise ValueError(f"{self.origin_type} assessments require origin_ref")
        if not self.question_id:
            raise ValueError("question_id is required")
        if not self.question:
            raise ValueError("question is required")
        return self

    @property
    def assessment_id(self) -> str:
        """Audit id derived from the notebook unique key — not a second identity."""
        owner = (
            self.session_id
            if self.origin_type == "conversation"
            else f"{self.origin_type}:{self.origin_ref}"
        )
        raw = f"{owner}|{self.turn_id}|{self.question_id}"
        return sha1(raw.encode("utf-8"), usedforsecurity=False).hexdigest()

    @property
    def attempt_identity(self) -> str:
        """Idempotency key for one immutable submission.

        Callers with their own durable attempt identity should pass it. The
        fallback deliberately excludes wall-clock time so transport retries
        of the same answer converge; callers that allow the exact same answer
        more than once distinguish it with ``attempt_count`` or ``attempt_id``.
        """
        if self.attempt_id:
            return self.attempt_id
        owner = (
            self.session_id
            if self.origin_type == "conversation"
            else f"{self.origin_type}:{self.origin_ref}"
        )
        raw = "|".join(
            (
                owner,
                self.turn_id,
                self.question_id,
                self.source,
                self.assessment_type,
                str(self.attempt_count),
                self.user_answer,
                self.result,
                str(self.is_correct),
            )
        )
        return sha1(raw.encode("utf-8"), usedforsecurity=False).hexdigest()


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
    if record.mastery_path_id and record.knowledge_point_id:
        return record.mastery_path_id, record.knowledge_point_id
    if record.mastery_path_id or record.knowledge_point_id:
        logger.warning(
            "Dropping incomplete mastery linkage on assessment source=%s "
            "mastery_path_id=%s knowledge_point_id=%s",
            record.source,
            record.mastery_path_id,
            record.knowledge_point_id,
        )
        diagnostics.append("dropped_incomplete_mastery_linkage")
    return "", ""


def _is_trusted_linkage(path_id: str, knowledge_point_id: str) -> bool:
    """Only a saved path's exact objective can consume cross-surface evidence."""
    from deeptutor.learning.policy import find_knowledge_point

    try:
        progress = _get_learning_store().load(path_id)
    except (OSError, ValueError):
        return False
    if progress is None or progress.book_id != path_id:
        return False
    kp, _, _ = find_knowledge_point(progress, knowledge_point_id)
    return kp is not None


def _get_learning_store():
    from deeptutor.learning.storage import LearningStore

    return LearningStore()


def _apply_linked_retention(
    record: AssessmentRecord,
    *,
    result: AssessmentResult,
    attempt_id: str,
) -> bool:
    """Apply explicitly linked non-Mastery evidence to its objective once."""
    if (
        record.source == "mastery_path"
        or result in {"ungraded", "voided"}
        or not record.mastery_path_id
        or not record.knowledge_point_id
    ):
        return False

    from deeptutor.learning.models import LearningEvidence
    from deeptutor.learning.policy import find_knowledge_point
    from deeptutor.learning.scheduler import SpacedRepetitionScheduler

    scheduler = SpacedRepetitionScheduler()
    event_result = result if result in {"correct", "incorrect", "partial"} else "incorrect"
    evidence = LearningEvidence(
        evidence_id=attempt_id,
        question_id=record.question_id,
        knowledge_point_id=record.knowledge_point_id,
        timestamp=record.created_at,
        source=record.source,
        assessment_type="quiz" if record.assessment_type in {"quiz", "focus_check"} else "review",
        result=event_result,
        quality=record.quality,
        hints_used=record.hints_used,
        attempt_count=record.attempt_count,
        confidence=record.confidence,
        response_time=record.response_time,
        session_id=record.session_id,
        turn_id=record.turn_id,
    )

    def apply(tx) -> bool:
        progress = tx.progress
        if any(item.evidence_id == attempt_id for item in progress.learning_evidence):
            return False
        kp, _, _ = find_knowledge_point(progress, record.knowledge_point_id)
        if kp is None:
            raise ValueError(
                f"Unknown linked objective {record.knowledge_point_id!r} "
                f"on path {record.mastery_path_id!r}"
            )
        prior_evidence = [
            item for item in progress.learning_evidence if item.knowledge_point_id == kp.id
        ]
        progress.learning_evidence.append(evidence)
        if any(item.timestamp > evidence.timestamp for item in prior_evidence):
            # A saved event may be retried after a newer assessment. Rebuild
            # this objective in evidence order instead of scheduling the old
            # event as if it had just happened.
            ordered = sorted(
                [*prior_evidence, evidence],
                key=lambda item: (item.timestamp, item.evidence_id),
            )
            progress.repetition_states[kp.id] = scheduler.replay(
                kp.type, ordered, desired_retention=progress.desired_retention
            )
        else:
            state = progress.repetition_states.get(kp.id) or scheduler.get_initial_state(
                kp.type,
                now=evidence.timestamp,
                desired_retention=progress.desired_retention,
            )
            progress.repetition_states[kp.id] = state
            scheduler.schedule_review(state, kp.type, evidence, now=evidence.timestamp)
        progress.review_queue = scheduler.build_review_queue(progress)
        tx.emit(
            "evidence.recorded",
            {
                "evidence_id": attempt_id,
                "knowledge_point_id": kp.id,
                "source": record.source,
                "result": event_result,
            },
            session_id=record.session_id,
            turn_id=record.turn_id,
        )
        return True

    _, applied = _get_learning_store().mutate(record.mastery_path_id, apply)
    return applied


def to_notebook_item(record: AssessmentRecord, diagnostics: list[str]) -> dict[str, Any]:
    """Build the dict ``upsert_notebook_entries`` expects."""
    result = _resolve_result(record, diagnostics)
    mastery_path_id, knowledge_point_id = _apply_linkage(record, diagnostics)
    is_correct = result_to_is_correct(result)
    item: dict[str, Any] = {
        "origin_type": record.origin_type,
        "origin_ref": record.origin_ref,
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
    """Persist the latest projection, immutable attempt, and linked evidence."""
    diagnostics: list[str] = []
    item = to_notebook_item(record, diagnostics)
    attempt_id = record.attempt_identity
    try:
        from deeptutor.services.session import get_sqlite_session_store

        store = get_sqlite_session_store()
        existing_attempt = await store.get_assessment_attempt(attempt_id)
        if existing_attempt is not None:
            # An earlier submission may have had an untrusted mapping removed.
            # Its immutable event owns the linkage on every retry.
            item["mastery_path_id"] = str(existing_attempt.get("mastery_path_id") or "")
            item["knowledge_point_id"] = str(existing_attempt.get("knowledge_point_id") or "")
        if (
            existing_attempt is None
            and record.source != "mastery_path"
            and item["mastery_path_id"]
            and item["knowledge_point_id"]
            and not await asyncio.to_thread(
                _is_trusted_linkage, item["mastery_path_id"], item["knowledge_point_id"]
            )
        ):
            item["mastery_path_id"] = ""
            item["knowledge_point_id"] = ""
            diagnostics.append("dropped_invalid_mastery_linkage")
        entry_id, upserted, attempt_recorded = await store.record_assessment(
            record.session_id or None,
            item,
            {
                **record.model_dump(mode="json"),
                "attempt_id": attempt_id,
                "result": item["result"],
                "mastery_path_id": item["mastery_path_id"],
                "knowledge_point_id": item["knowledge_point_id"],
                "occurred_at": record.created_at,
            },
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
    if item["mastery_path_id"] and item["knowledge_point_id"]:
        try:
            persisted = await store.get_assessment_attempt(attempt_id)
            if persisted is None:
                raise ValueError(f"Missing durable assessment attempt {attempt_id!r}")
            linked_record = AssessmentRecord.model_validate(persisted)
            applied = await asyncio.to_thread(
                _apply_linked_retention,
                linked_record,
                result=build_grade_result(
                    result=str(persisted.get("result") or ""),
                    is_correct=persisted.get("is_correct"),
                ),
                attempt_id=attempt_id,
            )
            await store.mark_assessment_link_applied(attempt_id)
            if applied:
                diagnostics.append("linked_retention_updated")
        except Exception as exc:
            logger.warning(
                "Assessment %s retained its linkage but could not update path %s objective %s",
                attempt_id,
                item["mastery_path_id"],
                item["knowledge_point_id"],
                exc_info=True,
            )
            raise RecordAssessmentError(
                f"Failed to update linked retention for assessment {attempt_id!r}"
            ) from exc
    return AssessmentOutcome(
        entry_id=entry_id,
        upserted=bool(upserted),
        attempt_id=attempt_id,
        attempt_recorded=attempt_recorded,
        diagnostics=diagnostics,
    )


async def reconcile_linked_assessments() -> tuple[int, int]:
    """Replay durable cross-surface attempts left pending by an interrupted run."""
    from deeptutor.services.session import get_sqlite_session_store

    store = get_sqlite_session_store()
    attempts = await store.pending_linked_assessments()
    recovered = 0
    failed = 0
    for attempt in attempts:
        attempt_id = str(attempt.get("attempt_id") or "")
        try:
            record = AssessmentRecord.model_validate(attempt)
            await asyncio.to_thread(
                _apply_linked_retention,
                record,
                result=build_grade_result(
                    result=str(attempt.get("result") or ""),
                    is_correct=attempt.get("is_correct"),
                ),
                attempt_id=attempt_id,
            )
            await store.mark_assessment_link_applied(attempt_id)
            recovered += 1
        except Exception:
            failed += 1
            logger.exception("Could not reconcile linked assessment %s", attempt_id)
    return recovered, failed


__all__ = [
    "ASSESSMENT_RESULTS",
    "ASSESSMENT_SOURCES",
    "ASSESSMENT_TYPES",
    "AssessmentOutcome",
    "AssessmentRecord",
    "AssessmentResult",
    "AssessmentSource",
    "AssessmentType",
    "QuestionOriginType",
    "RecordAssessmentError",
    "build_grade_result",
    "is_correct_to_result",
    "record_assessment",
    "reconcile_linked_assessments",
    "result_to_is_correct",
    "to_notebook_item",
]
