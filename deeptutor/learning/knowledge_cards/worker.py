"""Offline knowledge-card generation worker (KB-02).

Owns the single-flight lease, the pre-call invocation audit, the output-blob
apply boundary and deterministic restart recovery for knowledge-card draft
generation (§6.6, §7.9.1, requirement 4/5/8). It never stores credentials,
full private URLs or raw provider responses — errors are sanitized and output
blobs reject base64/media/provider envelopes before anything is persisted.

Restart recovery is deterministic:

* ``queued``  stays runnable (a card that became non-runnable is reconciled);
* ``running`` with a complete valid output blob reconciles apply-or-supersede;
* ``running`` without confirmable complete output becomes ``unknown``;
* terminal attempts never auto-run and are never reopened.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import time
from typing import Any, Callable, Protocol, runtime_checkable
from uuid import uuid4

from deeptutor.learning.knowledge_cards.audit import resolved_snapshot_from_evaluator
from deeptutor.learning.knowledge_cards.blobs import (
    KnowledgeCardBlobStore,
    sanitize_blob,
    validate_blob_payload,
)
from deeptutor.learning.knowledge_cards.config import KnowledgeCardLimits
from deeptutor.learning.knowledge_cards.eligibility import stable_assessment_is_current
from deeptutor.learning.knowledge_cards.errors import (
    KnowledgeCardLeaseError,
    KnowledgeCardNotFoundError,
    KnowledgeCardStaleVersionError,
)
from deeptutor.learning.knowledge_cards.store import (
    build_generation_input,
    content_hash,
    find_card,
    find_generation_attempt,
    require_card,
    require_generation_attempt,
)
from deeptutor.learning.models import (
    DraftGenerationStatus,
    GenerationAttemptStatus,
    KnowledgeCardRecord,
    KnowledgeCardStatus,
    LearningProgress,
    ModelInvocationRecord,
    ModelInvocationStatus,
    ModelInvocationUsage,
)
from deeptutor.learning.storage import (
    LearningStore,
    VersionConflictError,
    append_history,
    find_model_invocation,
)
from deeptutor.services.model_selection.audit import ModelInvocationRecorder
from deeptutor.services.model_selection.fingerprint import sanitize_error

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DraftOutput:
    """Normalized executor output for one knowledge-card generation.

    ``title``/``body`` are the draft payload. Provider-reported identity and
    usage are optional audit facts carried straight onto the invocation record
    (§7.8) — never raw provider responses.
    """

    title: str
    body: str
    reported_model: str | None = None
    reported_version: str | None = None
    usage: ModelInvocationUsage | dict[str, Any] | None = None


@runtime_checkable
class DraftExecutor(Protocol):
    """Provider-neutral generation contract implemented by offline adapters."""

    async def generate(self, input_projection: dict[str, Any]) -> DraftOutput | dict[str, Any]: ...


def _classify_error(exc: BaseException) -> tuple[str, str]:
    name = type(exc).__name__
    if name.endswith("Error"):
        name = name[: -len("Error")]
    code = (name or "unknown").lower() or "unknown"
    return code, sanitize_error(str(exc))


class KnowledgeCardGenerationWorker:
    """Single-flight lease, invocation audit and blob-apply for one attempt."""

    def __init__(
        self,
        store: LearningStore,
        *,
        blob_store: KnowledgeCardBlobStore | None = None,
        executor: DraftExecutor | None = None,
        media_store: Any = None,
        now: Callable[[], float] | None = None,
        limits: KnowledgeCardLimits | None = None,
    ) -> None:
        self._store = store
        self._blob_store = blob_store or KnowledgeCardBlobStore()
        self._executor = executor
        self._media_store = media_store
        self._now = now or time.time
        self._limits = limits or KnowledgeCardLimits()

    @property
    def store(self) -> LearningStore:
        return self._store

    @property
    def executor(self) -> DraftExecutor | None:
        return self._executor

    def set_executor(self, executor: DraftExecutor) -> None:
        self._executor = executor

    def save(self, progress: LearningProgress) -> None:
        try:
            self._store.save(progress)
        except VersionConflictError as exc:
            raise KnowledgeCardStaleVersionError(
                f"stale save rejected for {exc.book_id!r}: caller holds "
                f"{exc.expected_version}, persisted {exc.persisted_version}"
            ) from exc

    # ── runnability ─────────────────────────────────────────────────────────

    def _card_is_runnable(
        self,
        progress: LearningProgress,
        card: KnowledgeCardRecord | None,
        attempt: Any,
    ) -> tuple[bool, str]:
        if card is None:
            return False, "card_missing"
        if card.status != KnowledgeCardStatus.DRAFT:
            return False, "card_not_editable"
        if card.generation_locked_by_user_edit:
            return False, "generation_locked_by_user_edit"
        if card.revision != attempt.input_card_revision:
            return False, "card_revision_changed"
        if not stable_assessment_is_current(progress, card):
            return False, "stale_evidence"
        if attempt.frozen_model_snapshot is None:
            return False, "missing_frozen_model"
        return True, ""

    # ── single-flight lease (§7.9.1, requirement 4) ─────────────────────────

    def _claim_lease(
        self,
        progress: LearningProgress,
        attempt: Any,
        owner: str,
        now: float,
    ) -> None:
        """queued -> running with an unexpired owner token (CAS-guarded)."""
        if attempt.status != GenerationAttemptStatus.QUEUED:
            raise KnowledgeCardLeaseError(
                f"attempt {attempt.id!r} is {attempt.status.value}; only queued "
                "attempts can claim a lease"
            )
        if attempt.lease_active and attempt.lease_expires_at > now:
            raise KnowledgeCardLeaseError(
                f"attempt {attempt.id!r} lease is held by {attempt.lease_owner!r} and unexpired"
            )
        attempt.status = GenerationAttemptStatus.RUNNING
        attempt.lease_owner = owner
        attempt.lease_expires_at = now + self._limits.lease_duration_seconds
        if not attempt.started_at:
            attempt.started_at = now
        attempt.version += 1

    def _renew_lease(self, attempt: Any, owner: str, now: float) -> None:
        if attempt.status != GenerationAttemptStatus.RUNNING:
            raise KnowledgeCardLeaseError(f"attempt {attempt.id!r} is not running; cannot renew")
        if attempt.lease_owner != owner:
            raise KnowledgeCardLeaseError(
                f"attempt {attempt.id!r} lease belongs to {attempt.lease_owner!r}, not {owner!r}"
            )
        attempt.lease_expires_at = now + self._limits.lease_duration_seconds
        attempt.version += 1

    def _require_owner(self, attempt: Any, owner: str) -> None:
        if attempt.lease_owner != owner:
            raise KnowledgeCardLeaseError(
                f"attempt {attempt.id!r} lease belongs to {attempt.lease_owner!r}, "
                f"not {owner!r}; stale owners fail closed"
            )

    # ── invocation audit (§7.8/§9.4, requirement 4) ─────────────────────────

    def _append_pending_invocation(
        self,
        progress: LearningProgress,
        attempt: Any,
        *,
        now: float,
    ) -> str:
        """Append a durable ``pending`` invocation for the attempt and link it."""
        snapshot = resolved_snapshot_from_evaluator(attempt.frozen_model_snapshot)
        recorder = ModelInvocationRecorder()
        record = recorder.start(
            progress,
            purpose="knowledge_card_draft",
            snapshot=snapshot,
            knowledge_card_generation_attempt_id=attempt.id,
            now=now,
        )
        attempt.model_invocation_id = record.id
        return record.id

    def _finish_invocation(
        self,
        progress: LearningProgress,
        record_id: str,
        *,
        status: ModelInvocationStatus,
        reported_model: str | None = None,
        reported_version: str | None = None,
        usage: ModelInvocationUsage | dict[str, Any] | None = None,
        sanitized_error: str = "",
        error_code: str = "",
        now: float | None = None,
    ) -> None:
        """Finish the exact invocation, idempotently (already-terminal => skip).

        An audit failure here must never produce a false succeeded generation:
        the attempt only reaches a terminal state in the *same* CAS save as the
        invocation finish, so a finish that cannot be persisted also leaves the
        attempt non-terminal (and restart recovery will reconcile it from the
        durable blob instead of re-invoking the provider).
        """
        latest: ModelInvocationRecord | None = find_model_invocation(progress, record_id)
        if latest is None:
            return
        if latest.status != ModelInvocationStatus.PENDING:
            return  # already finalized by an earlier save of this completion
        recorder = ModelInvocationRecorder()
        recorder.finish(
            progress,
            record_id,
            status=status,
            reported_model=reported_model,
            reported_version=reported_version,
            usage=usage,
            sanitized_error=sanitized_error,
            error_code=error_code,
            now=now,
        )

    # ── output normalization / blob persist (requirement 5) ─────────────────

    @staticmethod
    def _normalize_output(raw: DraftOutput | dict[str, Any]) -> DraftOutput:
        if isinstance(raw, DraftOutput):
            return raw
        if isinstance(raw, dict):
            return DraftOutput(
                title=str(raw.get("title") or ""),
                body=str(raw.get("body") or ""),
                reported_model=raw.get("reported_model"),
                reported_version=raw.get("reported_version"),
                usage=raw.get("usage"),
            )
        raise TypeError(
            f"executor returned {type(raw).__name__}; expected DraftOutput or a "
            "{title, body} mapping"
        )

    def _persist_output_blob(self, raw: DraftOutput) -> tuple[dict[str, str], str, str]:
        """Normalize, validate, sanitize and atomically persist the output blob.

        Raises on unsafe/unbounded output before any blob or card is touched.
        """
        validate_blob_payload({"title": raw.title, "body": raw.body}, limits=self._limits)
        safe_title, safe_body = sanitize_blob(raw.title, raw.body)
        payload = {"title": safe_title, "body": safe_body}
        blob_ref, blob_hash = self._blob_store.save_blob(payload)
        return payload, blob_ref, blob_hash

    # ── apply / supersede (requirement 5) ───────────────────────────────────

    def _apply_or_supersede(
        self,
        progress: LearningProgress,
        card: KnowledgeCardRecord,
        attempt: Any,
        payload: dict[str, str],
        blob_ref: str,
        blob_hash: str,
        *,
        now: float,
    ) -> dict[str, Any]:
        """Apply the blob when the card-revision/evidence/user-edit guard holds;
        otherwise preserve the blob + audit and mark ``superseded_by_edit``."""
        guard_holds = (
            card.revision == attempt.input_card_revision
            and card.status == KnowledgeCardStatus.DRAFT
            and not card.generation_locked_by_user_edit
            and stable_assessment_is_current(progress, card)
        )
        attempt.output_blob_ref = blob_ref
        attempt.output_hash = blob_hash
        attempt.finished_at = now
        attempt.version += 1
        if guard_holds:
            card.title = payload["title"]
            card.body = payload["body"]
            card.content_hash = content_hash(card.title, card.body)
            card.revision += 1
            card.version += 1
            card.draft_generation_status = DraftGenerationStatus.READY
            card.latest_generation_attempt_id = attempt.id
            card.updated_at = now
            attempt.status = GenerationAttemptStatus.SUCCEEDED
            append_history(
                progress,
                "knowledge_card_generation_succeeded",
                aggregate="",
                summary=f"card {card.id} generation attempt {attempt.id} applied",
                payload={
                    "attempt_id": attempt.id,
                    "card_id": card.id,
                    "output_hash": blob_hash,
                    "revision": card.revision,
                },
            )
            return {"applied": True, "outcome": GenerationAttemptStatus.SUCCEEDED.value}
        attempt.status = GenerationAttemptStatus.SUPERSEDED_BY_EDIT
        if card.status == KnowledgeCardStatus.DRAFT:
            card.draft_generation_status = DraftGenerationStatus.SUPERSEDED_BY_EDIT
            card.version += 1
            card.updated_at = now
        append_history(
            progress,
            "knowledge_card_generation_superseded",
            aggregate="",
            summary=f"card {card.id} generation attempt {attempt.id} superseded",
            payload={
                "attempt_id": attempt.id,
                "card_id": card.id,
                "output_hash": blob_hash,
                "reason": "user_edit_or_card_state_changed",
            },
        )
        return {"applied": False, "outcome": GenerationAttemptStatus.SUPERSEDED_BY_EDIT.value}

    # ── execution ───────────────────────────────────────────────────────────

    async def run_attempt(self, path_id: str, attempt_id: str) -> dict[str, Any]:
        """Execute one queued generation attempt with single-flight lease.

        Caller supplies the path (book) id so the worker never has to scan all
        documents. A non-runnable card (user lock / stale evidence / revision
        change) is reconciled deterministically without invoking the executor.
        """
        owner = uuid4().hex
        now = self._now()

        # Phase 1: claim the lease (CAS loop).
        progress = self._store.load(path_id)
        if progress is None:
            raise KnowledgeCardNotFoundError(f"progress for path {path_id!r} not found")
        attempt = require_generation_attempt(progress, attempt_id)
        card = require_card(progress, attempt.card_id)
        runnable, reason = self._card_is_runnable(progress, card, attempt)
        if not runnable:
            self._reconcile_not_runnable(progress, card, attempt, reason, now)
            self.save(progress)
            return {
                "attempt_id": attempt_id,
                "outcome": attempt.status.value,
                "reason": reason,
            }
        self._claim_lease(progress, attempt, owner, now)
        try:
            self.save(progress)
        except KnowledgeCardStaleVersionError:
            progress = self._reload(path_id)
            attempt = require_generation_attempt(progress, attempt_id)
            card = require_card(progress, attempt.card_id)
            self._claim_lease(progress, attempt, owner, now)
            self.save(progress)

        # Phase 2: durable pending invocation audit + link before the call.
        record_id = self._append_pending_invocation(progress, attempt, now=now)
        try:
            self.save(progress)
        except KnowledgeCardStaleVersionError:
            progress = self._reload(path_id)
            attempt = require_generation_attempt(progress, attempt_id)
            self._require_owner(attempt, owner)
            record_id = self._append_pending_invocation(progress, attempt, now=now)
            self.save(progress)

        assessment = next(
            (
                assessment
                for assessment in progress.rubric_assessments
                if assessment.id == attempt.stable_assessment_id
            ),
            None,
        )
        if assessment is None:
            self._finish_failed(
                path_id,
                attempt_id,
                owner,
                record_id,
                error_code="missing_stable_assessment",
                message="stable assessment for the generation attempt is missing",
            )
            return {
                "attempt_id": attempt_id,
                "outcome": GenerationAttemptStatus.FAILED.value,
                "error_code": "missing_stable_assessment",
            }
        try:
            input_projection = build_generation_input(
                progress, card, assessment, media_store=self._media_store
            )
        except Exception as exc:  # noqa: BLE001
            error_code, message = _classify_error(exc)
            self._finish_failed(path_id, attempt_id, owner, record_id, error_code, message)
            return {
                "attempt_id": attempt_id,
                "outcome": GenerationAttemptStatus.FAILED.value,
                "error_code": error_code,
            }

        # Phase 3: call the executor exactly once.
        if self._executor is None:
            self._finish_failed(
                path_id,
                attempt_id,
                owner,
                record_id,
                error_code="no_executor",
                message="no draft generation executor is configured",
            )
            return {
                "attempt_id": attempt_id,
                "outcome": GenerationAttemptStatus.FAILED.value,
                "error_code": "no_executor",
            }
        try:
            raw = await self._executor.generate(input_projection)
        except Exception as exc:  # noqa: BLE001
            error_code, message = _classify_error(exc)
            self._finish_failed(path_id, attempt_id, owner, record_id, error_code, message)
            return {
                "attempt_id": attempt_id,
                "outcome": GenerationAttemptStatus.FAILED.value,
                "error_code": error_code,
            }

        # Phase 4: normalize/validate/sanitize and persist the output blob.
        try:
            output = self._normalize_output(raw)
            payload, blob_ref, blob_hash = self._persist_output_blob(output)
        except Exception as exc:  # noqa: BLE001
            error_code, message = _classify_error(exc)
            self._finish_failed(path_id, attempt_id, owner, record_id, error_code, message)
            return {
                "attempt_id": attempt_id,
                "outcome": GenerationAttemptStatus.FAILED.value,
                "error_code": error_code,
            }

        # Phase 5: finish invocation + apply-or-supersede + terminal (CAS loop).
        return self._complete_with_blob(
            path_id,
            attempt_id,
            owner,
            record_id,
            payload,
            blob_ref,
            blob_hash,
            reported_model=output.reported_model,
            reported_version=output.reported_version,
            usage=output.usage,
        )

    def _reload(self, path_id: str) -> LearningProgress:
        progress = self._store.load(path_id)
        if progress is None:
            raise KnowledgeCardNotFoundError(f"progress for path {path_id!r} not found")
        return progress

    def _complete_with_blob(
        self,
        path_id: str,
        attempt_id: str,
        owner: str,
        record_id: str,
        payload: dict[str, str],
        blob_ref: str,
        blob_hash: str,
        *,
        reported_model: str | None,
        reported_version: str | None,
        usage: ModelInvocationUsage | dict[str, Any] | None,
    ) -> dict[str, Any]:
        while True:
            progress = self._reload(path_id)
            attempt = require_generation_attempt(progress, attempt_id)
            if attempt.is_terminal:
                return {
                    "attempt_id": attempt_id,
                    "outcome": attempt.status.value,
                    "applied": attempt.status == GenerationAttemptStatus.SUCCEEDED,
                    "replayed": True,
                }
            self._require_owner(attempt, owner)
            card = require_card(progress, attempt.card_id)
            self._finish_invocation(
                progress,
                record_id,
                status=ModelInvocationStatus.COMPLETED,
                reported_model=reported_model,
                reported_version=reported_version,
                usage=usage,
                now=self._now(),
            )
            outcome = self._apply_or_supersede(
                progress, card, attempt, payload, blob_ref, blob_hash, now=self._now()
            )
            try:
                self.save(progress)
            except KnowledgeCardStaleVersionError:
                continue
            return {
                "attempt_id": attempt_id,
                "outcome": outcome["outcome"],
                "applied": outcome["applied"],
            }

    def _finish_failed(
        self,
        path_id: str,
        attempt_id: str,
        owner: str,
        record_id: str,
        error_code: str,
        message: str,
    ) -> None:
        while True:
            progress = self._reload(path_id)
            attempt = require_generation_attempt(progress, attempt_id)
            if attempt.is_terminal:
                return
            try:
                self._require_owner(attempt, owner)
            except KnowledgeCardLeaseError:
                # Lease was lost (e.g. expired takeover); the attempt's terminal
                # reconciliation is owned by the current holder. Do not clobber.
                return
            card = find_card(progress, attempt.card_id)
            self._finish_invocation(
                progress,
                record_id,
                status=ModelInvocationStatus.FAILED,
                sanitized_error=message,
                error_code=error_code,
                now=self._now(),
            )
            attempt.status = GenerationAttemptStatus.FAILED
            attempt.error_code = error_code
            attempt.sanitized_error = message
            attempt.finished_at = self._now()
            attempt.version += 1
            if card is not None and card.status == KnowledgeCardStatus.DRAFT:
                card.draft_generation_status = DraftGenerationStatus.FAILED
                card.version += 1
                card.updated_at = self._now()
            append_history(
                progress,
                "knowledge_card_generation_failed",
                aggregate="",
                summary=f"card {attempt.card_id} generation attempt {attempt.id} failed",
                payload={
                    "attempt_id": attempt.id,
                    "card_id": attempt.card_id,
                    "error_code": error_code,
                    "sanitized_error": message,
                },
            )
            try:
                self.save(progress)
            except KnowledgeCardStaleVersionError:
                continue
            return

    def _reconcile_not_runnable(
        self,
        progress: LearningProgress,
        card: KnowledgeCardRecord | None,
        attempt: Any,
        reason: str,
        now: float,
    ) -> None:
        """Terminate a queued attempt whose card became non-runnable.

        A user edit / revision change supersedes the attempt (never overwrite
        user content); stale/noneditable evidence fails it closed (generation
        disabled). The card, blobs and provenance are preserved.
        """
        if reason in ("generation_locked_by_user_edit", "card_revision_changed"):
            attempt.status = GenerationAttemptStatus.SUPERSEDED_BY_EDIT
            attempt.finished_at = now
            attempt.version += 1
            if card is not None and card.status == KnowledgeCardStatus.DRAFT:
                card.draft_generation_status = DraftGenerationStatus.SUPERSEDED_BY_EDIT
                card.version += 1
                card.updated_at = now
            append_history(
                progress,
                "knowledge_card_generation_superseded",
                aggregate="",
                summary=f"card {attempt.card_id} queued attempt {attempt.id} superseded",
                payload={
                    "attempt_id": attempt.id,
                    "card_id": attempt.card_id,
                    "reason": reason,
                },
            )
            return
        error_code = "stale_evidence" if reason == "stale_evidence" else "card_not_runnable"
        attempt.status = GenerationAttemptStatus.FAILED
        attempt.error_code = error_code
        attempt.sanitized_error = (
            "generation disabled: the card is no longer backed by current stable "
            "evidence or is not an editable draft"
            if reason == "stale_evidence"
            else "generation disabled: the card is not an editable draft"
        )
        attempt.finished_at = now
        attempt.version += 1
        if card is not None and card.status == KnowledgeCardStatus.DRAFT:
            card.draft_generation_status = DraftGenerationStatus.FAILED
            card.version += 1
            card.updated_at = now
        append_history(
            progress,
            "knowledge_card_generation_failed",
            aggregate="",
            summary=f"card {attempt.card_id} queued attempt {attempt.id} disabled",
            payload={
                "attempt_id": attempt.id,
                "card_id": attempt.card_id,
                "error_code": error_code,
                "reason": reason,
            },
        )

    # ── restart recovery (§7.9.1, requirement 8) ────────────────────────────

    def recover(self) -> list[dict[str, str]]:
        """Apply the deterministic restart rules to every stored attempt."""
        outcomes: list[dict[str, str]] = []
        for book_id in self._store.list_all():
            progress = self._store.load(book_id)
            if progress is None:
                continue
            for attempt in list(progress.knowledge_card_generation_attempts):
                outcome = self._recover_one(book_id, attempt.id)
                if outcome is not None:
                    outcomes.append(outcome)
        return outcomes

    def _recover_one(self, book_id: str, attempt_id: str) -> dict[str, str] | None:
        while True:
            progress = self._store.load(book_id)
            if progress is None:
                return None
            attempt = find_generation_attempt(progress, attempt_id)
            if attempt is None or attempt.is_terminal:
                return None
            now = self._now()
            card = find_card(progress, attempt.card_id)
            if attempt.status == GenerationAttemptStatus.QUEUED:
                # Queued stays runnable; reconcile a card that became
                # non-runnable so no stuck queued attempt blocks retry.
                if card is not None:
                    runnable, reason = self._card_is_runnable(progress, card, attempt)
                    if not runnable:
                        self._reconcile_not_runnable(progress, card, attempt, reason, now)
                        try:
                            self.save(progress)
                        except KnowledgeCardStaleVersionError:
                            continue
                        return {
                            "book_id": book_id,
                            "attempt_id": attempt_id,
                            "from": "queued",
                            "to": attempt.status.value,
                        }
                return None  # stays queued, runnable
            if attempt.status == GenerationAttemptStatus.RUNNING:
                if attempt.output_blob_ref and self._blob_store.blob_exists(
                    attempt.output_blob_ref
                ):
                    payload = self._blob_store.load_blob(attempt.output_blob_ref)
                    if (
                        payload is not None
                        and isinstance(payload.get("title"), str)
                        and isinstance(payload.get("body"), str)
                        and card is not None
                    ):
                        self._finish_invocation(
                            progress,
                            attempt.model_invocation_id,
                            status=ModelInvocationStatus.COMPLETED,
                            reported_model=None,
                            reported_version=None,
                            usage=None,
                            now=now,
                        )
                        outcome = self._apply_or_supersede(
                            progress,
                            card,
                            attempt,
                            payload,
                            attempt.output_blob_ref,
                            attempt.output_hash,
                            now=now,
                        )
                        try:
                            self.save(progress)
                        except KnowledgeCardStaleVersionError:
                            continue
                        return {
                            "book_id": book_id,
                            "attempt_id": attempt_id,
                            "from": "running",
                            "to": attempt.status.value,
                            "applied": str(outcome["applied"]).lower(),
                        }
                attempt.status = GenerationAttemptStatus.UNKNOWN
                attempt.error_code = "restart_no_confirmable_output"
                attempt.sanitized_error = (
                    "Running attempt has no complete durable output blob; the "
                    "provider result cannot be confirmed and is never "
                    "automatically re-submitted."
                )
                attempt.finished_at = now
                attempt.version += 1
                try:
                    self.save(progress)
                except KnowledgeCardStaleVersionError:
                    continue
                return {
                    "book_id": book_id,
                    "attempt_id": attempt_id,
                    "from": "running",
                    "to": "unknown",
                }
            return None


__all__ = ["DraftExecutor", "DraftOutput", "KnowledgeCardGenerationWorker"]
