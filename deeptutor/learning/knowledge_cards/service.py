"""Knowledge-card draft service (KB-02).

Owns the durable behavior for knowledge-card drafts: server-derived eligibility
and atomic draft-shell creation, versioned edits with the user-edit lock,
append-only explicit retries, discard, and stale-evidence reconciliation. Every
mutation runs under the :class:`LearningStore` CAS so concurrent create/edit/
retry/worker operations can never duplicate cards or attempts, drop append-only
history, or overwrite user edits.

This service never calls an LLM and never reaches the network. Generation is
delegated to the offline :class:`KnowledgeCardGenerationWorker`.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any
from uuid import uuid4

from deeptutor.learning.knowledge_cards.blobs import KnowledgeCardBlobStore
from deeptutor.learning.knowledge_cards.config import KnowledgeCardLimits
from deeptutor.learning.knowledge_cards.eligibility import (
    frozen_evaluator_snapshot_for,
    latest_valid_stable_assessment,
    max_retracted_sequence,
    occupying_card,
    reconcile_stale_evidence,
    stable_assessment_is_current,
)
from deeptutor.learning.knowledge_cards.errors import (
    GenerationLockedByUserEditError,
    KnowledgeCardEligibilityError,
    KnowledgeCardError,
    KnowledgeCardIdempotencyConflictError,
    KnowledgeCardInputValidationError,
    KnowledgeCardOwnershipError,
    KnowledgeCardStaleVersionError,
    KnowledgeCardStateError,
)
from deeptutor.learning.knowledge_cards.store import (
    append_generation_attempt,
    attempts_for_card,
    content_hash,
    frozen_input_fingerprint,
    has_active_attempt,
    latest_attempt_for_card,
    next_generation_attempt_no,
    require_card,
)
from deeptutor.learning.models import (
    DraftGenerationStatus,
    GenerationAttemptStatus,
    KnowledgeCardGenerationAttempt,
    KnowledgeCardRecord,
    KnowledgeCardStatus,
    LearningProgress,
)
from deeptutor.learning.storage import LearningStore, VersionConflictError, append_history
from deeptutor.services.media.models import ReferenceOwnerType

#: History event types used for idempotency replay (same request_id + same full
#: payload replays the stored result; different payload conflicts, §8.3).
_EVENT_CARD_EDIT = "knowledge_card_edited"
_EVENT_CARD_DISCARD = "knowledge_card_discarded"
_EVENT_CARD_RETRY = "knowledge_card_generation_retried"
_EVENT_CARD_CREATED = "knowledge_card_created"


def _request_fingerprint(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _prior_request(
    progress: LearningProgress, event_type: str, card_id: str, request_id: str
) -> dict[str, Any] | None:
    if not request_id:
        return None
    for event in progress.history:
        if (
            event.event_type == event_type
            and event.payload.get("card_id") == card_id
            and event.payload.get("request_id") == request_id
        ):
            return event.payload
    return None


def _replay_or_conflict(
    progress: LearningProgress,
    event_type: str,
    card_id: str,
    request_id: str,
    fingerprint: str,
) -> dict[str, Any] | None:
    """Return the stored result to replay, or raise on a payload conflict.

    Idempotency contract (§8.3): same ``request_id`` + same full payload replays
    the committed result; same key with a different payload is a stable conflict.
    """
    prior = _prior_request(progress, event_type, card_id, request_id)
    if prior is None:
        return None
    stored = prior.get("request_fingerprint")
    if stored == fingerprint:
        result = prior.get("result")
        if isinstance(result, dict):
            return {**result, "replayed": True}
        raise KnowledgeCardError(
            f"{event_type} replay missing stored result for {card_id!r}/{request_id!r}"
        )
    raise KnowledgeCardIdempotencyConflictError(
        f"request_id {request_id!r} reused with a different payload on card {card_id!r}"
    )


def _validate_content_bound(value: str | None, *, max_chars: int, field: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise KnowledgeCardInputValidationError(f"{field} must be a string")
    if len(value) > max_chars:
        raise KnowledgeCardInputValidationError(f"{field} exceeds {max_chars} characters")
    return value


def _require_ownership(card: KnowledgeCardRecord, user_id: str) -> None:
    if not user_id:
        raise KnowledgeCardOwnershipError("actor user id is required")
    if card.user_id and card.user_id != user_id:
        raise KnowledgeCardOwnershipError(
            f"card {card.id!r} belongs to user {card.user_id!r}, not {user_id!r}"
        )


class KnowledgeCardDraftService:
    """Durable create/ensure, edit, retry, discard and stale reconcile."""

    def __init__(
        self,
        store: LearningStore | None = None,
        *,
        media_store: Any = None,
        blob_store: KnowledgeCardBlobStore | None = None,
        now: Any = None,
        limits: KnowledgeCardLimits | None = None,
    ) -> None:
        self._store = store or LearningStore()
        self._media_store = media_store
        self._blob_store = blob_store or KnowledgeCardBlobStore()
        self._now = now or time.time
        self._limits = limits or KnowledgeCardLimits()

    @property
    def store(self) -> LearningStore:
        return self._store

    @property
    def media_store(self) -> Any:
        return self._media_store

    @property
    def blob_store(self) -> KnowledgeCardBlobStore:
        return self._blob_store

    def load(self, path_id: str) -> LearningProgress | None:
        return self._store.load(path_id)

    def save(self, progress: LearningProgress) -> None:
        """Persist under the store CAS; a stale write is a recoverable error."""
        try:
            self._store.save(progress)
        except VersionConflictError as exc:
            raise KnowledgeCardStaleVersionError(
                f"stale save rejected for {exc.book_id!r}: caller holds "
                f"{exc.expected_version}, persisted {exc.persisted_version}; "
                "reload before saving"
            ) from exc

    def _persist_reconcile_then_raise_eligibility(
        self,
        progress: LearningProgress,
        stale_ids: list[str],
        message: str,
        *,
        commit: bool = True,
    ) -> None:
        """Persist outstanding reconcile transitions, then fail closed.

        ``ensure_draft`` reconciles stale evidence before deriving eligibility;
        when eligibility then fails, every occupying card that reconcile staled
        must already be durably persisted through the CAS/version contract or
        it would remain editable forever (§6.6, §15). With ``commit=False`` the
        caller owns the single CAS save and the reconcile transitions ride
        along with the caller's save.
        """
        if stale_ids and commit:
            self.save(progress)
        raise KnowledgeCardEligibilityError(message)

    # ── create / ensure (§6.6, §8.5, requirement 2) ─────────────────────────

    def ensure_draft(
        self,
        progress: LearningProgress,
        *,
        user_id: str,
        path_id: str,
        knowledge_point_id: str,
        now: float | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Server-derived idempotent draft creation/resume.

        Accepts user/path/knowledge-point context — never an arbitrary
        assessment id. Derives the latest valid stable assessment from the
        projection, and in one CAS save creates an empty ``draft`` shell plus its
        first ``queued`` generation attempt when none occupies the slot.

        ``commit=False`` performs the same durable mutation on ``progress`` but
        defers the final save to the caller — used by the automatic §6.6
        transition so the card shell + queued generation attempt land in the
        same CAS save as the finalize that produced ``stable_mastery``.
        """
        moment = now if now is not None else self._now()
        if not user_id:
            raise KnowledgeCardOwnershipError("actor user id is required")
        if not path_id or path_id != progress.book_id:
            raise KnowledgeCardInputValidationError(
                f"path_id {path_id!r} does not match the progress document "
                f"{progress.book_id!r}; cross-path creation fails closed"
            )

        # Enforce ownership of an existing occupying card before any mutation so
        # a cross-user caller can never observe another user's draft/attempt and
        # can never use this path to durably alter unrelated state (§6.6, §14).
        occupying = occupying_card(progress, knowledge_point_id)
        if occupying is not None:
            _require_ownership(occupying, user_id)

        stale_ids = reconcile_stale_evidence(progress, now=moment)

        card = occupying_card(progress, knowledge_point_id)
        if card is not None:
            if card.status in (
                KnowledgeCardStatus.PUBLISHED,
                KnowledgeCardStatus.RETRACTING,
                KnowledgeCardStatus.RETRACT_RECONCILE_REQUIRED,
            ):
                raise KnowledgeCardStateError(
                    f"knowledge point {knowledge_point_id!r} is occupied by card "
                    f"{card.id!r} ({card.status.value}); retract or reconcile it "
                    "before creating a new draft"
                )
            if card.status == KnowledgeCardStatus.PUBLISHING:
                raise KnowledgeCardStateError(
                    f"card {card.id!r} is publishing; cannot create a new draft"
                )
            # DRAFT / PUBLISH_FAILED / RECONCILE_REQUIRED are resumed as-is.
            if stale_ids and commit:
                # Persist stale-evidence transitions the reconcile made so an
                # otherwise idempotent reuse still durably stales unrelated
                # cards (§6.6, §15). The resumed card itself is not re-saved.
                self.save(progress)
            attempt = latest_attempt_for_card(progress, card.id)
            return {
                "card": card,
                "attempt": attempt,
                "created": False,
            }

        current = latest_valid_stable_assessment(progress, knowledge_point_id)
        if current is None:
            self._persist_reconcile_then_raise_eligibility(
                progress,
                stale_ids,
                f"knowledge point {knowledge_point_id!r} has no latest valid "
                "stable assessment; provisional/needs-revision or missing "
                "evaluator snapshot fail closed",
                commit=commit,
            )
        stable_attempt, assessment = current
        sequence = assessment.assessment_sequence
        if sequence <= max_retracted_sequence(progress, knowledge_point_id):
            self._persist_reconcile_then_raise_eligibility(
                progress,
                stale_ids,
                f"stable assessment sequence {sequence} is not strictly greater "
                "than the last retracted card sequence; a newer stable "
                "assessment is required",
                commit=commit,
            )

        snapshot = frozen_evaluator_snapshot_for(stable_attempt, assessment)
        if snapshot is None:
            self._persist_reconcile_then_raise_eligibility(
                progress,
                stale_ids,
                "stable assessment has no nonempty frozen evaluator snapshot",
                commit=commit,
            )
        source_ids, evidence_ids = self._freeze_card_references(
            progress, stable_attempt, assessment
        )

        card = KnowledgeCardRecord(
            id=uuid4().hex,
            user_id=user_id,
            path_id=path_id,
            knowledge_point_id=knowledge_point_id,
            stable_attempt_id=stable_attempt.id,
            stable_assessment_id=assessment.id,
            stable_assessment_sequence=sequence,
            status=KnowledgeCardStatus.DRAFT,
            revision=1,
            version=0,
            generation_locked_by_user_edit=False,
            source_snapshot_ids=source_ids,
            evidence_ids=evidence_ids,
            draft_generation_status=DraftGenerationStatus.QUEUED,
            created_at=moment,
            updated_at=moment,
        )
        attempt = KnowledgeCardGenerationAttempt(
            id=uuid4().hex,
            card_id=card.id,
            input_card_revision=card.revision,
            stable_assessment_id=assessment.id,
            generation_attempt_no=1,
            frozen_model_snapshot=snapshot.model_copy(),
            input_hash=frozen_input_fingerprint(progress, card, assessment),
            status=GenerationAttemptStatus.QUEUED,
            created_at=moment,
        )
        progress.knowledge_cards.append(card)
        append_generation_attempt(progress, attempt)
        append_history(
            progress,
            _EVENT_CARD_CREATED,
            aggregate="",
            summary=f"knowledge card draft {card.id} created",
            payload={
                "card_id": card.id,
                "knowledge_point_id": knowledge_point_id,
                "stable_assessment_id": assessment.id,
                "stable_assessment_sequence": sequence,
                "generation_attempt_id": attempt.id,
                "user_id": user_id,
                "path_id": path_id,
            },
        )
        if commit:
            self.save(progress)
        return {
            "card": card,
            "attempt": attempt,
            "created": True,
        }

    def _freeze_card_references(
        self,
        progress: LearningProgress,
        stable_attempt: Any,
        assessment: Any,
    ) -> tuple[list[str], list[str]]:
        """Validate and freeze the assessment-bound source/evidence references.

        Every source snapshot must be frozen on the attempt and materialized;
        every evidence id must exist and belong to the assessment's attempt.
        Cross-path/arbitrary ids fail closed — a client can never inject them.
        """
        frozen = set(stable_attempt.source_snapshot_ids)
        by_id = {snapshot.id: snapshot for snapshot in progress.source_snapshots}
        source_ids: list[str] = []
        for citation in assessment.source_citations:
            sid = citation.source_snapshot_id
            if sid not in source_ids:
                source_ids.append(sid)
        for sid in source_ids:
            if sid not in frozen:
                raise KnowledgeCardInputValidationError(
                    f"source snapshot {sid!r} cited by assessment {assessment.id!r} "
                    "is not frozen on the attempt"
                )
            if sid not in by_id:
                raise KnowledgeCardInputValidationError(
                    f"source snapshot {sid!r} is not a materialized snapshot"
                )
        evidence_by_id = {item.id: item for item in progress.evidence_items}
        for eid in assessment.evidence_ids:
            item = evidence_by_id.get(eid)
            if item is None:
                raise KnowledgeCardInputValidationError(
                    f"evidence {eid!r} referenced by assessment {assessment.id!r} does not exist"
                )
            if item.attempt_id != assessment.attempt_id:
                raise KnowledgeCardInputValidationError(
                    f"evidence {eid!r} belongs to attempt {item.attempt_id!r}, "
                    f"not {assessment.attempt_id!r}"
                )
        return source_ids, list(assessment.evidence_ids)

    # ── versioned edit (§7.9, requirement 6) ────────────────────────────────

    def edit_draft(
        self,
        progress: LearningProgress,
        *,
        card_id: str,
        user_id: str,
        request_id: str,
        expected_card_revision: int,
        title: str | None = None,
        body: str | None = None,
        attach_artifact_ids: list[str] | None = None,
        detach_artifact_ids: list[str] | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        """Versioned draft edit with user-edit lock and artifact references.

        The first user change to title/body sets ``generation_locked_by_user_edit``
        so a later model retry/apply can never overwrite it. Attach/detach accept
        only persistent same-user artifacts, create/remove the ``KNOWLEDGE_CARD``
        media reference before/after committing the card ids, and roll back on
        partial failure. Any artifact change bumps the card revision so a
        concurrent late model result loses its card-revision guard.
        """
        moment = now if now is not None else self._now()
        card = require_card(progress, card_id)
        _require_ownership(card, user_id)
        attach = list(attach_artifact_ids or [])
        detach = list(detach_artifact_ids or [])

        new_title = _validate_content_bound(
            title, max_chars=self._limits.max_title_chars, field="title"
        )
        new_body = _validate_content_bound(
            body, max_chars=self._limits.max_body_chars, field="body"
        )
        fingerprint = _request_fingerprint(
            {
                "card_id": card_id,
                "request_id": request_id,
                "expected_card_revision": expected_card_revision,
                "title": new_title if title is not None else None,
                "body": new_body if body is not None else None,
                "attach_artifact_ids": sorted(attach),
                "detach_artifact_ids": sorted(detach),
            }
        )
        prior = _replay_or_conflict(progress, _EVENT_CARD_EDIT, card_id, request_id, fingerprint)
        if prior is not None:
            return prior

        if expected_card_revision != card.revision:
            raise KnowledgeCardStaleVersionError(
                f"card {card_id!r} revision conflict: expected "
                f"{expected_card_revision}, current {card.revision}"
            )
        if card.status != KnowledgeCardStatus.DRAFT:
            raise KnowledgeCardStateError(
                f"card {card_id!r} is {card.status.value}; only drafts are editable"
            )

        # ── artifact changes (validate + create refs before committing ids) ──
        created_references: list[Any] = []
        deleted_references: list[Any] = []
        try:
            new_artifact_ids = self._apply_artifact_changes(
                progress,
                card=card,
                user_id=user_id,
                attach_ids=attach,
                detach_ids=detach,
                created_references=created_references,
                deleted_references=deleted_references,
                now=moment,
            )
        except BaseException:
            self._compensate_references(
                created_references,
                deleted_references,
                user_id=user_id,
                card_id=card.id,
            )
            raise

        content_changed = False
        if title is not None and new_title != card.title:
            card.title = new_title
            content_changed = True
        if body is not None and new_body != card.body:
            card.body = new_body
            content_changed = True

        artifacts_changed = set(new_artifact_ids) != set(card.artifact_ids)
        if content_changed or artifacts_changed:
            if content_changed:
                card.generation_locked_by_user_edit = True
                card.content_hash = content_hash(card.title, card.body)
            card.artifact_ids = new_artifact_ids
            card.revision += 1
            card.version += 1
            card.updated_at = moment

        result = {
            "card": card,
            "revision": card.revision,
            "version": card.version,
            "generation_locked_by_user_edit": card.generation_locked_by_user_edit,
            "content_changed": content_changed,
            "artifacts_changed": artifacts_changed,
        }
        append_history(
            progress,
            _EVENT_CARD_EDIT,
            aggregate="",
            summary=f"card {card_id} edited",
            payload={
                "card_id": card_id,
                "request_id": request_id,
                "request_fingerprint": fingerprint,
                "result": result,
                "title": new_title if title is not None else None,
                "body": new_body if body is not None else None,
                "attach_artifact_ids": sorted(attach),
                "detach_artifact_ids": sorted(detach),
            },
        )
        try:
            self.save(progress)
        except BaseException:
            # The artifact-reference mutation and the card metadata are one
            # compensated operation: restore the pre-edit reference set so the
            # MediaStore never diverges from the card the failed save persisted.
            self._compensate_references(
                created_references,
                deleted_references,
                user_id=user_id,
                card_id=card.id,
            )
            raise
        return result

    def _apply_artifact_changes(
        self,
        progress: LearningProgress,
        *,
        card: KnowledgeCardRecord,
        user_id: str,
        attach_ids: list[str],
        detach_ids: list[str],
        created_references: list[Any],
        deleted_references: list[Any],
        now: float,
    ) -> list[str]:
        """Attach/detach artifact ids; returns the new card artifact id list.

        Attach requires a persistent same-user artifact and creates the
        ``KNOWLEDGE_CARD`` media reference *before* the id lands on the card;
        detach removes only this card's reference. On any failure the caller
        compensates every reference created here and re-establishes every
        reference this call soft-deleted.
        """
        if (attach_ids or detach_ids) and self._media_store is None:
            raise KnowledgeCardStateError(
                "artifact attach/detach requires a media store; none is configured"
            )
        overlap = set(attach_ids) & set(detach_ids)
        if overlap:
            raise KnowledgeCardInputValidationError(
                f"artifact ids cannot be both attached and detached: {sorted(overlap)}"
            )
        if len(attach_ids) > self._limits.max_artifact_attachments:
            raise KnowledgeCardInputValidationError(
                f"too many artifact attachments: {len(attach_ids)} exceeds "
                f"{self._limits.max_artifact_attachments}"
            )
        current = set(card.artifact_ids)
        for artifact_id in attach_ids:
            if artifact_id in current:
                continue
            artifact = self._media_store.load_artifact(artifact_id)
            if artifact is None:
                raise KnowledgeCardInputValidationError(
                    f"artifact {artifact_id!r} is not a persistent artifact"
                )
            if artifact.user_id != user_id:
                raise KnowledgeCardInputValidationError(
                    f"artifact {artifact_id!r} belongs to user "
                    f"{artifact.user_id!r}, not {user_id!r}"
                )
            reference = self._media_store.create_reference(
                artifact_id=artifact_id,
                user_id=user_id,
                owner_type=ReferenceOwnerType.KNOWLEDGE_CARD,
                owner_id=card.id,
            )
            created_references.append(reference)
            current.add(artifact_id)
        for artifact_id in detach_ids:
            if artifact_id not in current:
                continue
            deleted = self._media_store.delete_references_for_owner(
                artifact_id=artifact_id,
                user_id=user_id,
                owner_type=ReferenceOwnerType.KNOWLEDGE_CARD,
                owner_id=card.id,
            )
            deleted_references.extend(deleted)
            current.discard(artifact_id)
        return sorted(current)

    def _compensate_references(
        self,
        created_references: list[Any],
        deleted_references: list[Any],
        *,
        user_id: str,
        card_id: str,
    ) -> None:
        """Restore the pre-mutation reference set after a failed operation.

        Re-creates every ``KNOWLEDGE_CARD`` reference this operation soft-deleted
        for *card_id* and soft-deletes every reference this operation created, so
        the MediaStore never diverges from the card metadata a failed CAS save
        left persisted. Only this card's own owner references are touched —
        references owned by another context are never deleted or recreated.
        Compensation is best-effort but deterministic under normal MediaStore
        operation; the caller re-raises the original failure.
        """
        if self._media_store is None:
            return
        for reference in deleted_references:
            try:
                self._media_store.create_reference(
                    artifact_id=reference.artifact_id,
                    user_id=user_id,
                    owner_type=ReferenceOwnerType.KNOWLEDGE_CARD,
                    owner_id=card_id,
                )
            except Exception:  # noqa: BLE001 - best-effort compensation
                continue
        for reference in created_references:
            try:
                self._media_store.delete_reference(
                    reference.id,
                    expected_version=reference.version,
                    user_id=user_id,
                )
            except Exception:  # noqa: BLE001 - best-effort compensation
                continue

    # ── explicit retry (§7.9.1, §8.5, requirement 8) ────────────────────────

    def retry_generation(
        self,
        progress: LearningProgress,
        *,
        card_id: str,
        user_id: str,
        request_id: str,
        expected_card_revision: int,
        latest_generation_attempt_id: str,
        now: float | None = None,
    ) -> dict[str, Any]:
        """Create a new append-only generation attempt (explicit retry).

        Rejected after a user title/body lock, on a stale/discarded/noneditable
        card, when another active attempt exists, or when the card no longer
        holds current stable eligibility. The new attempt reuses the exact frozen
        model snapshot and input basis and links ``retry_of_generation_attempt_id``.
        """
        moment = now if now is not None else self._now()
        card = require_card(progress, card_id)
        _require_ownership(card, user_id)
        fingerprint = _request_fingerprint(
            {
                "card_id": card_id,
                "request_id": request_id,
                "expected_card_revision": expected_card_revision,
                "latest_generation_attempt_id": latest_generation_attempt_id,
            }
        )
        prior = _replay_or_conflict(progress, _EVENT_CARD_RETRY, card_id, request_id, fingerprint)
        if prior is not None:
            return prior

        if expected_card_revision != card.revision:
            raise KnowledgeCardStaleVersionError(
                f"card {card_id!r} revision conflict: expected "
                f"{expected_card_revision}, current {card.revision}"
            )
        if card.status != KnowledgeCardStatus.DRAFT:
            raise KnowledgeCardStateError(
                f"card {card_id!r} is {card.status.value}; retry requires a current editable draft"
            )
        if card.generation_locked_by_user_edit:
            raise GenerationLockedByUserEditError(
                f"card {card_id!r} is locked by a user edit; model retry would "
                "overwrite confirmed content"
            )
        if card.latest_generation_attempt_id != latest_generation_attempt_id:
            raise KnowledgeCardStaleVersionError(
                f"card {card_id!r} latest generation attempt is "
                f"{card.latest_generation_attempt_id!r}, not "
                f"{latest_generation_attempt_id!r}"
            )
        if has_active_attempt(progress, card_id):
            raise KnowledgeCardStateError(
                f"card {card_id!r} already has an active generation attempt"
            )
        if not stable_assessment_is_current(progress, card):
            raise KnowledgeCardStateError(
                f"card {card_id!r} is no longer backed by current stable "
                "evidence; retry is disabled until a new stable assessment"
            )
        prior_attempts = attempts_for_card(progress, card_id)
        if len(prior_attempts) >= self._limits.max_generation_attempts:
            raise KnowledgeCardStateError(
                f"card {card_id!r} exceeds {self._limits.max_generation_attempts} "
                "generation attempts"
            )

        source_attempt = latest_attempt_for_card(progress, card_id)
        frozen_snapshot = None
        if source_attempt is not None and source_attempt.frozen_model_snapshot is not None:
            frozen_snapshot = source_attempt.frozen_model_snapshot.model_copy()
        if frozen_snapshot is None:
            current = latest_valid_stable_assessment(progress, card.knowledge_point_id)
            if current is None:
                raise KnowledgeCardEligibilityError(f"card {card_id!r} has no frozen model basis")
            stable_attempt, assessment = current
            frozen_snapshot = frozen_evaluator_snapshot_for(stable_attempt, assessment)
            if frozen_snapshot is None:
                raise KnowledgeCardEligibilityError(
                    f"card {card_id!r} has no nonempty frozen evaluator snapshot"
                )
            frozen_snapshot = frozen_snapshot.model_copy()

        assessment = next(
            (
                assessment
                for assessment in progress.rubric_assessments
                if assessment.id == card.stable_assessment_id
            ),
            None,
        )
        attempt = KnowledgeCardGenerationAttempt(
            id=uuid4().hex,
            card_id=card.id,
            input_card_revision=card.revision,
            stable_assessment_id=card.stable_assessment_id,
            generation_attempt_no=next_generation_attempt_no(progress, card.id),
            retry_of_generation_attempt_id=card.latest_generation_attempt_id,
            frozen_model_snapshot=frozen_snapshot,
            input_hash=(
                frozen_input_fingerprint(progress, card, assessment)
                if assessment is not None
                else ""
            ),
            status=GenerationAttemptStatus.QUEUED,
            created_at=moment,
        )
        append_generation_attempt(progress, attempt)
        card.draft_generation_status = DraftGenerationStatus.QUEUED
        card.version += 1
        card.updated_at = moment

        result = {
            "card": card,
            "attempt": attempt,
            "generation_attempt_no": attempt.generation_attempt_no,
            "retry_of_generation_attempt_id": attempt.retry_of_generation_attempt_id,
        }
        append_history(
            progress,
            _EVENT_CARD_RETRY,
            aggregate="",
            summary=f"card {card_id} generation retry #{attempt.generation_attempt_no}",
            payload={
                "card_id": card_id,
                "request_id": request_id,
                "request_fingerprint": fingerprint,
                "result": result,
                "retry_of_generation_attempt_id": attempt.retry_of_generation_attempt_id,
            },
        )
        self.save(progress)
        return result

    # ── discard (§8.5) ──────────────────────────────────────────────────────

    def discard(
        self,
        progress: LearningProgress,
        *,
        card_id: str,
        user_id: str,
        request_id: str,
        expected_card_revision: int,
        now: float | None = None,
    ) -> dict[str, Any]:
        """Discard an unpublished draft without touching learning evidence.

        Releases the card's ``KNOWLEDGE_CARD`` artifact references so GC can
        eventually reclaim the media (§10.5). Draft and stale-evidence cards are
        discardable; published/in-flight cards are not.
        """
        moment = now if now is not None else self._now()
        card = require_card(progress, card_id)
        _require_ownership(card, user_id)
        fingerprint = _request_fingerprint(
            {
                "card_id": card_id,
                "request_id": request_id,
                "expected_card_revision": expected_card_revision,
            }
        )
        prior = _replay_or_conflict(progress, _EVENT_CARD_DISCARD, card_id, request_id, fingerprint)
        if prior is not None:
            return prior
        if expected_card_revision != card.revision:
            raise KnowledgeCardStaleVersionError(
                f"card {card_id!r} revision conflict: expected "
                f"{expected_card_revision}, current {card.revision}"
            )
        if card.status not in (
            KnowledgeCardStatus.DRAFT,
            KnowledgeCardStatus.STALE_EVIDENCE,
        ):
            raise KnowledgeCardStateError(
                f"card {card_id!r} is {card.status.value}; only draft or "
                "stale-evidence cards can be discarded"
            )
        deleted_references: list[Any] = []
        try:
            if self._media_store is not None:
                for artifact_id in card.artifact_ids:
                    deleted = self._media_store.delete_references_for_owner(
                        artifact_id=artifact_id,
                        user_id=user_id,
                        owner_type=ReferenceOwnerType.KNOWLEDGE_CARD,
                        owner_id=card.id,
                    )
                    deleted_references.extend(deleted)
            card.status = KnowledgeCardStatus.DISCARDED
            card.version += 1
            card.updated_at = moment

            result = {
                "card": card,
                "revision": card.revision,
                "version": card.version,
            }
            append_history(
                progress,
                _EVENT_CARD_DISCARD,
                aggregate="",
                summary=f"card {card_id} discarded",
                payload={
                    "card_id": card_id,
                    "request_id": request_id,
                    "request_fingerprint": fingerprint,
                    "result": result,
                },
            )
            self.save(progress)
        except BaseException:
            # Reference release and the CAS save are one compensated operation:
            # re-establish every reference so a failed discard never leaves an
            # active persisted card whose live references were already removed.
            self._compensate_references([], deleted_references, user_id=user_id, card_id=card.id)
            raise
        return result

    # ── stale-evidence reconcile (§6.6, §15, requirement 7) ────────────────

    def reconcile_stale(self, progress: LearningProgress, *, now: float | None = None) -> list[str]:
        """Atomically stale every unpublished occupying card whose bound stable
        assessment is no longer current; persists and returns the stale card ids."""
        moment = now if now is not None else self._now()
        stale_ids = reconcile_stale_evidence(progress, now=moment)
        if stale_ids:
            self.save(progress)
        return stale_ids


__all__ = ["KnowledgeCardDraftService"]
