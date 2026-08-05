"""Durable store for image jobs, generated artifacts and references (MED-01).

Record layout under the media root::

    jobs/<job_id>.json
    artifacts/<artifact_id>.json
    references/<reference_id>.json
    originals/<sha256[:2]>/<sha256>.<ext>
    thumbnails/<sha256[:2]>/<sha256>.jpg
    tmp/

All JSON records are written atomically (same-directory temp + rename).  A
module-level lock makes compare-and-swap transitions hold across store
instances in the process, mirroring ``deeptutor.learning.storage``.

Invariants enforced here (P0 data-safety surfaces):

* ``job.succeeded`` ⟺ every artifact + reference it lists is durably on disk.
* a live reference always blocks GC and physical deletion;
* ``remove_everywhere`` requires explicit confirmation;
* per-user quota is recoverable (used/limit/reclaimable are observable);
* content-addressed files shared by dedup are never deleted while another
  artifact record still references the same SHA-256;
* artifact ownership: reference creation, detach/remove-everywhere and job
  source/mask/continuation validation all enforce the artifact owner's user;
* same-user idempotency lookup, concurrency-slot admission and job creation
  are one atomic operation (``create_job_atomically``);
* restart reconciliation (``reconcile_artifacts_for_job``) arms or cleans the
  artifacts of any job that never reached ``succeeded`` so a crashed save
  never leaves invisible orphans or dangling live references behind;
* restart recovery (``reconcile_orphaned_files``) removes content-addressed
  files no artifact record references, so a crash between the atomic file save
  and the metadata write cannot leak disk space invisibly.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import threading
import time
from typing import Any, Iterable
import uuid

from deeptutor.services.file_io import atomic_write_json
from deeptutor.services.media.config import MediaLimits
from deeptutor.services.media.models import (
    ACTIVE_JOB_STATUSES,
    TERMINAL_JOB_STATUSES,
    ArtifactReference,
    ArtifactReferenceError,
    ConfirmationRequired,
    GcResult,
    GeneratedArtifact,
    ImageGenerationJob,
    ImageJobStatus,
    JobConcurrencyError,
    JobStateError,
    MediaError,
    MediaValidationError,
    QuotaExceededError,
    QuotaInfo,
    ReferenceOwnerType,
    SavedMedia,
)
from deeptutor.services.media.persistence import MediaPersistence

logger = logging.getLogger(__name__)

#: Module-level lock so CAS semantics hold across all store instances.
_lock = threading.Lock()


def _media_root_key(root: Path) -> str:
    """Canonical identity of a media root for in-flight refcount keying.

    Two stores rooted at the same resolved directory share one refcount entry;
    stores rooted at different directories (different users, or separate media
    roots in tests) never alias each other's in-flight saves even when they
    hold identical bytes.
    """
    return str(Path(root).resolve())


#: In-process refcount of in-flight content-addressed saves, keyed by
#: ``(canonical media root, sha256)``.  Guarded by ``_lock`` and held from
#: ``save_media_tracked`` until a save is committed (``commit_saved_media``)
#: or rolled back (``rollback_save``).  It makes the dedup ``created`` decision
#: and the file-cleanup check atomic, so a failed saver can never remove an
#: original/thumbnail still being referenced by another concurrent save whose
#: metadata has not been committed yet.  Keying by the media root isolates
#: identical content saved in different roots/users: a rollback in root A can
#: never be delayed, influenced, or leaked by an in-flight save of the same
#: bytes in root B.
_save_refcounts: dict[tuple[str, str], int] = {}

_DELETE_MODE_DETACH_CURRENT = "detach_current"
_DELETE_MODE_REMOVE_EVERYWHERE = "remove_everywhere"


def default_media_root() -> Path:
    """Per-user media root under the persistent ``data/user`` volume (§12.2)."""
    from deeptutor.services.path_service import get_path_service

    return get_path_service().get_user_root() / "workspace" / "media"


class MediaStore:
    """Single entry point for durable media records and lifecycle operations."""

    def __init__(self, root: Path | None = None, limits: MediaLimits | None = None) -> None:
        self._root = Path(root) if root is not None else default_media_root()
        self._limits = limits or MediaLimits()
        self._jobs_dir = self._root / "jobs"
        self._artifacts_dir = self._root / "artifacts"
        self._references_dir = self._root / "references"
        self._persistence = MediaPersistence(self._root, self._limits)
        for directory in (self._jobs_dir, self._artifacts_dir, self._references_dir):
            directory.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    @property
    def limits(self) -> MediaLimits:
        return self._limits

    @property
    def persistence(self) -> MediaPersistence:
        return self._persistence

    # ── path / id safety ─────────────────────────────────────────────────────

    @staticmethod
    def _validate_id(record_id: str) -> None:
        if not record_id or any(char in record_id for char in ("/", "\\", "..", ":")):
            raise MediaError(f"invalid record id: {record_id!r}")

    def _record_path(self, directory: Path, record_id: str) -> Path:
        self._validate_id(record_id)
        return directory / f"{record_id}.json"

    # ── jobs ─────────────────────────────────────────────────────────────────

    def save_job(self, job: ImageGenerationJob) -> ImageGenerationJob:
        with _lock:
            job.updated_at = time.time()
            atomic_write_json(
                self._record_path(self._jobs_dir, job.id), job.model_dump(mode="json")
            )
            return job

    def create_job_atomically(self, job: ImageGenerationJob) -> ImageGenerationJob:
        """Atomically admit and persist a new job.

        Runs the same-user idempotency-key lookup, the per-user concurrency
        slot admission and the durable write under the module lock, so
        concurrent submissions with the same key/payload yield exactly one
        job, a same-key/different-payload submission conflicts, and the
        configured slot limit is never exceeded.
        """
        with _lock:
            if job.idempotency_key:
                existing = self.find_job_by_idempotency_key(job.user_id, job.idempotency_key)
                if existing is not None:
                    if existing.request_hash and existing.request_hash != job.request_hash:
                        raise JobStateError(
                            f"idempotency_key {job.idempotency_key!r} already used for a "
                            "different image request"
                        )
                    return existing
            self.check_job_slot(job.user_id)
            job.updated_at = time.time()
            atomic_write_json(
                self._record_path(self._jobs_dir, job.id), job.model_dump(mode="json")
            )
            return job

    def load_job(self, job_id: str) -> ImageGenerationJob | None:
        path = self._record_path(self._jobs_dir, job_id)
        if not path.exists():
            return None
        return ImageGenerationJob.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def list_jobs(
        self,
        *,
        user_id: str | None = None,
        status: ImageJobStatus | None = None,
    ) -> list[ImageGenerationJob]:
        jobs: list[ImageGenerationJob] = []
        for path in self._jobs_dir.glob("*.json"):
            if path.name.startswith("."):
                continue
            job = ImageGenerationJob.model_validate(json.loads(path.read_text(encoding="utf-8")))
            if user_id is not None and job.user_id != user_id:
                continue
            if status is not None and job.status != status:
                continue
            jobs.append(job)
        return sorted(jobs, key=lambda item: item.created_at)

    def list_jobs_for_recovery(self) -> list[ImageGenerationJob]:
        """Recovery-only listing that tolerates individual corrupt records.

        Restart recovery must not be blocked by one bad record: a record that
        fails to parse or validate is skipped so the remaining valid jobs and
        the orphan-file cleanup still run.  Only the record id and the
        exception *type* are logged — never the raw file content or a
        validation message that could contain secrets.

        This tolerant listing is intentionally **not** used by the normal
        paths (``list_jobs``, idempotency lookup, slot admission, quota
        enforcement), which keep failing closed on a corrupt active record
        instead of silently skipping it.
        """
        jobs: list[ImageGenerationJob] = []
        for path in self._jobs_dir.glob("*.json"):
            if path.name.startswith("."):
                continue
            try:
                job = ImageGenerationJob.model_validate(
                    json.loads(path.read_text(encoding="utf-8"))
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "recovery: skipping unreadable job record %s (%s)",
                    path.stem,
                    type(exc).__name__,
                )
                continue
            jobs.append(job)
        return sorted(jobs, key=lambda item: item.created_at)

    def find_job_by_idempotency_key(
        self, user_id: str, idempotency_key: str
    ) -> ImageGenerationJob | None:
        if not idempotency_key:
            return None
        for job in self.list_jobs(user_id=user_id):
            if job.idempotency_key == idempotency_key:
                return job
        return None

    def transition_job(
        self,
        job_id: str,
        *,
        from_status: ImageJobStatus | Iterable[ImageJobStatus],
        to_status: ImageJobStatus,
        **updates: Any,
    ) -> ImageGenerationJob:
        """Move a job between states with an optimistic status-version bump."""
        allowed = {from_status} if isinstance(from_status, ImageJobStatus) else set(from_status)
        with _lock:
            job = self.load_job(job_id)
            if job is None:
                raise MediaError(f"job not found: {job_id}")
            if job.status not in allowed:
                raise JobStateError(
                    f"job {job_id} cannot transition from {job.status.value!r} "
                    f"to {to_status.value!r}"
                )
            for key, value in updates.items():
                if not hasattr(job, key):
                    raise MediaError(f"unknown job field: {key!r}")
                setattr(job, key, value)
            job.status = to_status
            job.status_version += 1
            job.updated_at = time.time()
            if to_status in TERMINAL_JOB_STATUSES:
                job.finished_at = time.time()
            atomic_write_json(
                self._record_path(self._jobs_dir, job_id), job.model_dump(mode="json")
            )
            return job

    def update_job(
        self,
        job_id: str,
        *,
        expected_status_version: int | None = None,
        **updates: Any,
    ) -> ImageGenerationJob:
        """Non-state update (e.g. ``poll_after``) guarded by status version."""
        with _lock:
            job = self.load_job(job_id)
            if job is None:
                raise MediaError(f"job not found: {job_id}")
            if (
                expected_status_version is not None
                and job.status_version != expected_status_version
            ):
                raise JobStateError(
                    f"job {job_id} version conflict: expected {expected_status_version}, "
                    f"got {job.status_version}"
                )
            for key, value in updates.items():
                if not hasattr(job, key):
                    raise MediaError(f"unknown job field: {key!r}")
                setattr(job, key, value)
            job.updated_at = time.time()
            atomic_write_json(
                self._record_path(self._jobs_dir, job_id), job.model_dump(mode="json")
            )
            return job

    def active_job_count(self, user_id: str) -> int:
        return sum(
            1 for job in self.list_jobs(user_id=user_id) if job.status in ACTIVE_JOB_STATUSES
        )

    def check_job_slot(self, user_id: str) -> None:
        if self.active_job_count(user_id) >= self._limits.max_concurrent_jobs:
            raise JobConcurrencyError(
                f"Too many in-flight image jobs for user {user_id!r}: "
                f"limit is {self._limits.max_concurrent_jobs}."
            )

    # ── artifacts ────────────────────────────────────────────────────────────

    def save_artifact(
        self, artifact: GeneratedArtifact, *, check_quota: bool = True
    ) -> GeneratedArtifact:
        with _lock:
            if check_quota:
                self._enforce_quota(artifact.user_id, artifact.size_bytes, artifact_id=artifact.id)
            atomic_write_json(
                self._record_path(self._artifacts_dir, artifact.id),
                artifact.model_dump(mode="json"),
            )
            return artifact

    def load_artifact(self, artifact_id: str) -> GeneratedArtifact | None:
        path = self._record_path(self._artifacts_dir, artifact_id)
        if not path.exists():
            return None
        return GeneratedArtifact.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def list_artifacts(self, *, user_id: str | None = None) -> list[GeneratedArtifact]:
        artifacts: list[GeneratedArtifact] = []
        for path in self._artifacts_dir.glob("*.json"):
            if path.name.startswith("."):
                continue
            artifact = GeneratedArtifact.model_validate(
                json.loads(path.read_text(encoding="utf-8"))
            )
            if user_id is not None and artifact.user_id != user_id:
                continue
            artifacts.append(artifact)
        return artifacts

    def _write_artifact(self, artifact: GeneratedArtifact) -> None:
        atomic_write_json(
            self._record_path(self._artifacts_dir, artifact.id), artifact.model_dump(mode="json")
        )

    def _delete_artifact_record(self, artifact_id: str) -> None:
        self._record_path(self._artifacts_dir, artifact_id).unlink(missing_ok=True)

    def rollback_save_metadata(self, *, artifact_ids: list[str], reference_ids: list[str]) -> None:
        """Remove artifact/reference records written by a failed media save.

        Called by the worker when persisting media fails after some metadata
        was already committed; deletes exactly the records this save wrote so
        no live reference or invisible orphan outlives a failed job.  Physical
        (not soft) deletion is correct here: the records were never exposed.
        """
        with _lock:
            for reference_id in reference_ids:
                self._record_path(self._references_dir, reference_id).unlink(missing_ok=True)
            for artifact_id in artifact_ids:
                self._delete_artifact_record(artifact_id)

    # ── tracked content-addressed save / rollback (dedup race safety) ────────

    def save_media_tracked(self, data: bytes, *, mime_type: str) -> SavedMedia:
        """Persist media and register the in-flight save under the content lock.

        Holding the module lock across the content-addressed write makes the
        ``created`` decision (the initial ``exists()`` check) and the in-flight
        refcount increment atomic.  A concurrent rollback therefore cannot
        remove a file this save is about to reference, even before this save's
        metadata is committed — the protection spans the full
        save-metadata-rollback boundary, not just the ``exists()`` check.

        The refcount is keyed by this store's canonical media root plus the
        content SHA-256, so identical bytes saved under a different root/user
        never alias this in-flight save.
        """
        with _lock:
            saved = self._persistence.save_media(data, mime_type=mime_type)
            key = (_media_root_key(self._root), saved.sha256)
            _save_refcounts[key] = _save_refcounts.get(key, 0) + 1
            return saved

    def commit_saved_media(self, saved_media: list[SavedMedia]) -> None:
        """Success path: release in-flight content refcounts.

        The caller has already committed every artifact record, and those
        records protect the content-addressed files, so nothing is removed.
        """
        with _lock:
            for saved in saved_media:
                self._release_save_refcount(saved.sha256)

    def rollback_save(
        self,
        *,
        artifact_ids: list[str],
        reference_ids: list[str],
        saved_media: list[SavedMedia],
    ) -> None:
        """Roll back a failed media save: metadata first, then content files.

        Artifact/reference records written by this save are physically removed
        (they were never exposed).  Each content-addressed file is then deleted
        only when *no* other in-flight save (refcount) in *this* media root and
        *no* surviving artifact record references it — closing the
        content-addressed dedup save/rollback race so a failed saver never
        breaks a concurrent successful artifact's files, and a rollback in one
        root never leaks files or strips another root's in-flight protection.
        """
        with _lock:
            for reference_id in reference_ids:
                self._record_path(self._references_dir, reference_id).unlink(missing_ok=True)
            for artifact_id in artifact_ids:
                self._delete_artifact_record(artifact_id)
            for saved in saved_media:
                self._maybe_remove_media(saved)

    def _release_save_refcount(self, sha256: str) -> None:
        key = (_media_root_key(self._root), sha256)
        count = _save_refcounts.get(key, 0) - 1
        if count <= 0:
            _save_refcounts.pop(key, None)
        else:
            _save_refcounts[key] = count

    def _maybe_remove_media(self, saved: SavedMedia) -> None:
        """Release *saved*'s in-flight refcount and remove its files when safe.

        The refcount is scoped to this media root, so an in-flight save of the
        same bytes under a different root never suppresses this rollback's file
        cleanup (and never leaks this root's orphaned files either).
        """
        key = (_media_root_key(self._root), saved.sha256)
        count = _save_refcounts.get(key, 0) - 1
        if count > 0:
            _save_refcounts[key] = count
            return  # another in-flight save in this root still holds the content
        _save_refcounts.pop(key, None)
        for relative in (saved.original_path, saved.thumbnail_path):
            if not relative:
                continue
            if self._any_artifact_references_path(relative):
                continue
            try:
                path = self._persistence.resolve(relative)
                if path.exists():
                    path.unlink()
            except (MediaValidationError, OSError):
                logger.debug("rollback could not remove %s", relative, exc_info=True)

    def _any_artifact_references_path(self, relative: str) -> bool:
        """True when any surviving artifact record references *relative*."""
        return any(
            artifact.original_path == relative or artifact.thumbnail_path == relative
            for artifact in self.list_artifacts()
        )

    def arm_gc_if_unreferenced(self, artifact_id: str) -> None:
        """Arm the GC grace period for an artifact with no live reference.

        A successfully saved artifact whose job had no session never received a
        session reference; arming the grace period immediately keeps its quota
        recoverable through the normal GC lifecycle (§12.3) instead of leaking
        it as an invisible, permanently-charged record.
        """
        with _lock:
            artifact = self.load_artifact(artifact_id)
            if artifact is None or artifact.gc_candidate_since:
                return
            if self.list_references(artifact_id=artifact.id, live_only=True):
                return
            artifact.gc_candidate_since = time.time()
            self._write_artifact(artifact)

    # ── references ───────────────────────────────────────────────────────────

    def create_reference(
        self,
        *,
        artifact_id: str,
        user_id: str,
        owner_type: ReferenceOwnerType,
        owner_id: str,
    ) -> ArtifactReference:
        with _lock:
            artifact = self.load_artifact(artifact_id)
            if artifact is None:
                raise ArtifactReferenceError(f"artifact not found: {artifact_id}")
            if artifact.user_id != user_id:
                raise ArtifactReferenceError(
                    f"artifact {artifact_id} belongs to user {artifact.user_id!r}, not {user_id!r}"
                )
            existing = self.find_live_reference(
                artifact_id=artifact_id,
                user_id=user_id,
                owner_type=owner_type,
                owner_id=owner_id,
            )
            if existing is not None:
                return existing
            # Re-establishing a reference during the grace period cancels GC.
            if artifact.gc_candidate_since:
                artifact.gc_candidate_since = 0.0
                self._write_artifact(artifact)
            reference = ArtifactReference(
                id=uuid.uuid4().hex,
                artifact_id=artifact_id,
                user_id=user_id,
                owner_type=owner_type,
                owner_id=owner_id,
            )
            atomic_write_json(
                self._record_path(self._references_dir, reference.id),
                reference.model_dump(mode="json"),
            )
            return reference

    def find_live_reference(
        self,
        *,
        artifact_id: str,
        user_id: str,
        owner_type: ReferenceOwnerType,
        owner_id: str,
    ) -> ArtifactReference | None:
        for reference in self.list_references(
            artifact_id=artifact_id, user_id=user_id, live_only=True
        ):
            if reference.owner_type == owner_type and reference.owner_id == owner_id:
                return reference
        return None

    def list_references(
        self,
        *,
        artifact_id: str | None = None,
        user_id: str | None = None,
        owner_type: ReferenceOwnerType | None = None,
        owner_id: str | None = None,
        live_only: bool = False,
    ) -> list[ArtifactReference]:
        references: list[ArtifactReference] = []
        for path in self._references_dir.glob("*.json"):
            if path.name.startswith("."):
                continue
            reference = ArtifactReference.model_validate(
                json.loads(path.read_text(encoding="utf-8"))
            )
            if artifact_id is not None and reference.artifact_id != artifact_id:
                continue
            if user_id is not None and reference.user_id != user_id:
                continue
            if owner_type is not None and reference.owner_type != owner_type:
                continue
            if owner_id is not None and reference.owner_id != owner_id:
                continue
            if live_only and reference.deleted_at:
                continue
            references.append(reference)
        return references

    def _load_reference(self, reference_id: str) -> ArtifactReference | None:
        path = self._record_path(self._references_dir, reference_id)
        if not path.exists():
            return None
        return ArtifactReference.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def load_reference(self, reference_id: str) -> ArtifactReference | None:
        """Load one reference by id, or ``None`` when it does not exist.

        Public read used by the detach endpoint to bind a reference to its
        owning artifact before mutating it (§12.3): a reference may only be
        detached through the artifact it actually points to.
        """
        return self._load_reference(reference_id)

    def _write_reference(self, reference: ArtifactReference) -> None:
        atomic_write_json(
            self._record_path(self._references_dir, reference.id),
            reference.model_dump(mode="json"),
        )

    def delete_reference(
        self,
        reference_id: str,
        *,
        expected_version: int | None = None,
        user_id: str | None = None,
    ) -> ArtifactReference:
        """Soft-delete one reference; the last live reference arms the grace period.

        ``user_id``, when provided, additionally enforces that the reference
        belongs to that user (cross-user deletion is rejected).
        """
        with _lock:
            reference = self._load_reference(reference_id)
            if reference is None:
                raise ArtifactReferenceError(f"reference not found: {reference_id}")
            if user_id is not None and reference.user_id != user_id:
                raise ArtifactReferenceError(
                    f"reference {reference_id} belongs to user {reference.user_id!r}, "
                    f"not {user_id!r}"
                )
            if expected_version is not None and reference.version != expected_version:
                raise ArtifactReferenceError(
                    f"reference {reference_id} version conflict: "
                    f"expected {expected_version}, got {reference.version}"
                )
            if reference.deleted_at:
                return reference
            reference.version += 1
            reference.deleted_at = time.time()
            self._write_reference(reference)
            self._recompute_grace(reference.artifact_id)
            return reference

    def delete_references_for_owner(
        self,
        *,
        artifact_id: str,
        user_id: str,
        owner_type: ReferenceOwnerType,
        owner_id: str,
    ) -> list[ArtifactReference]:
        """Soft-delete all live references of one owner context (``detach_current``)."""
        with _lock:
            deleted: list[ArtifactReference] = []
            for reference in self.list_references(
                artifact_id=artifact_id,
                user_id=user_id,
                owner_type=owner_type,
                owner_id=owner_id,
                live_only=True,
            ):
                reference.version += 1
                reference.deleted_at = time.time()
                self._write_reference(reference)
                deleted.append(reference)
            if deleted:
                self._recompute_grace(artifact_id)
            return deleted

    def delete_artifact(
        self,
        artifact_id: str,
        *,
        mode: str,
        user_id: str,
        confirmed: bool = False,
        owner_type: ReferenceOwnerType | None = None,
        owner_id: str | None = None,
    ) -> list[ArtifactReference]:
        """Delete references on an artifact without touching live-referenced media.

        ``detach_current`` removes only the given owner context's references.
        ``remove_everywhere`` soft-deletes every live reference the user owns
        and **requires** ``confirmed=True`` — it is the delete-all path and must
        be presented with the affected reference count before confirmation.
        """
        artifact = self.load_artifact(artifact_id)
        if artifact is None:
            raise ArtifactReferenceError(f"artifact not found: {artifact_id}")
        if artifact.user_id != user_id:
            raise ArtifactReferenceError(
                f"artifact {artifact_id} belongs to user {artifact.user_id!r}, not {user_id!r}"
            )

        if mode == _DELETE_MODE_DETACH_CURRENT:
            if owner_type is None or owner_id is None:
                raise MediaError("detach_current requires owner_type and owner_id")
            return self.delete_references_for_owner(
                artifact_id=artifact_id,
                user_id=user_id,
                owner_type=owner_type,
                owner_id=owner_id,
            )

        if mode == _DELETE_MODE_REMOVE_EVERYWHERE:
            live = self.list_references(artifact_id=artifact_id, user_id=user_id, live_only=True)
            if not confirmed:
                raise ConfirmationRequired(
                    "remove_everywhere requires explicit confirmation; "
                    f"{len(live)} live reference(s) will be removed"
                )
            with _lock:
                deleted: list[ArtifactReference] = []
                for reference in self.list_references(
                    artifact_id=artifact_id, user_id=user_id, live_only=True
                ):
                    reference.version += 1
                    reference.deleted_at = time.time()
                    self._write_reference(reference)
                    deleted.append(reference)
                self._recompute_grace(artifact_id)
                return deleted

        raise MediaError(f"unknown delete mode: {mode!r}")

    def _recompute_grace(self, artifact_id: str) -> None:
        artifact = self.load_artifact(artifact_id)
        if artifact is None:
            return
        live = self.list_references(artifact_id=artifact_id, live_only=True)
        if not live and not artifact.gc_candidate_since:
            artifact.gc_candidate_since = time.time()
            self._write_artifact(artifact)
        elif live and artifact.gc_candidate_since:
            artifact.gc_candidate_since = 0.0
            self._write_artifact(artifact)

    def reconcile_artifacts_for_job(self, job: ImageGenerationJob) -> int:
        """Reconcile artifacts left behind by an incomplete (non-succeeded) job.

        A crash can land between the atomic media save and the ``succeeded``
        transition, leaving artifact records that are either unreferenced with
        ``gc_candidate_since == 0`` (invisible to GC and permanently charged
        to quota) or referenced only by the crashed save's session reference.
        This removes those dangling session references and arms the GC grace
        period so the media is reclaimed through the normal lifecycle.

        Artifacts that still carry a user-created live reference are left
        untouched — GC never deletes user-owned live data.  Returns the number
        of artifacts reconciled.
        """
        if job.status == ImageJobStatus.SUCCEEDED:
            return 0
        reconciled = 0
        with _lock:
            for artifact in self.list_artifacts(user_id=job.user_id):
                if artifact.job_id != job.id:
                    continue
                dangling = self.list_references(
                    artifact_id=artifact.id,
                    user_id=job.user_id,
                    owner_type=ReferenceOwnerType.SESSION,
                    owner_id=job.session_id,
                    live_only=True,
                )
                if dangling:
                    for reference in dangling:
                        reference.version += 1
                        reference.deleted_at = time.time()
                        self._write_reference(reference)
                    self._recompute_grace(artifact.id)
                elif artifact.gc_candidate_since == 0 and not self.list_references(
                    artifact_id=artifact.id, live_only=True
                ):
                    artifact.gc_candidate_since = time.time()
                    self._write_artifact(artifact)
                reconciled += 1
        return reconciled

    def reconcile_orphaned_files(self) -> int:
        """Remove content-addressed media files no artifact record references.

        A crash can land between the atomic file save and the artifact metadata
        write in the worker's save pipeline, leaving a file in ``originals/`` or
        ``thumbnails/`` that no :class:`GeneratedArtifact` record references.
        Such a file is invisible to GC (GC iterates records) and would leak
        disk space forever.  Recovery runs at startup with no concurrent save,
        so any unreferenced file is an orphan; content-addressed files are
        re-creatable on demand.  Stale ``tmp/`` files left by a crashed temp
        write are removed as well.

        Returns the number of files removed.
        """
        referenced: set[str] = set()
        with _lock:
            for artifact in self.list_artifacts():
                if artifact.original_path:
                    referenced.add(artifact.original_path)
                if artifact.thumbnail_path:
                    referenced.add(artifact.thumbnail_path)
            removed = 0
            for directory in ("originals", "thumbnails"):
                for path in (self._root / directory).rglob("*"):
                    if not path.is_file():
                        continue
                    relative = path.relative_to(self._root).as_posix()
                    if relative in referenced:
                        continue
                    try:
                        path.unlink(missing_ok=True)
                        removed += 1
                    except OSError:
                        logger.debug("could not remove orphaned media %s", relative, exc_info=True)
            for path in (self._root / "tmp").glob("*"):
                if not path.is_file():
                    continue
                try:
                    path.unlink(missing_ok=True)
                    removed += 1
                except OSError:
                    logger.debug("could not remove stale temp media %s", path, exc_info=True)
            return removed

    # ── quota ────────────────────────────────────────────────────────────────

    def used_bytes(self, user_id: str) -> int:
        return sum(artifact.size_bytes for artifact in self.list_artifacts(user_id=user_id))

    def candidate_artifacts(self, user_id: str) -> list[GeneratedArtifact]:
        """Artifacts with no live reference that have entered the grace period."""
        return [
            artifact
            for artifact in self.list_artifacts(user_id=user_id)
            if artifact.gc_candidate_since > 0
            and not self.list_references(artifact_id=artifact.id, live_only=True)
        ]

    def reclaimable_bytes(self, user_id: str) -> int:
        return sum(artifact.size_bytes for artifact in self.candidate_artifacts(user_id))

    def quota_info(self, user_id: str) -> QuotaInfo:
        return QuotaInfo(
            used_bytes=self.used_bytes(user_id),
            limit_bytes=self._limits.max_user_bytes,
            reclaimable_bytes=self.reclaimable_bytes(user_id),
            file_count=len(self.list_artifacts(user_id=user_id)),
        )

    def check_quota_for_bytes(self, user_id: str, additional_bytes: int) -> None:
        if additional_bytes <= 0:
            return
        used = self.used_bytes(user_id)
        if used + additional_bytes > self._limits.max_user_bytes:
            raise QuotaExceededError(
                used_bytes=used,
                limit_bytes=self._limits.max_user_bytes,
                reclaimable_bytes=self.reclaimable_bytes(user_id),
            )

    def _enforce_quota(
        self, user_id: str, additional_bytes: int, *, artifact_id: str | None = None
    ) -> None:
        """Enforce quota when (re)saving an artifact.

        An existing record's own bytes are excluded from the projection so
        metadata-only rewrites (e.g. clearing the GC flag) never self-charge.
        """
        used = self.used_bytes(user_id)
        existing = 0
        if artifact_id is not None:
            current = self.load_artifact(artifact_id)
            if current is not None:
                existing = current.size_bytes
        projected = used - existing + additional_bytes
        if projected > self._limits.max_user_bytes:
            raise QuotaExceededError(
                used_bytes=used,
                limit_bytes=self._limits.max_user_bytes,
                reclaimable_bytes=self.reclaimable_bytes(user_id),
            )

    # ── GC ───────────────────────────────────────────────────────────────────

    def run_gc(self, *, user_id: str, now: float | None = None, force: bool = False) -> GcResult:
        """Delete zero-reference artifacts that have entered the grace period.

        ``force=False`` (automatic sweep) waits for ``grace_period_seconds`` to
        elapse; ``force=True`` (explicit user GC) ends the grace period early.
        A live reference always blocks collection.  Content-addressed files
        shared with any surviving artifact record are never deleted.
        """
        now = time.time() if now is None else now
        result = GcResult()
        with _lock:
            for artifact in self.candidate_artifacts(user_id):
                result.scanned_count += 1
                expired = now - artifact.gc_candidate_since >= self._limits.grace_period_seconds
                if not expired and not force:
                    continue
                if self.list_references(artifact_id=artifact.id, live_only=True):
                    continue
                freed = self._delete_artifact_files(artifact)
                self._delete_artifact_record(artifact.id)
                result.deleted_count += 1
                result.freed_bytes += freed
        return result

    def _sha256_usage_count(self, sha256: str, exclude_id: str | None = None) -> int:
        return sum(
            1
            for artifact in self.list_artifacts()
            if artifact.sha256 == sha256 and artifact.id != exclude_id
        )

    def _delete_artifact_files(self, artifact: GeneratedArtifact) -> int:
        """Remove original + thumbnail, preserving dedup-shared content.

        Returns the *logical* quota bytes freed (``artifact.size_bytes``) so
        ``freed_bytes`` stays in the same unit as ``used_bytes`` and
        ``reclaimable_bytes``; thumbnails are deleted but not double-counted
        against the per-user quota.
        """
        shared = self._sha256_usage_count(artifact.sha256, exclude_id=artifact.id) > 0
        for relative in (artifact.original_path, artifact.thumbnail_path):
            if not relative or shared:
                continue
            try:
                path = self._persistence.resolve(relative)
                if path.exists():
                    path.unlink()
            except (MediaValidationError, OSError):
                # Malformed stored path; metadata is removed regardless.
                logger.debug("GC could not remove %s", relative, exc_info=True)
        return artifact.size_bytes


__all__ = [
    "MediaStore",
    "default_media_root",
    "_DELETE_MODE_DETACH_CURRENT",
    "_DELETE_MODE_REMOVE_EVERYWHERE",
]
