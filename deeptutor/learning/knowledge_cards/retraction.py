"""Durable knowledge-card retraction (KB-04).

Owns recoverable, user-confirmed retraction of a previously published knowledge
card from a writable local indexed knowledge base (§7.11). Retraction is:

* **authorization-bound** — only the card owner may retract/reconcile, and the
  addressed path/card must match (requirement 1). The target KB / fixed document
  / hash are derived from the immutable published card; a client can never
  redirect deletion to another path or KB (requirement 2);
* **fail-closed preconditioned** — before any KB mutation the exact
  owner/path/card revision, the ``published`` state, internal publication
  consistency, the writable-KB policy (ordinary local indexed, ``ready``, no
  ``needs_reindex``, local raw set, not connected/external), the fixed path
  containment under ``raw/learning_cards``, and the raw bytes matching the
  published SHA-256 are all re-verified (requirement 3);
* **two-phase and crash-safe** — a durable retraction intent is persisted before
  lease acquisition, the ``card_retract`` operation carries exact
  target/card/request identity, a :class:`LeaseHeartbeat` guards every long
  filesystem/reindex step, and final ownership is verified before any terminal
  write. A crash at every boundary stays discoverable and never strands the KB
  or resolves another operation (requirement 4);
* **same-volume quarantine** — the exact raw file is hash-verified then
  atomically moved (``os.replace``, never a copy-and-delete race) to a
  deterministic sandboxed quarantine path, and the only recoverable bytes are
  never permanently deleted before the excluding index is explicitly confirmed
  (requirement 5);
* **proof-before-retracted** — only when the raw file is absent, the document
  hash/path is absent from the new index input/evidence, the full-reindex result
  explicitly succeeds, and the KB returns ``ready`` does the card become
  ``retracted`` and the ``card_retract`` operation succeed (requirement 6);
* **rigorous rollback** — on a definite reindex failure the exact quarantine
  bytes are atomically restored, the restored set is reindexed, and raw hash +
  index hash/evidence + ready KB are confirmed before the card returns to
  immutable ``published`` with a failed retraction record (requirement 7);
* **recoverable ambiguity** — when neither deletion-side nor rollback-side
  success can be proven the card locks ``retract_reconcile_required``, all
  durable target/path/hash/operation identities are retained, the KB is marked
  ``needs_reindex`` where possible, and later card/KB mutation is blocked by the
  existing coordinator (requirement 8);
* **observational reconcile** — ``reconcile-retraction`` inspects only the fixed
  raw/quarantine path+hash, KB metadata/index evidence, ready/needs-reindex
  state and the exact existing operation identity; it converges only to a fully
  proven ``retracted`` or ``published`` and otherwise stays
  ``retract_reconcile_required`` without ever moving/deleting/restoring/
  reindexing/resubmitting (requirement 9). Deleting the exact matching
  quarantine copy after a durable retraction is the job of the explicit
  post-terminal cleanup path — a replay of the same retract request or
  :meth:`KnowledgeCardRetractionService.complete_quarantine_cleanup` — which is
  durable (``pending``/``cleaned``/``failed`` on the exact retraction record),
  observable and deterministically retryable, and never runs inside reconcile
  (KB-04 review round 1);
* **reference lifecycle** — the card's live ``KNOWLEDGE_CARD`` media references
  stay live through ``published``/``retracting``/``retract_reconcile_required``
  and are released only after ``retracted`` is durably confirmed; release is
  idempotently recoverable and never changes the retained audit artifact ids
  (requirement 10);
* **mastery preserved** — retraction never lowers mastery and never reuses the
  old stable evidence (KB-02's later-stable-assessment sequence rule keeps
  preventing reuse; requirement 11).

This service never copies raw conversation, provider prompts/responses,
credentials, base64 or private URLs into any durable record.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
import time
from typing import Any, Callable
from uuid import uuid4

from deeptutor.knowledge.kb_types import is_connected_kb
from deeptutor.knowledge.manager import KnowledgeBaseManager
from deeptutor.knowledge.writable import (
    KbNotWritableError,
    assert_kb_writable,
    kb_is_ready,
)
from deeptutor.knowledge.write_coordinator import (
    KbBusyError,
    KbLeaseError,
    KbWriteCoordinator,
    LeaseHeartbeat,
    heartbeat_interval_seconds,
)
from deeptutor.learning.knowledge_cards.errors import (
    KnowledgeCardError,
    KnowledgeCardInputValidationError,
    KnowledgeCardKbNotWritableError,
    KnowledgeCardNotFoundError,
    KnowledgeCardOwnershipError,
    KnowledgeCardReconcileRequiredError,
    KnowledgeCardRetractionConflictError,
    KnowledgeCardRetractionUnavailableError,
    KnowledgeCardStaleVersionError,
    KnowledgeCardStateError,
)
from deeptutor.learning.knowledge_cards.publish import (
    _validate_document_rel_path,
    fixed_document_rel_path,
)
from deeptutor.learning.knowledge_cards.store import require_card
from deeptutor.learning.models import (
    TERMINAL_RETRACTION_STATUSES,
    KnowledgeCardPublicationRecord,
    KnowledgeCardRecord,
    KnowledgeCardRetractionRecord,
    KnowledgeCardStatus,
    LearningProgress,
    PublicationStatus,
    RetractionIntent,
    RetractionStatus,
)
from deeptutor.learning.storage import (
    LearningStore,
    VersionConflictError,
    append_history,
)
from deeptutor.services.file_io import atomic_write_json
from deeptutor.services.media.models import ReferenceOwnerType
from deeptutor.services.model_selection.fingerprint import sanitize_error
from deeptutor.services.rag.file_routing import FileTypeRouter
from deeptutor.services.rag.service import RAGService

logger = logging.getLogger(__name__)

#: Fixed relative document path prefix for published knowledge cards — reused
#: verbatim from KB-03 (§7.9.2). The quarantine lives on the same KB volume
#: under ``quarantine/learning_cards/`` so ``os.replace`` stays atomic.
FIXED_CARD_DIRECTORY = "learning_cards"
FIXED_QUARANTINE_DIRECTORY = "quarantine/learning_cards"

#: History event types for the retraction lifecycle (append-only audit).
_EVENT_RETRACTION_STARTED = "knowledge_card_retraction_started"
_EVENT_RETRACTED = "knowledge_card_retracted"
_EVENT_RETRACTION_FAILED = "knowledge_card_retraction_failed"
_EVENT_RETRACTION_ROLLED_BACK = "knowledge_card_retraction_rolled_back"
_EVENT_RETRACTION_RECONCILE_REQUIRED = "knowledge_card_retraction_reconcile_required"
_EVENT_RETRACTION_RECONCILED = "knowledge_card_retraction_reconciled"

#: Post-terminal quarantine-cleanup states (KB-04 review round 1 correction 2).
#: A durably ``retracted`` card's exact matching quarantine copy is deleted by
#: the explicit post-terminal cleanup path — a replay of the same retract
#: request or the dedicated :meth:`KnowledgeCardRetractionService
#: .complete_quarantine_cleanup` — never by the observational reconcile.
#: ``pending`` is persisted together with the terminal ``retracted`` write;
#: ``cleaned``/``failed`` durably record the outcome of the last cleanup attempt
#: (sanitized error + timestamp) so a restart can observe and deterministically
#: retry it.
CLEANUP_STATUS_PENDING = "pending"
CLEANUP_STATUS_CLEANED = "cleaned"
CLEANUP_STATUS_FAILED = "failed"


def _safe_card_id(card_id: str) -> str:
    """Return *card_id* only when it is a safe single document path segment."""
    if not isinstance(card_id, str) or not card_id:
        raise KnowledgeCardInputValidationError("card id is required")
    if any(ch in card_id for ch in ("/", "\\", ":", "\x00", "..")):
        raise KnowledgeCardInputValidationError(
            f"card id {card_id!r} is not a safe document path segment"
        )
    if any(ord(ch) < 32 for ch in card_id):
        raise KnowledgeCardInputValidationError(f"card id {card_id!r} contains control characters")
    return card_id


def fixed_quarantine_rel_path(card_id: str, card_revision: int, document_sha256: str) -> str:
    """Deterministic, sandboxed same-volume quarantine path (§7.11 requirement 5).

    The path embeds the card id, revision and a hash prefix so a malformed or
    legacy card id can never escape ``quarantine/learning_cards/``, two
    quarantines of the same revision share one path (idempotent), and a later
    restored document reuses the exact original bytes.
    """
    safe_id = _safe_card_id(card_id)
    if not isinstance(card_revision, int) or card_revision < 1:
        raise KnowledgeCardInputValidationError(
            f"card revision must be a positive integer, got {card_revision!r}"
        )
    if not document_sha256 or not isinstance(document_sha256, str):
        raise KnowledgeCardInputValidationError(
            "document SHA-256 is required for a deterministic quarantine path"
        )
    return f"{FIXED_QUARANTINE_DIRECTORY}/{safe_id}-v{card_revision}-{document_sha256[:16]}.md"


def _validate_quarantine_rel_path(rel_path: str) -> str:
    """Return *rel_path* only when it is a safe nested path under
    ``quarantine/learning_cards/`` (sandboxed before it is joined onto a KB dir)."""
    if not isinstance(rel_path, str) or not rel_path:
        raise KnowledgeCardInputValidationError("quarantine path is empty")
    parts = rel_path.split("/")
    if len(parts) != 3 or parts[0] != "quarantine" or parts[1] != FIXED_CARD_DIRECTORY:
        raise KnowledgeCardInputValidationError(
            f"quarantine path {rel_path!r} escapes {FIXED_QUARANTINE_DIRECTORY}/"
        )
    name = parts[2]
    if name in ("", ".", ".."):
        raise KnowledgeCardInputValidationError(
            f"quarantine path {rel_path!r} is not a single nested file"
        )
    if any(ch in name for ch in ("/", "\\", ":", "\x00")) or any(ord(ch) < 32 for ch in name):
        raise KnowledgeCardInputValidationError(
            f"quarantine path {rel_path!r} contains unsafe characters"
        )
    return rel_path


def retraction_fingerprint(
    card_revision: int,
    target_kb_name: str,
    original_rel_path: str,
    document_sha256: str,
) -> str:
    """Deterministic payload fingerprint for retraction idempotency.

    Same ``request_id`` for one card revision replays when the fingerprint
    matches; reusing it with different facts is a stable conflict (§7.11
    requirement 1).
    """
    canonical = json.dumps(
        {
            "card_revision": card_revision,
            "target_kb_name": target_kb_name,
            "original_rel_path": original_rel_path,
            "document_sha256": document_sha256,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _sha256_of_file(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


class KnowledgeCardRetractionService:
    """Durable retract / reconcile-retraction for one published card."""

    def __init__(
        self,
        store: LearningStore | None = None,
        *,
        kb_base_dir: str | Path | None = None,
        manager: KnowledgeBaseManager | None = None,
        media_store: Any | None = None,
        now: Callable[[], float] | None = None,
    ) -> None:
        self._store = store or LearningStore()
        self._kb_base_dir = Path(kb_base_dir) if kb_base_dir is not None else None
        self._manager = manager
        self._media_store = media_store
        self._now = now or time.time

    @property
    def store(self) -> LearningStore:
        return self._store

    @property
    def media_store(self) -> Any:
        """The media store used to release card media references on retraction."""
        if self._media_store is None:
            from deeptutor.services.media.store import MediaStore

            self._media_store = MediaStore()
        return self._media_store

    @property
    def kb_base_dir(self) -> Path:
        if self._kb_base_dir is not None:
            return self._kb_base_dir
        if self._manager is not None:
            return Path(self._manager.base_dir)
        from deeptutor.multi_user.knowledge_access import current_kb_base_dir

        return current_kb_base_dir()

    def _get_manager(self) -> KnowledgeBaseManager:
        if self._manager is not None:
            return self._manager
        if self._kb_base_dir is not None:
            return KnowledgeBaseManager(base_dir=str(self._kb_base_dir))
        from deeptutor.multi_user.knowledge_access import current_kb_manager

        return current_kb_manager()

    def _load(self, path_id: str) -> LearningProgress:
        progress = self._store.load(path_id)
        if progress is None:
            raise KnowledgeCardNotFoundError(f"progress for path {path_id!r} not found")
        return progress

    def save(self, progress: LearningProgress) -> None:
        try:
            self._store.save(progress)
        except VersionConflictError as exc:
            raise KnowledgeCardStaleVersionError(
                f"stale save rejected for {exc.book_id!r}: caller holds "
                f"{exc.expected_version}, persisted {exc.persisted_version}; "
                "reload before saving so append-only history is never overwritten"
            ) from exc

    # ── ownership / path / writable policy ──────────────────────────────────

    def _require_ownership_and_path(
        self,
        progress: LearningProgress,
        card: KnowledgeCardRecord,
        user_id: str,
    ) -> None:
        if not user_id:
            raise KnowledgeCardOwnershipError("actor user id is required")
        if card.user_id and card.user_id != user_id:
            raise KnowledgeCardOwnershipError(
                f"card {card.id!r} belongs to user {card.user_id!r}, not {user_id!r}"
            )
        if card.path_id and card.path_id != progress.book_id:
            raise KnowledgeCardInputValidationError(
                f"card {card.id!r} belongs to path {card.path_id!r}, not "
                f"{progress.book_id!r}; cross-path retraction fails closed"
            )

    def _assert_kb_writable(self, kb_name: str) -> dict[str, Any]:
        manager = self._get_manager()
        try:
            return assert_kb_writable(manager, kb_name)
        except KbNotWritableError as exc:
            raise KnowledgeCardKbNotWritableError(str(exc)) from exc

    # ── record lookups / projection helpers ────────────────────────────────

    @staticmethod
    def _latest_retraction_for_revision(
        progress: LearningProgress, card: KnowledgeCardRecord
    ) -> KnowledgeCardRetractionRecord | None:
        records = [
            record
            for record in progress.knowledge_card_retraction_records
            if record.card_id == card.id and record.card_revision == card.revision
        ]
        if not records:
            return None
        return max(records, key=lambda record: (record.created_at, record.id))

    @staticmethod
    def _active_retraction_for_revision(
        progress: LearningProgress, card: KnowledgeCardRecord
    ) -> KnowledgeCardRetractionRecord | None:
        records = [
            record
            for record in progress.knowledge_card_retraction_records
            if record.card_id == card.id
            and record.card_revision == card.revision
            and record.status not in TERMINAL_RETRACTION_STATUSES
        ]
        if not records:
            return None
        return max(records, key=lambda record: (record.created_at, record.id))

    @staticmethod
    def _records_for_card(
        progress: LearningProgress, card_id: str
    ) -> list[KnowledgeCardRetractionRecord]:
        return [
            record
            for record in progress.knowledge_card_retraction_records
            if record.card_id == card_id
        ]

    @staticmethod
    def _latest_publication(
        progress: LearningProgress, pub_key: str
    ) -> KnowledgeCardPublicationRecord | None:
        for record in reversed(progress.knowledge_card_publication_records):
            if record.publication_key == pub_key:
                return record
        return None

    def _card_result(
        self, progress: LearningProgress, card: KnowledgeCardRecord, *, replayed: bool
    ) -> dict[str, Any]:
        # Post-terminal quarantine cleanup state is observable through the exact
        # latest retraction record (never exposes raw paths or unsanitized
        # errors — only the safe ``cleanup_status``/``cleanup_error`` fields).
        record = self._latest_retraction_for_revision(progress, card)
        return {
            "card_id": card.id,
            "status": card.status.value,
            "replayed": replayed,
            "revision": card.revision,
            "target_kb_name": card.target_kb_name,
            "document_rel_path": card.document_rel_path,
            "document_sha256": card.document_sha256,
            "quarantine_rel_path": card.quarantine_rel_path,
            "retraction_request_id": card.retraction_request_id,
            "retraction_operation_id": card.retraction_operation_id,
            "error_code": card.error_code,
            "sanitized_error": card.sanitized_error,
            "retracted_at": card.retracted_at,
            "cleanup_status": record.cleanup_status if record else "",
            "cleanup_error": record.cleanup_error if record else "",
        }

    def _reload_result(self, path_id: str, card_id: str, *, replayed: bool) -> dict[str, Any]:
        progress = self._load(path_id)
        card = require_card(progress, card_id)
        return self._card_result(progress, card, replayed=replayed)

    def retraction_projection(self, path_id: str, *, card_id: str, user_id: str) -> dict[str, Any]:
        """A read projection so a client can observe retraction state after reload."""
        progress = self._load(path_id)
        card = require_card(progress, card_id)
        self._require_ownership_and_path(progress, card, user_id)
        records = self._records_for_card(progress, card_id)
        return {
            **self._card_result(progress, card, replayed=False),
            "retraction_records": [record.model_dump(mode="json") for record in records],
        }

    # ── retract ─────────────────────────────────────────────────────────────

    async def retract(
        self,
        path_id: str,
        *,
        card_id: str,
        user_id: str,
        request_id: str,
        expected_card_revision: int,
        now: float | None = None,
    ) -> dict[str, Any]:
        """User-confirmed retraction of a published card (requirement 2/6)."""
        moment = now if now is not None else self._now()
        if not user_id:
            raise KnowledgeCardOwnershipError("actor user id is required")
        if not request_id:
            raise KnowledgeCardInputValidationError("request_id is required")

        progress = self._load(path_id)
        card = require_card(progress, card_id)
        self._require_ownership_and_path(progress, card, user_id)

        # Resolve the idempotency start-state BEFORE any durable change. A
        # replayed request returns the existing result; a conflicting reuse, an
        # already-retracted card, an active retraction, or a reconcile-required
        # card all fail closed here.
        basis = self._resolve_retraction_basis(progress, card, request_id=request_id)
        if basis == "replay":
            # Replaying the same mutating retract request is the explicit,
            # deterministic post-terminal cleanup retry (KB-04 review round 1
            # correction 2): when the card is durably retracted and the exact
            # retraction record's quarantine cleanup is still pending/failed,
            # complete it here — never inside the observational reconcile.
            if card.status == KnowledgeCardStatus.RETRACTED:
                record = self._latest_retraction_for_revision(progress, card)
                if record is not None and record.cleanup_status != CLEANUP_STATUS_CLEANED:
                    self._complete_quarantine_cleanup_for_record(
                        path_id,
                        card_id,
                        user_id,
                        request_id=record.request_id,
                        now=moment,
                    )
                    return self._reload_result(path_id, card_id, replayed=True)
            return self._card_result(progress, card, replayed=True)
        if basis == "reconcile_required":
            raise KnowledgeCardReconcileRequiredError(
                f"card {card_id!r} has an unresolved retraction; reconcile it "
                "before retracting again"
            )
        if basis == "already_retracted":
            raise KnowledgeCardStateError(
                f"card {card_id!r} is already retracted; a new stable assessment "
                "must be created before a new card can occupy the slot"
            )
        if basis == "active":
            raise KnowledgeCardStateError(
                f"card {card_id!r} already has an active retraction for this revision"
            )

        if expected_card_revision != card.revision:
            raise KnowledgeCardStaleVersionError(
                f"card {card_id!r} revision conflict: expected "
                f"{expected_card_revision}, current {card.revision}"
            )
        if card.status != KnowledgeCardStatus.PUBLISHED:
            raise KnowledgeCardStateError(
                f"card {card_id!r} is {card.status.value}; only a published card can be retracted"
            )

        # Derive the target/fixed document/hash from the immutable published
        # card — a client can never redirect deletion elsewhere (requirement 2).
        target_kb_name = card.target_kb_name
        rel_path = card.document_rel_path
        document_sha = card.document_sha256
        if not target_kb_name or not rel_path or not document_sha:
            raise KnowledgeCardStateError(
                f"published card {card_id!r} has incomplete durable publication "
                "facts; publication must be reconciled before retraction"
            )
        rel_path = _validate_document_rel_path(rel_path)

        # Durable publication facts must be internally consistent: the fixed
        # path matches the card id/revision, and the latest publication record
        # agrees on the document hash (requirement 3).
        expected_rel_path = fixed_document_rel_path(card.id, card.revision)
        if rel_path != expected_rel_path:
            raise KnowledgeCardStateError(
                f"card {card_id!r} document path {rel_path!r} does not match the "
                f"fixed path {expected_rel_path!r}; retraction fails closed"
            )
        if card.publication_key:
            pub_record = self._latest_publication(progress, card.publication_key)
            if pub_record is not None:
                if pub_record.status == PublicationStatus.PUBLISHED:
                    if pub_record.document_sha256 and pub_record.document_sha256 != document_sha:
                        raise KnowledgeCardStateError(
                            f"card {card_id!r} publication record hash "
                            f"{pub_record.document_sha256!r} does not match the card "
                            f"hash {document_sha!r}; retraction fails closed"
                        )
                    if pub_record.document_rel_path and pub_record.document_rel_path != rel_path:
                        raise KnowledgeCardStateError(
                            f"card {card_id!r} publication record path "
                            f"{pub_record.document_rel_path!r} does not match the "
                            f"card path {rel_path!r}; retraction fails closed"
                        )
            elif card.status == KnowledgeCardStatus.PUBLISHED:
                # A published card without a PUBLISHED publication record is
                # internally inconsistent — retraction must not rely on it.
                raise KnowledgeCardStateError(
                    f"published card {card_id!r} has no published publication record; "
                    "retraction fails closed"
                )

        # Writable-KB policy (before any KB mutation) and raw-bytes hash proof.
        self._assert_kb_writable(target_kb_name)
        kb_dir = self._get_manager().get_knowledge_base_path(target_kb_name)
        raw_root = (kb_dir / "raw").resolve()
        raw_path = (raw_root / rel_path).resolve()
        if not raw_path.is_relative_to(raw_root):
            raise KnowledgeCardInputValidationError(
                f"document path {rel_path!r} escapes the KB raw directory"
            )
        if not raw_path.is_file():
            raise KnowledgeCardStateError(
                f"raw document {rel_path!r} is missing from KB {target_kb_name!r}; "
                "retraction fails closed"
            )
        raw_sha = _sha256_of_file(raw_path)
        if raw_sha != document_sha:
            raise KnowledgeCardStateError(
                f"raw document bytes at {rel_path!r} do not match the published "
                "SHA-256; retraction fails closed"
            )

        quarantine_rel = fixed_quarantine_rel_path(card.id, card.revision, document_sha)
        quarantine_rel = _validate_quarantine_rel_path(quarantine_rel)

        # Fail closed before any KB mutation when the excluding raw set would be
        # empty: quarantining a single-document KB and handing the provider an
        # empty reindex input would be an ordinary-provider-failure that is
        # really an unsupported state (KB-04 P0 additional check).
        if not self._excluding_raw_paths(kb_dir, rel_path):
            raise KnowledgeCardStateError(
                f"card {card_id!r} is the only supported document in KB "
                f"{target_kb_name!r}; retraction would leave an empty raw set "
                "that the provider rejects — retraction is unsupported for a "
                "single-document KB"
            )

        # Durable retraction intent (phase 1) — persisted *before* lease
        # acquisition so a crash at every boundary leaves a recoverable two-phase
        # record (target/request/original path/quarantine path/hash/revision).
        # The caller is handed its internal ``attempt_id`` only when it durably
        # owns the exact staged intent; a concurrent writer (even one reusing the
        # same public ``request_id``) fails closed and never proceeds to acquire.
        attempt_id = self._persist_retraction_intent(
            path_id,
            card_id,
            user_id=user_id,
            request_id=request_id,
            expected_card_revision=expected_card_revision,
            target_kb_name=target_kb_name,
            rel_path=rel_path,
            quarantine_rel=quarantine_rel,
            document_sha=document_sha,
            now=moment,
        )

        # Per-KB durable lease (``card_retract``).
        coordinator = KbWriteCoordinator(base_dir=self.kb_base_dir)
        owner = f"retract:{uuid4().hex[:12]}"
        try:
            op = coordinator.acquire(
                target_kb_name,
                "card_retract",
                owner=owner,
                request_id=request_id,
                subject_id=card_id,
                user_id=user_id,
            )
        except KbBusyError as exc:
            # The retraction never started. Clear only the intent this writer
            # durably owns: a concurrent winner's intent (a different request or
            # a same-request attempt) must never be overwritten/cleared here.
            self._clear_retraction_intent(
                path_id,
                card_id,
                user_id,
                moment,
                request_id=request_id,
                attempt_id=attempt_id,
                target_kb_name=target_kb_name,
                rel_path=rel_path,
                quarantine_rel=quarantine_rel,
                document_sha=document_sha,
                card_revision=expected_card_revision,
            )
            raise KnowledgeCardRetractionUnavailableError(
                f"target knowledge base {target_kb_name!r} is busy (kb_busy): a "
                f"{exc.operation_type} operation is {exc.status}; retry after it "
                "completes or is reconciled"
            ) from exc

        heartbeat = LeaseHeartbeat(
            coordinator,
            target_kb_name,
            op.id,
            owner=owner,
            interval=heartbeat_interval_seconds(coordinator),
        )
        heartbeat.start()

        def _lease_check() -> None:
            heartbeat.check()
            coordinator.verify_lease(target_kb_name, op.id, owner=owner)

        quarantine_root = (kb_dir / "quarantine" / FIXED_CARD_DIRECTORY).resolve()
        quarantine_path = (kb_dir / quarantine_rel).resolve()
        if not quarantine_path.is_relative_to(quarantine_root):
            raise KnowledgeCardInputValidationError(
                f"quarantine path {quarantine_rel!r} escapes {FIXED_QUARANTINE_DIRECTORY}/"
            )

        try:
            try:
                self._begin_retraction(
                    path_id,
                    card_id,
                    user_id=user_id,
                    request_id=request_id,
                    attempt_id=attempt_id,
                    expected_card_revision=expected_card_revision,
                    target_kb_name=target_kb_name,
                    rel_path=rel_path,
                    quarantine_rel=quarantine_rel,
                    document_sha=document_sha,
                    now=moment,
                    op_id=op.id,
                )
            except KnowledgeCardError:
                # Clear only this writer's exact staged intent; a concurrent
                # winner's intent/operation is never mutated by the loser.
                self._clear_retraction_intent(
                    path_id,
                    card_id,
                    user_id,
                    moment,
                    request_id=request_id,
                    attempt_id=attempt_id,
                    target_kb_name=target_kb_name,
                    rel_path=rel_path,
                    quarantine_rel=quarantine_rel,
                    document_sha=document_sha,
                    card_revision=expected_card_revision,
                )
                self._release_lease(
                    coordinator,
                    target_kb_name,
                    op.id,
                    owner,
                    error_code="retraction_did_not_start",
                    error="retraction eligibility check failed",
                )
                raise

            # ── Quarantine (requirement 5) ──
            try:
                _lease_check()
                self._quarantine_raw(kb_dir, raw_path, quarantine_path, document_sha)
                # The index evidence is NOT touched here: it is only updated
                # after the excluding reindex explicitly succeeds and ownership
                # is reverified (KB-04 P0 correction 3), so a failed reindex can
                # never leave self-written exclusion proof behind.
                _lease_check()
                self._update_record_status(
                    path_id,
                    card_id,
                    user_id,
                    request_id=request_id,
                    status=RetractionStatus.REINDEXING,
                    now=moment,
                    error_code="",
                    sanitized_error="",
                )
            except KnowledgeCardError:
                # Quarantine/hash mismatch or a record-write failure mid-flight:
                # neither deletion-side nor rollback-side success can be proven,
                # so lock retract_reconcile_required and retain every durable
                # identity. Reconcile decides from on-disk evidence.
                self._finalize_reconcile_required(
                    path_id,
                    card_id,
                    user_id=user_id,
                    coordinator=coordinator,
                    kb_name=target_kb_name,
                    op_id=op.id,
                    owner=owner,
                    request_id=request_id,
                    target_kb_name=target_kb_name,
                    rel_path=rel_path,
                    quarantine_rel=quarantine_rel,
                    document_sha=document_sha,
                    expected_revision=expected_card_revision,
                    now=moment,
                    error_code="quarantine_failed",
                    sanitized_error="quarantine could not be completed; reconcile required",
                    lease_check=None,
                )
                return self._reload_result(path_id, card_id, replayed=False)

            # ── Full production reindex over the raw set excluding the card ──
            try:
                reindex_ok, reindex_error = await heartbeat.run_guarded(
                    self._reindex_excluding(target_kb_name, kb_dir, rel_path)
                )
            except Exception as exc:  # noqa: BLE001 - failure classification
                reindex_ok, reindex_error = False, sanitize_error(str(exc))
            _lease_check()

            if reindex_ok:
                # The excluding index was built. Update the file-hash/index
                # evidence only AFTER the provider reindex explicitly succeeded
                # and ownership is reverified (correction 3); a failure to
                # persist the evidence is conservative reconcile-required, never
                # a claimed retraction.
                _lease_check()
                if not self._drop_index_evidence(kb_dir, rel_path):
                    self._mark_kb_needs_reindex(
                        target_kb_name,
                        reason=(
                            "the excluding reindex succeeded but the "
                            "index-evidence registry could not be updated; "
                            "reconcile required"
                        ),
                    )
                    self._finalize(
                        path_id,
                        card_id,
                        user_id=user_id,
                        status=KnowledgeCardStatus.RETRACT_RECONCILE_REQUIRED,
                        coordinator=coordinator,
                        kb_name=target_kb_name,
                        op_id=op.id,
                        owner=owner,
                        request_id=request_id,
                        target_kb_name=target_kb_name,
                        rel_path=rel_path,
                        quarantine_rel=quarantine_rel,
                        document_sha=document_sha,
                        expected_revision=expected_card_revision,
                        now=moment,
                        error_code="index_evidence_write_failed",
                        sanitized_error=(
                            "the excluding reindex succeeded but the "
                            "index-evidence registry could not be updated; "
                            "reconcile required"
                        ),
                        lease_check=_lease_check,
                    )
                    return self._reload_result(path_id, card_id, replayed=False)
                # Mark the durable reindex task identity (proof the excluding
                # index was built) BEFORE the terminal write.
                self._mark_reindex_done(
                    path_id, card_id, user_id, request_id=request_id, now=moment
                )
                _lease_check()
                if not kb_is_ready(self._get_manager(), target_kb_name, kb_dir):
                    self._mark_kb_needs_reindex(
                        target_kb_name,
                        reason="knowledge-card retraction left the KB not confirmably ready",
                    )
                    self._finalize(
                        path_id,
                        card_id,
                        user_id=user_id,
                        status=KnowledgeCardStatus.RETRACT_RECONCILE_REQUIRED,
                        coordinator=coordinator,
                        kb_name=target_kb_name,
                        op_id=op.id,
                        owner=owner,
                        request_id=request_id,
                        target_kb_name=target_kb_name,
                        rel_path=rel_path,
                        quarantine_rel=quarantine_rel,
                        document_sha=document_sha,
                        expected_revision=expected_card_revision,
                        now=moment,
                        error_code="kb_not_ready_after_retraction_reindex",
                        sanitized_error=(
                            "the KB is not confirmably ready after the excluding reindex"
                        ),
                        lease_check=_lease_check,
                    )
                else:
                    finalized = self._finalize(
                        path_id,
                        card_id,
                        user_id=user_id,
                        status=KnowledgeCardStatus.RETRACTED,
                        coordinator=coordinator,
                        kb_name=target_kb_name,
                        op_id=op.id,
                        owner=owner,
                        request_id=request_id,
                        target_kb_name=target_kb_name,
                        rel_path=rel_path,
                        quarantine_rel=quarantine_rel,
                        document_sha=document_sha,
                        expected_revision=expected_card_revision,
                        now=moment,
                        error_code="",
                        sanitized_error="",
                        lease_check=_lease_check,
                    )
                    # Complete the quarantine lifecycle only after the exact
                    # retraction was durably finalized: first the retracted write
                    # durably persisted cleanup pending, then hash/path-check and
                    # delete only the matching quarantine copy, then durably
                    # record cleaned/failed. A cleanup failure never reverts the
                    # proven retraction and never deletes other bytes (KB-04
                    # review round 1 corrections 2/3).
                    if finalized:
                        self._complete_quarantine_cleanup_for_record(
                            path_id,
                            card_id,
                            user_id,
                            request_id=request_id,
                            now=moment,
                        )
                return self._reload_result(path_id, card_id, replayed=False)

            # ── Definite reindex failure → roll back (requirement 7) ──
            _lease_check()
            try:
                await self._rollback(
                    path_id,
                    card_id,
                    user_id=user_id,
                    request_id=request_id,
                    target_kb_name=target_kb_name,
                    rel_path=rel_path,
                    quarantine_rel=quarantine_rel,
                    document_sha=document_sha,
                    expected_revision=expected_card_revision,
                    now=moment,
                    coordinator=coordinator,
                    op_id=op.id,
                    owner=owner,
                    kb_dir=kb_dir,
                    raw_path=raw_path,
                    quarantine_path=quarantine_path,
                    lease_check=_lease_check,
                    run_guarded=heartbeat.run_guarded,
                )
            except KbLeaseError:
                # Lease lost during rollback — never resolve another holder's
                # operation and never claim published without proof.
                self._finalize_reconcile_required(
                    path_id,
                    card_id,
                    user_id=user_id,
                    coordinator=coordinator,
                    kb_name=target_kb_name,
                    op_id=op.id,
                    owner=owner,
                    request_id=request_id,
                    target_kb_name=target_kb_name,
                    rel_path=rel_path,
                    quarantine_rel=quarantine_rel,
                    document_sha=document_sha,
                    expected_revision=expected_card_revision,
                    now=moment,
                    error_code="kb_lease_lost",
                    sanitized_error=(
                        "retraction rollback lease was lost or unknown; reconcile required"
                    ),
                    lease_check=None,
                    resolve=False,
                )
                return self._reload_result(path_id, card_id, replayed=False)
            except Exception as exc:  # noqa: BLE001 - failure-of-failure
                # Ambiguous rollback — neither published nor retracted is provable.
                # Lock retract_reconcile_required, retain every durable identity,
                # and mark the KB needs_reindex (requirement 8).
                self._mark_kb_needs_reindex(
                    target_kb_name,
                    reason=("knowledge-card retraction rollback could not be fully confirmed"),
                )
                self._finalize_reconcile_required(
                    path_id,
                    card_id,
                    user_id=user_id,
                    coordinator=coordinator,
                    kb_name=target_kb_name,
                    op_id=op.id,
                    owner=owner,
                    request_id=request_id,
                    target_kb_name=target_kb_name,
                    rel_path=rel_path,
                    quarantine_rel=quarantine_rel,
                    document_sha=document_sha,
                    expected_revision=expected_card_revision,
                    now=moment,
                    error_code="rollback_ambiguous",
                    sanitized_error=sanitize_error(str(exc)),
                    lease_check=None,
                )
                return self._reload_result(path_id, card_id, replayed=False)
            # A fully confirmed rollback returned the card to immutable
            # ``published`` (finalized inside ``_rollback``).
            return self._reload_result(path_id, card_id, replayed=False)
        except KbLeaseError:
            # Lease lost or unknown during quarantine/reindex: never mark the
            # card retracted/published and never resolve another holder's
            # operation. Converge conservatively to a recoverable reconcile state
            # with no further KB mutation.
            self._finalize_reconcile_required(
                path_id,
                card_id,
                user_id=user_id,
                coordinator=coordinator,
                kb_name=target_kb_name,
                op_id=op.id,
                owner=owner,
                request_id=request_id,
                target_kb_name=target_kb_name,
                rel_path=rel_path,
                quarantine_rel=quarantine_rel,
                document_sha=document_sha,
                expected_revision=expected_card_revision,
                now=moment,
                error_code="kb_lease_lost",
                sanitized_error="retraction lease was lost or unknown; reconcile required",
                lease_check=None,
                resolve=False,
            )
            return self._reload_result(path_id, card_id, replayed=False)
        finally:
            await heartbeat.stop()

    # ── idempotency / start-state resolution ────────────────────────────────

    def _resolve_retraction_basis(
        self, progress: LearningProgress, card: KnowledgeCardRecord, *, request_id: str
    ) -> str:
        """Resolve the retraction idempotency start-state.

        Returns ``"replay"`` (same request, same payload), ``"reconcile_required"``
        (unresolved prior retraction), ``"already_retracted"``, ``"active"`` (a
        different request holds the active retraction), or ``None`` (a fresh
        retraction is allowed).
        """
        latest = self._latest_retraction_for_revision(progress, card)
        if latest is None:
            if card.status == KnowledgeCardStatus.RETRACTED:
                return "replay"
            if card.retraction_intent is not None:
                # A published card carrying a durable staged retraction intent
                # with no record is not a fresh retraction: another attempt (even
                # the same public ``request_id``) holds the crash-recovery bridge
                # until an explicit reconcile proves and clears it (KB-04 review
                # round 2). A new retraction must never overwrite that intent or
                # acquire a new operation underneath it.
                return "reconcile_required"
            return None
        fingerprint = retraction_fingerprint(
            card.revision, card.target_kb_name, card.document_rel_path, card.document_sha256
        )
        stored_fingerprint = retraction_fingerprint(
            latest.card_revision,
            latest.target_kb_name,
            latest.original_rel_path,
            latest.document_sha256,
        )
        if latest.request_id == request_id:
            if stored_fingerprint != fingerprint:
                raise KnowledgeCardRetractionConflictError(
                    f"retraction request_id {latest.request_id!r} reused with "
                    f"different facts on card {card.id!r}; a new revision or a "
                    "new request id is required"
                )
            if latest.status not in TERMINAL_RETRACTION_STATUSES:
                # The same in-flight retraction is replayed, never restarted.
                return "replay"
            if latest.status == RetractionStatus.RETRACTED:
                return "replay"
            if latest.status == RetractionStatus.RECONCILE_REQUIRED:
                return "reconcile_required"
            if latest.status == RetractionStatus.FAILED:
                if card.status != KnowledgeCardStatus.PUBLISHED:
                    return "reconcile_required"
                # A confirmed failed rollback returned the card to published; the
                # same request replays the failure rather than silently re-mutating.
                return "replay"
        # Different request id.
        if latest.status not in TERMINAL_RETRACTION_STATUSES:
            return "active"
        if latest.status == RetractionStatus.RETRACTED:
            return "already_retracted"
        if latest.status == RetractionStatus.RECONCILE_REQUIRED:
            return "reconcile_required"
        if (
            latest.status == RetractionStatus.FAILED
            and card.status == KnowledgeCardStatus.PUBLISHED
        ):
            # A confirmed failed rollback; a fresh retraction is allowed.
            return None
        return "reconcile_required"

    # ── durable retraction intent (crash-safe two-phase protocol) ─────────

    @staticmethod
    def _retraction_intent_matches(
        card: KnowledgeCardRecord,
        *,
        request_id: str,
        attempt_id: str,
        target_kb_name: str = "",
        rel_path: str = "",
        quarantine_rel: str = "",
        document_sha: str = "",
        card_revision: int = 0,
    ) -> bool:
        """True only when *card* still carries the exact expected staged intent.

        Compares the internal attempt token, the public request id, and (when
        supplied) every durable fact of the staged retraction. An empty
        ``attempt_id`` (a legacy intent persisted before the review-round-2
        field) matches on the remaining identity so it can still be cleared.
        """
        intent = card.retraction_intent
        if intent is None:
            return False
        if request_id and intent.request_id != request_id:
            return False
        if attempt_id and intent.attempt_id != attempt_id:
            return False
        if target_kb_name and intent.target_kb_name != target_kb_name:
            return False
        if rel_path and intent.original_rel_path != rel_path:
            return False
        if quarantine_rel and intent.quarantine_rel_path != quarantine_rel:
            return False
        if document_sha and intent.document_sha256 != document_sha:
            return False
        if card_revision and intent.card_revision != card_revision:
            return False
        if card.retraction_request_id != request_id:
            return False
        return True

    def _persist_retraction_intent(
        self,
        path_id: str,
        card_id: str,
        *,
        user_id: str,
        request_id: str,
        expected_card_revision: int,
        target_kb_name: str,
        rel_path: str,
        quarantine_rel: str,
        document_sha: str,
        now: float,
    ) -> str:
        """Durably record the retraction intent *before* lease acquisition.

        Returns the caller's internal ``attempt_id`` only when the caller
        durably owns the exact staged intent. Closes the crash window between
        ``coordinator.acquire`` and the durable ``retracting`` transition: if
        the process dies after this save but before operation-id attachment,
        ``reconcile-retraction`` can still locate the exact orphan
        ``card_retract`` operation from the intent's durable target + subject +
        request identity.

        Under the store CAS the loop either atomically creates the caller's
        exact intent (reporting ownership) or detects an existing intent. An
        existing different attempt — another request, or a concurrent writer
        reusing the same public ``request_id`` — fails closed with
        :class:`KnowledgeCardReconcileRequiredError` so the caller never
        overwrites the winner's crash-recovery bridge or proceeds to acquire
        (KB-04 review round 2).
        """
        attempt_id = uuid4().hex
        while True:
            progress = self._load(path_id)
            card = require_card(progress, card_id)
            self._require_ownership_and_path(progress, card, user_id)
            if card.status != KnowledgeCardStatus.PUBLISHED:
                raise KnowledgeCardStateError(
                    f"card {card_id!r} is {card.status.value}; retraction requires a published card"
                )
            if card.revision != expected_card_revision:
                raise KnowledgeCardStaleVersionError(
                    f"card {card_id!r} revision conflict: expected "
                    f"{expected_card_revision}, current {card.revision}"
                )
            existing = card.retraction_intent
            if existing is not None:
                if (
                    existing.attempt_id == attempt_id
                    and existing.request_id == request_id
                    and existing.card_revision == expected_card_revision
                    and existing.target_kb_name == target_kb_name
                    and existing.original_rel_path == rel_path
                    and existing.quarantine_rel_path == quarantine_rel
                    and existing.document_sha256 == document_sha
                ):
                    # A CAS retry of this same writer: the exact attempt already
                    # durably owns the bridge.
                    return attempt_id
                raise KnowledgeCardReconcileRequiredError(
                    f"card {card_id!r} already carries a durable retraction "
                    "intent; reconcile the pending retraction before retrying"
                )
            card.retraction_intent = RetractionIntent(
                target_kb_name=target_kb_name,
                request_id=request_id,
                attempt_id=attempt_id,
                original_rel_path=rel_path,
                quarantine_rel_path=quarantine_rel,
                document_sha256=document_sha,
                card_revision=expected_card_revision,
                created_at=now,
            )
            card.retraction_request_id = request_id
            card.updated_at = now
            card.version += 1
            try:
                self.save(progress)
            except KnowledgeCardStaleVersionError:
                continue
            return attempt_id

    def _clear_retraction_intent(
        self,
        path_id: str,
        card_id: str,
        user_id: str,
        now: float,
        *,
        request_id: str,
        attempt_id: str,
        target_kb_name: str = "",
        rel_path: str = "",
        quarantine_rel: str = "",
        document_sha: str = "",
        card_revision: int = 0,
        coordinator: KbWriteCoordinator | None = None,
    ) -> bool:
        """Durably clear the exact staged intent owned by the caller.

        Returns ``True`` only when the reloaded card still carries the exact
        expected intent (request/attempt/facts match), is still ``published``,
        has no operation linkage, and — for the reconcile no-operation path —
        no current target-KB operation appeared at the commit boundary. Any
        drift — a concurrent writer replaced the intent, the card left
        ``published``, an operation was attached, or a current target-KB
        operation appeared — is a no-op returning ``False`` so a stale handler
        can never remove a concurrent winner's intent/operation (KB-04 review
        round 2).
        """
        while True:
            progress = self._load(path_id)
            card = require_card(progress, card_id)
            self._require_ownership_and_path(progress, card, user_id)
            if not self._retraction_intent_matches(
                card,
                request_id=request_id,
                attempt_id=attempt_id,
                target_kb_name=target_kb_name,
                rel_path=rel_path,
                quarantine_rel=quarantine_rel,
                document_sha=document_sha,
                card_revision=card_revision,
            ):
                return False
            if card.status != KnowledgeCardStatus.PUBLISHED:
                return False
            if card.retraction_operation_id:
                return False
            if coordinator is not None and target_kb_name:
                current_op = coordinator.current_operation(target_kb_name)
                if current_op is not None:
                    return False
            card.retraction_intent = None
            card.retraction_request_id = ""
            card.updated_at = now
            card.version += 1
            try:
                self.save(progress)
            except KnowledgeCardStaleVersionError:
                continue
            return True

    def _matching_orphan_operation(
        self, coordinator: KbWriteCoordinator, intent: RetractionIntent, card_id: str
    ) -> Any:
        """Locate the exact orphan ``card_retract`` operation for *intent*.

        Returns ``None`` when there is no operation, the current operation is a
        different type/subject/request, or it is already terminal (not
        ``reconcile_required``) — the caller must never guess or release another
        card's operation.
        """
        if not intent.target_kb_name:
            return None
        op = coordinator.current_operation(intent.target_kb_name)
        if op is None:
            return None
        if op.operation_type != "card_retract":
            return None
        if not op.subject_id or op.subject_id != card_id:
            return None
        if not op.request_id or not intent.request_id:
            return None
        if op.request_id != intent.request_id:
            return None
        if op.status in ("succeeded", "failed"):
            return None
        return op

    # ── begin / phase transitions ──────────────────────────────────────────

    def _begin_retraction(
        self,
        path_id: str,
        card_id: str,
        *,
        user_id: str,
        request_id: str,
        attempt_id: str,
        expected_card_revision: int,
        target_kb_name: str,
        rel_path: str,
        quarantine_rel: str,
        document_sha: str,
        now: float,
        op_id: str,
    ) -> tuple[LearningProgress, KnowledgeCardRecord, KnowledgeCardRetractionRecord]:
        """Durably transition the card to ``retracting`` and attach the operation.

        Runs under the store CAS: a conflicting save reloads and re-applies so a
        concurrent writer can never be overwritten. The prior retraction record
        is re-resolved by durable key on every CAS retry.

        Only the writer that durably owns the exact staged intent may begin: if
        the reloaded card carries a different intent (or no intent at all — the
        crash-recovery bridge was lost), the begin fails closed so a losing
        concurrent caller can never mutate the winning intent/operation (KB-04
        review round 2).
        """
        while True:
            progress = self._load(path_id)
            card = require_card(progress, card_id)
            self._require_ownership_and_path(progress, card, user_id)
            if card.status != KnowledgeCardStatus.PUBLISHED:
                raise KnowledgeCardStateError(
                    f"card {card_id!r} is {card.status.value}; retraction requires a published card"
                )
            if card.revision != expected_card_revision:
                raise KnowledgeCardStaleVersionError(
                    f"card {card_id!r} revision conflict: expected "
                    f"{expected_card_revision}, current {card.revision}"
                )
            if not self._retraction_intent_matches(
                card,
                request_id=request_id,
                attempt_id=attempt_id,
                target_kb_name=target_kb_name,
                rel_path=rel_path,
                quarantine_rel=quarantine_rel,
                document_sha=document_sha,
                card_revision=expected_card_revision,
            ):
                raise KnowledgeCardStateError(
                    f"card {card_id!r} retraction intent is owned by a different "
                    "attempt; reload and reconcile before retracting"
                )
            active = self._active_retraction_for_revision(progress, card)
            if active is not None and active.request_id != request_id:
                raise KnowledgeCardStateError(
                    f"card {card_id!r} already has an active retraction for this revision"
                )

            card.status = KnowledgeCardStatus.RETRACTING
            card.retraction_operation_id = op_id
            card.retraction_request_id = request_id
            card.quarantine_rel_path = quarantine_rel
            if card.retraction_intent is not None:
                card.retraction_intent.operation_id = op_id
            card.error_code = ""
            card.sanitized_error = ""
            card.updated_at = now
            card.version += 1

            record = self._latest_retraction_for_revision(progress, card)
            if record is not None and record.status not in TERMINAL_RETRACTION_STATUSES:
                # Reuse the active record (idempotent begin under CAS retry).
                record.status = RetractionStatus.QUARANTINING
                record.operation_id = op_id
                record.updated_at = now
                record.started_at = record.started_at or now
                record.error_code = ""
                record.sanitized_error = ""
            else:
                record = KnowledgeCardRetractionRecord(
                    id=uuid4().hex,
                    card_id=card.id,
                    card_revision=card.revision,
                    user_id=user_id,
                    target_kb_name=target_kb_name,
                    request_id=request_id,
                    status=RetractionStatus.QUARANTINING,
                    operation_id=op_id,
                    original_rel_path=rel_path,
                    quarantine_rel_path=quarantine_rel,
                    document_sha256=document_sha,
                    created_at=now,
                    started_at=now,
                    updated_at=now,
                )
                progress.knowledge_card_retraction_records.append(record)

            append_history(
                progress,
                _EVENT_RETRACTION_STARTED,
                aggregate="",
                summary=f"card {card.id} retraction from {target_kb_name!r} started",
                payload={
                    "card_id": card.id,
                    "request_id": request_id,
                    "target_kb_name": target_kb_name,
                    "original_rel_path": rel_path,
                    "quarantine_rel_path": quarantine_rel,
                    "document_sha256": document_sha,
                    "record_id": record.id,
                    "operation_id": op_id,
                    "user_id": user_id,
                },
            )
            try:
                self.save(progress)
            except KnowledgeCardStaleVersionError:
                continue
            return progress, card, record

    def _update_record_status(
        self,
        path_id: str,
        card_id: str,
        user_id: str,
        *,
        request_id: str,
        status: RetractionStatus,
        now: float,
        error_code: str,
        sanitized_error: str,
    ) -> None:
        """Transition the active retraction record's status under the store CAS."""
        while True:
            progress = self._load(path_id)
            card = require_card(progress, card_id)
            self._require_ownership_and_path(progress, card, user_id)
            record = self._active_retraction_for_revision(progress, card)
            if record is None or record.request_id != request_id:
                return
            if record.status == status:
                return
            record.status = status
            record.updated_at = now
            record.error_code = error_code
            record.sanitized_error = sanitized_error
            try:
                self.save(progress)
            except KnowledgeCardStaleVersionError:
                continue
            return

    def _mark_reindex_done(
        self,
        path_id: str,
        card_id: str,
        user_id: str,
        *,
        request_id: str,
        now: float,
    ) -> None:
        """Durably record the excluding-reindex task identity (proof it ran)."""
        while True:
            progress = self._load(path_id)
            card = require_card(progress, card_id)
            self._require_ownership_and_path(progress, card, user_id)
            record = self._active_retraction_for_revision(progress, card)
            if record is None or record.request_id != request_id:
                return
            if record.index_task_id:
                return
            record.index_task_id = uuid4().hex
            record.updated_at = now
            try:
                self.save(progress)
            except KnowledgeCardStaleVersionError:
                continue
            return

    # ── KB volume quarantine / restore / evidence ─────────────────────────

    @staticmethod
    def _quarantine_raw(
        kb_dir: Path,
        raw_path: Path,
        quarantine_path: Path,
        document_sha: str,
    ) -> None:
        """Hash-verify then atomically move the exact raw file into quarantine.

        ``os.replace`` is atomic on the same volume (no copy-and-delete race).
        The only recoverable bytes are never permanently deleted — the original
        path is emptied only by the atomic move into the deterministic
        quarantine path (§7.11 requirement 5).
        """
        if quarantine_path.exists():
            q_sha = _sha256_of_file(quarantine_path)
            if q_sha == document_sha:
                if raw_path.exists():
                    r_sha = _sha256_of_file(raw_path)
                    if r_sha == document_sha:
                        # Both copies identical (a retry after a partial rollback
                        # re-added the raw file); the quarantine copy survives.
                        raw_path.unlink()
                        return
                    raise KnowledgeCardStateError(
                        "quarantine already holds the document but the raw file "
                        "differs; retraction fails closed"
                    )
                return  # already quarantined
            raise KnowledgeCardStateError(
                "quarantine path is occupied by different bytes; retraction fails closed"
            )
        if not raw_path.is_file():
            raise KnowledgeCardStateError(f"raw document {raw_path} is missing; cannot quarantine")
        raw_sha = _sha256_of_file(raw_path)
        if raw_sha != document_sha:
            raise KnowledgeCardStateError(
                "raw document bytes changed before quarantine; retraction fails closed"
            )
        quarantine_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(str(raw_path), str(quarantine_path))

    @staticmethod
    def _restore_raw(
        kb_dir: Path,
        raw_path: Path,
        quarantine_path: Path,
        document_sha: str,
    ) -> None:
        """Atomically restore the exact quarantine bytes to the original path.

        Both copies are hash-verified before any removal; the only recoverable
        bytes are never lost (§7.11 requirement 7).
        """
        if not quarantine_path.is_file():
            if raw_path.is_file() and _sha256_of_file(raw_path) == document_sha:
                return  # already restored
            raise KnowledgeCardStateError(
                "quarantine bytes are missing; cannot restore the original document"
            )
        q_sha = _sha256_of_file(quarantine_path)
        if q_sha != document_sha:
            raise KnowledgeCardStateError(
                "quarantine bytes do not match the published SHA-256; cannot restore"
            )
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        if raw_path.exists():
            r_sha = _sha256_of_file(raw_path)
            if r_sha == document_sha:
                # Both copies identical; the restore is done — remove the quarantine
                # copy (the original survives at its fixed path).
                quarantine_path.unlink()
                return
            raise KnowledgeCardStateError(
                "the original path is occupied by different bytes; cannot restore"
            )
        os.replace(str(quarantine_path), str(raw_path))

    @staticmethod
    def _drop_index_evidence(kb_dir: Path, rel_path: str) -> bool:
        """Remove the fixed document's hash from the KB index-evidence registry.

        Called only AFTER the excluding reindex explicitly succeeds and
        ownership is reverified (KB-04 P0 correction 3): before success the
        prior evidence is left intact so a failed reindex can never leave a
        self-written "excluded" claim behind. Returns ``True`` when the entry is
        durably absent, ``False`` when the registry could not be updated — the
        caller converges conservatively to ``retract_reconcile_required`` rather
        than manufacturing index proof.
        """
        metadata_file = kb_dir / "metadata.json"
        if not metadata_file.exists():
            return True  # no registry entry claims the document
        try:
            metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - unreadable metadata cannot be updated
            return False
        if not isinstance(metadata, dict):
            return False
        hashes = metadata.get("file_hashes")
        if not isinstance(hashes, dict) or rel_path not in hashes:
            return True  # already absent
        try:
            del hashes[rel_path]
            atomic_write_json(metadata_file, metadata)
        except Exception as exc:  # noqa: BLE001 - failure-of-failure, no false proof
            logger.warning(
                "could not drop index evidence for %s on %s: %s",
                rel_path,
                kb_dir,
                sanitize_error(str(exc)),
            )
            return False
        return True

    @staticmethod
    def _add_index_evidence(kb_dir: Path, rel_path: str, document_sha: str) -> bool:
        """Record the restored document's hash in the index-evidence registry.

        Called only AFTER the rollback reindex explicitly succeeds and ownership
        is reverified (KB-04 P0 correction 3): a failure to persist the evidence
        must never let reconcile claim restoration the provider did not confirm.
        Returns ``True`` when the entry is durably present, ``False`` otherwise.
        """
        metadata_file = kb_dir / "metadata.json"
        metadata: dict[str, Any] = {}
        if metadata_file.exists():
            try:
                metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001 - unreadable metadata cannot be updated
                return False
        if not isinstance(metadata, dict):
            return False
        try:
            hashes = metadata.setdefault("file_hashes", {})
            hashes[rel_path] = document_sha
            atomic_write_json(metadata_file, metadata)
        except Exception as exc:  # noqa: BLE001 - failure-of-failure, no false proof
            logger.warning(
                "could not add index evidence for %s on %s: %s",
                rel_path,
                kb_dir,
                sanitize_error(str(exc)),
            )
            return False
        return True

    @staticmethod
    def _index_evidence(kb_dir: Path, rel_path: str) -> str | None:
        """The recorded SHA in the KB ``metadata.json`` ``file_hashes`` registry."""
        metadata_file = kb_dir / "metadata.json"
        if not metadata_file.exists():
            return None
        try:
            metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - unreadable metadata is absent evidence
            return None
        if not isinstance(metadata, dict):
            return None
        hashes = metadata.get("file_hashes")
        if not isinstance(hashes, dict):
            return None
        value = hashes.get(rel_path)
        return str(value) if value else None

    @staticmethod
    def _excluding_raw_paths(kb_dir: Path, excluded_rel_path: str) -> list[str]:
        """The supported raw file set for a full reindex that excludes *rel_path*.

        Mirrors the set ``_reindex_excluding`` would hand to the provider after
        the card is quarantined (the fixed document is the only file absent).
        """
        raw_dir = kb_dir / "raw"
        if not raw_dir.is_dir():
            return []
        file_paths = [
            str(path) for path in FileTypeRouter.collect_supported_files(raw_dir, recursive=True)
        ]
        excluded = (raw_dir / excluded_rel_path).resolve()
        return [path for path in file_paths if Path(path).resolve() != excluded]

    async def _reindex_excluding(
        self, kb_name: str, kb_dir: Path, excluded_rel_path: str
    ) -> tuple[bool, str]:
        """Trigger the existing production full-reindex path over the raw set that
        excludes the quarantined card.

        Returns ``(True, "")`` only when the provider reindex explicitly
        succeeds. A truthy-looking ``False`` and any exception are failures. The
        raw set is enumerated with the production ``FileTypeRouter``; the
        quarantined card's fixed path is absent because the file was atomically
        moved out of ``raw/``.
        """
        file_paths = self._excluding_raw_paths(kb_dir, excluded_rel_path)
        if not file_paths:
            # Fail-closed contract: an empty raw set is not a normal provider
            # failure. ``retract`` refuses to mutate a single-document KB before
            # any KB change, so this is only reachable defensively.
            return False, "the excluding raw set is empty; nothing to reindex"
        rag_service = RAGService(kb_base_dir=str(self.kb_base_dir), provider=None)
        success = await rag_service.initialize(kb_name=kb_name, file_paths=file_paths)
        if not success:
            return False, "the provider reported no documents were indexed"
        return True, ""

    # ── rollback (requirement 7) ────────────────────────────────────────────

    async def _rollback(
        self,
        path_id: str,
        card_id: str,
        *,
        user_id: str,
        request_id: str,
        target_kb_name: str,
        rel_path: str,
        quarantine_rel: str,
        document_sha: str,
        expected_revision: int,
        now: float,
        coordinator: KbWriteCoordinator,
        op_id: str,
        owner: str,
        kb_dir: Path,
        raw_path: Path,
        quarantine_path: Path,
        lease_check: Callable[[], None],
        run_guarded: Callable[[Any], Any],
    ) -> None:
        """Restore the exact quarantine bytes and reindex the restored set.

        Only a fully confirmed rollback returns the card to immutable
        ``published`` with a failed retraction record. Ambiguity raises (the
        caller locks ``retract_reconcile_required`` + ``needs_reindex``).

        The including reindex is heartbeat-guarded exactly like the excluding
        one: a lost lease aborts/cancels the in-flight reindex instead of
        letting a stale writer keep mutating the provider under a newer holder
        (KB-04 P0 correction 4). The file-hash/index evidence is only re-added
        AFTER the rollback reindex explicitly succeeds and ownership is
        reverified (correction 3).
        """
        lease_check()
        self._update_record_status(
            path_id,
            card_id,
            user_id,
            request_id=request_id,
            status=RetractionStatus.ROLLING_BACK,
            now=now,
            error_code="reindex_failed",
            sanitized_error="the excluding reindex failed; rolling back the document",
        )
        # Restore the exact bytes, then reindex the restored set; the index
        # evidence is updated only after the provider explicitly succeeds.
        self._restore_raw(kb_dir, raw_path, quarantine_path, document_sha)
        lease_check()
        reindex_ok, reindex_error = await run_guarded(
            self._reindex_including(kb_name=target_kb_name, kb_dir=kb_dir, rel_path=rel_path)
        )
        if not reindex_ok:
            raise KnowledgeCardStateError(f"rollback reindex failed: {reindex_error or 'unknown'}")
        lease_check()
        if not self._add_index_evidence(kb_dir, rel_path, document_sha):
            raise KnowledgeCardStateError(
                "the rollback reindex succeeded but the index-evidence registry "
                "could not be updated; reconcile required"
            )
        lease_check()
        if not kb_is_ready(self._get_manager(), target_kb_name, kb_dir):
            raise KnowledgeCardStateError(
                "the KB is not confirmably ready after the rollback reindex"
            )
        # Confirm raw hash + index evidence before finalizing published.
        if _sha256_of_file(raw_path) != document_sha:
            raise KnowledgeCardStateError("restored raw bytes do not match the published SHA-256")
        if self._index_evidence(kb_dir, rel_path) != document_sha:
            raise KnowledgeCardStateError(
                "the restored document is not recorded in the index evidence"
            )
        lease_check()
        self._finalize(
            path_id,
            card_id,
            user_id=user_id,
            status=KnowledgeCardStatus.PUBLISHED,
            coordinator=coordinator,
            kb_name=target_kb_name,
            op_id=op_id,
            owner=owner,
            request_id=request_id,
            target_kb_name=target_kb_name,
            rel_path=rel_path,
            quarantine_rel=quarantine_rel,
            document_sha=document_sha,
            expected_revision=expected_revision,
            now=now,
            error_code="retraction_failed",
            sanitized_error=("the excluding reindex failed and the rollback was fully confirmed"),
            lease_check=lease_check,
        )

    async def _reindex_including(
        self, kb_name: str, kb_dir: Path, rel_path: str
    ) -> tuple[bool, str]:
        """Full production reindex over the restored raw set (card included)."""
        raw_dir = kb_dir / "raw"
        if not raw_dir.is_dir():
            return False, "the KB has no raw directory to reindex"
        file_paths = [
            str(path) for path in FileTypeRouter.collect_supported_files(raw_dir, recursive=True)
        ]
        if not file_paths:
            return False, "the restored raw set is empty; nothing to reindex"
        rag_service = RAGService(kb_base_dir=str(self.kb_base_dir), provider=None)
        success = await rag_service.initialize(kb_name=kb_name, file_paths=file_paths)
        if not success:
            return False, "the provider reported no documents were indexed"
        return True, ""

    # ── terminal finalization ───────────────────────────────────────────────

    def _mark_kb_needs_reindex(self, kb_name: str, *, reason: str) -> None:
        try:
            self._get_manager().mark_needs_reindex(kb_name, reason=reason)
        except Exception as exc:  # noqa: BLE001 - failure-of-failure
            logger.warning("could not mark KB '%s' needs_reindex: %s", kb_name, exc)

    def _finalize(
        self,
        path_id: str,
        card_id: str,
        *,
        user_id: str,
        status: KnowledgeCardStatus,
        coordinator: KbWriteCoordinator,
        kb_name: str,
        op_id: str,
        owner: str,
        request_id: str,
        target_kb_name: str,
        rel_path: str,
        quarantine_rel: str,
        document_sha: str,
        expected_revision: int,
        now: float,
        error_code: str,
        sanitized_error: str,
        lease_check: Callable[[], None] | None = None,
        resolve: bool = True,
    ) -> bool:
        """Apply a terminal retraction state under the store CAS.

        Before the terminal card write, ``lease_check`` (when provided) proves
        the exact operation is still current and owned — a newer
        upload/delete/reindex or a lost/unknown lease therefore prevents a stale
        ``retracted``/``published`` finalization. ``retracted`` is only ever
        written when the excluding index is already confirmed; ``published`` only
        when the rollback was fully confirmed. The per-KB lease is released (or
        left for reconcile) after the card state is durable.

        Returns ``True`` only when the exact terminal write durably applied to
        the exact request/revision/operation (or the card was already durably in
        that exact ``retracted`` snapshot). Returns ``False`` when the CAS loop
        bailed out — a newer operation owns the card, it left the retraction
        lifecycle, or it is an immutable terminal snapshot this finalization is
        not bound to. A caller must never clean up KB bytes after a non-applied
        finalization (KB-04 review round 1 finding 3).
        """
        if lease_check is not None:
            lease_check()

        applied = False
        try:
            while True:
                progress = self._load(path_id)
                card = require_card(progress, card_id)
                if card.status == KnowledgeCardStatus.RETRACTED:
                    # Immutable terminal snapshot. Proven only when it is the
                    # exact operation/revision this finalization is bound to;
                    # anything else is drift the caller must not clean up after.
                    if (
                        status == KnowledgeCardStatus.RETRACTED
                        and card.revision == expected_revision
                        and (
                            not card.retraction_operation_id
                            or card.retraction_operation_id == op_id
                        )
                    ):
                        applied = True
                    break
                if card.retraction_operation_id and card.retraction_operation_id != op_id:
                    break  # a newer retraction owns the operation
                if card.status not in (
                    KnowledgeCardStatus.RETRACTING,
                    KnowledgeCardStatus.RETRACT_RECONCILE_REQUIRED,
                ):
                    break  # the card left retracting; don't clobber a concurrent decision
                if card.revision != expected_revision:
                    status = KnowledgeCardStatus.RETRACT_RECONCILE_REQUIRED
                    error_code = error_code or "card_revision_changed_during_retraction"
                    sanitized_error = sanitized_error or ("card revision changed during retraction")
                card.status = status
                card.error_code = error_code
                card.sanitized_error = sanitized_error
                card.updated_at = now
                card.version += 1
                if status == KnowledgeCardStatus.RETRACTED:
                    card.retracted_at = card.retracted_at or now
                if status == KnowledgeCardStatus.PUBLISHED:
                    card.published_at = card.published_at or now
                # A terminal outcome clears the staged intent; an ambiguous
                # reconcile-required state retains it so the orphan stays
                # discoverable.
                if status != KnowledgeCardStatus.RETRACT_RECONCILE_REQUIRED:
                    card.retraction_intent = None
                self._append_retraction_record_terminal(
                    progress,
                    card,
                    status=status,
                    request_id=request_id,
                    target_kb_name=target_kb_name,
                    rel_path=rel_path,
                    quarantine_rel=quarantine_rel,
                    document_sha=document_sha,
                    error_code=error_code,
                    sanitized_error=sanitized_error,
                    now=now,
                )
                append_history(
                    progress,
                    self._event_type_for(status),
                    aggregate="",
                    summary=self._summary_for(status, card, kb_name),
                    payload={
                        "card_id": card.id,
                        "request_id": request_id,
                        "target_kb_name": kb_name,
                        "original_rel_path": rel_path,
                        "quarantine_rel_path": quarantine_rel,
                        "document_sha256": document_sha,
                        "operation_id": op_id,
                        "error_code": error_code,
                        "sanitized_error": sanitized_error,
                    },
                )
                try:
                    self.save(progress)
                except KnowledgeCardStaleVersionError:
                    continue
                applied = True
                break
        except Exception as exc:  # noqa: BLE001 - failure-of-failure
            logger.error(
                "could not finalize card %s retraction (error_code=%s): %s",
                card_id,
                error_code,
                sanitize_error(str(exc)),
            )
            try:
                coordinator.resolve_manual(
                    kb_name,
                    op_id,
                    "reconcile_required",
                    error_code=error_code or "finalize_failed",
                    error=sanitize_error(str(exc)),
                    owner=owner,
                )
            except Exception:  # noqa: BLE001 - best-effort recoverable resolve
                logger.warning(
                    "could not resolve card_retract operation %s for KB '%s'",
                    op_id,
                    kb_name,
                )
            raise

        if applied:
            # After ``retracted`` is durably confirmed, release only this card's
            # live KNOWLEDGE_CARD media references (requirement 10). Ordered after
            # the card save so a crash cannot expose a still-published/recoverable
            # card's media to GC; a later reconcile re-attempts idempotently.
            if status == KnowledgeCardStatus.RETRACTED:
                self._release_media_references(card, user_id)

            if resolve:
                terminal = (
                    "succeeded"
                    if status == KnowledgeCardStatus.RETRACTED
                    else "failed"
                    if status == KnowledgeCardStatus.PUBLISHED
                    else "reconcile_required"
                )
                try:
                    coordinator.resolve_manual(
                        kb_name,
                        op_id,
                        terminal,
                        error_code=error_code or None,
                        error=sanitized_error or None,
                        owner=owner,
                    )
                except Exception:  # noqa: BLE001 - best-effort lease release
                    logger.warning(
                        "could not resolve card_retract operation %s for KB '%s'",
                        op_id,
                        kb_name,
                    )

        return applied

    def _append_retraction_record_terminal(
        self,
        progress: LearningProgress,
        card: KnowledgeCardRecord,
        *,
        status: KnowledgeCardStatus,
        request_id: str,
        target_kb_name: str,
        rel_path: str,
        quarantine_rel: str,
        document_sha: str,
        error_code: str,
        sanitized_error: str,
        now: float,
    ) -> None:
        """Set the active retraction record's terminal status (idempotent)."""
        record = self._active_retraction_for_revision(progress, card)
        if record is None or record.request_id != request_id:
            return
        target_status = self._record_status_for(status)
        if record.status == target_status:
            # Idempotent re-finalization: still ensure the post-terminal
            # quarantine cleanup is durably pending for a retracted record so a
            # crash after the terminal write but before cleanup is observable.
            if (
                status == KnowledgeCardStatus.RETRACTED
                and record.cleanup_status != CLEANUP_STATUS_CLEANED
            ):
                record.cleanup_status = CLEANUP_STATUS_PENDING
                record.cleanup_updated_at = record.cleanup_updated_at or now
            return
        record.status = target_status
        record.updated_at = now
        record.finished_at = now
        record.error_code = error_code
        record.sanitized_error = sanitized_error
        if status == KnowledgeCardStatus.RETRACTED:
            # Persist the post-terminal quarantine cleanup as pending with the
            # same terminal write (correction 2): cleanup happens only after the
            # proven retraction and stays durable/observable/retryable.
            record.cleanup_status = CLEANUP_STATUS_PENDING
            record.cleanup_error = ""
            record.cleanup_updated_at = now

    @staticmethod
    def _record_status_for(status: KnowledgeCardStatus) -> RetractionStatus:
        return {
            KnowledgeCardStatus.RETRACTED: RetractionStatus.RETRACTED,
            KnowledgeCardStatus.PUBLISHED: RetractionStatus.FAILED,
            KnowledgeCardStatus.RETRACT_RECONCILE_REQUIRED: (RetractionStatus.RECONCILE_REQUIRED),
        }[status]

    @staticmethod
    def _event_type_for(status: KnowledgeCardStatus) -> str:
        return {
            KnowledgeCardStatus.RETRACTED: _EVENT_RETRACTED,
            KnowledgeCardStatus.PUBLISHED: _EVENT_RETRACTION_FAILED,
            KnowledgeCardStatus.RETRACT_RECONCILE_REQUIRED: (_EVENT_RETRACTION_RECONCILE_REQUIRED),
        }[status]

    @staticmethod
    def _summary_for(status: KnowledgeCardStatus, card: KnowledgeCardRecord, kb_name: str) -> str:
        verb = {
            KnowledgeCardStatus.RETRACTED: "retracted",
            KnowledgeCardStatus.PUBLISHED: "retraction rolled back (failed)",
            KnowledgeCardStatus.RETRACT_RECONCILE_REQUIRED: "retraction needs reconcile",
        }[status]
        return f"card {card.id} {verb} on {kb_name!r}"

    def _finalize_reconcile_required(
        self,
        path_id: str,
        card_id: str,
        *,
        user_id: str,
        coordinator: KbWriteCoordinator,
        kb_name: str,
        op_id: str,
        owner: str,
        request_id: str,
        target_kb_name: str,
        rel_path: str,
        quarantine_rel: str,
        document_sha: str,
        expected_revision: int,
        now: float,
        error_code: str,
        sanitized_error: str,
        lease_check: Callable[[], None] | None = None,
        resolve: bool = True,
    ) -> None:
        """Converge to ``retract_reconcile_required`` retaining all durable
        identity, without resolving another holder's operation."""
        try:
            self._finalize(
                path_id,
                card_id,
                user_id=user_id,
                status=KnowledgeCardStatus.RETRACT_RECONCILE_REQUIRED,
                coordinator=coordinator,
                kb_name=kb_name,
                op_id=op_id,
                owner=owner,
                request_id=request_id,
                target_kb_name=target_kb_name,
                rel_path=rel_path,
                quarantine_rel=quarantine_rel,
                document_sha=document_sha,
                expected_revision=expected_revision,
                now=now,
                error_code=error_code,
                sanitized_error=sanitized_error,
                lease_check=lease_check,
                resolve=resolve,
            )
        except Exception as exc:  # noqa: BLE001 - failure-of-failure
            logger.error(
                "could not converge card %s retraction to reconcile_required: %s",
                card_id,
                sanitize_error(str(exc)),
            )
            raise

    def _release_media_references(self, card: KnowledgeCardRecord, user_id: str) -> None:
        """Idempotently release this card's live ``KNOWLEDGE_CARD`` references.

        Only soft-deletes references whose owner is exactly this card; never
        touches references owned by another context. Retained audit artifact ids
        on the card are unchanged. Best-effort: a failure is logged and a later
        reconcile/retry re-attempts the same idempotent release (§7.11
        requirement 10).
        """
        for artifact_id in card.artifact_ids:
            try:
                self.media_store.delete_references_for_owner(
                    artifact_id=artifact_id,
                    user_id=user_id,
                    owner_type=ReferenceOwnerType.KNOWLEDGE_CARD,
                    owner_id=card.id,
                )
            except Exception as exc:  # noqa: BLE001 - idempotent retry later
                logger.warning(
                    "could not release knowledge-card media references for card %s artifact %s: %s",
                    card.id,
                    artifact_id,
                    sanitize_error(str(exc)),
                )

    def _cleanup_quarantine(
        self, kb_dir: Path, quarantine_path: Path, document_sha: str
    ) -> tuple[str, str]:
        """Delete the matching quarantine copy only after durable retraction.

        The quarantine copy is the only recoverable bytes during the retraction;
        it is deleted only once the card is durably ``retracted`` (the excluding
        index was confirmed and the exact finalization committed). Hash-checked,
        path-contained and idempotent: mismatched bytes or an out-of-sandbox path
        are never touched, and a missing file is already-clean.

        Returns ``(CLEANUP_STATUS_CLEANED, "")`` when the matching copy is
        durably gone, or ``(CLEANUP_STATUS_FAILED, reason)`` when the copy is
        retained (mismatched bytes, escaped path, or an ``OSError`` on unlink).
        The caller records the outcome durably; a failure never reverts the
        proven retraction (KB-04 review round 1 corrections 2/3).
        """
        if not quarantine_path.is_file():
            return CLEANUP_STATUS_CLEANED, ""
        if _sha256_of_file(quarantine_path) != document_sha:
            return CLEANUP_STATUS_FAILED, (
                "quarantine bytes do not match the published SHA-256; copy retained"
            )
        quarantine_root = (kb_dir / "quarantine" / FIXED_CARD_DIRECTORY).resolve()
        if not quarantine_path.resolve().is_relative_to(quarantine_root):
            return CLEANUP_STATUS_FAILED, (
                f"quarantine path escapes {FIXED_QUARANTINE_DIRECTORY}/; copy retained"
            )
        try:
            quarantine_path.unlink()
        except OSError as exc:
            return CLEANUP_STATUS_FAILED, sanitize_error(str(exc))
        return CLEANUP_STATUS_CLEANED, ""

    def _persist_cleanup_state(
        self,
        path_id: str,
        card_id: str,
        user_id: str,
        *,
        request_id: str,
        cleanup_status: str,
        error: str,
        now: float,
    ) -> None:
        """Durably record the post-terminal quarantine cleanup state on the exact
        retraction record under the store CAS (append-only history preserved)."""
        while True:
            progress = self._load(path_id)
            card = require_card(progress, card_id)
            self._require_ownership_and_path(progress, card, user_id)
            record = self._latest_retraction_for_revision(progress, card)
            if record is None or record.request_id != request_id:
                return
            if record.cleanup_status == cleanup_status and record.cleanup_error == error:
                return
            record.cleanup_status = cleanup_status
            record.cleanup_error = error
            record.cleanup_updated_at = now
            try:
                self.save(progress)
            except KnowledgeCardStaleVersionError:
                continue
            return

    def _complete_quarantine_cleanup_for_record(
        self,
        path_id: str,
        card_id: str,
        user_id: str,
        *,
        request_id: str,
        now: float,
    ) -> None:
        """Hash/path-check and delete only the matching quarantine copy, then
        durably record ``cleaned`` or ``failed`` on the exact retraction record.

        Called only when the exact retraction is durably ``retracted`` — by the
        retract flow after ``_finalize`` commits, and by the explicit
        post-terminal cleanup path (replay of the same retract request /
        :meth:`complete_quarantine_cleanup`), never by the observational
        reconcile. A failure is persisted (never just logged) with a sanitized
        error and timestamp so a restart exposes it and retries deterministically;
        it never reverts the proven retraction and never deletes other bytes.
        """
        progress = self._load(path_id)
        card = require_card(progress, card_id)
        self._require_ownership_and_path(progress, card, user_id)
        record = self._latest_retraction_for_revision(progress, card)
        if record is None or record.request_id != request_id:
            return
        if record.cleanup_status == CLEANUP_STATUS_CLEANED:
            return
        if not card.target_kb_name or not card.quarantine_rel_path or not card.document_sha256:
            return
        try:
            manager = self._get_manager()
            entry = manager.get_kb_entry(card.target_kb_name)
            if not isinstance(entry, dict) or is_connected_kb(entry):
                return
            kb_dir = manager.get_knowledge_base_path(card.target_kb_name)
        except Exception:  # noqa: BLE001 - KB directory may be gone
            return
        try:
            quarantine_rel = _validate_quarantine_rel_path(card.quarantine_rel_path)
        except KnowledgeCardError:
            return
        quarantine_path = (kb_dir / quarantine_rel).resolve()
        outcome, reason = self._cleanup_quarantine(kb_dir, quarantine_path, card.document_sha256)
        self._persist_cleanup_state(
            path_id,
            card_id,
            user_id,
            request_id=request_id,
            cleanup_status=outcome,
            error=reason,
            now=now,
        )

    def complete_quarantine_cleanup(
        self,
        path_id: str,
        *,
        card_id: str,
        user_id: str,
        now: float | None = None,
    ) -> dict[str, Any]:
        """Idempotent post-terminal quarantine cleanup **outside** reconcile.

        This is the explicit, durable, retryable cleanup path for a durably
        ``retracted`` card whose exact matching quarantine copy is still present
        (cleanup ``pending``) or whose last cleanup attempt failed (``failed``).
        It is deliberately NOT the observational reconcile: it is allowed to
        delete the exact matching quarantine copy, but only after the exact
        retraction was durably finalized. It never moves/restores/reindexes/
        resubmits and never deletes mismatched bytes or out-of-sandbox paths.

        A restart exposes ``pending``/``failed`` through the retraction
        projection; calling this method again (or replaying the same retract
        request) deterministically retries to ``cleaned``.
        """
        moment = now if now is not None else self._now()
        progress = self._load(path_id)
        card = require_card(progress, card_id)
        self._require_ownership_and_path(progress, card, user_id)
        if card.status != KnowledgeCardStatus.RETRACTED:
            return self._card_result(progress, card, replayed=False)
        record = self._latest_retraction_for_revision(progress, card)
        if record is None or record.status != RetractionStatus.RETRACTED:
            return self._card_result(progress, card, replayed=False)
        if record.cleanup_status != CLEANUP_STATUS_CLEANED:
            self._complete_quarantine_cleanup_for_record(
                path_id,
                card_id,
                user_id,
                request_id=record.request_id,
                now=moment,
            )
        return self._reload_result(path_id, card_id, replayed=True)

    def _release_lease(
        self,
        coordinator: KbWriteCoordinator,
        kb_name: str,
        op_id: str,
        owner: str,
        *,
        error_code: str,
        error: str,
    ) -> None:
        try:
            coordinator.complete(
                kb_name,
                op_id,
                "failed",
                owner=owner,
                error_code=error_code,
                error=error,
            )
        except Exception:  # noqa: BLE001 - best-effort lease release
            logger.warning(
                "could not release card_retract operation %s for KB '%s'",
                op_id,
                kb_name,
            )

    # ── reconcile-retraction (observational, requirement 9) ─────────────────

    def _converge_retracted_operation(
        self,
        card: KnowledgeCardRecord,
        *,
        user_id: str,
    ) -> None:
        """Converge the exact stranded ``card_retract`` operation of a retracted card.

        ``_finalize`` durably saves the ``retracted`` card *before* it releases
        the per-KB lease. A crash, ``None`` return or exception on that release
        leaves the exact ``card_retract`` operation active or
        ``reconcile_required`` while the KB is blocked. The immutable retracted
        card is durable proof that retraction finalization passed, so an explicit
        reconcile converges that exact operation to ``succeeded`` — never another
        operation, never a live active one without matching ownership.
        """
        target_kb_name = card.target_kb_name
        op_id = card.retraction_operation_id
        if not target_kb_name or not op_id:
            return
        coordinator = KbWriteCoordinator(base_dir=self.kb_base_dir)
        op = coordinator.current_operation(target_kb_name)
        if op is None or op.id != op_id:
            return
        if op.operation_type != "card_retract":
            return
        if op.status in ("succeeded", "failed"):
            return
        if op.user_id and op.user_id != user_id:
            return
        if coordinator.is_lease_live(target_kb_name, op_id):
            return
        try:
            coordinator.resolve_manual(
                target_kb_name,
                op_id,
                "succeeded",
                error_code="",
                error="",
                owner=None,
            )
        except Exception as exc:  # noqa: BLE001 - best-effort convergence
            logger.warning(
                "could not converge card_retract operation %s for retracted card %s on KB '%s': %s",
                op_id,
                card.id,
                target_kb_name,
                sanitize_error(str(exc)),
            )

    def _converge_published_operation(
        self,
        card: KnowledgeCardRecord,
        *,
        user_id: str,
    ) -> None:
        """Converge the exact stranded ``card_retract`` operation of a published card.

        A confirmed rollback returns the card to immutable ``published`` with a
        failed retraction record. ``_finalize`` durably saves that card *before*
        it releases the per-KB lease; a crash, ``None`` return or exception on the
        release leaves the exact ``card_retract`` operation active or
        ``reconcile_required`` while the KB is blocked. The immutable published
        card is durable proof that the rollback finalization passed, so an
        explicit reconcile converges that exact operation to ``failed`` — never
        another operation, never a live active one without matching ownership.
        """
        target_kb_name = card.target_kb_name
        op_id = card.retraction_operation_id
        if not target_kb_name or not op_id:
            return
        coordinator = KbWriteCoordinator(base_dir=self.kb_base_dir)
        op = coordinator.current_operation(target_kb_name)
        if op is None or op.id != op_id:
            return
        if op.operation_type != "card_retract":
            return
        if op.status in ("succeeded", "failed"):
            return
        if op.user_id and op.user_id != user_id:
            return
        if coordinator.is_lease_live(target_kb_name, op_id):
            return
        try:
            coordinator.resolve_manual(
                target_kb_name,
                op_id,
                "failed",
                error_code="retraction_failed",
                error="the retraction was fully rolled back and the card is published again",
                owner=None,
            )
        except Exception as exc:  # noqa: BLE001 - best-effort convergence
            logger.warning(
                "could not converge card_retract operation %s for published card %s on KB '%s': %s",
                op_id,
                card.id,
                target_kb_name,
                sanitize_error(str(exc)),
            )

    def _resolve_orphan_operation_failed(
        self,
        coordinator: KbWriteCoordinator,
        target_kb_name: str,
        op: Any,
        *,
        error_code: str = "interrupted",
        error: str = ("retraction interrupted before any durable KB mutation occurred"),
    ) -> bool:
        """Durably resolve the exact expired orphan ``card_retract`` operation.

        Returns ``True`` only when the operation was durably converged (or is
        already terminal); ``False`` when the resolution returned ``None``/raised
        so the caller retains the durable intent for a later retry (KB-04 P0
        correction 1).
        """
        try:
            resolved = coordinator.resolve_manual(
                target_kb_name,
                op.id,
                "failed",
                error_code=error_code,
                error=error,
            )
        except Exception as exc:  # noqa: BLE001 - failure-of-failure
            logger.warning(
                "could not resolve orphan card_retract operation %s for KB '%s': %s",
                op.id,
                target_kb_name,
                sanitize_error(str(exc)),
            )
            return False
        return resolved is not None

    def reconcile_retraction(
        self,
        path_id: str,
        *,
        card_id: str,
        user_id: str,
        now: float | None = None,
    ) -> dict[str, Any]:
        """Inspect existing evidence only and converge the card conservatively.

        Never stages, moves, deletes, restores, reindexes or resubmits. Converges
        to ``retracted`` only when exclusion is fully proven (raw absent,
        quarantine present with matching hash, the document absent from index
        evidence, an excluding reindex was durably recorded, and the KB ready);
        to ``published`` only when restoration is fully proven (raw present with
        matching hash, quarantine absent, the document present in index evidence,
        and the KB ready). Otherwise it stays ``retract_reconcile_required``.

        Only a card in the retraction lifecycle — ``retracting``,
        ``retract_reconcile_required``, or a published card carrying a durable
        retraction intent — may be reconciled. Fresh drafts, ordinary published
        cards with no durable retraction intent, other card states, live
        operations, or a different current operation are never modified/resolved.
        """
        moment = now if now is not None else self._now()
        progress = self._load(path_id)
        card = require_card(progress, card_id)
        self._require_ownership_and_path(progress, card, user_id)

        if card.status == KnowledgeCardStatus.RETRACTED:
            # The immutable retracted snapshot is durable proof that retraction
            # finalization passed. Guard BEFORE any side effect (KB-04 review
            # round 1 finding 5): if a different current KB operation exists, or
            # the exact operation is live, return without operation/media/cleanup
            # mutation. Reconcile never deletes the quarantine copy here — that
            # is the explicit post-terminal cleanup path's job (finding 1).
            target_kb_name = card.target_kb_name
            op_id = card.retraction_operation_id
            coordinator = KbWriteCoordinator(base_dir=self.kb_base_dir)
            if target_kb_name:
                current_op = coordinator.current_operation(target_kb_name)
                if current_op is not None:
                    if op_id is None or current_op.id != op_id:
                        # A different operation owns the KB; leave the card alone.
                        return self._card_result(progress, card, replayed=True)
                    if coordinator.is_lease_live(target_kb_name, current_op.id):
                        # The exact operation is genuinely in-flight; leave it.
                        return self._card_result(progress, card, replayed=True)
            # Only the exact, non-live stranded operation may be converged and
            # the card's own media references re-released (both idempotent).
            self._converge_retracted_operation(card, user_id=user_id)
            self._release_media_references(card, user_id)
            return self._card_result(progress, card, replayed=True)

        intent = card.retraction_intent
        in_lifecycle = card.status in (
            KnowledgeCardStatus.RETRACTING,
            KnowledgeCardStatus.RETRACT_RECONCILE_REQUIRED,
        ) or (card.status == KnowledgeCardStatus.PUBLISHED and intent is not None)
        if not in_lifecycle:
            # Unrelated card states must never change on reconcile. A published
            # card that carries only a durable retraction_operation_id (a
            # confirmed rollback whose lease release crashed/None'd) converges
            # its exact stranded operation so the KB is never permanently
            # blocked.
            if card.status == KnowledgeCardStatus.PUBLISHED and card.retraction_operation_id:
                self._converge_published_operation(card, user_id=user_id)
            return self._card_result(progress, card, replayed=False)

        coordinator = KbWriteCoordinator(base_dir=self.kb_base_dir)
        target_kb_name = card.target_kb_name or (intent.target_kb_name if intent else "")
        rel_path = (
            card.document_rel_path
            or (intent.original_rel_path if intent else "")
            or fixed_document_rel_path(card.id, card.revision)
        )
        quarantine_rel = (
            card.quarantine_rel_path
            or (intent.quarantine_rel_path if intent else "")
            or fixed_quarantine_rel_path(
                card.id,
                card.revision,
                card.document_sha256 or (intent.document_sha256 if intent else ""),
            )
        )
        expected_sha = card.document_sha256 or (intent.document_sha256 if intent else "")
        rel_path = _validate_document_rel_path(rel_path)
        quarantine_rel = _validate_quarantine_rel_path(quarantine_rel)

        # Locate the exact operation this retraction is bound to (if any): the
        # card's durable operation linkage, or the exact orphan matched by
        # target + subject + request identity for a crash-before-attach intent.
        op = None
        if target_kb_name and card.retraction_operation_id:
            op = coordinator.current_operation(target_kb_name)
            if op is None or op.id != card.retraction_operation_id:
                op = None
        elif target_kb_name and intent is not None:
            op = self._matching_orphan_operation(coordinator, intent, card.id)

        # KB-04 P0 correction 2: never reconcile while another live/different KB
        # operation can mutate the target. If the current target-KB operation is
        # live, or differs from the card/intent operation, return without
        # card/record/media mutation — never decide from filesystem evidence
        # concurrently with a different upload/delete/reindex/publish/retract
        # operation.
        current_op = coordinator.current_operation(target_kb_name) if target_kb_name else None
        if current_op is not None:
            if op is None or current_op.id != op.id:
                # A different operation owns the KB; leave it and the card alone.
                return self._card_result(progress, card, replayed=False)
            if coordinator.is_lease_live(target_kb_name, current_op.id):
                # A genuinely in-flight retraction with a live lease is left
                # alone for every lifecycle state.
                return self._card_result(progress, card, replayed=False)

        # Read-only evidence gathering.
        manager = self._get_manager()
        entry = manager.get_kb_entry(target_kb_name) if target_kb_name else None
        kb_dir: Path | None = None
        raw_present = False
        raw_hash_matches = False
        quarantine_present = False
        quarantine_hash_matches = False
        index_evidence_sha: str | None = None
        kb_ready = False
        reindex_confirmed = False
        record = None
        if isinstance(entry, dict):
            kb_ready = str(entry.get("status") or "") == "ready" and not bool(
                entry.get("needs_reindex", False)
            )
            if not is_connected_kb(entry):
                try:
                    kb_dir = manager.get_knowledge_base_path(target_kb_name)
                except Exception:  # noqa: BLE001 - KB directory may be gone
                    kb_dir = None
                if kb_dir is not None:
                    raw_file = kb_dir / "raw" / rel_path
                    if raw_file.is_file():
                        raw_present = True
                        raw_hash_matches = _sha256_of_file(raw_file) == expected_sha
                    quarantine_file = kb_dir / quarantine_rel
                    if quarantine_file.is_file():
                        quarantine_present = True
                        quarantine_hash_matches = _sha256_of_file(quarantine_file) == expected_sha
                    index_evidence_sha = self._index_evidence(kb_dir, rel_path)
        if card.id:
            record = self._latest_retraction_for_revision(progress, card)
            reindex_confirmed = bool(record and record.index_task_id)

        # KB-04 P0 correction 1: "no mutation" means the published KB is fully
        # intact — raw present with the exact hash, no quarantine copy, the
        # matching published index evidence, and a ready KB. Raw absent +
        # quarantine absent is data loss/ambiguity, never the normal
        # no-mutation state.
        no_mutation_proven = (
            raw_present
            and raw_hash_matches
            and not quarantine_present
            and index_evidence_sha == expected_sha
            and kb_ready
        )

        # A published card carrying a staged intent is a retraction that never
        # durably transitioned to ``retracting``. Converge only the exact
        # no-mutation state: with no operation, clear the staged intent and
        # remain published; with the exact expired orphan operation, durably
        # resolve it failed then clear the intent. On None/exception the intent
        # is retained for retry; raw absent + quarantine absent never clears the
        # intent or claims published.
        if card.status == KnowledgeCardStatus.PUBLISHED and intent is not None:
            if op is None:
                if no_mutation_proven:
                    # Clear only the exact staged intent observed, re-checking the
                    # coordinator at the commit boundary: a concurrent operation
                    # that appeared between the initial ``current_op is None`` read
                    # and this clear (or a replaced intent / card-status / operation
                    # linkage drift) makes the clear a no-op, and the reloaded
                    # current card is returned without reporting that the old intent
                    # was cleared (KB-04 review round 2).
                    self._clear_retraction_intent(
                        path_id,
                        card_id,
                        user_id,
                        moment,
                        request_id=intent.request_id,
                        attempt_id=intent.attempt_id,
                        target_kb_name=intent.target_kb_name,
                        rel_path=intent.original_rel_path,
                        quarantine_rel=intent.quarantine_rel_path,
                        document_sha=intent.document_sha256,
                        card_revision=intent.card_revision,
                        coordinator=coordinator,
                    )
                    return self._reload_result(path_id, card_id, replayed=False)
                # Ambiguous/data-loss evidence — retain the durable intent.
                return self._card_result(progress, card, replayed=False)
            # ``op`` is the exact orphan; a live lease was ruled out above.
            if no_mutation_proven:
                if not self._resolve_orphan_operation_failed(coordinator, target_kb_name, op):
                    return self._card_result(progress, card, replayed=False)
                # Durably attach the exact operation id, terminalize any record
                # and clear the intent only after the orphan was durably
                # resolved (a same-status convergence — _apply_reconcile must
                # not early-return for a published card carrying retraction
                # staging). A no-op caused by drift (a concurrent retract
                # acquired the freed lease and transitioned the card) must not
                # clear staging or report a fabricated terminal (finding 4).
                progress, card, applied = self._apply_reconcile(
                    path_id,
                    card_id,
                    user_id=user_id,
                    status=KnowledgeCardStatus.PUBLISHED,
                    target_kb_name=target_kb_name,
                    rel_path=rel_path,
                    quarantine_rel=quarantine_rel,
                    document_sha=expected_sha,
                    now=moment,
                    error_code="interrupted",
                    sanitized_error=(
                        "retraction interrupted before any durable KB mutation occurred"
                    ),
                    operation_id=op.id,
                    request_id=intent.request_id if intent else card.retraction_request_id,
                    coordinator=coordinator,
                )
                return self._card_result(progress, card, replayed=False)
            # Raw absent + quarantine absent (data loss/ambiguity) or any other
            # non-no-mutation state: never clear the intent or claim published.
            return self._card_result(progress, card, replayed=False)

        # ── convergence (RETRACTING / RETRACT_RECONCILE_REQUIRED) ──
        exclusion_proven = (
            not raw_present
            and quarantine_present
            and quarantine_hash_matches
            and index_evidence_sha is None
            and reindex_confirmed
            and kb_ready
        )
        restoration_proven = (
            raw_present
            and raw_hash_matches
            and not quarantine_present
            and index_evidence_sha == expected_sha
            and kb_ready
        )

        if exclusion_proven:
            new_status = KnowledgeCardStatus.RETRACTED
            error_code, err = "", ""
        elif restoration_proven:
            new_status = KnowledgeCardStatus.PUBLISHED
            error_code, err = (
                "retraction_failed",
                ("the retraction was fully rolled back and the card is published again"),
            )
        else:
            new_status = KnowledgeCardStatus.RETRACT_RECONCILE_REQUIRED
            error_code, err = (
                "ambiguous_state",
                ("retraction state is ambiguous; manual inspection of the KB is required"),
            )

        progress, card, applied = self._apply_reconcile(
            path_id,
            card_id,
            user_id=user_id,
            status=new_status,
            target_kb_name=target_kb_name,
            rel_path=rel_path,
            quarantine_rel=quarantine_rel,
            document_sha=expected_sha,
            now=moment,
            error_code=error_code,
            sanitized_error=err,
            operation_id=op.id if op is not None else "",
            request_id=card.retraction_request_id or (intent.request_id if intent else ""),
            coordinator=coordinator,
        )

        if not applied:
            # Drift: a concurrent writer owns the card/operation now. Never
            # resolve the stale operation, release media, clear staging, or
            # report a fabricated terminal transition (finding 4).
            return self._card_result(progress, card, replayed=False)

        if op is not None:
            terminal = (
                "succeeded"
                if new_status == KnowledgeCardStatus.RETRACTED
                else "failed"
                if new_status == KnowledgeCardStatus.PUBLISHED
                else "reconcile_required"
            )
            try:
                coordinator.resolve_manual(
                    target_kb_name,
                    op.id,
                    terminal,
                    error_code=error_code or None,
                    error=err or None,
                )
            except Exception:  # noqa: BLE001 - best-effort lease release
                logger.warning(
                    "could not resolve interrupted card_retract operation %s for KB '%s'",
                    op.id,
                    target_kb_name,
                )

        if new_status == KnowledgeCardStatus.RETRACTED:
            # Durable retraction confirmed; release this card's media references
            # (idempotent, recoverable on a later reconcile). The quarantine
            # lifecycle is completed by the explicit post-terminal cleanup path,
            # never by reconcile (finding 1).
            self._release_media_references(card, user_id)

        return self._card_result(progress, card, replayed=False)

    def _apply_reconcile(
        self,
        path_id: str,
        card_id: str,
        *,
        user_id: str,
        status: KnowledgeCardStatus,
        target_kb_name: str,
        rel_path: str,
        quarantine_rel: str,
        document_sha: str,
        now: float,
        error_code: str,
        sanitized_error: str,
        operation_id: str = "",
        request_id: str = "",
        coordinator: KbWriteCoordinator | None = None,
    ) -> tuple[LearningProgress, KnowledgeCardRecord, bool]:
        """Persist the converged reconcile state under the store CAS.

        Appends/transitions the retraction record (never drops history) and
        clears the staged intent once the state is terminal. When this reconcile
        started from a published-with-intent orphan, the exact
        ``retraction_operation_id`` is durably attached *before* the intent is
        cleared, so a later failed operation convergence can still locate and
        converge the operation from the card's durable operation linkage.

        Returns ``(progress, card, applied)``. ``applied=True`` means the
        reconcile converged (or the card was already in the exact target
        snapshot); ``applied=False`` means the CAS loop detected lifecycle drift
        — a concurrent writer transitioned the card to a new retraction, changed
        the retraction request/intent/operation identity, or the current KB
        operation became different/live — so the caller must NOT resolve the
        stale operation, release media, clear staging, or report a fabricated
        terminal transition (KB-04 review round 1 finding 4).
        """
        while True:
            progress = self._load(path_id)
            card = require_card(progress, card_id)
            self._require_ownership_and_path(progress, card, user_id)

            # ── lifecycle drift guards (finding 4) ──
            # A CAS retry must never overwrite a card that concurrently changed
            # to a new retraction lifecycle. The expected starting identity is
            # carried in as ``operation_id``/``request_id``; any mismatch is a
            # no-op.
            if card.status == KnowledgeCardStatus.RETRACTED:
                # Immutable terminal snapshot. Converging to ``retracted`` is an
                # idempotent no-op for the exact operation; any other target is
                # drift (an immutable retraction cannot be reverted).
                if status == KnowledgeCardStatus.RETRACTED:
                    return progress, card, True
                return progress, card, False
            if (
                request_id
                and card.retraction_request_id
                and card.retraction_request_id != request_id
            ):
                # A different retraction owns the card now; drift.
                return progress, card, False
            if (
                operation_id
                and card.retraction_operation_id
                and card.retraction_operation_id != operation_id
            ):
                # A different operation owns the card now; drift.
                return progress, card, False
            if (
                card.status == KnowledgeCardStatus.PUBLISHED
                and card.retraction_intent is None
                and not card.retraction_request_id
                and not card.retraction_operation_id
            ):
                # A clean published card with no retraction staging is a stable
                # snapshot. Only a published/restoration convergence is
                # compatible with it; a retracted convergence would be drift (a
                # concurrent writer cleared the staging).
                if status == KnowledgeCardStatus.PUBLISHED:
                    return progress, card, True
                return progress, card, False

            # Re-check the coordinator at the commit boundary (finding 4): never
            # overwrite/resolve while a different current operation owns the KB
            # or the exact operation is genuinely live.
            if coordinator is not None and target_kb_name:
                current_op = coordinator.current_operation(target_kb_name)
                if operation_id:
                    if current_op is None or current_op.id != operation_id:
                        return progress, card, False
                    if coordinator.is_lease_live(target_kb_name, current_op.id):
                        return progress, card, False
                elif current_op is not None:
                    return progress, card, False

            card.status = status
            card.error_code = error_code
            card.sanitized_error = sanitized_error
            card.updated_at = now
            card.version += 1
            if status == KnowledgeCardStatus.RETRACTED:
                card.retracted_at = card.retracted_at or now
            if status == KnowledgeCardStatus.PUBLISHED:
                card.published_at = card.published_at or now
            if operation_id:
                card.retraction_operation_id = operation_id
            if card.retraction_intent is not None:
                intent = card.retraction_intent
                card.target_kb_name = card.target_kb_name or intent.target_kb_name
                card.document_rel_path = card.document_rel_path or intent.original_rel_path
                card.document_sha256 = card.document_sha256 or intent.document_sha256
                card.quarantine_rel_path = card.quarantine_rel_path or intent.quarantine_rel_path
                card.retraction_request_id = card.retraction_request_id or intent.request_id
            if status != KnowledgeCardStatus.RETRACT_RECONCILE_REQUIRED:
                card.retraction_intent = None
            record = self._active_retraction_for_revision(progress, card)
            if record is not None:
                target_status = self._record_status_for(status)
                if record.status != target_status:
                    record.status = target_status
                    record.updated_at = now
                    record.finished_at = now
                    record.error_code = error_code
                    record.sanitized_error = sanitized_error
            append_history(
                progress,
                _EVENT_RETRACTION_RECONCILED,
                aggregate="",
                summary=f"card {card.id} retraction reconciled to {status.value}",
                payload={
                    "card_id": card.id,
                    "target_kb_name": target_kb_name,
                    "original_rel_path": rel_path,
                    "quarantine_rel_path": quarantine_rel,
                    "document_sha256": document_sha,
                    "status": status.value,
                    "error_code": error_code,
                    "sanitized_error": sanitized_error,
                },
            )
            try:
                self.save(progress)
            except KnowledgeCardStaleVersionError:
                continue
            return progress, card, True


__all__ = [
    "KnowledgeCardRetractionService",
    "fixed_quarantine_rel_path",
    "retraction_fingerprint",
]
