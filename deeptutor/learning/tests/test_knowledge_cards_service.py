"""Service tests for knowledge-card drafts (KB-02).

Covers server-derived eligibility and atomic draft-shell creation, versioned
edits with the user-edit lock and artifact references, append-only explicit
retries, discard, stale-evidence reconciliation, and the idempotency/ownership
contracts (§6.6, §7.9, §8.3/§8.5, requirement 2/6/7/8).
"""

from __future__ import annotations

import pytest

from deeptutor.learning.knowledge_cards.blobs import KnowledgeCardBlobStore
from deeptutor.learning.knowledge_cards.errors import (
    GenerationLockedByUserEditError,
    KnowledgeCardEligibilityError,
    KnowledgeCardIdempotencyConflictError,
    KnowledgeCardInputValidationError,
    KnowledgeCardOwnershipError,
    KnowledgeCardStaleVersionError,
    KnowledgeCardStateError,
)
from deeptutor.learning.knowledge_cards.service import KnowledgeCardDraftService
from deeptutor.learning.models import (
    DraftGenerationStatus,
    GenerationAttemptStatus,
    KnowledgeCardStatus,
    MasteryState,
    ReviewState,
)
from deeptutor.learning.storage import LearningStore
from deeptutor.learning.tests.knowledge_card_builders import (
    media_store_with_artifact,
    stable_mastery_progress,
)
from deeptutor.services.media.models import ReferenceOwnerType


@pytest.fixture
def store(tmp_path):
    return LearningStore(root=tmp_path)


@pytest.fixture
def media_store(tmp_path):
    return media_store_with_artifact(tmp_path)[0]


@pytest.fixture
def service(tmp_path, media_store):
    return KnowledgeCardDraftService(
        LearningStore(root=tmp_path),
        media_store=media_store,
        blob_store=KnowledgeCardBlobStore(tmp_path / "blobs"),
    )


def _card_of(progress, card_id: str):
    return next(card for card in progress.knowledge_cards if card.id == card_id)


def _raise_stale_save(_progress):
    """Fail a LearningProgress CAS save as if the caller held a stale version."""
    raise KnowledgeCardStaleVersionError(
        "stale save rejected for 'b1': caller holds 1, persisted 2"
    )


# ── eligibility / atomic draft shell ───────────────────────────────────────


class TestEnsureDraftEligibility:
    def test_creates_empty_draft_shell_and_queued_attempt(self, store, service):
        progress, attempt, assessment = stable_mastery_progress()
        store.save(progress)
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )

        assert result["created"] is True
        card = result["card"]
        assert card.status == KnowledgeCardStatus.DRAFT
        assert card.title == ""
        assert card.body == ""
        assert card.stable_attempt_id == "a1"
        assert card.stable_assessment_id == "ra1"
        assert card.stable_assessment_sequence == 1
        assert card.source_snapshot_ids == ["s1"]
        assert card.evidence_ids == ["ev1"]
        assert card.generation_locked_by_user_edit is False
        assert card.draft_generation_status == DraftGenerationStatus.QUEUED
        assert card.occupies_slot is True

        gen = result["attempt"]
        assert gen.status == GenerationAttemptStatus.QUEUED
        assert gen.input_card_revision == 1
        assert gen.stable_assessment_id == "ra1"
        assert gen.frozen_model_snapshot is not None
        assert gen.frozen_model_snapshot.resolved_model == "gpt-4o-mini"
        assert gen.input_hash  # frozen deterministic input fingerprint

        persisted = store.load("b1")
        assert len(persisted.knowledge_cards) == 1
        assert len(persisted.knowledge_card_generation_attempts) == 1

    def test_ensure_draft_is_idempotent(self, store, service):
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        first = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        progress = store.load("b1")
        second = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )

        assert second["created"] is False
        assert second["card"].id == first["card"].id
        assert len(store.load("b1").knowledge_cards) == 1
        assert len(store.load("b1").knowledge_card_generation_attempts) == 1

    def test_blank_actor_rejected(self, store, service):
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        with pytest.raises(KnowledgeCardOwnershipError):
            service.ensure_draft(progress, user_id="", path_id="b1", knowledge_point_id="kp1")

    def test_cross_user_repeated_ensure_rejected(self, store, service):
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        service.ensure_draft(progress, user_id="owner", path_id="b1", knowledge_point_id="kp1")
        progress = store.load("b1")
        version_before = progress.version
        with pytest.raises(KnowledgeCardOwnershipError):
            service.ensure_draft(
                progress, user_id="intruder", path_id="b1", knowledge_point_id="kp1"
            )
        # The owner's draft/attempt were never exposed and nothing mutated
        # durably (the document version is unchanged).
        persisted = store.load("b1")
        assert len(persisted.knowledge_cards) == 1
        assert persisted.knowledge_cards[0].user_id == "owner"
        assert len(persisted.knowledge_card_generation_attempts) == 1
        assert persisted.version == version_before

    def test_fails_closed_for_provisional_mastery(self, store, service):
        progress, attempt, assessment = stable_mastery_progress()
        progress.projections["kp1"].mastery_state = MasteryState.PROVISIONAL_MASTERY
        store.save(progress)
        with pytest.raises(KnowledgeCardEligibilityError):
            service.ensure_draft(progress, user_id="owner", path_id="b1", knowledge_point_id="kp1")

    def test_fails_closed_for_needs_revision(self, store, service):
        progress, _, _ = stable_mastery_progress()
        progress.projections["kp1"].mastery_state = MasteryState.NEEDS_REVISION
        store.save(progress)
        with pytest.raises(KnowledgeCardEligibilityError):
            service.ensure_draft(progress, user_id="owner", path_id="b1", knowledge_point_id="kp1")

    def test_fails_closed_when_no_evaluator_snapshot(self, store, service):
        progress, _, _ = stable_mastery_progress()
        progress.attempts[0].evaluator_snapshot = None
        progress.rubric_assessments[0].evaluator_snapshot = None
        store.save(progress)
        with pytest.raises(KnowledgeCardEligibilityError):
            service.ensure_draft(progress, user_id="owner", path_id="b1", knowledge_point_id="kp1")

    def test_fails_closed_on_cross_path_input(self, store, service):
        progress, _, _ = stable_mastery_progress(book_id="b1")
        store.save(progress)
        with pytest.raises(KnowledgeCardInputValidationError):
            service.ensure_draft(
                progress, user_id="owner", path_id="other-path", knowledge_point_id="kp1"
            )

    def test_fails_closed_when_latest_assessment_failed(self, store, service):
        progress, _, _ = stable_mastery_progress(passed=False)
        store.save(progress)
        with pytest.raises(KnowledgeCardEligibilityError):
            service.ensure_draft(progress, user_id="owner", path_id="b1", knowledge_point_id="kp1")

    def test_sequence_must_exceed_retracted_sequence(self, store, service):
        progress, _, assessment = stable_mastery_progress(
            assessment_sequence=2, retracted_sequence=2
        )
        store.save(progress)
        with pytest.raises(KnowledgeCardEligibilityError) as excinfo:
            service.ensure_draft(progress, user_id="owner", path_id="b1", knowledge_point_id="kp1")
        assert "strictly greater" in str(excinfo.value)

    def test_stale_occupying_card_does_not_block_newer_stable(self, store, service):
        progress, _, assessment = stable_mastery_progress()
        # An old draft whose stable assessment is no longer current.
        from deeptutor.learning.models import KnowledgeCardRecord

        progress.knowledge_cards.append(
            KnowledgeCardRecord(
                id="old-draft",
                user_id="owner",
                path_id="b1",
                knowledge_point_id="kp1",
                stable_attempt_id="a-old",
                stable_assessment_id="ra-old",
                stable_assessment_sequence=1,
                status=KnowledgeCardStatus.DRAFT,
            )
        )
        store.save(progress)
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        assert result["created"] is True
        persisted = store.load("b1")
        assert _card_of(persisted, "old-draft").status == KnowledgeCardStatus.STALE_EVIDENCE
        assert _card_of(persisted, "old-draft").occupies_slot is False
        assert result["card"].id != "old-draft"

    def test_published_occupying_card_rejected(self, store, service):
        progress, _, _ = stable_mastery_progress()
        from deeptutor.learning.models import KnowledgeCardRecord

        progress.knowledge_cards.append(
            KnowledgeCardRecord(
                id="pub",
                user_id="owner",
                path_id="b1",
                knowledge_point_id="kp1",
                stable_assessment_id="ra1",
                stable_assessment_sequence=1,
                status=KnowledgeCardStatus.PUBLISHED,
                published_at=1.0,
            )
        )
        store.save(progress)
        with pytest.raises(KnowledgeCardStateError):
            service.ensure_draft(progress, user_id="owner", path_id="b1", knowledge_point_id="kp1")

    def test_stable_mastery_survives_generation_failure(self, store, service):
        """A later generation failure never rolls back stable mastery."""
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        service.ensure_draft(progress, user_id="owner", path_id="b1", knowledge_point_id="kp1")
        progress = store.load("b1")
        # Simulate a failed generation attempt.
        attempt = progress.knowledge_card_generation_attempts[0]
        attempt.status = GenerationAttemptStatus.FAILED
        attempt.error_code = "provider_error"
        attempt.finished_at = 100.0
        store.save(progress)

        loaded = store.load("b1")
        assert loaded.projections["kp1"].mastery_state == MasteryState.STABLE_MASTERY
        assert loaded.knowledge_cards[0].status == KnowledgeCardStatus.DRAFT


# ── versioned edits / user-edit lock ───────────────────────────────────────


class TestEditDraft:
    def test_versioned_edit_requires_expected_revision(self, store, service):
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        progress = store.load("b1")
        card_id = result["card"].id

        with pytest.raises(KnowledgeCardStaleVersionError):
            service.edit_draft(
                progress,
                card_id=card_id,
                user_id="owner",
                request_id="r1",
                expected_card_revision=99,
                title="My title",
            )

    def test_first_content_edit_locks_generation(self, store, service):
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        progress = store.load("b1")
        card_id = result["card"].id

        service.edit_draft(
            progress,
            card_id=card_id,
            user_id="owner",
            request_id="r1",
            expected_card_revision=1,
            title="User title",
            body="User body",
        )
        card = _card_of(store.load("b1"), card_id)
        assert card.title == "User title"
        assert card.body == "User body"
        assert card.generation_locked_by_user_edit is True
        assert card.content_hash
        assert card.revision == 2
        assert card.version >= 1

    def test_edit_rejects_publishing_non_editable(self, store, service):
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        progress = store.load("b1")
        card_id = result["card"].id
        card = _card_of(progress, card_id)
        card.status = KnowledgeCardStatus.PUBLISHING
        store.save(progress)
        progress = store.load("b1")

        with pytest.raises(KnowledgeCardStateError):
            service.edit_draft(
                progress,
                card_id=card_id,
                user_id="owner",
                request_id="r1",
                expected_card_revision=1,
                title="T",
            )

    def test_cross_user_edit_rejected(self, store, service):
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        progress = store.load("b1")
        with pytest.raises(KnowledgeCardOwnershipError):
            service.edit_draft(
                progress,
                card_id=result["card"].id,
                user_id="intruder",
                request_id="r1",
                expected_card_revision=1,
                title="T",
            )

    def test_idempotent_edit_replays_same_result(self, store, service):
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        progress = store.load("b1")
        card_id = result["card"].id
        first = service.edit_draft(
            progress,
            card_id=card_id,
            user_id="owner",
            request_id="r1",
            expected_card_revision=1,
            title="Title",
            body="Body",
        )
        progress = store.load("b1")
        # Replay uses the same idempotency key (card_id + request_id +
        # expected_card_revision) as the original request.
        second = service.edit_draft(
            progress,
            card_id=card_id,
            user_id="owner",
            request_id="r1",
            expected_card_revision=1,
            title="Title",
            body="Body",
        )
        assert second["replayed"] is True
        assert second["revision"] == first["revision"]

    def test_idempotency_conflict_on_different_payload(self, store, service):
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        progress = store.load("b1")
        card_id = result["card"].id
        service.edit_draft(
            progress,
            card_id=card_id,
            user_id="owner",
            request_id="r1",
            expected_card_revision=1,
            title="Title A",
        )
        progress = store.load("b1")
        with pytest.raises(KnowledgeCardIdempotencyConflictError):
            service.edit_draft(
                progress,
                card_id=card_id,
                user_id="owner",
                request_id="r1",
                expected_card_revision=2,
                title="Title B",
            )


# ── artifact references ────────────────────────────────────────────────────


class TestArtifactReferences:
    def test_attach_creates_knowledge_card_reference(self, store, service):
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        progress = store.load("b1")
        card_id = result["card"].id

        service.edit_draft(
            progress,
            card_id=card_id,
            user_id="owner",
            request_id="r1",
            expected_card_revision=1,
            attach_artifact_ids=["art1"],
        )
        card = _card_of(store.load("b1"), card_id)
        assert card.artifact_ids == ["art1"]
        # Artifact change bumps revision (late model result loses the guard).
        assert card.revision == 2
        assert card.generation_locked_by_user_edit is False
        # Live KNOWLEDGE_CARD reference exists and blocks GC.
        refs = service.media_store.list_references(
            artifact_id="art1", user_id="owner", live_only=True
        )
        assert any(
            ref.owner_type == ReferenceOwnerType.KNOWLEDGE_CARD and ref.owner_id == card_id
            for ref in refs
        )

    def test_attach_rejects_cross_user_artifact(self, store, service):
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        progress = store.load("b1")
        from deeptutor.services.media.models import GeneratedArtifact

        service.media_store.save_artifact(
            GeneratedArtifact(
                id="other-art",
                user_id="someone-else",
                sha256="b" * 64,
                mime_type="image/png",
                size_bytes=5,
            ),
            check_quota=False,
        )
        with pytest.raises(KnowledgeCardInputValidationError):
            service.edit_draft(
                progress,
                card_id=result["card"].id,
                user_id="owner",
                request_id="r1",
                expected_card_revision=1,
                attach_artifact_ids=["other-art"],
            )
        # No reference leaked, card untouched.
        assert service.media_store.list_references(artifact_id="other-art", live_only=True) == []

    def test_attach_rejects_missing_artifact(self, store, service):
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        progress = store.load("b1")
        with pytest.raises(KnowledgeCardInputValidationError):
            service.edit_draft(
                progress,
                card_id=result["card"].id,
                user_id="owner",
                request_id="r1",
                expected_card_revision=1,
                attach_artifact_ids=["ghost"],
            )

    def test_attach_partial_failure_rolls_back(self, store, service):
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        progress = store.load("b1")
        card_id = result["card"].id
        # First id is valid, second is missing: the first reference must roll back.
        with pytest.raises(KnowledgeCardInputValidationError):
            service.edit_draft(
                progress,
                card_id=card_id,
                user_id="owner",
                request_id="r1",
                expected_card_revision=1,
                attach_artifact_ids=["art1", "ghost"],
            )
        assert (
            service.media_store.list_references(artifact_id="art1", user_id="owner", live_only=True)
            == []
        )
        card = _card_of(store.load("b1"), card_id)
        assert card.artifact_ids == []

    def test_detach_removes_only_this_cards_reference(self, store, service):
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        progress = store.load("b1")
        card_id = result["card"].id
        service.edit_draft(
            progress,
            card_id=card_id,
            user_id="owner",
            request_id="r1",
            expected_card_revision=1,
            attach_artifact_ids=["art1"],
        )
        progress = store.load("b1")
        service.edit_draft(
            progress,
            card_id=card_id,
            user_id="owner",
            request_id="r2",
            expected_card_revision=2,
            detach_artifact_ids=["art1"],
        )
        card = _card_of(store.load("b1"), card_id)
        assert card.artifact_ids == []
        assert (
            service.media_store.list_references(artifact_id="art1", user_id="owner", live_only=True)
            == []
        )


# ── content-only edits without a media store ───────────────────────────────


class TestNoMediaStoreEdit:
    """Title/body edits never require a media store; only attach/detach do."""

    def _no_media_service(self, store, tmp_path):
        return KnowledgeCardDraftService(
            store,
            blob_store=KnowledgeCardBlobStore(tmp_path / "blobs-no-media"),
        )

    def test_content_only_edit_allowed_without_media_store(self, store, tmp_path):
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        no_media_service = self._no_media_service(store, tmp_path)
        result = no_media_service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        progress = store.load("b1")
        card_id = result["card"].id
        _card_of(progress, card_id).artifact_ids = ["art1"]
        store.save(progress)
        progress = store.load("b1")

        edited = no_media_service.edit_draft(
            progress,
            card_id=card_id,
            user_id="owner",
            request_id="r1",
            expected_card_revision=1,
            title="User title",
            body="User body",
        )
        assert edited["content_changed"] is True
        assert edited["artifacts_changed"] is False
        card = _card_of(store.load("b1"), card_id)
        assert card.title == "User title"
        assert card.body == "User body"
        assert card.generation_locked_by_user_edit is True
        # Existing artifact ids are preserved without any media store.
        assert card.artifact_ids == ["art1"]

    def test_attach_without_media_store_rejected(self, store, tmp_path):
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        no_media_service = self._no_media_service(store, tmp_path)
        result = no_media_service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        progress = store.load("b1")
        with pytest.raises(KnowledgeCardStateError):
            no_media_service.edit_draft(
                progress,
                card_id=result["card"].id,
                user_id="owner",
                request_id="r1",
                expected_card_revision=1,
                attach_artifact_ids=["art1"],
            )


# ── media-reference compensation on CAS failure ────────────────────────────


class TestMediaReferenceCompensation:
    """Attachment/reference mutation and the CAS save are one compensated op.

    A LearningStore CAS/save failure after attach/detach/discard must leave the
    persisted card metadata unchanged and restore the exact live owner-reference
    set — new references removed, every previously live reference re-established
    (§10.5, requirement 6).
    """

    @staticmethod
    def _add_art2(service) -> str:
        from deeptutor.services.media.models import GeneratedArtifact

        service.media_store.save_artifact(
            GeneratedArtifact(
                id="art2",
                user_id="owner",
                sha256="c" * 64,
                mime_type="image/png",
                size_bytes=12,
            ),
            check_quota=False,
        )
        return "art2"

    def test_attach_cas_failure_rolls_back_created_reference(self, store, service, monkeypatch):
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        progress = store.load("b1")
        card_id = result["card"].id

        monkeypatch.setattr(service, "save", _raise_stale_save)
        with pytest.raises(KnowledgeCardStaleVersionError):
            service.edit_draft(
                progress,
                card_id=card_id,
                user_id="owner",
                request_id="r1",
                expected_card_revision=1,
                attach_artifact_ids=["art1"],
            )
        card = _card_of(store.load("b1"), card_id)
        assert card.artifact_ids == []
        assert card.revision == 1
        assert (
            service.media_store.list_references(artifact_id="art1", user_id="owner", live_only=True)
            == []
        )

    def test_detach_cas_failure_restores_deleted_reference(self, store, service, monkeypatch):
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        progress = store.load("b1")
        card_id = result["card"].id
        service.edit_draft(
            progress,
            card_id=card_id,
            user_id="owner",
            request_id="r1",
            expected_card_revision=1,
            attach_artifact_ids=["art1"],
        )
        progress = store.load("b1")

        monkeypatch.setattr(service, "save", _raise_stale_save)
        with pytest.raises(KnowledgeCardStaleVersionError):
            service.edit_draft(
                progress,
                card_id=card_id,
                user_id="owner",
                request_id="r2",
                expected_card_revision=2,
                detach_artifact_ids=["art1"],
            )
        card = _card_of(store.load("b1"), card_id)
        assert card.artifact_ids == ["art1"]
        assert card.revision == 2
        refs = service.media_store.list_references(
            artifact_id="art1", user_id="owner", live_only=True
        )
        assert any(
            ref.owner_type == ReferenceOwnerType.KNOWLEDGE_CARD and ref.owner_id == card_id
            for ref in refs
        )

    def test_mixed_attach_detach_cas_failure_restores_exact_set(self, store, service, monkeypatch):
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        progress = store.load("b1")
        card_id = result["card"].id
        service.edit_draft(
            progress,
            card_id=card_id,
            user_id="owner",
            request_id="r1",
            expected_card_revision=1,
            attach_artifact_ids=["art1"],
        )
        progress = store.load("b1")
        art2 = self._add_art2(service)

        monkeypatch.setattr(service, "save", _raise_stale_save)
        with pytest.raises(KnowledgeCardStaleVersionError):
            service.edit_draft(
                progress,
                card_id=card_id,
                user_id="owner",
                request_id="r2",
                expected_card_revision=2,
                attach_artifact_ids=[art2],
                detach_artifact_ids=["art1"],
            )
        card = _card_of(store.load("b1"), card_id)
        assert card.artifact_ids == ["art1"]
        assert card.revision == 2
        art1_refs = service.media_store.list_references(
            artifact_id="art1", user_id="owner", live_only=True
        )
        assert any(
            ref.owner_type == ReferenceOwnerType.KNOWLEDGE_CARD and ref.owner_id == card_id
            for ref in art1_refs
        )
        assert (
            service.media_store.list_references(artifact_id=art2, user_id="owner", live_only=True)
            == []
        )

    def test_discard_cas_failure_restores_references(self, store, service, monkeypatch):
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        progress = store.load("b1")
        card_id = result["card"].id
        service.edit_draft(
            progress,
            card_id=card_id,
            user_id="owner",
            request_id="r1",
            expected_card_revision=1,
            attach_artifact_ids=["art1"],
        )
        progress = store.load("b1")

        monkeypatch.setattr(service, "save", _raise_stale_save)
        with pytest.raises(KnowledgeCardStaleVersionError):
            service.discard(
                progress,
                card_id=card_id,
                user_id="owner",
                request_id="d1",
                expected_card_revision=2,
            )
        card = _card_of(store.load("b1"), card_id)
        assert card.status == KnowledgeCardStatus.DRAFT
        assert card.artifact_ids == ["art1"]
        refs = service.media_store.list_references(
            artifact_id="art1", user_id="owner", live_only=True
        )
        assert any(
            ref.owner_type == ReferenceOwnerType.KNOWLEDGE_CARD and ref.owner_id == card_id
            for ref in refs
        )


# ── discard ────────────────────────────────────────────────────────────────


class TestDiscard:
    def test_discard_draft_releases_references(self, store, service):
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        progress = store.load("b1")
        card_id = result["card"].id
        service.edit_draft(
            progress,
            card_id=card_id,
            user_id="owner",
            request_id="r1",
            expected_card_revision=1,
            attach_artifact_ids=["art1"],
        )
        progress = store.load("b1")
        service.discard(
            progress, card_id=card_id, user_id="owner", request_id="d1", expected_card_revision=2
        )
        card = _card_of(store.load("b1"), card_id)
        assert card.status == KnowledgeCardStatus.DISCARDED
        assert card.occupies_slot is False
        assert (
            service.media_store.list_references(artifact_id="art1", user_id="owner", live_only=True)
            == []
        )
        # Learning evidence is untouched.
        loaded = store.load("b1")
        assert loaded.projections["kp1"].mastery_state == MasteryState.STABLE_MASTERY

    def test_discard_stale_card_allowed(self, store, service):
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        progress = store.load("b1")
        card_id = result["card"].id
        card = _card_of(progress, card_id)
        card.status = KnowledgeCardStatus.STALE_EVIDENCE
        card.stale_at = 1.0
        store.save(progress)
        progress = store.load("b1")
        service.discard(
            progress, card_id=card_id, user_id="owner", request_id="d1", expected_card_revision=1
        )
        assert _card_of(store.load("b1"), card_id).status == KnowledgeCardStatus.DISCARDED

    def test_discard_rejects_published(self, store, service):
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        progress = store.load("b1")
        card_id = result["card"].id
        card = _card_of(progress, card_id)
        card.status = KnowledgeCardStatus.PUBLISHED
        store.save(progress)
        progress = store.load("b1")
        with pytest.raises(KnowledgeCardStateError):
            service.discard(
                progress,
                card_id=card_id,
                user_id="owner",
                request_id="d1",
                expected_card_revision=1,
            )


# ── explicit retry ─────────────────────────────────────────────────────────


class TestRetryGeneration:
    def test_retry_appends_new_attempt_with_retry_lineage(self, store, service):
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        progress = store.load("b1")
        card_id = result["card"].id
        first_attempt = result["attempt"].id
        # Terminate the first attempt (e.g. it failed).
        attempt = progress.knowledge_card_generation_attempts[0]
        attempt.status = GenerationAttemptStatus.FAILED
        attempt.finished_at = 100.0
        store.save(progress)
        progress = store.load("b1")

        retry = service.retry_generation(
            progress,
            card_id=card_id,
            user_id="owner",
            request_id="retry1",
            expected_card_revision=1,
            latest_generation_attempt_id=first_attempt,
        )
        new_attempt = retry["attempt"]
        assert new_attempt.generation_attempt_no == 2
        assert new_attempt.retry_of_generation_attempt_id == first_attempt
        assert new_attempt.status == GenerationAttemptStatus.QUEUED
        assert new_attempt.frozen_model_snapshot is not None
        # Same frozen model basis, never silently re-resolved.
        assert (
            new_attempt.frozen_model_snapshot.resolved_model
            == progress.knowledge_card_generation_attempts[0].frozen_model_snapshot.resolved_model
        )
        assert new_attempt.input_card_revision == 1

        persisted = store.load("b1")
        assert len(persisted.knowledge_card_generation_attempts) == 2
        # Old attempt history preserved.
        assert (
            persisted.knowledge_card_generation_attempts[0].status == GenerationAttemptStatus.FAILED
        )
        assert persisted.knowledge_cards[0].latest_generation_attempt_id == new_attempt.id

    def test_retry_rejected_after_user_edit_lock(self, store, service):
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        progress = store.load("b1")
        card_id = result["card"].id
        first_attempt = result["attempt"].id
        service.edit_draft(
            progress,
            card_id=card_id,
            user_id="owner",
            request_id="edit1",
            expected_card_revision=1,
            title="User title",
        )
        progress = store.load("b1")
        with pytest.raises(GenerationLockedByUserEditError):
            service.retry_generation(
                progress,
                card_id=card_id,
                user_id="owner",
                request_id="retry1",
                expected_card_revision=2,
                latest_generation_attempt_id=first_attempt,
            )

    def test_retry_rejected_when_active_attempt_exists(self, store, service):
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        progress = store.load("b1")
        with pytest.raises(KnowledgeCardStateError):
            service.retry_generation(
                progress,
                card_id=result["card"].id,
                user_id="owner",
                request_id="retry1",
                expected_card_revision=1,
                latest_generation_attempt_id=result["attempt"].id,
            )

    def test_retry_rejected_on_stale_evidence(self, store, service):
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        progress = store.load("b1")
        card_id = result["card"].id
        first_attempt = result["attempt"].id
        # Overturn the stable evidence.
        progress.projections["kp1"].mastery_state = MasteryState.NEEDS_REVISION
        store.save(progress)
        progress = store.load("b1")
        with pytest.raises(KnowledgeCardStateError):
            service.retry_generation(
                progress,
                card_id=card_id,
                user_id="owner",
                request_id="retry1",
                expected_card_revision=1,
                latest_generation_attempt_id=first_attempt,
            )


# ── stale-evidence reconcile ───────────────────────────────────────────────


class TestStaleReconcile:
    def test_reconcile_stales_draft_when_evidence_overturned(self, store, service):
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        progress = store.load("b1")
        card_id = result["card"].id
        # A later failed review overturns stable mastery.
        progress.projections["kp1"].mastery_state = MasteryState.NEEDS_REVISION
        progress.projections["kp1"].latest_assessment_id = ""
        store.save(progress)
        progress = store.load("b1")

        stale_ids = service.reconcile_stale(progress)
        assert stale_ids == [card_id]
        card = _card_of(store.load("b1"), card_id)
        assert card.status == KnowledgeCardStatus.STALE_EVIDENCE
        assert card.stale_at is not None
        # Preserved: attempts and provenance intact.
        assert card.generation_attempt_ids

    def test_reconcile_preserves_current_card(self, store, service):
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        progress = store.load("b1")
        stale_ids = service.reconcile_stale(progress)
        assert stale_ids == []
        assert _card_of(store.load("b1"), result["card"].id).status == KnowledgeCardStatus.DRAFT

    def test_idempotent_ensure_persists_unrelated_stale_transition(self, store, service):
        """A pure reuse still durably stales an unrelated card's draft."""
        from deeptutor.learning.models import KnowledgeCardRecord, KnowledgePoint, KnowledgeType

        progress, _, _ = stable_mastery_progress()
        progress.modules[0].knowledge_points.append(
            KnowledgePoint(id="kp2", name="KP2", type=KnowledgeType.CONCEPT, module_id="m1")
        )
        progress.knowledge_types["kp2"] = KnowledgeType.CONCEPT
        store.save(progress)

        # A current draft for kp1.
        service.ensure_draft(progress, user_id="owner", path_id="b1", knowledge_point_id="kp1")
        progress = store.load("b1")

        # kp2 has an occupying draft whose stable basis is no longer current.
        progress.knowledge_cards.append(
            KnowledgeCardRecord(
                id="kp2-stale",
                user_id="owner",
                path_id="b1",
                knowledge_point_id="kp2",
                stable_assessment_id="ra-old2",
                stable_assessment_sequence=1,
                status=KnowledgeCardStatus.DRAFT,
            )
        )
        store.save(progress)

        # Reuse kp1's draft (idempotent); the global reconcile must durably
        # stale kp2's unrelated card even though nothing new is created.
        progress = store.load("b1")
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        assert result["created"] is False
        persisted = store.load("b1")
        kp2_card = next(card for card in persisted.knowledge_cards if card.id == "kp2-stale")
        assert kp2_card.status == KnowledgeCardStatus.STALE_EVIDENCE

    def test_reconcile_does_not_reactivate_stale_card(self, store, service):
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        progress = store.load("b1")
        card_id = result["card"].id
        card = _card_of(progress, card_id)
        card.status = KnowledgeCardStatus.STALE_EVIDENCE
        card.stale_at = 1.0
        store.save(progress)
        progress = store.load("b1")

        stale_ids = service.reconcile_stale(progress)
        assert stale_ids == []
        assert _card_of(store.load("b1"), card_id).status == KnowledgeCardStatus.STALE_EVIDENCE

    def test_ensure_draft_persists_stale_before_eligibility_failure(self, store, service):
        """A dropped stable assessment durably stales the occupying draft even
        when ensure_draft fails closed for lack of a replacement assessment."""
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        progress = store.load("b1")
        card_id = result["card"].id
        # Overturn stable mastery; no replacement stable assessment exists.
        progress.projections["kp1"].mastery_state = MasteryState.NEEDS_REVISION
        progress.projections["kp1"].latest_assessment_id = ""
        store.save(progress)
        progress = store.load("b1")

        with pytest.raises(KnowledgeCardEligibilityError):
            service.ensure_draft(progress, user_id="owner", path_id="b1", knowledge_point_id="kp1")
        # The reconcile transitions are persisted through the CAS/version
        # contract, so the stale card can never remain durably editable.
        persisted = store.load("b1")
        card = _card_of(persisted, card_id)
        assert card.status == KnowledgeCardStatus.STALE_EVIDENCE
        assert card.stale_at is not None
        assert card.occupies_slot is False

    def test_reconcile_never_stales_publishing_card(self, store, service):
        """An in-flight publishing card is owned by KB-03; KB-02 reconcile
        leaves its status untouched even when the evidence is overturned."""
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        progress = store.load("b1")
        card_id = result["card"].id
        card = _card_of(progress, card_id)
        card.status = KnowledgeCardStatus.PUBLISHING
        store.save(progress)
        progress = store.load("b1")
        progress.projections["kp1"].mastery_state = MasteryState.NEEDS_REVISION
        progress.projections["kp1"].latest_assessment_id = ""
        store.save(progress)
        progress = store.load("b1")

        stale_ids = service.reconcile_stale(progress)
        assert stale_ids == []
        assert _card_of(store.load("b1"), card_id).status == KnowledgeCardStatus.PUBLISHING

    def test_ensure_draft_never_competes_with_publishing_card(self, store, service):
        """ensure_draft fails closed under an in-flight publication instead of
        staling it or creating a competing draft."""
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        progress = store.load("b1")
        card_id = result["card"].id
        card = _card_of(progress, card_id)
        card.status = KnowledgeCardStatus.PUBLISHING
        store.save(progress)
        progress = store.load("b1")
        progress.projections["kp1"].mastery_state = MasteryState.NEEDS_REVISION
        progress.projections["kp1"].latest_assessment_id = ""
        store.save(progress)
        progress = store.load("b1")

        with pytest.raises(KnowledgeCardStateError):
            service.ensure_draft(progress, user_id="owner", path_id="b1", knowledge_point_id="kp1")
        persisted = store.load("b1")
        assert len(persisted.knowledge_cards) == 1
        assert _card_of(persisted, card_id).status == KnowledgeCardStatus.PUBLISHING
