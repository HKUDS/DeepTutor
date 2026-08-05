"""Legacy → v2 migration tests (LRN-01, spec §16.1).

Legacy JSON must load losslessly as a provisional legacy projection: the old
mastery indicators are preserved, a ``legacy_import`` attempt/assessment is
appended per qualifying knowledge point, the projection is provisional
mastery, and a delayed reteach is scheduled.
"""

import json
from pathlib import Path

import pytest

from deeptutor.learning.models import (
    AttemptCycleType,
    AttemptStatus,
    KnowledgeStateProjection,
    KnowledgeType,
    LearningProgress,
    MasteryState,
    ReviewState,
)
from deeptutor.learning.storage import (
    LearningStore,
    migrate_legacy_projection,
    needs_legacy_migration,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def store(tmp_path):
    return LearningStore(root=tmp_path)


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def legacy_progress(store) -> LearningProgress:
    """Store populated with the legacy v1 fixture, then loaded raw."""
    data = _load_fixture("legacy_progress_v1.json")
    (store._root / "legacy-book.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
    return store.load("legacy-book")


@pytest.fixture
def feynman_progress(store) -> LearningProgress:
    """Store populated with the feynman v2 fixture, then loaded raw."""
    data = _load_fixture("feynman_progress_v2.json")
    (store._root / "feynman-book.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
    return store.load("feynman-book")


# ── legacy fixture loading ────────────────────────────────────────────────


class TestLegacyFixture:
    def test_legacy_json_loads_without_loss(self, legacy_progress):
        progress = legacy_progress
        assert progress.book_id == "legacy-book"
        # Old mastery indicators survive losslessly.
        assert progress.mastery_levels == {"kp-mem1": 0.9, "kp-con1": 0.4}
        assert progress.qualitative_mastery == {"kp-con1": True}
        assert len(progress.quiz_attempts) == 1
        assert progress.quiz_attempts[0].question_id == "q1"
        assert progress.feynman_explanations["kp-con1"].startswith("Because")
        # Retired fields are ignored, not an error.
        assert not hasattr(progress, "learning_mode")

    def test_needs_legacy_migration_detects_gate(self, legacy_progress):
        assert needs_legacy_migration(legacy_progress) is True

    def test_needs_legacy_migration_false_when_imported(self, legacy_progress):
        migrate_legacy_projection(legacy_progress)
        assert needs_legacy_migration(legacy_progress) is False


# ── provisional legacy projection ─────────────────────────────────────────


class TestMigrationProjection:
    def test_migrates_to_provisional_mastery(self, legacy_progress):
        migrate_legacy_projection(legacy_progress)

        # kp-mem1 reached the quantitative gate (0.9 >= 0.7); kp-con1 reached
        # the qualitative gate (qualitative_mastery=true).
        assert set(legacy_progress.projections) == {"kp-mem1", "kp-con1"}
        for kp_id in ("kp-mem1", "kp-con1"):
            proj = legacy_progress.projections[kp_id]
            assert proj.mastery_state == MasteryState.PROVISIONAL_MASTERY
            assert proj.review_state == ReviewState.SCHEDULED
            assert proj.next_review_at is not None

        # A legacy_import attempt/assessment exists per qualifying KP.
        legacy_attempts = [
            a for a in legacy_progress.attempts if a.cycle_type == AttemptCycleType.LEGACY_IMPORT
        ]
        assert len(legacy_attempts) == 2
        for attempt in legacy_attempts:
            assert attempt.status == AttemptStatus.ASSESSED
            assert attempt.knowledge_point_id in {"kp-mem1", "kp-con1"}
            assessments = [
                ra for ra in legacy_progress.rubric_assessments if ra.attempt_id == attempt.id
            ]
            assert len(assessments) == 1
            assert assessments[0].server_gate_result.passed is True

        # Delayed reteach is scheduled in the review queue.
        reteach_tasks = [
            t for t in legacy_progress.review_queue if t.id.startswith("legacy-reteach-")
        ]
        assert len(reteach_tasks) == 2

        # History records the import.
        assert any(e.event_type == "legacy_import" for e in legacy_progress.history)

    def test_migration_preserves_existing_fields(self, legacy_progress):
        before_mastery = dict(legacy_progress.mastery_levels)
        before_quiz = list(legacy_progress.quiz_attempts)
        before_explanations = dict(legacy_progress.feynman_explanations)
        migrate_legacy_projection(legacy_progress)
        # Lossless: nothing pre-existing is dropped or altered.
        assert legacy_progress.mastery_levels == before_mastery
        assert legacy_progress.quiz_attempts == before_quiz
        assert legacy_progress.feynman_explanations == before_explanations
        assert legacy_progress.book_id == "legacy-book"

    def test_migration_is_idempotent(self, legacy_progress):
        first = migrate_legacy_projection(legacy_progress)
        second = migrate_legacy_projection(legacy_progress)
        assert len(first) == 2
        assert second == []
        assert len(legacy_progress.attempts) == 2
        assert len(legacy_progress.review_queue) == 2
        assert legacy_progress.aggregate_versions.attempt == 2
        assert legacy_progress.aggregate_versions.assessment == 2

    def test_migration_skips_already_projected(self, store):
        progress = _fresh_legacy_progress()
        progress.projections["kp-mem1"] = KnowledgeStateProjection(
            knowledge_point_id="kp-mem1", mastery_state=MasteryState.NEW
        )
        imported = migrate_legacy_projection(progress)
        assert imported == ["kp-con1"]

    def test_load_with_migration_persists(self, store):
        data = _load_fixture("legacy_progress_v1.json")
        (store._root / "legacy-book.json").write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )
        progress = store.load_with_migration("legacy-book")
        assert progress is not None
        assert "kp-mem1" in progress.projections
        # Re-loading does not duplicate imports.
        again = store.load_with_migration("legacy-book")
        assert len(again.attempts) == len(progress.attempts) == 2


# ── feynman v2 fixture ────────────────────────────────────────────────────


class TestFeynmanFixture:
    def test_new_fixture_roundtrips_losslessly(self, feynman_progress):
        data = _load_fixture("feynman_progress_v2.json")
        loaded = feynman_progress
        # All new aggregates present and lossless.
        assert {a.id for a in loaded.attempts} == {"a1", "a2", "a3"}
        assert {e.id for e in loaded.evidence_items} == {"ev1", "ev2", "ev3", "ev4"}
        assert loaded.rubric_assessments[0].server_gate_result.passed is True
        assert loaded.rubric_assessments[0].evidence_ids == ["ev1", "ev2", "ev3"]
        assert loaded.challenge_records[0].mode.value == "reassess_existing"
        assert loaded.projections["kp-1"].mastery_state == MasteryState.PROVISIONAL_MASTERY
        assert {s.id for s in loaded.source_snapshots} == {"s1", "s2"}
        assert loaded.map_versions[0].version == 1
        assert loaded.source_conflicts[0].status.value == "open"
        assert [e.seq for e in loaded.history] == [1, 2]
        assert loaded.aggregate_versions.attempt == 3
        # Re-dumping the loaded document yields the same JSON as the fixture.
        assert loaded.model_dump(mode="json") == data

    def test_v2_fixture_needs_no_migration(self, feynman_progress):
        assert needs_legacy_migration(feynman_progress) is False


# ── helpers ───────────────────────────────────────────────────────────────


def _fresh_legacy_progress() -> LearningProgress:
    """In-memory legacy progress without reading the fixture file."""
    from deeptutor.learning.models import KnowledgePoint, LearningModule

    kp1 = KnowledgePoint(id="kp-mem1", name="R", type=KnowledgeType.MEMORY, module_id="m1")
    kp2 = KnowledgePoint(id="kp-con1", name="C", type=KnowledgeType.CONCEPT, module_id="m1")
    mod = LearningModule(id="m1", name="Circuits", order=1, knowledge_points=[kp1, kp2])
    return LearningProgress(
        book_id="legacy-book",
        modules=[mod],
        mastery_levels={"kp-mem1": 0.9, "kp-con1": 0.4},
        qualitative_mastery={"kp-con1": True},
        knowledge_types={
            "kp-mem1": KnowledgeType.MEMORY,
            "kp-con1": KnowledgeType.CONCEPT,
        },
    )
