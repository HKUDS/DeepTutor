"""Public source exposure assists its assessment attempt, not future learning."""

import json

import pytest

from deeptutor.learning import lesson_evidence
from deeptutor.learning.models import (
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
    LearningProgress,
    PendingQuestion,
)
from deeptutor.learning.pending import public_pending_question
from deeptutor.learning.scheduler import SpacedRepetitionScheduler
from deeptutor.learning.service import LearningService, MasteryInteractionError
from deeptutor.learning.storage import LearningStore
from deeptutor.services.rag import source_pages


def source(page=0):
    return {
        "source_ref": {
            "kb_ref": "synthetic-kb",
            "document_key": "material.pdf",
            "source_digest": "a" * 64,
            "page_index": page,
        }
    }


def question(key="one", page=0):
    return PendingQuestion(
        question_id=key,
        knowledge_point_id=key,
        module_id="m",
        prompt=f"Question {key}?",
        question_type="choice",
        expected_answer="A",
        options=[{"label": "A", "body": "alpha"}, {"label": "B", "body": "beta"}],
        source_evidence={"sources": [{"ref": source(page)["source_ref"]}]},
    )


@pytest.fixture
def service(tmp_path, monkeypatch):
    svc = LearningService(LearningStore(tmp_path))
    svc.save(
        LearningProgress(
            book_id="p",
            modules=[
                LearningModule(
                    id="m",
                    name="Synthetic module",
                    order=0,
                    knowledge_points=[
                        KnowledgePoint(id=key, name=key, module_id="m", type=KnowledgeType.MEMORY)
                        for key in ("one", "two")
                    ],
                )
            ],
            knowledge_types={"one": KnowledgeType.MEMORY, "two": KnowledgeType.MEMORY},
        )
    )
    monkeypatch.setattr(
        lesson_evidence,
        "question_snapshot",
        lambda _s, _p, key: {"sources": [{"ref": source(0 if key == "one" else 1)["source_ref"]}]},
    )
    monkeypatch.setattr(lesson_evidence, "validate_evidence", lambda *_a, **_kw: None)
    monkeypatch.setattr(source_pages, "resolve_source", lambda _ref: tmp_path / "material.pdf")
    return svc


def test_public_source_before_question_remains_assisted_after_reload(service):
    service.present_sources("p", [source()], "teaching", session_id="s", turn_id="t")
    service = LearningService(LearningStore(service.store._root))
    _, pending, _ = service.register_question("p", question(), session_id="s", turn_id="t")
    progress, graded, _ = service.grade_interaction(
        "p", question_id="one", answer="A", scheduler=SpacedRepetitionScheduler()
    )
    assert progress.quiz_attempts[0].independent is False
    assert graded.result["independent"] is False
    assert progress.mastery_levels["one"] == 0
    assert progress.learning_evidence[0].hints_used >= 1
    assert progress.learning_evidence[0].quality <= 0.6
    assert pending.question.visual_context == {}
    assert "assistance_used" not in json.dumps(public_pending_question(pending.question).to_dict())
    assert "source_evidence" not in json.dumps(graded.result)


def test_unexposed_source_still_earns_independent_credit(service):
    service.present_sources("p", [source(4)], "teaching", session_id="s", turn_id="t")
    service.register_question("p", question(), session_id="s", turn_id="t")
    progress, graded, _ = service.grade_interaction("p", question_id="one", answer="A")
    assert progress.quiz_attempts[0].independent is True
    assert graded.result["independent"] is True
    assert progress.learning_evidence[0].quality == 1


def test_group_assistance_is_per_leaf_and_survives_correction_replay(service):
    service.present_sources("p", [source()], "teaching", session_id="s", turn_id="t")
    service.register_question(
        "p",
        PendingQuestion(
            question_id="group",
            knowledge_point_id="one",
            question_type="group",
            questions=[question(), question("two", 1)],
        ),
        session_id="s",
        turn_id="t",
    )
    progress, graded, _ = service.grade_interaction(
        "p", question_id="group", answer="", answers={"one": "B", "two": "A"}
    )
    assert [a.independent for a in progress.quiz_attempts] == [False, True]
    service.repair_question(
        "p", "one", action="correct", expected_answer="B", reason="Synthetic correction"
    )
    progress, replay, replayed = service.grade_interaction("p", question_id="group", answer="")
    assert replayed
    assert [a.independent for a in progress.quiz_attempts] == [False, True]
    assert [row["independent"] for row in replay.result["results"]] == [False, True]
    assert progress.learning_evidence[0].quality <= 0.6
    assert progress.mastery_levels["one"] == 0
    assert len(progress.quiz_attempts) == 2


@pytest.mark.parametrize("purpose", ["teaching", "reveal"])
def test_active_question_blocks_answer_source_display_without_mutation(service, purpose):
    service.register_question("p", question())
    before = service.store.load("p").model_dump()
    with pytest.raises(MasteryInteractionError):
        service.present_sources("p", [source()], purpose)
    assert service.store.load("p").model_dump() == before


def test_unrelated_teaching_image_allowed_while_question_pending(service):
    service.register_question("p", question())
    assert service.present_sources("p", [source(5)], "teaching")
    progress, _, _ = service.grade_interaction("p", question_id="one", answer="A")
    assert progress.quiz_attempts[0].independent


def test_partial_group_cannot_reveal_page_with_unanswered_sibling(service):
    service.register_question(
        "p",
        PendingQuestion(
            question_id="group",
            knowledge_point_id="one",
            question_type="group",
            questions=[question(), question("two", 1)],
        ),
    )
    service.grade_interaction("p", question_id="group", answer="", answers={"one": "A"})
    with pytest.raises(MasteryInteractionError):
        service.present_sources("p", [source()], "reveal")
    service.grade_interaction("p", question_id="group", answer="", answers={"two": "A"})
    assert service.present_sources("p", [source()], "reveal")
    assert all(a.independent for a in service.store.load("p").quiz_attempts)


def test_duplicate_publication_keeps_one_durable_receipt(service):
    for _ in range(2):
        service.present_sources("p", [source()], "teaching", session_id="s", turn_id="t")
    assert len(service.store.load("p").source_exposures) == 1


def test_source_access_failure_does_not_record_publication(service, monkeypatch):
    def revoked(_ref):
        raise source_pages.SourcePageError("Synthetic revoked source")

    monkeypatch.setattr(source_pages, "resolve_source", revoked)
    before = service.store.load("p").model_dump()
    with pytest.raises(ValueError):
        service.present_sources("p", [source()], "teaching")
    assert service.store.load("p").model_dump() == before


@pytest.mark.parametrize("session_id,turn_id", [("s", "later"), ("new-session", "t")])
def test_previous_teaching_does_not_contaminate_new_assessment(service, session_id, turn_id):
    service.present_sources("p", [source()], "teaching", session_id="s", turn_id="t")
    service.register_question("p", question(), session_id=session_id, turn_id=turn_id)
    progress, graded, _ = service.grade_interaction("p", question_id="one", answer="A")
    assert progress.quiz_attempts[0].independent is True
    assert graded.result["independent"] is True
    assert progress.learning_evidence[0].hints_used == 0
    assert progress.learning_evidence[0].quality == 1


def test_repeated_page_presentation_has_a_receipt_for_each_native_turn(service):
    service.present_sources("p", [source()], "teaching", session_id="s", turn_id="old")
    service.present_sources("p", [source()], "teaching", session_id="s", turn_id="now")
    assert len(service.store.load("p").source_exposures) == 2
    service.register_question("p", question(), session_id="s", turn_id="now")
    progress, _, _ = service.grade_interaction("p", question_id="one", answer="A")
    assert progress.quiz_attempts[0].independent is False


@pytest.mark.parametrize("receipt_session,independent", [("s", False), ("other", True)])
def test_later_public_receipt_applies_only_to_same_pending_attempt_session(
    service, receipt_session, independent
):
    _, interaction, _ = service.register_question(
        "p", question(), session_id="s", turn_id="question"
    )

    # Model an already delivered server receipt, not a caller assistance flag.
    # Normal presentation refuses answer-bearing pages while a card is open.
    def record_exposure(tx):
        tx.progress.source_exposures.append(
            {
                **source(),
                "purpose": "teaching",
                "session_id": receipt_session,
                "turn_id": "later",
                "created_at": interaction.question.created_at + 1,
            }
        )
        tx.touch()

    service.store.mutate("p", record_exposure)
    service = LearningService(LearningStore(service.store._root))
    progress, graded, _ = service.grade_interaction("p", question_id="one", answer="A")
    assert progress.quiz_attempts[0].independent is independent
    assert graded.result["independent"] is independent
