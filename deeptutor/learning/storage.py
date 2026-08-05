from __future__ import annotations

import json
from pathlib import Path
import threading
import time
from typing import Any

from deeptutor.learning.models import (
    INVALIDATION_REASON_SOURCE_VERSION_CHANGED,
    AttemptCycleType,
    AttemptStatus,
    FeynmanAttempt,
    HistoryEvent,
    KnowledgeMapVersion,
    KnowledgeStateProjection,
    KnowledgeType,
    LearningProgress,
    MasteryState,
    ModelInvocationRecord,
    ModelInvocationStatus,
    ModelInvocationUsage,
    RepetitionState,
    ReviewState,
    ReviewTask,
    RubricAssessment,
    RubricScores,
    ServerGateResult,
    SourceSnapshot,
)
from deeptutor.services.file_io import atomic_write_text as _atomic_write_text
from deeptutor.services.path_service import get_path_service

# Module-level lock so CAS semantics hold across all store instances.
_cas_lock = threading.Lock()

#: Mastery states that are still "live" — an attempt in one of these states is
#: a candidate for atomic invalidation on an incompatible source/map update.
_ACTIVE_ATTEMPT_STATUSES = frozenset(
    {
        AttemptStatus.DRAFT,
        AttemptStatus.COLLECTING,
        AttemptStatus.READY_TO_ASSESS,
        AttemptStatus.ASSESSED,
    }
)

_DEFAULT_PASS_THRESHOLD = 0.7
#: Interval used when a legacy import is scheduled for its delayed reteach.
_LEGACY_RETEACH_INTERVAL = 86400.0


class VersionConflictError(Exception):
    """A save was rejected because the caller holds a stale snapshot.

    ``LearningStore.save`` compares the caller's ``progress.version`` against
    the version persisted on disk and refuses to overwrite a newer document.
    The check runs before any file or in-memory persisted-version mutation, so
    a stale writer can never clobber append-only history or per-aggregate
    counters. Callers must reload the document and re-apply their change.
    """

    def __init__(
        self,
        *,
        book_id: str,
        expected_version: int,
        persisted_version: int,
    ) -> None:
        self.book_id = book_id
        self.expected_version = expected_version
        self.persisted_version = persisted_version
        super().__init__(
            f"stale save rejected for {book_id!r}: caller holds version "
            f"{expected_version}, persisted version is {persisted_version}; "
            "reload before saving so append-only history is never overwritten"
        )


class LearningStore:
    def __init__(self, root: Path | None = None) -> None:
        self._root = root or (get_path_service().get_workspace_dir() / "learning")
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, book_id: str) -> Path:
        if "/" in book_id or "\\" in book_id or ".." in book_id or ":" in book_id:
            raise ValueError(f"Invalid book_id: {book_id!r}")
        return self._root / f"{book_id}.json"

    def save(self, progress: LearningProgress) -> None:
        with _cas_lock:
            # Optimistic concurrency: reject a stale snapshot before mutating
            # anything. Every save bumps the document version, so a caller
            # holding an older version would otherwise overwrite append-only
            # history and per-aggregate counters persisted by a newer writer.
            persisted_version = self._persisted_version(progress.book_id)
            if progress.version != persisted_version:
                raise VersionConflictError(
                    book_id=progress.book_id,
                    expected_version=progress.version,
                    persisted_version=persisted_version,
                )
            progress.updated_at = time.time()
            progress.version += 1
            data = progress.model_dump(mode="json")
            text = json.dumps(data, ensure_ascii=False, indent=2)
            _atomic_write_text(self._path(progress.book_id), text)

    def _persisted_version(self, book_id: str) -> int:
        """Version currently persisted for ``book_id`` (0 when no file exists)."""
        path = self._path(book_id)
        if not path.exists():
            return 0
        data = json.loads(path.read_text(encoding="utf-8"))
        try:
            return int(data.get("version", 0))
        except (TypeError, ValueError):
            return 0

    def load(self, book_id: str) -> LearningProgress | None:
        path = self._path(book_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return LearningProgress.model_validate(data)

    def load_with_migration(self, book_id: str) -> LearningProgress | None:
        """Load progress, migrating legacy mastery on first read.

        Legacy knowledge points that reached the old qualitative/quantitative
        gate are imported as ``provisional_mastery`` projections and scheduled
        for a delayed reteach (§16.1). The migration is lossless and idempotent,
        and the migrated document is persisted with the same single atomic write
        as any other save.
        """
        progress = self.load(book_id)
        if progress is not None and needs_legacy_migration(progress):
            migrate_legacy_projection(progress)
            self.save(progress)
        return progress

    def delete(self, book_id: str) -> None:
        with _cas_lock:
            path = self._path(book_id)
            if path.exists():
                path.unlink()

    def exists(self, book_id: str) -> bool:
        return self._path(book_id).exists()

    def list_all(self) -> list[str]:
        """Return all book_ids that have stored progress."""
        return sorted(p.stem for p in self._root.glob("*.json") if not p.name.startswith("."))


# ── append-only history + aggregate versions ──────────────────────────────


def next_history_seq(progress: LearningProgress) -> int:
    return progress.history[-1].seq + 1 if progress.history else 1


def bump_aggregate_version(progress: LearningProgress, aggregate: str) -> int:
    """Advance one per-aggregate version counter and return the new value."""
    if not hasattr(progress.aggregate_versions, aggregate):
        raise ValueError(f"Unknown aggregate: {aggregate!r}")
    current = getattr(progress.aggregate_versions, aggregate) + 1
    setattr(progress.aggregate_versions, aggregate, current)
    return current


def append_history(
    progress: LearningProgress,
    event_type: str,
    *,
    aggregate: str = "",
    summary: str = "",
    payload: dict[str, Any] | None = None,
) -> HistoryEvent:
    """Append an audit event, bumping the matching aggregate version.

    History is append-only: callers must never reorder or replace persisted
    entries. The event's ``aggregate_version`` is the counter *after* the bump.
    """
    aggregate_version = bump_aggregate_version(progress, aggregate) if aggregate else 0
    event = HistoryEvent(
        seq=next_history_seq(progress),
        event_type=event_type,
        aggregate=aggregate,
        aggregate_version=aggregate_version,
        summary=summary,
        payload=payload or {},
    )
    progress.history.append(event)
    return event


# ── append-only model-invocation audit (§7.8, §9.4) ───────────────────────


class InvocationAlreadyFinalizedError(Exception):
    """A pending-only invocation record cannot be re-finalized.

    ``finish`` is immutable: a ``pending`` record transitions to a terminal
    state exactly once. Historical invocations can therefore never be
    overwritten or dropped by a duplicate finish.
    """

    def __init__(self, *, record_id: str, status: ModelInvocationStatus) -> None:
        self.record_id = record_id
        self.status = status
        super().__init__(
            f"model invocation {record_id!r} already finalized with status {status.value!r}"
        )


class InvalidInvocationFinishError(Exception):
    """A finish request cannot target ``status=pending``.

    ``finish`` appends a *terminal* revision (``completed``/``failed``/
    ``paused``). Requesting another ``pending`` revision is always a caller
    bug — nothing would ever become terminal and the pending record would stay
    unfinalized.
    """

    def __init__(self, *, record_id: str) -> None:
        self.record_id = record_id
        super().__init__(
            f"model invocation {record_id!r} cannot be finished with "
            f"status {ModelInvocationStatus.PENDING.value!r}; finish targets "
            "must be terminal"
        )


def find_model_invocation(
    progress: LearningProgress, record_id: str
) -> ModelInvocationRecord | None:
    """Return the *latest* revision of the invocation with ``record_id``.

    Because ``finish`` appends a terminal revision and never rewrites the
    ``pending`` revision, multiple records share an ``id``. This deterministically
    selects the newest revision (the last appended entry for that id), which is
    the current projection. ``None`` when no revision exists.
    """
    latest: ModelInvocationRecord | None = None
    for record in progress.model_invocations:
        if record.id == record_id:
            latest = record
    return latest


def latest_model_invocation(
    progress: LearningProgress, record_id: str
) -> ModelInvocationRecord | None:
    """Alias of :func:`find_model_invocation` (latest revision)."""
    return find_model_invocation(progress, record_id)


def _unknown_or(value: str | None) -> str:
    """Coerce a provider-reported identity to a stable string.

    Absent/blank values become the literal ``unknown``; the requested model is
    never copied into the reported fields (§7.6).
    """
    if value is None:
        return "unknown"
    text = str(value).strip()
    return text or "unknown"


def append_model_invocation(
    progress: LearningProgress, record: ModelInvocationRecord
) -> ModelInvocationRecord:
    """Append the ``pending`` pre-call revision of an invocation (§7.8).

    The record is persisted as ``pending`` (revision 1) so a crash after this
    point still leaves an audit trail. ``started_at`` is populated here when
    the caller did not already set it — the pre-call start moment. The list is
    append-only and the aggregate counter advances with the history event.
    """
    if record.started_at is None:
        record.started_at = time.time()
    progress.model_invocations.append(record)
    append_history(
        progress,
        "model_invocation_started",
        aggregate="model_invocation",
        summary=f"{record.purpose.value} invocation {record.id} started",
        payload={"invocation_id": record.id, "purpose": record.purpose.value},
    )
    return record


def finish_model_invocation(
    progress: LearningProgress,
    record_id: str,
    *,
    status: ModelInvocationStatus,
    reported_model: str | None = None,
    reported_version: str | None = None,
    usage: ModelInvocationUsage | None = None,
    sanitized_error: str = "",
    error_code: str = "",
    response_fingerprint: str = "",
    now: float | None = None,
) -> ModelInvocationRecord:
    """Finalize a pending invocation by *appending* a terminal revision.

    Immutable append/revision semantics (§7.8, §9.4):

    * the ``pending`` revision is preserved untouched and a new record with the
      same ``id`` and ``revision + 1`` is appended with the terminal state, so
      historical revisions stay serialized and can never be overwritten/dropped;
    * duplicate finalization (the latest revision is already terminal) raises
      :class:`InvocationAlreadyFinalizedError`;
    * a finish targeting ``status=pending`` raises
      :class:`InvalidInvocationFinishError`;
    * ``finished_at`` is clamped to never precede ``started_at`` (monotonic).

    Provider-reported model/version defaults to the literal ``unknown`` and is
    never filled from the requested model (§7.6).
    """
    if status == ModelInvocationStatus.PENDING:
        raise InvalidInvocationFinishError(record_id=record_id)
    pending = find_model_invocation(progress, record_id)
    if pending is None:
        raise KeyError(f"model invocation {record_id!r} not found")
    if pending.status != ModelInvocationStatus.PENDING:
        raise InvocationAlreadyFinalizedError(record_id=record_id, status=pending.status)

    moment = now if now is not None else time.time()
    started_at = pending.started_at if pending.started_at is not None else moment
    finished_at = moment if moment >= started_at else started_at
    terminal = pending.model_copy(
        update={
            "revision": pending.revision + 1,
            "provider_reported_model": _unknown_or(reported_model),
            "provider_model_version": _unknown_or(reported_version),
            "usage": usage or ModelInvocationUsage(),
            "sanitized_error": sanitized_error,
            "error_code": error_code,
            "response_fingerprint": response_fingerprint,
            "status": status,
            "finished_at": finished_at,
        }
    )
    progress.model_invocations.append(terminal)
    append_history(
        progress,
        "model_invocation_finished",
        aggregate="model_invocation",
        summary=f"{pending.purpose.value} invocation {record_id} {status.value}",
        payload={"invocation_id": record_id, "status": status.value},
    )
    return terminal


# ── legacy migration (§16.1) ──────────────────────────────────────────────


def _pass_threshold_for_kp(progress: LearningProgress, kp_id: str) -> float:
    for module in progress.modules:
        for kp in module.knowledge_points:
            if kp.id == kp_id:
                return module.pass_threshold
    return _DEFAULT_PASS_THRESHOLD


def _legacy_eligible_knowledge_point_ids(progress: LearningProgress) -> list[str]:
    """Knowledge points with an old mastery indicator not yet imported."""
    eligible: list[str] = []
    seen = set(progress.projections) | {a.knowledge_point_id for a in progress.attempts}
    for kp_id, qualified in progress.qualitative_mastery.items():
        if qualified and kp_id not in seen:
            eligible.append(kp_id)
            seen.add(kp_id)
    for kp_id, level in progress.mastery_levels.items():
        if kp_id in seen:
            continue
        if level >= _pass_threshold_for_kp(progress, kp_id):
            eligible.append(kp_id)
            seen.add(kp_id)
    return eligible


def needs_legacy_migration(progress: LearningProgress) -> bool:
    return bool(_legacy_eligible_knowledge_point_ids(progress))


def next_assessment_sequence(progress: LearningProgress, kp_id: str) -> int:
    """Monotonic per-knowledge-point assessment sequence (next value)."""
    attempt_ids = {a.id for a in progress.attempts if a.knowledge_point_id == kp_id}
    current = max(
        (a.assessment_sequence for a in progress.rubric_assessments if a.attempt_id in attempt_ids),
        default=0,
    )
    return current + 1


def migrate_legacy_projection(progress: LearningProgress, *, now: float | None = None) -> list[str]:
    """Import legacy mastery as provisional projections with delayed reteach.

    Lossless: existing fields (``quiz_attempts``, ``error_records``,
    ``feynman_explanations``, review state, ...) are left untouched. For every
    knowledge point that reached the old qualitative or quantitative gate a
    ``legacy_import`` attempt/assessment is appended, the projection is set to
    ``provisional_mastery``, and a delayed-reteach review task is scheduled.
    Returns the imported knowledge point ids. Idempotent: already-imported KPs
    are skipped.
    """
    now = now if now is not None else time.time()
    imported: list[str] = []
    for kp_id in _legacy_eligible_knowledge_point_ids(progress):
        attempt_id = f"legacy-import-{kp_id}"
        assessment_id = f"legacy-import-assessment-{kp_id}"
        next_review_at = now + _LEGACY_RETEACH_INTERVAL
        kp_type = progress.knowledge_types.get(kp_id, KnowledgeType.MEMORY)
        level = progress.mastery_levels.get(kp_id, 0.0)

        progress.attempts.append(
            FeynmanAttempt(
                id=attempt_id,
                knowledge_point_id=kp_id,
                cycle_type=AttemptCycleType.LEGACY_IMPORT,
                status=AttemptStatus.ASSESSED,
                closed_at=now,
            )
        )
        bump_aggregate_version(progress, "attempt")

        progress.rubric_assessments.append(
            RubricAssessment(
                id=assessment_id,
                attempt_id=attempt_id,
                revision=1,
                assessment_sequence=next_assessment_sequence(progress, kp_id),
                rubric=RubricScores(
                    correctness=level,
                    completeness=level,
                    causal_clarity=level,
                    transfer=level,
                ),
                server_gate_result=ServerGateResult(passed=True, reasons=["legacy import"]),
            )
        )
        bump_aggregate_version(progress, "assessment")

        progress.projections[kp_id] = KnowledgeStateProjection(
            knowledge_point_id=kp_id,
            mastery_state=MasteryState.PROVISIONAL_MASTERY,
            review_state=ReviewState.SCHEDULED,
            active_attempt_id=attempt_id,
            latest_assessment_id=assessment_id,
            provisional_since=now,
            next_review_at=next_review_at,
            updated_at=now,
        )
        progress.review_queue.append(
            ReviewTask(
                id=f"legacy-reteach-{kp_id}",
                knowledge_point_id=kp_id,
                knowledge_type=kp_type,
                due_at=next_review_at,
                priority=1,
                state=RepetitionState(
                    interval_index=0,
                    consecutive_correct=0,
                    consecutive_wrong=0,
                    next_review_at=next_review_at,
                ),
            )
        )
        imported.append(kp_id)

    if imported:
        append_history(
            progress,
            "legacy_import",
            summary=f"Imported {len(imported)} knowledge point(s) as provisional "
            "legacy projections",
            payload={"knowledge_point_ids": imported},
        )
    return imported


# ── atomic source/map updates and invalidation (§7.7) ─────────────────────


def invalidate_attempts(
    progress: LearningProgress,
    *,
    attempt_ids: list[str],
    reason: str,
    summary: str = "",
) -> list[str]:
    """Atomically invalidate the given live attempts and their evidence.

    The invalidation is atomic with the caller's subsequent single ``save()``:
    attempt status and read-only evidence change together in memory and are
    persisted in one atomic file write. Old evidence stays readable but can no
    longer be recorded against, finalised, or resumed.
    """
    invalidated: list[str] = []
    for attempt in progress.attempts:
        if attempt.id in attempt_ids and attempt.status in _ACTIVE_ATTEMPT_STATUSES:
            attempt.status = AttemptStatus.INVALIDATED
            attempt.invalidated_reason = reason
            attempt.updated_at = time.time()
            attempt.closed_at = attempt.closed_at or time.time()
            invalidated.append(attempt.id)
    if invalidated:
        append_history(
            progress,
            "attempt_invalidated",
            aggregate="attempt",
            summary=summary or f"invalidated {len(invalidated)} attempt(s)",
            payload={"attempt_ids": invalidated, "reason": reason},
        )
    return invalidated


def register_source_snapshot(progress: LearningProgress, snapshot: SourceSnapshot) -> list[str]:
    """Add or replace a source snapshot.

    Replacing an existing snapshot whose ``content_hash`` changed is an
    incompatible update: every live attempt that references the snapshot is
    atomically invalidated with ``invalidated_reason=source_version_changed``.
    Returns the ids of invalidated attempts.
    """
    existing = next((s for s in progress.source_snapshots if s.id == snapshot.id), None)
    changed = existing is not None and existing.content_hash != snapshot.content_hash
    if existing is not None:
        progress.source_snapshots = [s for s in progress.source_snapshots if s.id != snapshot.id]
    progress.source_snapshots.append(snapshot)

    if not changed:
        append_history(
            progress,
            "source_snapshot_registered",
            summary=f"snapshot {snapshot.id} registered",
            payload={"snapshot_id": snapshot.id, "content_hash": snapshot.content_hash},
        )
        return []

    invalidated = invalidate_attempts(
        progress,
        attempt_ids=[
            a.id
            for a in progress.attempts
            if a.status in _ACTIVE_ATTEMPT_STATUSES and snapshot.id in a.source_snapshot_ids
        ],
        reason=INVALIDATION_REASON_SOURCE_VERSION_CHANGED,
        summary=f"source snapshot {snapshot.id} content changed",
    )
    append_history(
        progress,
        "source_snapshot_replaced",
        summary=f"snapshot {snapshot.id} replaced",
        payload={
            "snapshot_id": snapshot.id,
            "old_content_hash": existing.content_hash,
            "new_content_hash": snapshot.content_hash,
            "invalidated_attempt_ids": invalidated,
        },
    )
    return invalidated


def apply_map_version(progress: LearningProgress, version: KnowledgeMapVersion) -> list[str]:
    """Register a confirmed map version and atomically invalidate stale attempts.

    Live attempts bound to an older map version — or referencing source
    snapshots the new version no longer includes — are invalidated with
    ``invalidated_reason=source_version_changed`` in the same atomic update.
    Returns the ids of invalidated attempts.
    """
    progress.map_versions.append(version)
    current_snapshot_ids = set(version.source_snapshot_ids)
    invalidated = invalidate_attempts(
        progress,
        attempt_ids=[
            a.id
            for a in progress.attempts
            if a.status in _ACTIVE_ATTEMPT_STATUSES
            and (
                (a.map_version_id and a.map_version_id != version.id)
                or (
                    a.source_snapshot_ids
                    and not current_snapshot_ids.issuperset(a.source_snapshot_ids)
                )
            )
            # An attempt with no frozen map/source basis would otherwise
            # silently adopt the new version's sources through the grading
            # fallback. Invalidate it so it can never inherit a different map.
            or (not a.map_version_id and not a.source_snapshot_ids)
        ],
        reason=INVALIDATION_REASON_SOURCE_VERSION_CHANGED,
        summary=f"map version {version.version} ({version.id}) confirmed",
    )
    append_history(
        progress,
        "map_version_confirmed",
        aggregate="map",
        summary=f"map {version.path_id} v{version.version}",
        payload={
            "version_id": version.id,
            "path_id": version.path_id,
            "version": version.version,
            "invalidated_attempt_ids": invalidated,
        },
    )
    return invalidated


def is_evidence_read_only(progress: LearningProgress, evidence_id: str) -> bool:
    """Evidence belonging to a closed or invalidated attempt is read-only."""
    evidence = next((e for e in progress.evidence_items if e.id == evidence_id), None)
    if evidence is None:
        return False
    attempt = next((a for a in progress.attempts if a.id == evidence.attempt_id), None)
    if attempt is None:
        return False
    return attempt.status in (AttemptStatus.CLOSED, AttemptStatus.INVALIDATED)


__all__ = [
    "VersionConflictError",
    "InvocationAlreadyFinalizedError",
    "InvalidInvocationFinishError",
    "LearningStore",
    "next_history_seq",
    "bump_aggregate_version",
    "append_history",
    "find_model_invocation",
    "latest_model_invocation",
    "append_model_invocation",
    "finish_model_invocation",
    "needs_legacy_migration",
    "next_assessment_sequence",
    "migrate_legacy_projection",
    "invalidate_attempts",
    "register_source_snapshot",
    "apply_map_version",
    "is_evidence_read_only",
]
