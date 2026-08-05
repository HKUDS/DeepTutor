"""Guided Learning API Router."""

from __future__ import annotations

import html
import json
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from deeptutor.learning import policy as learning_policy
from deeptutor.learning import prompts as learning_prompts
from deeptutor.learning.cycles import (
    ConflictResolutionError,
    EvidenceConflictError,
    EvidenceOrderError,
    FeynmanCycleService,
    FeynmanError,
    IdempotencyConflictError,
    InvalidAttemptStateError,
    OwnershipError,
    StaleVersionError,
    UnknownAttemptError,
    UnknownConflictError,
)
from deeptutor.learning.knowledge_cards.errors import (
    KnowledgeCardEligibilityError,
    KnowledgeCardError,
    KnowledgeCardIdempotencyConflictError,
    KnowledgeCardInputValidationError,
    KnowledgeCardKbNotWritableError,
    KnowledgeCardNotFoundError,
    KnowledgeCardOwnershipError,
    KnowledgeCardPublicationConflictError,
    KnowledgeCardPublicationUnavailableError,
    KnowledgeCardReconcileRequiredError,
    KnowledgeCardRetractionConflictError,
    KnowledgeCardRetractionUnavailableError,
    KnowledgeCardStaleVersionError,
    KnowledgeCardStateError,
)
from deeptutor.learning.knowledge_cards.publish import KnowledgeCardPublicationService
from deeptutor.learning.knowledge_cards.retraction import KnowledgeCardRetractionService
from deeptutor.learning.knowledge_cards.service import KnowledgeCardDraftService
from deeptutor.learning.knowledge_cards.store import latest_attempt_for_card
from deeptutor.learning.models import (
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
    LearningProgress,
    LearningStage,
)
from deeptutor.learning.service import LearningService
from deeptutor.learning.storage import LearningStore
from deeptutor.multi_user.context import get_current_user
from deeptutor.services.media.store import MediaStore
from deeptutor.services.media.views import artifact_file_path, artifact_view
from deeptutor.services.settings.interface_settings import get_ui_language
from deeptutor.utils.json_parser import parse_json_response

router = APIRouter()


def get_learning_service() -> LearningService:
    # Create a fresh store + service per request to avoid object-level race conditions.
    store = LearningStore()
    return LearningService(store)


def get_cycle_service() -> FeynmanCycleService:
    """A fresh LRN-03 cycle service (fresh store) per request.

    The production evaluator resolver freezes the learning path's configured
    evaluator at every attempt-creation boundary; the service never makes an
    LLM call at freeze time (§9.3).
    """
    from deeptutor.learning.cycles import production_evaluator_resolver

    return FeynmanCycleService(LearningStore(), evaluator_resolver=production_evaluator_resolver())


def get_publication_service() -> KnowledgeCardPublicationService:
    """A fresh KB-03 publication service (fresh store) per request.

    The service resolves the current user's knowledge-base root lazily, so it is
    safe to construct per request without reaching into the knowledge router.
    """
    return KnowledgeCardPublicationService(LearningStore())


def get_retraction_service() -> KnowledgeCardRetractionService:
    """A fresh KB-04 retraction service (fresh store) per request."""
    return KnowledgeCardRetractionService(LearningStore())


def get_draft_service() -> KnowledgeCardDraftService:
    """A fresh KB-02 draft service (fresh store + media store) per request.

    The media store is required only for artifact attach/detach and discard
    reference release; a fresh per-request instance keeps object-level state
    out of the way while every mutation still runs under the store CAS.
    """
    return KnowledgeCardDraftService(LearningStore(), media_store=MediaStore())


def _current_actor_id() -> str:
    try:
        return str(get_current_user().id or "")
    except Exception:
        return ""


def _feynman_http_error(exc: FeynmanError) -> HTTPException:
    """Map a recoverable LRN-03 domain error onto a stable HTTP status."""
    if isinstance(exc, OwnershipError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, (UnknownAttemptError, UnknownConflictError)):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(
        exc,
        (
            StaleVersionError,
            EvidenceConflictError,
            IdempotencyConflictError,
            InvalidAttemptStateError,
        ),
    ):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, (ConflictResolutionError, EvidenceOrderError)):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=409, detail=str(exc))


def _knowledge_card_http_error(exc: KnowledgeCardError) -> HTTPException:
    """Map a KB-03 publication domain error onto a stable HTTP status + code.

    ``detail`` carries ``{"code", "message"}`` so clients can branch on the
    stable structured error code rather than the human-readable message.
    """
    if isinstance(exc, KnowledgeCardOwnershipError):
        status_code = 403
    elif isinstance(exc, KnowledgeCardNotFoundError):
        status_code = 404
    elif isinstance(exc, KnowledgeCardInputValidationError):
        status_code = 422
    elif isinstance(
        exc,
        (
            KnowledgeCardEligibilityError,
            KnowledgeCardKbNotWritableError,
            KnowledgeCardPublicationConflictError,
            KnowledgeCardPublicationUnavailableError,
            KnowledgeCardReconcileRequiredError,
            KnowledgeCardRetractionConflictError,
            KnowledgeCardRetractionUnavailableError,
            KnowledgeCardStaleVersionError,
            KnowledgeCardStateError,
            KnowledgeCardIdempotencyConflictError,
        ),
    ):
        # stale version / idempotency conflict / eligibility / state / writable
        # KB / publication unavailable / reconcile required → all recoverable
        # conflicts.
        status_code = 409
    else:
        status_code = 409
    return HTTPException(
        status_code=status_code,
        detail={
            "code": getattr(exc, "code", "knowledge_card_error"),
            "message": str(exc),
        },
    )


def _validate_book_id(book_id: str) -> None:
    """Reject empty or path-traversal-bearing book ids (shared by all endpoints)."""
    if not book_id or ".." in book_id or "/" in book_id or "\\" in book_id or ":" in book_id:
        raise HTTPException(status_code=400, detail="Invalid book_id")


def _generation_attempt_view(progress: LearningProgress, card: Any) -> dict[str, Any] | None:
    """Serialize the latest generation attempt for a card (audit-safe fields).

    Only attempt identity/status/hashes/sanitized diagnostics are exposed — a
    model invocation id, never the provider prompt/response or credentials
    (§7.9.1, §14). Returns ``None`` when the card has no attempt yet.
    """
    attempt = latest_attempt_for_card(progress, card.id)
    if attempt is None:
        return None
    return {
        "id": attempt.id,
        "status": attempt.status.value,
        "generation_attempt_no": attempt.generation_attempt_no,
        "retry_of_generation_attempt_id": attempt.retry_of_generation_attempt_id,
        "input_card_revision": attempt.input_card_revision,
        "model_invocation_id": attempt.model_invocation_id,
        "output_hash": attempt.output_hash,
        "error_code": attempt.error_code,
        "sanitized_error": attempt.sanitized_error,
        "created_at": attempt.created_at,
        "started_at": attempt.started_at,
        "finished_at": attempt.finished_at,
    }


def _model_identity_view(progress: LearningProgress, card: Any) -> dict[str, Any] | None:
    """The frozen generation/evaluator model identity for a card.

    Prefers the frozen snapshot on the latest generation attempt (the model the
    generation actually ran under); falls back to the stable assessment's frozen
    evaluator snapshot. Only audit-safe identity fields are exposed (§9.4).
    """
    attempt = latest_attempt_for_card(progress, card.id)
    snapshot = attempt.frozen_model_snapshot if attempt is not None else None
    if snapshot is None:
        assessment = next(
            (item for item in progress.rubric_assessments if item.id == card.stable_assessment_id),
            None,
        )
        snapshot = assessment.evaluator_snapshot if assessment is not None else None
    if snapshot is None:
        return None
    return {
        "provider": snapshot.resolved_provider or snapshot.requested_provider,
        "profile": snapshot.profile_name or snapshot.profile_id,
        "model": snapshot.resolved_model or snapshot.requested_model,
        "protocol": snapshot.resolved_api_protocol or snapshot.requested_api_protocol,
        "base_url_fingerprint": snapshot.base_url_fingerprint,
        "strict_protocol": bool(snapshot.strict_protocol),
        "rubric_version": snapshot.rubric_version,
    }


def _card_view(
    progress: LearningProgress,
    card: Any,
    *,
    user_id: str,
    media_store: MediaStore | None = None,
) -> dict[str, Any]:
    """Owner-scoped read projection of one knowledge card (KB-02/KB-03/KB-04).

    Reuses the MED-03 artifact serializer for persistent same-user artifact
    references (§10.5) and never exposes provider prompts, raw errors,
    credentials, base64 or private URLs — only ids/hashes and sanitized
    diagnostics (§14). Deleted/missing artifacts degrade to ``available=False``.
    """
    source_by_id = {snapshot.id: snapshot for snapshot in progress.source_snapshots}
    sources = [
        {
            "id": snapshot.id,
            "title": snapshot.title or snapshot.id,
            "locator": snapshot.locator or "",
            "anchors": list(snapshot.citation_anchors or []),
        }
        for snapshot in (
            source_by_id[sid] for sid in card.source_snapshot_ids if sid in source_by_id
        )
    ]
    latest_retraction = next(
        (
            record
            for record in reversed(progress.knowledge_card_retraction_records)
            if record.card_id == card.id
        ),
        None,
    )
    artifacts: list[dict[str, Any]] = []
    if media_store is not None:
        for artifact_id in card.artifact_ids:
            artifact = media_store.load_artifact(artifact_id)
            if artifact is None:
                artifacts.append(
                    {
                        "id": artifact_id,
                        "available": False,
                        "mime_type": "",
                        "width": 0,
                        "height": 0,
                        "sha256": "",
                        "preview_url": None,
                        "download_url": None,
                        "references": [],
                    }
                )
                continue
            if artifact.user_id != user_id:
                continue
            references = media_store.list_references(artifact_id=artifact_id, user_id=user_id)
            artifacts.append(
                {
                    **artifact_view(
                        artifact,
                        references=references,
                        **artifact_file_path(artifact),
                    ),
                    "available": True,
                }
            )
    return {
        "card_id": card.id,
        "knowledge_point_id": card.knowledge_point_id,
        "status": card.status.value,
        "revision": card.revision,
        "version": card.version,
        "generation_locked_by_user_edit": card.generation_locked_by_user_edit,
        "draft_generation_status": card.draft_generation_status.value,
        "title": card.title,
        "body": card.body,
        "content_hash": card.content_hash,
        "source_snapshot_ids": list(card.source_snapshot_ids),
        "evidence_ids": list(card.evidence_ids),
        "artifact_ids": list(card.artifact_ids),
        "source_count": len(card.source_snapshot_ids),
        "evidence_count": len(card.evidence_ids),
        "artifact_count": len(card.artifact_ids),
        "stable_assessment_id": card.stable_assessment_id,
        "stable_assessment_sequence": card.stable_assessment_sequence,
        # KB-03 publication projection (§7.9).
        "target_kb_name": card.target_kb_name,
        "document_rel_path": card.document_rel_path,
        "document_sha256": card.document_sha256,
        "publication_key": card.publication_key,
        # KB-04 retraction projection (§7.11).
        "quarantine_rel_path": card.quarantine_rel_path,
        "retraction_request_id": card.retraction_request_id,
        "retraction_operation_id": card.retraction_operation_id,
        "cleanup_status": (latest_retraction.cleanup_status if latest_retraction else ""),
        "cleanup_error": (latest_retraction.cleanup_error if latest_retraction else ""),
        "confirmed_at": card.confirmed_at,
        "published_at": card.published_at,
        "stale_at": card.stale_at,
        "retracted_at": card.retracted_at,
        "error_code": card.error_code,
        "sanitized_error": card.sanitized_error,
        "latest_generation_attempt": _generation_attempt_view(progress, card),
        "model_identity": _model_identity_view(progress, card),
        "sources": sources,
        "artifacts": artifacts,
        "occupies_slot": card.occupies_slot,
    }


def _card_view_for(
    path_id: str,
    card_id: str,
    *,
    user_id: str,
    draft_service: KnowledgeCardDraftService,
    media_store: MediaStore | None = None,
) -> dict[str, Any]:
    """Load a single owner-scoped card view (authoritative after a mutation)."""
    progress = draft_service.load(path_id)
    if progress is None:
        raise KnowledgeCardNotFoundError(f"progress for path {path_id!r} not found")
    card = next((item for item in progress.knowledge_cards if item.id == card_id), None)
    if card is None:
        raise KnowledgeCardNotFoundError(f"knowledge card {card_id!r} not found")
    if user_id and card.user_id and card.user_id != user_id:
        raise KnowledgeCardOwnershipError(
            f"card {card_id!r} belongs to user {card.user_id!r}, not {user_id!r}"
        )
    return _card_view(progress, card, user_id=user_id, media_store=media_store)


def _parse_modules(body_modules: list[dict]) -> list[LearningModule]:
    """Parse raw module dicts into LearningModule objects (shared by init/replace)."""
    modules: list[LearningModule] = []
    for i, m in enumerate(body_modules):
        kps_data = m.get("knowledge_points", [])
        try:
            kps = [KnowledgePoint(**kp) for kp in kps_data]
        except PydanticValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid knowledge_point data in modules[{i}]: {exc.errors()}",
            ) from exc
        # Remove knowledge_points from m to avoid duplicate argument to LearningModule.
        m_clean = {k: v for k, v in m.items() if k != "knowledge_points"}
        try:
            modules.append(LearningModule(knowledge_points=kps, **m_clean))
        except PydanticValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid module data in modules[{i}]: {exc.errors()}",
            ) from exc
    return modules


def _validate_runnable_modules(modules: list[LearningModule], *, status_code: int = 400) -> None:
    if not modules:
        raise HTTPException(
            status_code=status_code, detail="At least one learning module is required"
        )
    for mod in modules:
        if not mod.knowledge_points:
            raise HTTPException(
                status_code=status_code,
                detail=f"Module {mod.id!r} must contain at least one knowledge point",
            )


async def _cancel_active_learning_turn(book_id: str) -> None:
    from deeptutor.services.session import get_turn_runtime_manager

    runtime = get_turn_runtime_manager()
    active_turn = await runtime.store.get_active_turn(book_id)
    if active_turn:
        await runtime.cancel_turn(active_turn["id"])


# ── Request models ───────────────────────────────────────────────────────────


class InitModulesRequest(BaseModel):
    modules: list[dict]  # list of LearningModule-compatible dicts


class ChapterImport(BaseModel):
    title: str
    knowledge_points: list[str] = []


class ImportFromBookRequest(BaseModel):
    chapters: list[ChapterImport]


# ── LRN-03 request models (spec §8.2, §8.3) ──────────────────────────────


class MapEditRequest(BaseModel):
    nodes: list[str] = []
    edges: list[dict] = []
    priorities: dict[str, int] = {}
    # §8.3: the idempotency key and expected version are required — a missing
    # request_id or an omitted version is a 422, never a default-empty/zero
    # bypass of the concurrency contract.
    expected_map_version: int
    request_id: str


class MapConfirmRequest(BaseModel):
    expected_map_version: int
    request_id: str
    source_snapshot_ids: list[str] | None = None


class ConflictResolveRequest(BaseModel):
    accepted_snapshot_id: str
    resolution_note: str
    request_id: str
    expected_conflict_version: int
    expected_map_version: int


class ConflictReopenRequest(BaseModel):
    request_id: str
    expected_conflict_version: int
    expected_map_version: int


class ChallengeRequest(BaseModel):
    mode: str
    reason: str = ""
    requested_evaluator_snapshot: dict | None = None
    request_id: str
    expected_attempt_version: int


# ── KB-03 publication request models (spec §7.9.2) ────────────────────────


class PublishCardRequest(BaseModel):
    """Owner-only, user-confirmed knowledge-card publication.

    ``expected_card_revision`` and ``request_id`` are required — a missing
    revision or idempotency key is a 422, never a default bypass of the
    optimistic-concurrency / idempotency contract (§8.3, §7.9.2).
    """

    target_kb_name: str
    expected_card_revision: int
    request_id: str


class RetryPublishCardRequest(BaseModel):
    """Retry a confirmed-failed publication.

    ``target_kb_name`` is optional: when omitted the original target is reused;
    when supplied it must match the original (a retry never migrates the
    publication to a different KB).
    """

    expected_card_revision: int
    request_id: str
    target_kb_name: str | None = None


class RetractCardRequest(BaseModel):
    """Owner-only, user-confirmed knowledge-card retraction (KB-04, §7.11).

    ``expected_card_revision`` and ``request_id`` are required — a missing
    revision or idempotency key is a 422, never a default bypass of the
    optimistic-concurrency / idempotency contract (§8.3, §7.11).
    """

    expected_card_revision: int
    request_id: str


class EditCardRequest(BaseModel):
    """Versioned draft edit (KB-02, §8.5 / §7.9 requirement 6).

    ``expected_card_revision`` and ``request_id`` are required — a missing
    revision or idempotency key is a 422. ``attach_artifact_ids`` /
    ``detach_artifact_ids`` are versioned through the draft service's media
    references; only persistent same-user artifacts are accepted (§10.5).
    """

    expected_card_revision: int
    request_id: str
    title: str | None = None
    body: str | None = None
    attach_artifact_ids: list[str] = []
    detach_artifact_ids: list[str] = []


class RetryGenerationRequest(BaseModel):
    """Explicit knowledge-card generation retry (KB-02, §8.5 requirement 8).

    ``latest_generation_attempt_id`` binds the retry to the exact attempt the
    client observed so a stale/different attempt is a recoverable conflict.
    """

    expected_card_revision: int
    request_id: str
    latest_generation_attempt_id: str


class DiscardCardRequest(BaseModel):
    """Owner-only discard of an unpublished draft (KB-02, §8.5).

    ``expected_card_revision`` and ``request_id`` are required — a missing
    revision or idempotency key is a 422, never a default bypass of the
    optimistic-concurrency / idempotency contract (§8.3).
    """

    expected_card_revision: int
    request_id: str


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/progress")
async def list_all_progress():
    service = get_learning_service()
    return service.list_progress()


@router.get("/progress/{book_id}")
async def get_progress(book_id: str):
    _validate_book_id(book_id)
    service = get_learning_service()
    progress = service.get_or_create(book_id)
    return progress.model_dump()


@router.get("/progress/{book_id}/map")
async def get_progress_map(book_id: str):
    """The dashboard view of a path (§8.2 read API).

    Returns the gate-decided next step plus the orthogonal mastery/review
    projections, active attempt and evidence summary, map versions, source
    snapshots and open/resolved source conflicts. A page reload recovers the
    Evidence Panel entirely through this endpoint (§8.4).
    """
    _validate_book_id(book_id)
    service = get_cycle_service()
    progress = service.load(book_id)
    if progress is None:
        raise HTTPException(status_code=404, detail="Progress not found")
    payload = service.map_read_payload(progress)
    payload["map"] = learning_policy.map_summary(progress)
    return payload


@router.get("/progress/{book_id}/attempts/{attempt_id}")
async def get_attempt_detail(book_id: str, attempt_id: str):
    """Full attempt detail: evidence, assessment revisions, gaps, challenges,
    and audit metadata (§8.2 read API)."""
    _validate_book_id(book_id)
    service = get_cycle_service()
    progress = service.load(book_id)
    if progress is None:
        raise HTTPException(status_code=404, detail="Progress not found")
    try:
        return service.attempt_read_payload(progress, attempt_id=attempt_id)
    except UnknownAttemptError as exc:
        raise _feynman_http_error(exc)


@router.get("/progress/{book_id}/reviews")
async def get_unified_reviews(book_id: str):
    """Unified review queue across every knowledge type (§8.2 read API)."""
    _validate_book_id(book_id)
    service = get_cycle_service()
    progress = service.load(book_id)
    if progress is None:
        raise HTTPException(status_code=404, detail="Progress not found")
    return service.reviews_read_payload(progress)


@router.patch("/progress/{book_id}/map")
async def edit_map(book_id: str, body: MapEditRequest):
    """Versioned map edit (§8.2): updates ordering/priorities/nodes and creates
    a new map version; incompatible active attempts are atomically invalidated."""
    _validate_book_id(book_id)
    service = get_cycle_service()
    progress = service.load(book_id)
    if progress is None:
        raise HTTPException(status_code=404, detail="Progress not found")
    try:
        result = service.edit_map(
            progress,
            nodes=body.nodes,
            edges=body.edges,
            priorities=body.priorities,
            expected_map_version=body.expected_map_version,
            request_id=body.request_id,
            actor_id=_current_actor_id(),
        )
        service.save(progress)
    except FeynmanError as exc:
        raise _feynman_http_error(exc)
    return result


@router.post("/progress/{book_id}/map/confirm")
async def confirm_map(book_id: str, body: MapConfirmRequest):
    """Confirm the current map version and its source snapshots (§8.2).

    Idempotent under ``request_id``; a stale ``expected_map_version`` returns
    a recoverable conflict instead of overwriting.
    """
    _validate_book_id(book_id)
    service = get_cycle_service()
    progress = service.load(book_id)
    if progress is None:
        raise HTTPException(status_code=404, detail="Progress not found")
    try:
        result = service.confirm_map(
            progress,
            expected_map_version=body.expected_map_version,
            request_id=body.request_id,
            source_snapshot_ids=body.source_snapshot_ids,
            actor_id=_current_actor_id(),
        )
        service.save(progress)
    except FeynmanError as exc:
        raise _feynman_http_error(exc)
    return result


@router.post("/progress/{book_id}/conflicts/{conflict_id}/resolve")
async def resolve_conflict(book_id: str, conflict_id: str, body: ConflictResolveRequest):
    """Owner-only conflict resolution (§7.7, §8.2).

    Selects a snapshot already listed on the conflict, requires a resolution
    note, creates a new conflict revision + map version, and atomically
    invalidates incompatible active attempts.
    """
    _validate_book_id(book_id)
    service = get_cycle_service()
    progress = service.load(book_id)
    if progress is None:
        raise HTTPException(status_code=404, detail="Progress not found")
    try:
        result = service.resolve_conflict(
            progress,
            conflict_id=conflict_id,
            accepted_snapshot_id=body.accepted_snapshot_id,
            resolution_note=body.resolution_note,
            actor_id=_current_actor_id(),
            request_id=body.request_id,
            expected_conflict_version=body.expected_conflict_version,
            expected_map_version=body.expected_map_version,
        )
        service.save(progress)
    except FeynmanError as exc:
        raise _feynman_http_error(exc)
    return result


@router.post("/progress/{book_id}/conflicts/{conflict_id}/reopen")
async def reopen_conflict(book_id: str, conflict_id: str, body: ConflictReopenRequest):
    """Owner-only conflict reopen (§7.7, §8.2): immediately restores the
    correctness block for the affected knowledge points."""
    _validate_book_id(book_id)
    service = get_cycle_service()
    progress = service.load(book_id)
    if progress is None:
        raise HTTPException(status_code=404, detail="Progress not found")
    try:
        result = service.reopen_conflict(
            progress,
            conflict_id=conflict_id,
            actor_id=_current_actor_id(),
            request_id=body.request_id,
            expected_conflict_version=body.expected_conflict_version,
            expected_map_version=body.expected_map_version,
        )
        service.save(progress)
    except FeynmanError as exc:
        raise _feynman_http_error(exc)
    return result


@router.post("/progress/{book_id}/attempts/{attempt_id}/challenge")
async def create_challenge(book_id: str, attempt_id: str, body: ChallengeRequest):
    """Create a challenge (§8.3): ``reassess_existing`` appends a later
    assessment revision to the same attempt; ``collect_new_evidence`` creates a
    linked reevaluation attempt. Challenges never directly write a pass."""
    _validate_book_id(book_id)
    service = get_cycle_service()
    progress = service.load(book_id)
    if progress is None:
        raise HTTPException(status_code=404, detail="Progress not found")
    from deeptutor.learning.cycles import is_configured_evaluator_snapshot
    from deeptutor.learning.models import EvaluatorSnapshot

    requested = None
    if body.requested_evaluator_snapshot:
        requested = EvaluatorSnapshot.model_validate(body.requested_evaluator_snapshot)
        # The challenge may only re-evaluate with the frozen original evaluator
        # or an explicitly selected *configured* alternative (§7.3.1/§9.3). A
        # forged/unknown snapshot is rejected here and would also fail closed at
        # the evaluation boundary.
        if not is_configured_evaluator_snapshot(requested):
            raise HTTPException(
                status_code=409,
                detail=(
                    "requested challenge evaluator is not a configured profile/model; "
                    "explicitly select a configured evaluator or omit the override"
                ),
            )
    try:
        challenge = service.create_challenge(
            progress,
            attempt_id=attempt_id,
            mode=body.mode,
            reason=body.reason,
            requested_evaluator_snapshot=requested,
            request_id=body.request_id,
            expected_attempt_version=body.expected_attempt_version,
        )
        service.save(progress)
    except FeynmanError as exc:
        raise _feynman_http_error(exc)
    return {
        "challenge_id": challenge.id,
        "mode": challenge.mode.value,
        "status": challenge.status.value,
        "source_attempt_id": challenge.source_attempt_id,
        "source_assessment_id": challenge.source_assessment_id,
        "result_attempt_id": challenge.result_attempt_id,
        "knowledge_point_id": challenge.knowledge_point_id,
        # The advanced concurrency token the caller must use for the next
        # mutation (a stale token can no longer be reused, §8.3).
        "attempt_version": progress.aggregate_versions.attempt,
    }


@router.post("/progress/{book_id}/attempts/{attempt_id}/resume")
async def resume_attempt(book_id: str, attempt_id: str):
    """Resume a draft/interrupted attempt (§8.3).

    An invalidated attempt returns a stable ``requires_restart`` with the
    current map version; its old evidence chain is never resumed."""
    _validate_book_id(book_id)
    service = get_cycle_service()
    progress = service.load(book_id)
    if progress is None:
        raise HTTPException(status_code=404, detail="Progress not found")
    try:
        return service.resume_attempt(progress, attempt_id=attempt_id)
    except UnknownAttemptError as exc:
        raise _feynman_http_error(exc)


# ── KB-02 knowledge-card draft collection / edit / retry / discard (§8.5) ─


@router.get("/progress/{book_id}/knowledge-cards")
async def list_knowledge_cards(book_id: str):
    """Owner-visible knowledge-card collection for the path (§8.5).

    Reconciles stale evidence through the KB-02 domain contract before building
    the projection, so a card whose bound stable assessment was overturned
    becomes ``stale_evidence`` (read-only) on the next read. Returns every card
    the actor owns (legacy cards with no owner included); the client filters
    ``discarded``/``retracted`` out of the *pending* display while still showing
    their final state. Never derives mastery from a card and never mutates
    assessment/evidence when reconciling.
    """
    _validate_book_id(book_id)
    service = get_draft_service()
    user_id = _current_actor_id()
    progress = service.load(book_id)
    if progress is None:
        raise HTTPException(status_code=404, detail="Progress not found")
    # Reconcile stale evidence (durable, CAS-safe) before serving the read so a
    # stale card is never presented as editable (§6.6, §15). A concurrent writer
    # winning the CAS is a recoverable read: re-load and serve the current
    # persisted state (the server still enforces eligibility on every mutation).
    try:
        service.reconcile_stale(progress)
    except KnowledgeCardStaleVersionError:
        progress = service.load(book_id) or progress
    media_store = service.media_store
    cards = [
        _card_view(progress, card, user_id=user_id, media_store=media_store)
        for card in progress.knowledge_cards
        if (not card.user_id or card.user_id == user_id)
    ]
    return {"cards": cards, "updated_at": progress.updated_at}


@router.post("/progress/{book_id}/knowledge-points/{kp_id}/knowledge-card")
async def ensure_knowledge_card(book_id: str, kp_id: str):
    """Server-derived idempotent draft creation/resume (§8.5).

    The request never carries an assessment id — the service selects the current
    latest valid stable assessment from the projection and atomically creates an
    empty ``draft`` shell plus its first ``queued`` generation attempt. Reuses an
    existing occupying card (draft / publish_failed / reconcile_required);
    returns ``new_stable_evidence_required`` when a newer stable assessment is
    needed after a retraction.
    """
    _validate_book_id(book_id)
    service = get_draft_service()
    user_id = _current_actor_id()
    progress = service.load(book_id)
    if progress is None:
        raise HTTPException(status_code=404, detail="Progress not found")
    try:
        result = service.ensure_draft(
            progress,
            user_id=user_id,
            path_id=book_id,
            knowledge_point_id=kp_id,
        )
    except KnowledgeCardError as exc:
        raise _knowledge_card_http_error(exc)
    card = result["card"]
    return {
        **_card_view_for(
            book_id,
            card.id,
            user_id=user_id,
            draft_service=service,
            media_store=service.media_store,
        ),
        "created": result["created"],
    }


@router.patch("/progress/{book_id}/knowledge-cards/{card_id}")
async def edit_knowledge_card(book_id: str, card_id: str, body: EditCardRequest):
    """Versioned draft edit (title/body + optional artifact attach/detach, §8.5).

    ``expected_card_revision`` and ``request_id`` are required; the first user
    change to title/body sets ``generation_locked_by_user_edit`` so a later
    model retry can never overwrite confirmed content. Artifact changes are
    versioned through the KB-02 draft service's MED-03 references and roll back
    on a failed CAS save.
    """
    _validate_book_id(book_id)
    service = get_draft_service()
    user_id = _current_actor_id()
    progress = service.load(book_id)
    if progress is None:
        raise HTTPException(status_code=404, detail="Progress not found")
    try:
        service.edit_draft(
            progress,
            card_id=card_id,
            user_id=user_id,
            request_id=body.request_id,
            expected_card_revision=body.expected_card_revision,
            title=body.title,
            body=body.body,
            attach_artifact_ids=body.attach_artifact_ids,
            detach_artifact_ids=body.detach_artifact_ids,
        )
        return _card_view_for(
            book_id,
            card_id,
            user_id=user_id,
            draft_service=service,
            media_store=service.media_store,
        )
    except KnowledgeCardError as exc:
        raise _knowledge_card_http_error(exc)


@router.post("/progress/{book_id}/knowledge-cards/{card_id}/retry-generation")
async def retry_card_generation(book_id: str, card_id: str, body: RetryGenerationRequest):
    """Explicit knowledge-card generation retry (§8.5 requirement 8).

    Only for a draft still holding current stable eligibility whose latest
    attempt has terminated and which is not locked by a user edit. Creates a new
    append-only attempt reusing the exact frozen model snapshot; a stale
    ``latest_generation_attempt_id`` or revision is a recoverable conflict.
    """
    _validate_book_id(book_id)
    service = get_draft_service()
    user_id = _current_actor_id()
    progress = service.load(book_id)
    if progress is None:
        raise HTTPException(status_code=404, detail="Progress not found")
    try:
        service.retry_generation(
            progress,
            card_id=card_id,
            user_id=user_id,
            request_id=body.request_id,
            expected_card_revision=body.expected_card_revision,
            latest_generation_attempt_id=body.latest_generation_attempt_id,
        )
        return _card_view_for(
            book_id,
            card_id,
            user_id=user_id,
            draft_service=service,
            media_store=service.media_store,
        )
    except KnowledgeCardError as exc:
        raise _knowledge_card_http_error(exc)


@router.post("/progress/{book_id}/knowledge-cards/{card_id}/discard")
async def discard_knowledge_card(book_id: str, card_id: str, body: DiscardCardRequest):
    """Discard an unpublished draft without touching learning evidence (§8.5).

    Releases the card's ``KNOWLEDGE_CARD`` media references so GC can eventually
    reclaim the media. Draft and stale-evidence cards are discardable; published
    or in-flight cards are not.
    """
    _validate_book_id(book_id)
    service = get_draft_service()
    user_id = _current_actor_id()
    progress = service.load(book_id)
    if progress is None:
        raise HTTPException(status_code=404, detail="Progress not found")
    try:
        service.discard(
            progress,
            card_id=card_id,
            user_id=user_id,
            request_id=body.request_id,
            expected_card_revision=body.expected_card_revision,
        )
        return _card_view_for(
            book_id,
            card_id,
            user_id=user_id,
            draft_service=service,
            media_store=service.media_store,
        )
    except KnowledgeCardError as exc:
        raise _knowledge_card_http_error(exc)


# ── KB-03 knowledge-card publication (§7.9.2) ─────────────────────────────


@router.get("/progress/{book_id}/knowledge-cards/{card_id}")
async def get_card_publication(book_id: str, card_id: str):
    """Read one knowledge card's publication projection (§8.5).

    Lets a client observe publication state (status, fixed path, SHA-256,
    publication key, timestamps, sanitized diagnostics, publication records)
    after a reload."""
    _validate_book_id(book_id)
    service = get_publication_service()
    try:
        return service.publication_projection(book_id, card_id=card_id, user_id=_current_actor_id())
    except KnowledgeCardError as exc:
        raise _knowledge_card_http_error(exc)


@router.post("/progress/{book_id}/knowledge-cards/{card_id}/publish")
async def publish_knowledge_card(book_id: str, card_id: str, body: PublishCardRequest):
    """Owner-only, user-confirmed knowledge-card publication (§7.9.2).

    Revalidates card/assessment/mastery eligibility, enforces the writable-KB
    policy, sets ``confirmed_at``, writes the deterministic fixed document and
    integrates it through the DocumentAdder/RAGService path. Idempotent under
    ``publication_key`` (``user_id + card_id + card_revision + target_kb_name``):
    same key + same content replays; same key + different content conflicts.
    """
    _validate_book_id(book_id)
    service = get_publication_service()
    try:
        return await service.publish(
            book_id,
            card_id=card_id,
            user_id=_current_actor_id(),
            request_id=body.request_id,
            expected_card_revision=body.expected_card_revision,
            target_kb_name=body.target_kb_name,
        )
    except KnowledgeCardError as exc:
        raise _knowledge_card_http_error(exc)


@router.post("/progress/{book_id}/knowledge-cards/{card_id}/retry-publish")
async def retry_publish_knowledge_card(book_id: str, card_id: str, body: RetryPublishCardRequest):
    """Retry a confirmed-failed publication, reusing the original key/path/hash.

    Never creates a second raw file, publication record, or indexed knowledge-card
    document (§7.9.2 requirement 10).
    """
    _validate_book_id(book_id)
    service = get_publication_service()
    try:
        return await service.retry_publish(
            book_id,
            card_id=card_id,
            user_id=_current_actor_id(),
            request_id=body.request_id,
            expected_card_revision=body.expected_card_revision,
            target_kb_name=body.target_kb_name,
        )
    except KnowledgeCardError as exc:
        raise _knowledge_card_http_error(exc)


@router.post("/progress/{book_id}/knowledge-cards/{card_id}/reconcile-publication")
async def reconcile_card_publication(book_id: str, card_id: str):
    """Conservatively reconcile an interrupted/ambiguous publication (§7.9.2).

    Read-only with respect to raw/index submission: inspects only the fixed
    path/hash, KB metadata, the write-operation record, and existing index
    evidence — never creates/copies/resubmits a file. Converges to
    ``published``, ``publish_failed``, or ``reconcile_required``.
    """
    _validate_book_id(book_id)
    service = get_publication_service()
    try:
        return service.reconcile_publication(book_id, card_id=card_id, user_id=_current_actor_id())
    except KnowledgeCardError as exc:
        raise _knowledge_card_http_error(exc)


@router.post("/progress/{book_id}/knowledge-cards/{card_id}/retract")
async def retract_knowledge_card(book_id: str, card_id: str, body: RetractCardRequest):
    """Owner-only, user-confirmed knowledge-card retraction (§7.11).

    Re-verifies owner/path/revision/published state, internal publication
    consistency, the writable-KB policy, fixed-path containment under
    ``raw/learning_cards``, and the raw bytes matching the published SHA-256
    before any KB mutation; then quarantines the exact raw document on the same
    KB volume, triggers the full production reindex over the excluding set, and
    only marks the card ``retracted`` once the exclusion is fully proven.
    Idempotent under ``request_id`` for one card revision: same payload replays;
    reuse with different facts conflicts.
    """
    _validate_book_id(book_id)
    service = get_retraction_service()
    try:
        return await service.retract(
            book_id,
            card_id=card_id,
            user_id=_current_actor_id(),
            request_id=body.request_id,
            expected_card_revision=body.expected_card_revision,
        )
    except KnowledgeCardError as exc:
        raise _knowledge_card_http_error(exc)


@router.post("/progress/{book_id}/knowledge-cards/{card_id}/reconcile-retraction")
async def reconcile_card_retraction(book_id: str, card_id: str):
    """Conservatively reconcile an interrupted/ambiguous retraction (§7.11).

    Observational: inspects only the fixed raw/quarantine path+hash, KB
    metadata/index evidence, ready/needs-reindex state, and the exact existing
    operation identity. Converges to ``retracted`` or ``published`` only when
    one terminal side is fully proven; otherwise stays
    ``retract_reconcile_required``. Never moves/deletes/restores/reindexes/
    resubmits.
    """
    _validate_book_id(book_id)
    service = get_retraction_service()
    try:
        return service.reconcile_retraction(book_id, card_id=card_id, user_id=_current_actor_id())
    except KnowledgeCardError as exc:
        raise _knowledge_card_http_error(exc)


@router.post("/progress/{book_id}/init-modules")
async def init_modules(book_id: str, body: InitModulesRequest):
    _validate_book_id(book_id)
    modules = _parse_modules(body.modules)
    _validate_runnable_modules(modules)
    await _cancel_active_learning_turn(book_id)
    service = get_learning_service()
    progress = service.get_or_create(book_id)
    service.init_modules(progress, modules)
    progress.current_module_id = modules[0].id
    progress.current_kp_index = 0
    service.save(progress)
    return {"status": "ok", "module_count": len(modules)}


@router.post("/progress/{book_id}/import-from-book")
async def import_from_book(book_id: str, body: ImportFromBookRequest):
    _validate_book_id(book_id)
    modules = []
    for i, ch in enumerate(body.chapters):
        kps = [
            KnowledgePoint(
                id=f"{book_id}_ch{i}_kp{j}",
                name=kp_name,
                type=KnowledgeType("concept"),
                module_id=f"{book_id}_ch{i}",
            )
            for j, kp_name in enumerate(ch.knowledge_points)
        ]
        modules.append(
            LearningModule(
                id=f"{book_id}_ch{i}",
                name=ch.title or f"Chapter {i + 1}",
                order=i,
                pass_threshold=0.7,
                knowledge_points=kps,
            )
        )
    _validate_runnable_modules(modules)
    await _cancel_active_learning_turn(book_id)
    service = get_learning_service()
    progress = service.get_or_create(book_id)
    service.init_modules(progress, modules)
    progress.current_module_id = modules[0].id
    progress.current_kp_index = 0
    service.save(progress)
    return {"status": "ok", "module_count": len(modules)}


@router.delete("/progress/{book_id}")
async def delete_progress(book_id: str):
    _validate_book_id(book_id)
    store = LearningStore()
    if not store.exists(book_id):
        raise HTTPException(status_code=404, detail="Progress not found")
    store.delete(book_id)
    return {"status": "ok"}


@router.post("/progress/{book_id}/redo")
async def redo_progress(book_id: str):
    _validate_book_id(book_id)
    store = LearningStore()
    progress = store.load(book_id)
    if progress is None:
        raise HTTPException(status_code=404, detail="Progress not found")
    progress.current_stage = LearningStage.DIAGNOSTIC
    progress.mastery_levels = {}
    progress.qualitative_mastery = {}
    progress.quiz_attempts = []
    progress.error_records = []
    progress.repetition_states = {}
    progress.review_queue = []
    progress.pending_question = None
    progress.feynman_retries = {}
    progress.feynman_explanations = {}
    progress.stage_failure_counts = {}
    progress.stage_failure_notes = {}
    progress.diagnostic = None
    progress.current_kp_index = 0
    progress.current_module_id = progress.modules[0].id if progress.modules else ""
    store.save(progress)
    return {"status": "ok"}


class NotebookRecordInput(BaseModel):
    id: str
    type: str = "note"
    title: str = ""
    output: str = ""


class GenerateFromNotebookRequest(BaseModel):
    notebook_id: str
    records: list[NotebookRecordInput]


@router.post("/progress/{book_id}/generate-from-notebook")
async def generate_from_notebook(book_id: str, body: GenerateFromNotebookRequest):
    _validate_book_id(book_id)
    if not body.records:
        raise HTTPException(status_code=400, detail="No records provided")

    records_data = [
        {
            "type": html.escape(r.type[:50], quote=False),
            "title": html.escape(r.title[:200], quote=False),
            "output": html.escape(r.output[:500], quote=False),
        }
        for r in body.records[:20]
    ]
    records_json = json.dumps(records_data, ensure_ascii=False)
    from deeptutor.services.llm import complete

    language = get_ui_language()
    system_prompt, prompt = learning_prompts.notebook_generation_prompts(language, records_json)
    response = await complete(prompt=prompt, system_prompt=system_prompt)
    # LLMs commonly fence/slightly-malform JSON; use the shared fence-stripping
    # repair parser instead of bare json.loads so the common case isn't a 502.
    data = parse_json_response(response, fallback=None)
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="LLM returned invalid JSON")

    modules_raw = data.get("modules", [])
    if not isinstance(modules_raw, list):
        raise HTTPException(
            status_code=502, detail="LLM returned invalid structure: modules is not a list"
        )
    _ALLOWED_KP_TYPES = {"memory", "concept", "procedure", "design"}
    modules = []
    for i, m in enumerate(modules_raw):
        if not isinstance(m, dict) or "name" not in m:
            continue
        fallback_name = learning_prompts.default_module_name(language, i + 1)
        module_name = str(m.get("name") or fallback_name).strip()[:200] or fallback_name
        kps = []
        for j, kp in enumerate(m.get("knowledge_points", [])):
            if not isinstance(kp, dict) or "name" not in kp:
                continue
            kp_name = str(kp["name"]).strip()[:200]
            if len(kp_name) < 2:
                continue
            kp_type = str(kp.get("type", "concept")).strip()
            if kp_type not in _ALLOWED_KP_TYPES:
                kp_type = "concept"
            kps.append(
                KnowledgePoint(
                    id=f"{book_id}_nb{i}_kp{j}",
                    name=kp_name,
                    type=KnowledgeType(kp_type),
                    module_id=f"{book_id}_nb{i}",
                )
            )
        modules.append(
            LearningModule(
                id=f"{book_id}_nb{i}",
                name=module_name,
                order=i,
                pass_threshold=0.7,
                knowledge_points=kps,
            )
        )
    _validate_runnable_modules(modules, status_code=502)
    await _cancel_active_learning_turn(book_id)
    service = get_learning_service()
    progress = service.get_or_create(book_id)
    service.init_modules(progress, modules)
    progress.current_module_id = modules[0].id
    progress.current_kp_index = 0
    service.save(progress)
    return {
        "status": "ok",
        "module_count": len(modules),
        "modules": [m.model_dump() for m in modules],
    }
