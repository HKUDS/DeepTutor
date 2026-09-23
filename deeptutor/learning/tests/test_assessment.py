"""Tests for the unified assessment adapter used to persist review records.

These cover the normalization, identity, linkage and failure semantics that
every surface (Mastery Path, Book, Immersive Reading) relies on when it
records a graded attempt into the Question Notebook.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from deeptutor.learning.assessment import (
    AssessmentOutcome,
    AssessmentRecord,
    RecordAssessmentError,
    is_correct_to_result,
    record_assessment,
    result_to_is_correct,
    to_notebook_item,
)
from deeptutor.learning.models import (
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
    LearningProgress,
)
from deeptutor.learning.storage import LearningStore
from deeptutor.services.session.sqlite_store import SQLiteSessionStore


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SQLiteSessionStore:
    instance = SQLiteSessionStore(db_path=tmp_path / "assessment.db")
    monkeypatch.setattr(
        "deeptutor.services.session.get_sqlite_session_store",
        lambda: instance,
    )
    return instance


def _mastery_record(**overrides) -> AssessmentRecord:
    values: dict = {
        "session_id": "session-1",
        "turn_id": "turn-1",
        "question_id": "q-1",
        "question": "What is 2+2?",
        "result": "incorrect",
        "is_correct": False,
        "source": "mastery_path",
        "assessment_type": "quiz",
        "mastery_path_id": "path-1",
        "knowledge_point_id": "kp-1",
        "quality": 0.0,
    }
    values.update(overrides)
    return AssessmentRecord(**values)


def test_assessment_id_is_derived_identity() -> None:
    record = _mastery_record()
    same = _mastery_record()
    assert record.assessment_id == same.assessment_id
    assert len(record.assessment_id) == 40  # sha1 hex


def test_record_round_trip_persists_all_phase2_fields(store: SQLiteSessionStore) -> None:
    session = asyncio.run(store.create_session(title="S", session_id="session-1"))
    assert "id" in session
    record = _mastery_record()
    outcome = asyncio.run(record_assessment(record))
    assert isinstance(outcome, AssessmentOutcome)
    assert outcome.upserted is True
    assert outcome.entry_id is not None
    assert outcome.attempt_recorded is True
    assert outcome.attempt_id
    assert outcome.diagnostics == []

    entry = asyncio.run(store.find_notebook_entry("session-1", "q-1", turn_id="turn-1"))
    assert entry is not None
    assert entry["source"] == "mastery_path"
    assert entry["assessment_type"] == "quiz"
    assert entry["result"] == "incorrect"
    assert entry["mastery_path_id"] == "path-1"
    assert entry["knowledge_point_id"] == "kp-1"
    assert entry["is_correct"] is False
    assert entry["quality"] == 0.0


def test_unknown_source_falls_back_to_deep_question() -> None:
    record = AssessmentRecord(
        session_id="s",
        question_id="q",
        question="...",
        source="made_up_surface",
    )
    assert record.source == "deep_question"


def test_result_wins_over_conflicting_bool() -> None:
    record = _mastery_record(result="partial", is_correct=True)
    diagnostics: list[str] = []
    item = to_notebook_item(record, diagnostics)
    assert item["result"] == "partial"
    assert item["is_correct"] is False  # partial is never a boolean "correct"
    assert "is_correct_result_conflict" in diagnostics


def test_ungraded_is_not_treated_as_wrong() -> None:
    record = _mastery_record(result="ungraded", is_correct=False)
    assert result_to_is_correct("ungraded") is False
    assert is_correct_to_result(False) == "incorrect"
    item = to_notebook_item(record, [])
    assert item["result"] == "ungraded"
    assert item["is_correct"] is False


def test_non_mastery_complete_linkage_is_preserved() -> None:
    record = AssessmentRecord(
        session_id="s",
        turn_id="t",
        question_id="q",
        question="...",
        source="book",
        mastery_path_id="path-1",
        knowledge_point_id="kp-1",
    )
    diagnostics: list[str] = []
    item = to_notebook_item(record, diagnostics)
    assert item["mastery_path_id"] == "path-1"
    assert item["knowledge_point_id"] == "kp-1"
    assert diagnostics == []


def test_incomplete_linkage_is_dropped() -> None:
    record = AssessmentRecord(
        session_id="s",
        question_id="q",
        question="...",
        source="book",
        mastery_path_id="path-1",
    )
    diagnostics: list[str] = []
    item = to_notebook_item(record, diagnostics)
    assert item["mastery_path_id"] == ""
    assert item["knowledge_point_id"] == ""
    assert "dropped_incomplete_mastery_linkage" in diagnostics


def test_mastery_defaults_attempt_and_hints() -> None:
    record = _mastery_record(attempt_count=0, hints_used=-3)
    item = to_notebook_item(record, [])
    assert item["attempt_count"] == 1
    assert item["hints_used"] == 0


def test_repeated_record_is_idempotent(store: SQLiteSessionStore) -> None:
    asyncio.run(store.create_session(title="S", session_id="session-1"))
    record = _mastery_record()
    asyncio.run(record_assessment(record))
    second = asyncio.run(record_assessment(record))
    assert second.entry_id == asyncio.run(record_assessment(record)).entry_id
    listing = asyncio.run(
        store.list_notebook_entries(source="mastery_path", session_id="session-1")
    )
    assert listing["total"] == 1
    attempts = asyncio.run(store.list_assessment_attempts("session-1", question_id="q-1"))
    assert len(attempts) == 1


def test_document_assessment_persists_without_a_chat_session(
    store: SQLiteSessionStore,
) -> None:
    record = AssessmentRecord(
        origin_type="document_analysis",
        origin_ref="book:calculus:focus-check-3",
        question_id="q-3",
        question="Differentiate x².",
        user_answer="2x",
        result="correct",
        source="book",
        material_id="calculus",
    )

    first = asyncio.run(record_assessment(record))
    second = asyncio.run(record_assessment(record))

    assert first.entry_id == second.entry_id
    assert first.attempt_recorded is True
    assert second.attempt_recorded is False
    entry = asyncio.run(
        store.find_notebook_entry_by_origin(
            "document_analysis",
            "book:calculus:focus-check-3",
            "q-3",
        )
    )
    assert entry is not None
    assert entry["session_id"] == ""
    assert entry["origin_type"] == "document_analysis"


def test_reanswer_keeps_immutable_attempts_and_updates_latest_projection(
    store: SQLiteSessionStore,
) -> None:
    asyncio.run(store.create_session(title="S", session_id="session-1"))
    asyncio.run(
        record_assessment(
            _mastery_record(attempt_id="attempt-1", user_answer="3", result="incorrect")
        )
    )
    asyncio.run(
        record_assessment(
            _mastery_record(
                attempt_id="attempt-2",
                attempt_count=2,
                user_answer="4",
                result="correct",
                is_correct=True,
            )
        )
    )

    latest = asyncio.run(store.find_notebook_entry("session-1", "q-1", turn_id="turn-1"))
    attempts = asyncio.run(store.list_assessment_attempts("session-1", question_id="q-1"))
    assert latest["user_answer"] == "4"
    assert latest["result"] == "correct"
    assert [attempt["attempt_id"] for attempt in attempts] == ["attempt-1", "attempt-2"]
    assert [attempt["result"] for attempt in attempts] == ["incorrect", "correct"]


def test_linked_book_assessment_updates_mastery_retention_once(
    store: SQLiteSessionStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(store.create_session(title="S", session_id="session-1"))
    learning_store = LearningStore(root=tmp_path / "learning")
    progress = LearningProgress(
        book_id="path-1",
        modules=[
            LearningModule(
                id="module-1",
                name="Module",
                order=0,
                knowledge_points=[
                    KnowledgePoint(
                        id="kp-1",
                        name="Concept",
                        type=KnowledgeType.CONCEPT,
                        module_id="module-1",
                    )
                ],
            )
        ],
        knowledge_types={"kp-1": KnowledgeType.CONCEPT},
    )
    learning_store.save(progress)
    monkeypatch.setattr("deeptutor.learning.assessment._get_learning_store", lambda: learning_store)
    record = AssessmentRecord(
        session_id="session-1",
        turn_id="book-turn",
        question_id="book-q",
        question="Explain the concept",
        user_answer="Answer",
        result="correct",
        is_correct=True,
        source="book",
        assessment_type="focus_check",
        mastery_path_id="path-1",
        knowledge_point_id="kp-1",
        attempt_id="book-attempt-1",
    )

    first = asyncio.run(record_assessment(record))
    second = asyncio.run(record_assessment(record))

    assert "linked_retention_updated" in first.diagnostics
    assert second.attempt_recorded is False
    linked = learning_store.load("path-1")
    assert len(linked.learning_evidence) == 1
    assert linked.learning_evidence[0].evidence_id == "book-attempt-1"
    assert linked.learning_evidence[0].source == "book"
    assert linked.repetition_states["kp-1"].review_count == 1


def test_missing_session_raises_record_error() -> None:
    record = _mastery_record(session_id="no-such-session")
    with pytest.raises(RecordAssessmentError):
        asyncio.run(record_assessment(record))


def test_missing_identity_is_rejected() -> None:
    with pytest.raises(ValueError):
        AssessmentRecord(session_id="", question_id="q", question="...")
    with pytest.raises(ValueError):
        AssessmentRecord(session_id="s", question_id="", question="...")


def test_missing_question_is_rejected() -> None:
    with pytest.raises(ValueError):
        AssessmentRecord(session_id="s", question_id="q", question="  ")
