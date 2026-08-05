"""Domain-schema tests for knowledge cards and generation attempts (KB-02).

Covers §7.9 / §7.9.1 backward-compatible schema: safe defaulted fields, lossless
round-trip with :class:`LearningProgress`, legacy JSON without these fields
still loading, and the append-only/occupying-status invariants.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deeptutor.learning.models import (
    KNOWLEDGE_CARD_OCCUPYING_STATUSES,
    STALEABLE_CARD_STATUSES,
    TERMINAL_GENERATION_ATTEMPT_STATUSES,
    DraftGenerationStatus,
    GenerationAttemptStatus,
    KnowledgeCardGenerationAttempt,
    KnowledgeCardRecord,
    KnowledgeCardStatus,
    LearningProgress,
)
from deeptutor.learning.storage import LearningStore
from deeptutor.learning.tests.knowledge_card_builders import evaluator_snapshot

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def store(tmp_path):
    return LearningStore(root=tmp_path)


def _card(**overrides) -> KnowledgeCardRecord:
    base = dict(
        id="card1",
        user_id="owner",
        path_id="b1",
        knowledge_point_id="kp1",
        stable_attempt_id="a1",
        stable_assessment_id="ra1",
        stable_assessment_sequence=1,
    )
    base.update(overrides)
    return KnowledgeCardRecord(**base)


def _attempt(**overrides) -> KnowledgeCardGenerationAttempt:
    base = dict(
        id="att1",
        card_id="card1",
        input_card_revision=1,
        stable_assessment_id="ra1",
        generation_attempt_no=1,
        frozen_model_snapshot=evaluator_snapshot(),
        input_hash="inp-hash-1",
    )
    base.update(overrides)
    return KnowledgeCardGenerationAttempt(**base)


# ── status enums ───────────────────────────────────────────────────────────


class TestStatusEnums:
    def test_card_status_values(self):
        assert KnowledgeCardStatus.DRAFT.value == "draft"
        assert KnowledgeCardStatus.PUBLISHING.value == "publishing"
        assert KnowledgeCardStatus.PUBLISHED.value == "published"
        assert KnowledgeCardStatus.PUBLISH_FAILED.value == "publish_failed"
        assert KnowledgeCardStatus.RECONCILE_REQUIRED.value == "reconcile_required"
        assert KnowledgeCardStatus.STALE_EVIDENCE.value == "stale_evidence"
        assert KnowledgeCardStatus.DISCARDED.value == "discarded"
        assert KnowledgeCardStatus.RETRACTING.value == "retracting"
        assert KnowledgeCardStatus.RETRACT_RECONCILE_REQUIRED.value == "retract_reconcile_required"
        assert KnowledgeCardStatus.RETRACTED.value == "retracted"

    def test_generation_status_values(self):
        assert DraftGenerationStatus.QUEUED.value == "queued"
        assert DraftGenerationStatus.RUNNING.value == "running"
        assert DraftGenerationStatus.READY.value == "ready"
        assert DraftGenerationStatus.FAILED.value == "failed"
        assert DraftGenerationStatus.UNKNOWN.value == "unknown"
        assert DraftGenerationStatus.SUPERSEDED_BY_EDIT.value == "superseded_by_edit"

    def test_attempt_status_values(self):
        assert GenerationAttemptStatus.QUEUED.value == "queued"
        assert GenerationAttemptStatus.RUNNING.value == "running"
        assert GenerationAttemptStatus.SUCCEEDED.value == "succeeded"
        assert GenerationAttemptStatus.FAILED.value == "failed"
        assert GenerationAttemptStatus.UNKNOWN.value == "unknown"
        assert GenerationAttemptStatus.SUPERSEDED_BY_EDIT.value == "superseded_by_edit"

    def test_occupying_statuses(self):
        for status in (
            KnowledgeCardStatus.DRAFT,
            KnowledgeCardStatus.PUBLISHING,
            KnowledgeCardStatus.PUBLISH_FAILED,
            KnowledgeCardStatus.RECONCILE_REQUIRED,
            KnowledgeCardStatus.PUBLISHED,
            KnowledgeCardStatus.RETRACTING,
            KnowledgeCardStatus.RETRACT_RECONCILE_REQUIRED,
        ):
            assert status in KNOWLEDGE_CARD_OCCUPYING_STATUSES
        for status in (
            KnowledgeCardStatus.STALE_EVIDENCE,
            KnowledgeCardStatus.DISCARDED,
            KnowledgeCardStatus.RETRACTED,
        ):
            assert status not in KNOWLEDGE_CARD_OCCUPYING_STATUSES

    def test_staleable_statuses_exclude_in_flight_publication(self):
        """KB-02 stale reconcile never rewrites a ``publishing`` card; that
        ownership belongs to KB-03 publication."""
        assert KnowledgeCardStatus.PUBLISHING not in STALEABLE_CARD_STATUSES
        for status in (
            KnowledgeCardStatus.DRAFT,
            KnowledgeCardStatus.PUBLISH_FAILED,
            KnowledgeCardStatus.RECONCILE_REQUIRED,
        ):
            assert status in STALEABLE_CARD_STATUSES

    def test_terminal_attempt_statuses(self):
        for status in (
            GenerationAttemptStatus.SUCCEEDED,
            GenerationAttemptStatus.FAILED,
            GenerationAttemptStatus.UNKNOWN,
            GenerationAttemptStatus.SUPERSEDED_BY_EDIT,
        ):
            assert status in TERMINAL_GENERATION_ATTEMPT_STATUSES
        assert GenerationAttemptStatus.QUEUED not in TERMINAL_GENERATION_ATTEMPT_STATUSES
        assert GenerationAttemptStatus.RUNNING not in TERMINAL_GENERATION_ATTEMPT_STATUSES


# ── card defaults / shape ──────────────────────────────────────────────────


class TestKnowledgeCardRecordDefaults:
    def test_defaults(self):
        card = _card()
        assert card.status == KnowledgeCardStatus.DRAFT
        assert card.revision == 1
        assert card.version == 0
        assert card.generation_locked_by_user_edit is False
        assert card.title == ""
        assert card.body == ""
        assert card.content_hash == ""
        assert card.source_snapshot_ids == []
        assert card.evidence_ids == []
        assert card.artifact_ids == []
        assert card.generation_attempt_ids == []
        assert card.latest_generation_attempt_id == ""
        assert card.draft_generation_status == DraftGenerationStatus.QUEUED
        assert card.error_code == ""
        assert card.sanitized_error == ""
        assert card.occupies_slot is True
        assert card.is_editable_draft is True

    def test_stale_does_not_occupy(self):
        card = _card(status=KnowledgeCardStatus.STALE_EVIDENCE, stale_at=123.0)
        assert card.occupies_slot is False
        assert card.is_editable_draft is False

    def test_roundtrip_lossless(self):
        card = _card(
            title="A title",
            body="A body",
            content_hash="abc",
            generation_locked_by_user_edit=True,
            revision=3,
            version=2,
            artifact_ids=["art1"],
            draft_generation_status=DraftGenerationStatus.READY,
        )
        data = card.model_dump(mode="json")
        reloaded = KnowledgeCardRecord.model_validate(data)
        assert reloaded.model_dump(mode="json") == data
        assert reloaded.generation_locked_by_user_edit is True

    def test_extra_fields_ignored(self):
        data = _card().model_dump(mode="json")
        data["api_key"] = "sk-secret"
        card = KnowledgeCardRecord.model_validate(data)
        assert "api_key" not in card.model_dump(mode="json")


class TestKnowledgeCardGenerationAttemptDefaults:
    def test_defaults(self):
        attempt = _attempt()
        assert attempt.status == GenerationAttemptStatus.QUEUED
        assert attempt.version == 1
        assert attempt.generation_attempt_no == 1
        assert attempt.retry_of_generation_attempt_id == ""
        assert attempt.model_invocation_id == ""
        assert attempt.output_blob_ref == ""
        assert attempt.output_hash == ""
        assert attempt.lease_owner == ""
        assert attempt.lease_expires_at == 0.0
        assert attempt.error_code == ""
        assert attempt.is_terminal is False
        assert attempt.lease_active is False

    def test_terminal_flag(self):
        assert _attempt(status=GenerationAttemptStatus.UNKNOWN).is_terminal is True
        assert _attempt(status=GenerationAttemptStatus.RUNNING).is_terminal is False

    def test_roundtrip_with_frozen_snapshot(self):
        attempt = _attempt(
            status=GenerationAttemptStatus.SUCCEEDED,
            output_blob_ref="blobs/hash.json",
            output_hash="hash",
            lease_owner="owner",
            lease_expires_at=1234.0,
            finished_at=1234.0,
        )
        data = attempt.model_dump(mode="json")
        reloaded = KnowledgeCardGenerationAttempt.model_validate(data)
        assert reloaded.model_dump(mode="json") == data
        assert reloaded.frozen_model_snapshot.resolved_model == "gpt-4o-mini"
        assert reloaded.is_terminal is True


# ── LearningProgress persistence ───────────────────────────────────────────


class TestLearningProgressPersistence:
    def test_progress_roundtrips_cards(self, store):
        progress = LearningProgress(book_id="b1")
        progress.knowledge_cards.append(_card())
        progress.knowledge_card_generation_attempts.append(_attempt())
        store.save(progress)

        loaded = store.load("b1")
        assert loaded.knowledge_cards[0].id == "card1"
        assert loaded.knowledge_cards[0].status == KnowledgeCardStatus.DRAFT
        assert loaded.knowledge_card_generation_attempts[0].id == "att1"
        assert loaded.knowledge_card_generation_attempts[0].frozen_model_snapshot is not None

    def test_new_progress_defaults(self):
        progress = LearningProgress(book_id="b1")
        assert progress.knowledge_cards == []
        assert progress.knowledge_card_generation_attempts == []

    def test_v2_fixture_loads_with_defaulted_card_fields(self, store):
        data = json.loads((FIXTURES / "feynman_progress_v2.json").read_text(encoding="utf-8"))
        loaded = LearningProgress.model_validate(data)
        assert loaded.knowledge_cards == []
        assert loaded.knowledge_card_generation_attempts == []
        # Lossless: re-dumping matches the fixture exactly.
        assert loaded.model_dump(mode="json") == data

    def test_legacy_json_without_card_fields_still_loads(self, store):
        data = json.loads((FIXTURES / "legacy_progress_v1.json").read_text(encoding="utf-8"))
        loaded = LearningProgress.model_validate(data)
        assert loaded.knowledge_cards == []
        assert loaded.knowledge_card_generation_attempts == []

    def test_history_and_attempts_append_only_across_saves(self, store):
        progress = LearningProgress(book_id="b1")
        progress.knowledge_cards.append(_card())
        progress.knowledge_card_generation_attempts.append(_attempt())
        store.save(progress)

        loaded = store.load("b1")
        loaded.knowledge_cards[0].revision = 2  # current-card projection may change
        loaded.knowledge_card_generation_attempts.append(
            _attempt(
                id="att2",
                generation_attempt_no=2,
                retry_of_generation_attempt_id="att1",
            )
        )
        store.save(loaded)

        final = store.load("b1")
        # Historical attempt #1 is byte-for-byte unchanged.
        assert final.knowledge_card_generation_attempts[0].id == "att1"
        assert final.knowledge_card_generation_attempts[0].generation_attempt_no == 1
        assert final.knowledge_card_generation_attempts[1].id == "att2"
        assert final.knowledge_cards[0].revision == 2
