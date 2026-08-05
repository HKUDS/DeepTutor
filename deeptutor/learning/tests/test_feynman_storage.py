"""Storage tests for append-only history and atomic source/map invalidation."""

import json

import pytest

from deeptutor.learning.models import (
    INVALIDATION_REASON_SOURCE_VERSION_CHANGED,
    AttemptCycleType,
    AttemptStatus,
    EvidenceItem,
    EvidenceKind,
    FeynmanAttempt,
    HistoryEvent,
    KnowledgeMapVersion,
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
    LearningProgress,
    RubricAssessment,
    SourceSnapshot,
)
from deeptutor.learning.storage import (
    LearningStore,
    VersionConflictError,
    append_history,
    apply_map_version,
    bump_aggregate_version,
    invalidate_attempts,
    is_evidence_read_only,
    next_history_seq,
    register_source_snapshot,
)


@pytest.fixture
def store(tmp_path):
    return LearningStore(root=tmp_path)


def _snapshot(sid: str, content_hash: str) -> SourceSnapshot:
    return SourceSnapshot(id=sid, content_hash=content_hash, title=f"src-{sid}")


def _map_version(vid: str, version: int, snapshot_ids: list[str]) -> KnowledgeMapVersion:
    return KnowledgeMapVersion(
        id=vid, path_id="circuits", version=version, source_snapshot_ids=snapshot_ids
    )


def _progress_with_attempt(book_id: str = "b1", attempt_id: str = "a1") -> LearningProgress:
    """Progress with one live attempt bound to map mv1 and snapshot s1."""
    lp = LearningProgress(book_id=book_id)
    lp.attempts.append(
        FeynmanAttempt(
            id=attempt_id,
            knowledge_point_id="kp1",
            cycle_type=AttemptCycleType.INITIAL,
            status=AttemptStatus.COLLECTING,
            knowledge_point_version=1,
            map_version_id="mv1",
            source_snapshot_ids=["s1"],
        )
    )
    lp.evidence_items.append(
        EvidenceItem(id="ev1", attempt_id=attempt_id, kind=EvidenceKind.EXPLANATION)
    )
    return lp


# ── save / load round-trip ────────────────────────────────────────────────


class TestFeynmanRoundtrip:
    def test_aggregates_roundtrip(self, store):
        lp = _progress_with_attempt()
        lp.map_versions.append(_map_version("mv1", 1, ["s1"]))
        lp.source_snapshots.append(_snapshot("s1", "hash-1"))
        lp.rubric_assessments.append(
            RubricAssessment(id="ra1", attempt_id="a1", assessment_sequence=1)
        )
        lp.history.append(HistoryEvent(seq=1, event_type="attempt_created"))
        store.save(lp)

        loaded = store.load("b1")
        assert loaded.attempts[0].id == "a1"
        assert loaded.attempts[0].map_version_id == "mv1"
        assert loaded.map_versions[0].version == 1
        assert loaded.source_snapshots[0].content_hash == "hash-1"
        assert loaded.rubric_assessments[0].assessment_sequence == 1
        assert loaded.history[0].seq == 1

    def test_saved_json_contains_new_aggregate_keys(self, store, tmp_path):
        lp = _progress_with_attempt()
        store.save(lp)
        raw = json.loads((tmp_path / "b1.json").read_text(encoding="utf-8"))
        for key in (
            "attempts",
            "evidence_items",
            "rubric_assessments",
            "challenge_records",
            "gaps",
            "projections",
            "source_snapshots",
            "map_versions",
            "source_conflicts",
            "history",
            "aggregate_versions",
        ):
            assert key in raw


# ── append-only history ───────────────────────────────────────────────────


class TestAppendOnlyHistory:
    def test_never_overwritten_across_saves(self, store):
        lp = LearningProgress(book_id="b1")
        append_history(lp, "attempt_created", aggregate="attempt", summary="create a1")
        append_history(lp, "map_version_confirmed", aggregate="map", summary="v1")
        store.save(lp)

        # Reload, keep the same in-memory object mutated by save(), append more.
        loaded = store.load("b1")
        loaded.mastery_levels["kp1"] = 0.9
        append_history(loaded, "attempt_invalidated", aggregate="attempt", summary="invalidate a1")
        append_history(loaded, "source_snapshot_registered", summary="s2")
        store.save(loaded)

        final = store.load("b1")
        assert [e.seq for e in final.history] == [1, 2, 3, 4]
        # The original events must be byte-for-byte unchanged.
        assert final.history[0].summary == "create a1"
        assert final.history[0].aggregate_version == 1
        assert final.history[1].summary == "v1"
        assert final.history[1].aggregate == "map"
        assert final.history[1].aggregate_version == 1
        assert final.history[2].summary == "invalidate a1"
        assert final.history[3].summary == "s2"

    def test_stale_snapshot_save_is_rejected_before_mutation(self, store):
        """A save from a stale snapshot must not overwrite append-only history.

        Regression for the LRN-01 coordinator finding: two independent
        snapshots loaded from the same version, one saved with e2, then the
        stale one saved with e3 — previously the stale save silently dropped
        e2. The store now rejects it with ``VersionConflictError`` before any
        file or in-memory persisted-version mutation.
        """
        lp = LearningProgress(book_id="b1")
        append_history(lp, "attempt_created", aggregate="attempt", summary="e1")
        store.save(lp)

        left = store.load("b1")
        right = store.load("b1")
        assert left.version == right.version == 1

        append_history(left, "attempt_created", aggregate="attempt", summary="e2")
        store.save(left)

        # right is stale now: its version predates left's save.
        append_history(right, "attempt_created", aggregate="attempt", summary="e3")
        right_updated_before = right.updated_at
        before = json.loads((store._root / "b1.json").read_text(encoding="utf-8"))
        with pytest.raises(VersionConflictError) as excinfo:
            store.save(right)
        err = excinfo.value
        assert err.book_id == "b1"
        assert err.expected_version == 1
        assert err.persisted_version == 2

        # Nothing persisted changed, and the rejected object was not mutated.
        after = json.loads((store._root / "b1.json").read_text(encoding="utf-8"))
        assert after == before
        assert [e["summary"] for e in after["history"]] == ["e1", "e2"]
        assert after["version"] == 2
        assert right.version == 1
        assert right.updated_at == right_updated_before

    def test_history_grows_monotonically_even_without_reload(self, store):
        lp = LearningProgress(book_id="b1")
        append_history(lp, "e1")
        store.save(lp)
        append_history(lp, "e2")
        store.save(lp)
        append_history(lp, "e3")
        store.save(lp)
        final = store.load("b1")
        assert [e.seq for e in final.history] == [1, 2, 3]

    def test_next_history_seq(self):
        lp = LearningProgress(book_id="b1")
        assert next_history_seq(lp) == 1
        append_history(lp, "e1")
        assert next_history_seq(lp) == 2

    def test_append_history_bumps_aggregate_version(self):
        lp = LearningProgress(book_id="b1")
        append_history(lp, "attempt_created", aggregate="attempt")
        append_history(lp, "attempt_invalidated", aggregate="attempt")
        assert lp.aggregate_versions.attempt == 2
        assert lp.history[1].aggregate_version == 2

    def test_bump_unknown_aggregate_raises(self):
        lp = LearningProgress(book_id="b1")
        with pytest.raises(ValueError, match="Unknown aggregate"):
            bump_aggregate_version(lp, "nope")


# ── atomic map-version invalidation ───────────────────────────────────────


class TestMapVersionInvalidation:
    def test_new_map_version_invalidates_stale_bound_attempt(self, store):
        lp = _progress_with_attempt()
        store.save(lp)

        invalidated = apply_map_version(lp, _map_version("mv2", 2, ["s1"]))
        store.save(lp)

        assert invalidated == ["a1"]
        loaded = store.load("b1")
        assert loaded.attempts[0].status == AttemptStatus.INVALIDATED
        assert loaded.attempts[0].invalidated_reason == INVALIDATION_REASON_SOURCE_VERSION_CHANGED
        # Evidence of the invalidated attempt is read-only.
        assert is_evidence_read_only(loaded, "ev1") is True
        # History recorded both the confirmation and the invalidation.
        events = [e.event_type for e in loaded.history]
        assert "map_version_confirmed" in events
        assert "attempt_invalidated" in events
        # Map aggregate version advanced.
        assert loaded.aggregate_versions.map == 1
        assert loaded.aggregate_versions.attempt >= 1

    def test_attempt_bound_to_new_map_version_not_invalidated(self, store):
        lp = _progress_with_attempt()
        lp.attempts[0].map_version_id = "mv2"
        lp.attempts[0].knowledge_point_version = 2
        store.save(lp)

        invalidated = apply_map_version(lp, _map_version("mv2", 2, ["s1"]))
        store.save(lp)

        assert invalidated == []
        loaded = store.load("b1")
        assert loaded.attempts[0].status == AttemptStatus.COLLECTING

    def test_map_dropping_source_invalidates_attempt(self, store):
        # Attempt references snapshots ["s1", "s2"]; the new map only keeps s1.
        lp = _progress_with_attempt()
        lp.attempts[0].source_snapshot_ids = ["s1", "s2"]
        invalidated = apply_map_version(lp, _map_version("mv2", 2, ["s1"]))
        assert invalidated == ["a1"]

    def test_map_update_is_atomic_on_disk(self, store, tmp_path):
        """The new map version and the invalidation land in one file write."""
        lp = _progress_with_attempt()
        store.save(lp)
        apply_map_version(lp, _map_version("mv2", 2, ["s1"]))
        store.save(lp)

        raw = json.loads((tmp_path / "b1.json").read_text(encoding="utf-8"))
        map_versions = {v["id"]: v for v in raw["map_versions"]}
        attempts = {a["id"]: a for a in raw["attempts"]}
        # mv2 present and a1 invalidated in the same persisted document.
        assert "mv2" in map_versions
        assert attempts["a1"]["status"] == "invalidated"
        assert attempts["a1"]["invalidated_reason"] == "source_version_changed"


# ── atomic source-snapshot invalidation ───────────────────────────────────


class TestSourceSnapshotInvalidation:
    def test_source_content_change_invalidates_referencing_attempt(self, store):
        lp = _progress_with_attempt()
        lp.source_snapshots.append(_snapshot("s1", "hash-1"))
        store.save(lp)

        invalidated = register_source_snapshot(lp, _snapshot("s1", "hash-CHANGED"))
        store.save(lp)

        assert invalidated == ["a1"]
        loaded = store.load("b1")
        assert loaded.attempts[0].status == AttemptStatus.INVALIDATED
        assert loaded.attempts[0].invalidated_reason == INVALIDATION_REASON_SOURCE_VERSION_CHANGED
        assert is_evidence_read_only(loaded, "ev1") is True
        # Snapshot replaced with new content hash.
        assert loaded.source_snapshots[0].content_hash == "hash-CHANGED"
        assert len(loaded.source_snapshots) == 1

    def test_source_registration_without_change_does_not_invalidate(self, store):
        lp = _progress_with_attempt()
        invalidated = register_source_snapshot(lp, _snapshot("s1", "hash-1"))
        assert invalidated == []

    def test_source_change_ignores_closed_attempt(self):
        lp = _progress_with_attempt()
        lp.attempts[0].status = AttemptStatus.CLOSED
        invalidated = register_source_snapshot(lp, _snapshot("s1", "hash-CHANGED"))
        assert invalidated == []

    def test_invalidate_attempts_only_live(self):
        lp = _progress_with_attempt()
        lp.attempts.append(
            FeynmanAttempt(
                id="a2",
                knowledge_point_id="kp1",
                status=AttemptStatus.CLOSED,
                source_snapshot_ids=["s1"],
            )
        )
        invalidated = invalidate_attempts(
            lp, attempt_ids=["a1", "a2"], reason=INVALIDATION_REASON_SOURCE_VERSION_CHANGED
        )
        assert invalidated == ["a1"]
        assert lp.attempts[0].status == AttemptStatus.INVALIDATED
        assert lp.attempts[1].status == AttemptStatus.CLOSED


# ── read-only evidence ────────────────────────────────────────────────────


class TestReadOnlyEvidence:
    def test_active_attempt_evidence_is_writable(self):
        lp = _progress_with_attempt()
        assert is_evidence_read_only(lp, "ev1") is False

    def test_missing_evidence_is_not_read_only(self):
        lp = _progress_with_attempt()
        assert is_evidence_read_only(lp, "nope") is False

    def test_closed_attempt_evidence_is_read_only(self):
        lp = _progress_with_attempt()
        lp.attempts[0].status = AttemptStatus.CLOSED
        assert is_evidence_read_only(lp, "ev1") is True


# ── model helpers / aggregates in storage ─────────────────────────────────


class TestModulesStillLoad:
    def test_progress_with_modules_roundtrips(self, store):
        kp = KnowledgePoint(id="kp1", name="R", type=KnowledgeType.MEMORY, module_id="m1")
        mod = LearningModule(id="m1", name="Circuits", order=1, knowledge_points=[kp])
        lp = LearningProgress(book_id="b1", modules=[mod])
        store.save(lp)
        loaded = store.load("b1")
        assert loaded.modules[0].knowledge_points[0].name == "R"
