"""Tests for evidence gates and null semantics in six-dimension snapshots."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers.mastery_path import router
from deeptutor.learning.models import (
    ErrorRecord,
    ErrorType,
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
    LearningProgress,
    QuizAttempt,
    RepetitionState,
    ReviewTask,
)
from deeptutor.learning.six_dimensions import (
    RouteTaskEvidence,
    TransferEvidence,
    compute_six_dimension_snapshot,
)
from deeptutor.learning.storage import LearningStore


def _progress(*, kp_type: KnowledgeType = KnowledgeType.MEMORY) -> LearningProgress:
    kp = KnowledgePoint(id="kp1", name="Objective", type=kp_type, module_id="m1")
    return LearningProgress(
        book_id="book-1",
        modules=[LearningModule(id="m1", name="Module", order=0, knowledge_points=[kp])],
        knowledge_types={kp.id: kp.type},
        created_at=100,
        updated_at=200,
    )


def _by_key(progress: LearningProgress, **kwargs):
    snapshot = compute_six_dimension_snapshot(progress, generated_at=300, **kwargs)
    return snapshot, {dimension.key: dimension for dimension in snapshot.dimensions}


def test_empty_progress_has_six_insufficient_dimensions_and_no_overall():
    snapshot, dimensions = _by_key(_progress())

    assert [dimension.key for dimension in snapshot.dimensions] == [
        "knowledge",
        "procedure",
        "understanding",
        "transfer",
        "retention",
        "habit",
    ]
    assert snapshot.overall is None
    assert all(dimension.score is None for dimension in dimensions.values())
    assert all(dimension.data_state == "insufficient" for dimension in dimensions.values())


def test_one_choice_attempt_does_not_fabricate_transfer_or_habit_scores():
    progress = _progress()
    progress.mastery_levels["kp1"] = 1.0
    progress.quiz_attempts.append(
        QuizAttempt(
            question_id="choice-1",
            knowledge_point_id="kp1",
            is_correct=True,
            timestamp=150,
        )
    )

    _, dimensions = _by_key(progress)

    assert dimensions["knowledge"].score == 100
    assert dimensions["knowledge"].evidence_refs[0].id == "choice-1@150.000000"
    assert dimensions["procedure"].score == 100
    for key in ("transfer", "habit"):
        assert dimensions[key].score is None
        assert dimensions[key].data_state == "insufficient"


def test_wrong_answer_is_a_scored_zero_not_missing_data():
    progress = _progress()
    progress.mastery_levels["kp1"] = 0.0
    progress.quiz_attempts.append(
        QuizAttempt(
            question_id="choice-wrong",
            knowledge_point_id="kp1",
            is_correct=False,
            timestamp=150,
        )
    )

    _, dimensions = _by_key(progress)

    assert dimensions["knowledge"].score == 0
    assert dimensions["knowledge"].data_state == "scored"
    assert dimensions["knowledge"].evidence_count == 1


def test_application_error_is_traceable_procedure_evidence():
    progress = _progress(kp_type=KnowledgeType.CONCEPT)
    progress.quiz_attempts.append(
        QuizAttempt(
            question_id="apply-1",
            knowledge_point_id="kp1",
            is_correct=False,
            error_type=ErrorType.APPLICATION_ERROR,
            timestamp=150,
        )
    )
    progress.error_records.append(
        ErrorRecord(
            id="error-1",
            question_id="apply-1",
            knowledge_point_id="kp1",
            module_id="m1",
            error_type=ErrorType.APPLICATION_ERROR,
            created_at=150,
        )
    )

    _, dimensions = _by_key(progress)

    procedure = dimensions["procedure"]
    assert procedure.score == 0
    assert {(ref.kind, ref.id) for ref in procedure.evidence_refs} == {
        ("attempt", "apply-1@150.000000"),
        ("error", "error-1"),
    }


@pytest.mark.parametrize("passed, expected", [(True, 100), (False, 0)])
def test_understanding_uses_qualitative_feynman_evidence(passed, expected):
    progress = _progress(kp_type=KnowledgeType.CONCEPT)
    progress.qualitative_mastery["kp1"] = passed
    progress.feynman_explanations["kp1"] = "My explanation"

    _, dimensions = _by_key(progress)

    understanding = dimensions["understanding"]
    assert understanding.score == expected
    assert understanding.evidence_refs[0].id == "feynman:kp1"


def test_retention_uses_review_id_and_interval_progress():
    progress = _progress()
    state = RepetitionState(interval_index=3, next_review_at=500)
    progress.repetition_states["kp1"] = state
    progress.review_queue.append(
        ReviewTask(
            id="review-kp1",
            knowledge_point_id="kp1",
            knowledge_type=KnowledgeType.MEMORY,
            due_at=500,
            priority=2,
            state=state,
        )
    )

    _, dimensions = _by_key(progress)

    retention = dimensions["retention"]
    assert retention.score == 50
    assert retention.evidence_refs[0].model_dump() == {
        "kind": "review",
        "id": "review-kp1",
    }


def test_retention_can_read_legacy_repetition_state_without_queue_entry():
    progress = _progress()
    progress.repetition_states["kp1"] = RepetitionState(
        interval_index=1,
        next_review_at=500,
    )

    _, dimensions = _by_key(progress)

    retention = dimensions["retention"]
    assert retention.data_state == "scored"
    assert retention.evidence_refs[0].id == "review_kp1"


def test_external_evidence_scores_transfer_but_habit_has_three_item_gate():
    progress = _progress()
    transfer = [TransferEvidence(id="variant-1", score=0.8, timestamp=150)]
    two_route_tasks = [
        RouteTaskEvidence(id="route-1", score=1.0, timestamp=150),
        RouteTaskEvidence(id="route-2", score=0.0, timestamp=160),
    ]

    snapshot, dimensions = _by_key(
        progress,
        transfer_evidence=transfer,
        route_task_evidence=two_route_tasks,
    )

    assert dimensions["transfer"].score == 80
    assert dimensions["transfer"].evidence_refs[0].id == "variant-1"
    assert dimensions["habit"].score is None
    assert dimensions["habit"].evidence_count == 2
    assert snapshot.overall == 80

    three_route_tasks = [
        *two_route_tasks,
        RouteTaskEvidence(id="route-3", score=1.0, timestamp=170),
    ]
    _, dimensions = _by_key(progress, route_task_evidence=three_route_tasks)
    assert dimensions["habit"].score == pytest.approx(66.7)
    assert all(ref.kind == "route_task" for ref in dimensions["habit"].evidence_refs)


def test_time_window_excludes_old_attempts_and_external_evidence():
    progress = _progress()
    progress.mastery_levels["kp1"] = 1.0
    progress.quiz_attempts.append(
        QuizAttempt(
            question_id="old",
            knowledge_point_id="kp1",
            is_correct=True,
            timestamp=100,
        )
    )

    _, dimensions = _by_key(
        progress,
        since=120,
        until=180,
        transfer_evidence=[TransferEvidence(id="old-transfer", score=1.0, timestamp=100)],
    )

    assert dimensions["knowledge"].data_state == "insufficient"
    assert dimensions["transfer"].data_state == "insufficient"


def test_invalid_time_window_is_rejected():
    with pytest.raises(ValueError, match="since"):
        compute_six_dimension_snapshot(_progress(), since=20, until=10)


def test_snapshot_endpoint_exposes_contract_and_validates_window(tmp_path, monkeypatch):
    def _store(root=None):
        return LearningStore(root=tmp_path)

    monkeypatch.setattr("deeptutor.api.routers.mastery_path.LearningStore", _store)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/learning")
    client = TestClient(app)

    response = client.get("/api/v1/learning/progress/api-book/six-dimensions")
    assert response.status_code == 200
    payload = response.json()
    assert payload["book_id"] == "api-book"
    assert len(payload["dimensions"]) == 6
    assert payload["dimensions"][3]["key"] == "transfer"
    assert payload["dimensions"][3]["score"] is None
    assert payload["dimensions"][3]["data_state"] == "insufficient"

    invalid = client.get("/api/v1/learning/progress/api-book/six-dimensions?since=2&until=1")
    assert invalid.status_code == 400
