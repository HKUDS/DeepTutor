"""MED-01 focused tests: artifact references, soft deletion, GC and quota recovery."""

from __future__ import annotations

import uuid

import pytest

from deeptutor.services.media.models import (
    ArtifactReferenceError,
    ConfirmationRequired,
    GeneratedArtifact,
    QuotaExceededError,
    ReferenceOwnerType,
)
from deeptutor.services.media.store import MediaStore
from tests.services.media._media_helpers import make_png


def _persisted_artifact(
    store: MediaStore,
    *,
    user_id: str = "u1",
    data: bytes | None = None,
    session_id: str = "sess-a",
    **overrides,
) -> GeneratedArtifact:
    data = make_png(8, 8) if data is None else data
    saved = store.persistence.save_media(data, mime_type="image/png")
    artifact = GeneratedArtifact(
        id=uuid.uuid4().hex,
        user_id=user_id,
        session_id=session_id,
        sha256=saved.sha256,
        mime_type=saved.mime_type,
        width=saved.width,
        height=saved.height,
        size_bytes=saved.size_bytes,
        original_path=saved.original_path,
        thumbnail_path=saved.thumbnail_path,
    )
    for key, value in overrides.items():
        setattr(artifact, key, value)
    store.save_artifact(artifact, check_quota=False)
    return artifact


def _crafted_artifact(
    store: MediaStore,
    *,
    user_id: str = "u1",
    size_bytes: int,
    sha256: str | None = None,
    **overrides,
) -> GeneratedArtifact:
    """An artifact record with no backing file, for deterministic quota math."""
    artifact = GeneratedArtifact(
        id=uuid.uuid4().hex,
        user_id=user_id,
        sha256=sha256 or uuid.uuid4().hex,
        size_bytes=size_bytes,
    )
    for key, value in overrides.items():
        setattr(artifact, key, value)
    store.save_artifact(artifact, check_quota=False)
    return artifact


def _reference(
    store: MediaStore,
    artifact: GeneratedArtifact,
    *,
    owner_type: ReferenceOwnerType = ReferenceOwnerType.SESSION,
    owner_id: str = "sess-a",
    user_id: str = "u1",
):
    return store.create_reference(
        artifact_id=artifact.id,
        user_id=user_id,
        owner_type=owner_type,
        owner_id=owner_id,
    )


# ── references ──────────────────────────────────────────────────────────────


def test_create_reference_is_idempotent(media_store: MediaStore) -> None:
    artifact = _persisted_artifact(media_store)
    first = _reference(media_store, artifact)
    second = _reference(media_store, artifact)
    assert first.id == second.id
    assert len(media_store.list_references(artifact_id=artifact.id, live_only=True)) == 1


def test_delete_reference_requires_expected_version(media_store: MediaStore) -> None:
    artifact = _persisted_artifact(media_store)
    ref = _reference(media_store, artifact)
    with pytest.raises(ArtifactReferenceError, match="version conflict"):
        media_store.delete_reference(ref.id, expected_version=ref.version + 1)


# ── cross-user ownership denial (P0) ────────────────────────────────────────


def test_create_reference_denies_cross_user(media_store: MediaStore) -> None:
    artifact = _persisted_artifact(media_store, user_id="u1")
    with pytest.raises(ArtifactReferenceError, match="not 'u2'"):
        media_store.create_reference(
            artifact_id=artifact.id,
            user_id="u2",
            owner_type=ReferenceOwnerType.SESSION,
            owner_id="sess-u2",
        )
    # No cross-user reference was persisted.
    assert media_store.list_references(artifact_id=artifact.id) == []


def test_delete_reference_denies_cross_user(media_store: MediaStore) -> None:
    artifact = _persisted_artifact(media_store, user_id="u1")
    ref = _reference(media_store, artifact, user_id="u1")
    with pytest.raises(ArtifactReferenceError, match="not 'u2'"):
        media_store.delete_reference(ref.id, user_id="u2")
    # The owner's live reference is untouched.
    live = media_store.list_references(artifact_id=artifact.id, live_only=True)
    assert [item.id for item in live] == [ref.id]


def test_delete_artifact_denies_cross_user(media_store: MediaStore) -> None:
    artifact = _persisted_artifact(media_store, user_id="u1")
    _reference(media_store, artifact, user_id="u1")

    with pytest.raises(ArtifactReferenceError, match="not 'u2'"):
        media_store.delete_artifact(
            artifact.id, mode="remove_everywhere", user_id="u2", confirmed=True
        )
    with pytest.raises(ArtifactReferenceError, match="not 'u2'"):
        media_store.delete_artifact(
            artifact.id,
            mode="detach_current",
            user_id="u2",
            owner_type=ReferenceOwnerType.SESSION,
            owner_id="sess-a",
        )
    # The artifact and its owner's reference are untouched.
    assert media_store.load_artifact(artifact.id) is not None
    assert len(media_store.list_references(artifact_id=artifact.id, live_only=True)) == 1


def test_delete_reference_arms_grace_period(media_store: MediaStore) -> None:
    artifact = _persisted_artifact(media_store)
    ref = _reference(media_store, artifact)

    media_store.delete_reference(ref.id, expected_version=ref.version)

    reloaded = media_store.load_artifact(artifact.id)
    assert reloaded is not None and reloaded.gc_candidate_since > 0
    assert media_store.list_references(artifact_id=artifact.id, live_only=True) == []
    # Soft-deleted reference is retained for audit.
    assert len(media_store.list_references(artifact_id=artifact.id)) == 1


def test_restore_during_grace_cancels_gc(media_store: MediaStore) -> None:
    artifact = _persisted_artifact(media_store)
    ref = _reference(media_store, artifact)
    media_store.delete_reference(ref.id)
    assert media_store.load_artifact(artifact.id).gc_candidate_since > 0

    _reference(media_store, artifact)  # re-reference during grace

    reloaded = media_store.load_artifact(artifact.id)
    assert reloaded is not None and reloaded.gc_candidate_since == 0
    result = media_store.run_gc(user_id="u1", force=True)
    assert result.deleted_count == 0
    assert media_store.load_artifact(artifact.id) is not None


# ── GC ──────────────────────────────────────────────────────────────────────


def test_live_reference_blocks_gc(media_store: MediaStore) -> None:
    artifact = _persisted_artifact(media_store)
    _reference(media_store, artifact)

    result = media_store.run_gc(user_id="u1", force=True)

    assert result.deleted_count == 0
    assert media_store.load_artifact(artifact.id) is not None
    assert media_store.persistence.resolve(artifact.original_path).exists()


def test_gc_waits_for_grace_period(media_store: MediaStore) -> None:
    artifact = _persisted_artifact(media_store)
    ref = _reference(media_store, artifact)
    media_store.delete_reference(ref.id)

    now = media_store.load_artifact(artifact.id).gc_candidate_since
    # Automatic GC before the grace period elapses must not delete.
    early = media_store.run_gc(user_id="u1", now=now + 1.0)
    assert early.deleted_count == 0

    # After the grace period elapses the sweep collects it.
    later = media_store.run_gc(
        user_id="u1", now=now + media_store.limits.grace_period_seconds + 1.0
    )
    assert later.deleted_count == 1
    assert later.freed_bytes == artifact.size_bytes
    assert media_store.load_artifact(artifact.id) is None
    assert not media_store.persistence.resolve(artifact.original_path).exists()


def test_explicit_gc_ends_grace_early(media_store: MediaStore) -> None:
    artifact = _persisted_artifact(media_store)
    ref = _reference(media_store, artifact)
    media_store.delete_reference(ref.id)

    result = media_store.run_gc(user_id="u1", force=True)

    assert result.deleted_count == 1
    assert media_store.load_artifact(artifact.id) is None


def test_dedup_shared_original_survives_partial_gc(media_store: MediaStore) -> None:
    data = make_png(4, 4)
    artifact_a = _persisted_artifact(media_store, data=data)
    artifact_b = _persisted_artifact(media_store, data=data)
    assert artifact_a.sha256 == artifact_b.sha256
    original = media_store.persistence.resolve(artifact_a.original_path)
    assert original.exists()

    # Only artifact_b loses its last reference -> it enters the grace period.
    ref_b = _reference(media_store, artifact_b)
    media_store.delete_reference(ref_b.id)
    assert media_store.load_artifact(artifact_b.id).gc_candidate_since > 0

    # The sweep collects b, but the shared content-addressed original must
    # survive because artifact_a still references the same SHA-256.
    result = media_store.run_gc(user_id="u1", force=True)
    assert result.deleted_count == 1
    assert media_store.load_artifact(artifact_b.id) is None
    assert media_store.load_artifact(artifact_a.id) is not None
    assert original.exists()

    # Once artifact_a also loses its last reference, the sweep removes the file.
    ref_a = _reference(media_store, artifact_a)
    media_store.delete_reference(ref_a.id)
    result_two = media_store.run_gc(user_id="u1", force=True)
    assert result_two.deleted_count == 1
    assert not original.exists()


# ── delete-all confirmation contract ────────────────────────────────────────


def test_remove_everywhere_requires_confirmation(media_store: MediaStore) -> None:
    artifact = _persisted_artifact(media_store)
    _reference(media_store, artifact)
    _reference(media_store, artifact, owner_id="sess-b")

    with pytest.raises(ConfirmationRequired, match="confirmation"):
        media_store.delete_artifact(
            artifact.id, mode="remove_everywhere", user_id="u1", confirmed=False
        )


def test_remove_everywhere_confirmed_soft_deletes_and_gc_removes_media(
    media_store: MediaStore,
) -> None:
    artifact = _persisted_artifact(media_store)
    _reference(media_store, artifact)
    _reference(media_store, artifact, owner_id="sess-b")

    deleted = media_store.delete_artifact(
        artifact.id, mode="remove_everywhere", user_id="u1", confirmed=True
    )

    assert len(deleted) == 2
    assert all(not ref.is_live for ref in deleted)
    assert media_store.load_artifact(artifact.id).gc_candidate_since > 0

    result = media_store.run_gc(user_id="u1", force=True)
    assert result.deleted_count == 1
    assert media_store.load_artifact(artifact.id) is None


def test_detach_current_removes_only_that_owner_context(media_store: MediaStore) -> None:
    artifact = _persisted_artifact(media_store)
    _reference(media_store, artifact, owner_id="sess-a")
    _reference(media_store, artifact, owner_id="sess-b")

    deleted = media_store.delete_artifact(
        artifact.id,
        mode="detach_current",
        user_id="u1",
        owner_type=ReferenceOwnerType.SESSION,
        owner_id="sess-a",
    )

    assert len(deleted) == 1
    assert deleted[0].owner_id == "sess-a"
    # Another owner context still references the artifact -> no grace period.
    reloaded = media_store.load_artifact(artifact.id)
    assert reloaded is not None and reloaded.gc_candidate_since == 0
    assert len(media_store.list_references(artifact_id=artifact.id, live_only=True)) == 1


# ── quota ───────────────────────────────────────────────────────────────────


def test_quota_exhaustion_is_recoverable(tiny_quota_store: MediaStore) -> None:
    store = tiny_quota_store
    # Two crafted artifacts, 100 bytes each, against a 150-byte quota.
    artifact_a = _crafted_artifact(store, size_bytes=100)
    artifact_b = _crafted_artifact(store, size_bytes=100)
    assert store.used_bytes("u1") == 200

    # A third artifact no longer fits -> recoverable QuotaExceededError.
    with pytest.raises(QuotaExceededError) as excinfo:
        store.check_quota_for_bytes("u1", 100)
    error = excinfo.value
    assert error.used_bytes == 200
    assert error.limit_bytes == 150
    assert error.reclaimable_bytes == 0

    # Free space by removing references and running an explicit GC.
    for artifact in (artifact_a, artifact_b):
        ref = _reference(store, artifact)
        store.delete_reference(ref.id)
    info = store.quota_info("u1")
    assert info.reclaimable_bytes == 200

    gc = store.run_gc(user_id="u1", force=True)
    assert gc.deleted_count == 2
    assert store.used_bytes("u1") == 0

    # Quota is recovered: the previously rejected save now succeeds.
    store.check_quota_for_bytes("u1", 100)
    assert store.quota_info("u1").remaining_bytes == 150
