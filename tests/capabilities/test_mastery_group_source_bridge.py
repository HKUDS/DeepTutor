"""Local source bridge stays strict for every grouped assessment leaf."""

import pytest

from deeptutor.learning import lesson_evidence
from deeptutor.learning.models import (
    InteractionStatus,
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
    LearningProgress,
    PendingQuestion,
)
from deeptutor.learning.service import LearningService, MasteryInteractionError
from deeptutor.learning.storage import LearningStore


@pytest.fixture
def service(tmp_path):
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
                        for key in ["one", "two"]
                    ],
                )
            ],
        )
    )
    return svc


def group():
    return PendingQuestion(
        question_id="parent",
        knowledge_point_id="one",
        question_type="group",
        questions=[
            PendingQuestion(
                question_id=key,
                knowledge_point_id=key,
                module_id="m",
                prompt=f"Question {key}?",
                expected_answer="answer",
            )
            for key in ["one", "two"]
        ],
    )


def test_registration_snapshots_each_leaf_without_parent_snapshot(service, monkeypatch):
    calls = []

    def snapshot(_store, _progress, kp_id):
        calls.append(kp_id)
        return {"objective_id": kp_id, "verified": True}

    monkeypatch.setattr(lesson_evidence, "question_snapshot", snapshot)
    _, interaction, _ = service.register_question("p", group())
    assert calls == ["one", "two"]
    assert [q.source_evidence["objective_id"] for q in interaction.question.questions] == [
        "one",
        "two",
    ]
    assert interaction.question.source_evidence == {}


def test_second_source_failure_does_not_retire_previous_pending(service, monkeypatch):
    def snapshot(_store, _progress, kp_id):
        if kp_id == "two":
            raise lesson_evidence.LessonUnavailable("Synthetic unavailable source")
        return {"objective_id": kp_id}

    monkeypatch.setattr(lesson_evidence, "question_snapshot", snapshot)
    old = PendingQuestion(
        question_id="old", knowledge_point_id="one", prompt="Old?", expected_answer="answer"
    )
    service.register_question("p", old)
    before = service.store.load("p").model_dump()
    with pytest.raises(MasteryInteractionError):
        service.register_question("p", group(), pending_action="replace", replace_question_id="old")
    assert service.store.load("p").model_dump() == before
    assert service.store.get_active_interaction("p").interaction_id == "old"


def test_all_leaf_sources_validate_before_any_attempt(service, monkeypatch):
    monkeypatch.setattr(lesson_evidence, "question_snapshot", lambda *_args: {"verified": True})
    service.register_question("p", group())
    calls = []

    def validate(_store, _progress, kp_id, snapshot):
        calls.append(kp_id)
        assert snapshot["verified"]
        if kp_id == "two":
            raise lesson_evidence.LessonUnavailable("Synthetic stale second source")

    monkeypatch.setattr(lesson_evidence, "validate_evidence", validate)
    before = service.store.load("p").model_dump()
    with pytest.raises(MasteryInteractionError):
        service.grade_interaction(
            "p", answer="", question_id="parent", answers={"one": "answer", "two": "answer"}
        )
    assert calls == ["one", "two"]
    assert service.store.load("p").model_dump() == before
    assert service.store.get_interaction("p", "parent").status == InteractionStatus.REGISTERED


def test_verified_leaves_grade_independently_and_keep_private_provenance(service, monkeypatch):
    monkeypatch.setattr(
        lesson_evidence, "question_snapshot", lambda _s, _p, kp: {"objective_id": kp}
    )
    verified = []

    def validate(_store, _progress, kp_id, snapshot):
        assert snapshot["objective_id"] == kp_id
        verified.append(kp_id)

    monkeypatch.setattr(lesson_evidence, "validate_evidence", validate)
    service.register_question("p", group())
    progress, interaction, _ = service.grade_interaction(
        "p", answer="", question_id="parent", answers={"one": "answer", "two": "incorrect"}
    )
    assert verified == ["one", "two"]
    assert len(progress.quiz_attempts) == 2
    assert [result["is_correct"] for result in interaction.result["results"]] == [True, False]
    assert all("source_evidence" not in result for result in interaction.result["results"])
