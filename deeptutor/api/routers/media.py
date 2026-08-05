"""User-scoped media management API (MED-03).

Exposes the accepted MED-01/MED-02 service contracts as REST endpoints:

* image-job submit / read / list / cancel / explicit retry
* generated-artifact preview / download, single-reference detach and
  confirmed ``remove_everywhere``
* quota summary and explicit eligible cleanup

Every endpoint is scoped to the authenticated user, enforces expected versions
and idempotency keys server-side, and returns only safe ids and sanitized error
copy (§11.3/§14).  Provider/profile/model/protocol/operation are validated
exactly; no caller-supplied remote identity is ever trusted.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from deeptutor.multi_user.context import get_current_user
from deeptutor.services.config.provider_runtime import (
    IMAGEGEN_PROVIDERS,
    _canonical_generation_provider,
)
from deeptutor.services.media.models import (
    ArtifactOperation,
    ArtifactReferenceError,
    ConfirmationRequired,
    GeneratedArtifact,
    ImageGenerationJob,
    ImageJobStatus,
    JobStateError,
    MediaConfigError,
    MediaError,
    MediaValidationError,
    ReferenceOwnerType,
)
from deeptutor.services.media.redaction import redact_text
from deeptutor.services.media.store import MediaStore
from deeptutor.services.media.views import (
    artifact_file_path,
    artifact_view,
    job_card,
    quota_view,
)
from deeptutor.services.media.worker import ImageGenerationJobWorker

logger = logging.getLogger(__name__)

router = APIRouter()

#: Image protocols the resolver routes to a dedicated MED-02 adapter (§10/§16.3).
_IMAGE_PROTOCOLS = frozenset({"openai_images", "openai_responses", "mcp"})

#: States a submitted job may be cancelled from.  A job that has already
#: submitted to a provider needs the remote cancel-confirmation path; a queued
#: job has never touched the provider and is cancelled definitively.
_CANCELLABLE_ACTIVE = frozenset(
    {ImageJobStatus.QUEUED, ImageJobStatus.RUNNING, ImageJobStatus.POLLING}
)

#: Terminal states a user may explicitly retry (new lineage).  ``succeeded`` is
#: excluded — a completed job has its artifacts; regenerating is a fresh submit,
#: not a retry (§11.5).
_RETRYABLE = frozenset(
    {
        ImageJobStatus.FAILED,
        ImageJobStatus.TIMED_OUT,
        ImageJobStatus.UNKNOWN,
        ImageJobStatus.CANCELLED,
        ImageJobStatus.CANCELLED_UNCONFIRMED,
    }
)

_EXT_BY_MIME = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
}


def _current_user_id() -> str:
    try:
        return str(get_current_user().id or "")
    except Exception:
        return ""


def _store() -> MediaStore:
    """A fresh per-request store rooted at the current user's media root."""
    return MediaStore()


def _worker(store: MediaStore) -> ImageGenerationJobWorker:
    return ImageGenerationJobWorker(store=store)


def _load_owned_job(store: MediaStore, job_id: str) -> ImageGenerationJob:
    job = store.load_job(job_id)
    if job is None or job.user_id != _current_user_id():
        raise HTTPException(status_code=404, detail="Job not found")
    return job


def _load_owned_artifact(store: MediaStore, artifact_id: str) -> GeneratedArtifact:
    artifact = store.load_artifact(artifact_id)
    if artifact is None or artifact.user_id != _current_user_id():
        raise HTTPException(status_code=404, detail="Artifact not found")
    return artifact


def _media_error_status(exc: Exception) -> tuple[int, str]:
    """Map a media domain error onto a stable HTTP status + safe message."""
    if isinstance(exc, (MediaConfigError, MediaValidationError)):
        return 422, redact_text(str(exc))
    if isinstance(exc, ConfirmationRequired):
        return 409, redact_text(str(exc))
    if isinstance(exc, (ArtifactReferenceError, JobStateError)):
        return 409, redact_text(str(exc))
    if isinstance(exc, MediaError):
        return 409, redact_text(str(exc))
    logger.warning("media API error: %s", type(exc).__name__)
    return 500, "Media operation failed"


def _imagegen_profile(profile_id: str) -> dict[str, Any]:
    """Validate that *profile_id* exists in the imagegen catalog (fail closed)."""
    from deeptutor.services.config.model_catalog import get_model_catalog_service

    catalog = get_model_catalog_service().load()
    profiles = catalog.get("services", {}).get("imagegen", {}).get("profiles") or []
    profile = next((p for p in profiles if p.get("id") == profile_id), None)
    if profile is None:
        raise HTTPException(
            status_code=422,
            detail=f"Image profile {profile_id!r} does not exist.",
        )
    return profile


def _validate_image_request(
    *,
    profile_id: str,
    model_id: str,
    protocol: str,
) -> tuple[dict[str, Any], str]:
    """Validate the exact profile/model/protocol the job will freeze (§10/§11.3).

    Returns ``(profile, provider)``.  An MCP protocol does not require a model
    (the tool mapping is authoritative); every other protocol must name a model
    that exists on the profile.  Unsupported protocols fail closed — the server
    never silently reroutes to another wire contract.
    """
    if protocol not in _IMAGE_PROTOCOLS:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported image protocol {protocol!r}.",
        )
    profile = _imagegen_profile(profile_id)
    if protocol != "mcp":
        if not model_id:
            raise HTTPException(
                status_code=422,
                detail="A model is required for the selected image profile.",
            )
        models = profile.get("models") or []
        if not any(m.get("id") == model_id or m.get("model") == model_id for m in models):
            raise HTTPException(
                status_code=422,
                detail=f"Image model {model_id!r} is not on profile {profile_id!r}.",
            )
    provider = _canonical_generation_provider(str(profile.get("binding") or ""), IMAGEGEN_PROVIDERS)
    return profile, provider


# ── request bodies ───────────────────────────────────────────────────────────


class ImageJobSubmit(BaseModel):
    operation: Literal["generate", "edit"] = "generate"
    prompt: str = Field(..., min_length=1)
    profile: str = ""
    model: str = ""
    protocol: str = ""
    size: str = ""
    quality: str = ""
    count: int = 1
    source_artifact_ids: list[str] = Field(default_factory=list)
    mask_artifact_id: str = ""
    continuation_job_id: str = ""
    #: §8.3 binds image-job submission to ``user_id + idempotency_key``: the
    #: key is mandatory at the API boundary so the same durable request never
    #: issues duplicate provider calls.  The worker stays backward compatible
    #: (empty key = no idempotency) for internal tool callers.
    idempotency_key: str = Field(..., min_length=1)
    session_id: str = ""
    turn_id: str = ""
    tool_call_id: str = ""
    provider_options: dict[str, Any] = Field(default_factory=dict)


class ImageJobCancel(BaseModel):
    expected_status_version: int | None = None


class ImageJobRetry(BaseModel):
    #: §8.3 binds retry to ``job_id + expected_status_version``.  Mandatory so
    #: a retry is a deterministic, conflict-checked action: the same terminal
    #: source version yields the same server-side idempotency key and therefore
    #: the same child job.
    expected_status_version: int = Field(...)
    profile: str = ""
    model: str = ""
    protocol: str = ""


class ReferenceDetach(BaseModel):
    expected_version: int | None = None


class ArtifactDelete(BaseModel):
    mode: Literal["detach_current", "remove_everywhere"]
    confirmed: bool = False
    owner_type: (
        Literal["session", "message", "notebook", "learning_material", "knowledge_card"] | None
    ) = None
    owner_id: str = ""


# ── image jobs ───────────────────────────────────────────────────────────────


@router.post("/image-jobs", status_code=201)
def submit_image_job(payload: ImageJobSubmit) -> dict[str, Any]:
    """Idempotently create a durable image-generation job (§11.3)."""
    store = _store()
    user_id = _current_user_id()
    profile_id = payload.profile.strip()
    protocol = (payload.protocol or "").strip().lower()
    idempotency_key = (payload.idempotency_key or "").strip()
    if not idempotency_key:
        raise HTTPException(
            status_code=422,
            detail="idempotency_key is required for image job submission.",
        )

    _profile, provider = _validate_image_request(
        profile_id=profile_id, model_id=payload.model.strip(), protocol=protocol
    )
    operation = ArtifactOperation(payload.operation)
    try:
        job = _worker(store).create_job(
            user_id=user_id,
            prompt=payload.prompt,
            operation=operation,
            session_id=payload.session_id,
            turn_id=payload.turn_id,
            tool_call_id=payload.tool_call_id,
            provider=provider,
            profile=profile_id,
            protocol=protocol,
            model=payload.model.strip(),
            idempotency_key=idempotency_key,
            source_artifact_ids=payload.source_artifact_ids,
            mask_artifact_id=payload.mask_artifact_id,
            continuation_job_id=payload.continuation_job_id,
            size=payload.size.strip(),
            quality=payload.quality.strip(),
            count=payload.count,
            request_snapshot={"provider_options": payload.provider_options},
        )
    except Exception as exc:  # noqa: BLE001 - mapped to a stable status
        status, message = _media_error_status(exc)
        raise HTTPException(status_code=status, detail=message) from exc
    return {"job": job_card(job)}


@router.get("/image-jobs")
def list_image_jobs(
    session_id: str = Query(default=""),
) -> dict[str, Any]:
    """List the current user's jobs, optionally scoped to one session."""
    store = _store()
    user_id = _current_user_id()
    jobs = store.list_jobs(user_id=user_id)
    if session_id:
        jobs = [job for job in jobs if job.session_id == session_id]
    return {"jobs": [job_card(job) for job in reversed(jobs)]}


@router.get("/image-jobs/{job_id}")
def read_image_job(job_id: str) -> dict[str, Any]:
    """Read one job card (the chat card polls this endpoint)."""
    store = _store()
    job = _load_owned_job(store, job_id)
    return {"job": job_card(job)}


@router.post("/image-jobs/{job_id}/cancel")
def cancel_image_job(job_id: str, payload: ImageJobCancel) -> dict[str, Any]:
    """Request cancellation of an active job (§11.6).

    A job that never reached the provider (``queued``) is cancelled
    definitively; a job that may have been accepted transitions to
    ``cancel_requested`` and the background scheduler confirms the remote
    cancellation (``cancelled`` or ``cancelled_unconfirmed``).
    """
    store = _store()
    job = _load_owned_job(store, job_id)
    if payload.expected_status_version is not None:
        if job.status_version != payload.expected_status_version:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Job {job_id} version conflict: expected "
                    f"{payload.expected_status_version}, got {job.status_version}."
                ),
            )
    if job.status not in _CANCELLABLE_ACTIVE:
        raise HTTPException(
            status_code=409,
            detail=f"Job {job_id} is not cancellable from {job.status.value!r}.",
        )
    if job.status == ImageJobStatus.QUEUED and not (job.remote_response_id or job.remote_job_id):
        updated = store.transition_job(
            job_id,
            from_status=ImageJobStatus.QUEUED,
            to_status=ImageJobStatus.CANCELLED,
            error_code="cancelled_before_submit",
        )
        return {"job": job_card(updated)}
    updated = store.transition_job(
        job_id,
        from_status=job.status,
        to_status=ImageJobStatus.CANCEL_REQUESTED,
    )
    return {"job": job_card(updated)}


@router.post("/image-jobs/{job_id}/retry", status_code=201)
def retry_image_job(job_id: str, payload: ImageJobRetry) -> dict[str, Any]:
    """Explicitly retry a terminal job as a new lineage (§11.5).

    The new job is linked to the old one via ``retry_of_job_id`` and freezes
    the same operation/prompt/sources unless the caller selects a different
    profile/model/protocol (profile-change retry).  Retry is always an explicit
    user action — never automatic.
    """
    store = _store()
    source = _load_owned_job(store, job_id)
    user_id = _current_user_id()
    # ``expected_status_version`` is mandatory (§8.3: retry carries
    # ``job_id + expected_status_version``); always conflict-check it so a stale
    # client can never retry against an already-superseded source version.
    if source.status_version != payload.expected_status_version:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Job {job_id} version conflict: expected "
                f"{payload.expected_status_version}, got {source.status_version}."
            ),
        )
    if source.status not in _RETRYABLE:
        raise HTTPException(
            status_code=409,
            detail=f"Job {job_id} cannot be retried from {source.status.value!r}.",
        )

    profile_id = (payload.profile or source.profile).strip()
    model_id = (payload.model or source.model).strip()
    protocol = (payload.protocol or source.protocol).strip().lower()
    _profile, _provider = _validate_image_request(
        profile_id=profile_id, model_id=model_id, protocol=protocol
    )

    # Stable server-side retry idempotency key derived from the current user,
    # the source job and the expected terminal status version.  The requested
    # profile/model/protocol stay out of the key (they remain in
    # ``request_hash``), so an identical retry returns the same child job while
    # a same-source/version retry with a different payload conflicts instead of
    # spawning a second child/provider call.
    retry_key = f"retry:{user_id}:{source.id}:{payload.expected_status_version}"
    try:
        job = _worker(store).create_job(
            user_id=user_id,
            prompt=source.original_prompt,
            operation=source.operation,
            session_id=source.session_id,
            turn_id=source.turn_id,
            tool_call_id=source.tool_call_id,
            provider=_provider,
            profile=profile_id,
            protocol=protocol,
            model=model_id,
            idempotency_key=retry_key,
            source_artifact_ids=list(source.source_artifact_ids),
            mask_artifact_id=source.mask_artifact_id,
            continuation_job_id=source.continuation_job_id,
            size=(source.request_snapshot or {}).get("size") or "",
            quality=(source.request_snapshot or {}).get("quality") or "",
            count=(source.request_snapshot or {}).get("count") or 1,
            retry_of_job_id=source.id,
        )
    except Exception as exc:  # noqa: BLE001 - mapped to a stable status
        status, message = _media_error_status(exc)
        raise HTTPException(status_code=status, detail=message) from exc
    return {"job": job_card(job)}


# ── generated artifacts ──────────────────────────────────────────────────────


@router.get("/generated-artifacts")
def list_generated_artifacts(
    session_id: str = Query(default=""),
) -> dict[str, Any]:
    """List the current user's artifacts with references and quota (§12.3)."""
    store = _store()
    user_id = _current_user_id()
    artifacts = store.list_artifacts(user_id=user_id)
    if session_id:
        artifacts = [a for a in artifacts if a.session_id == session_id]
    views = []
    for artifact in artifacts:
        references = store.list_references(artifact_id=artifact.id, user_id=user_id)
        views.append(
            artifact_view(
                artifact,
                references=references,
                **artifact_file_path(artifact),
            )
        )
    return {"artifacts": views, "quota": quota_view(store.quota_info(user_id))}


@router.get("/generated-artifacts/quota")
def read_generated_artifact_quota() -> dict[str, Any]:
    """Quota summary: used / limit / reclaimable / file count (§12.3)."""
    store = _store()
    return {"quota": quota_view(store.quota_info(_current_user_id()))}


@router.get("/generated-artifacts/{artifact_id}")
def read_generated_artifact(artifact_id: str) -> dict[str, Any]:
    """Read one artifact view (used by the succeeded job card)."""
    store = _store()
    artifact = _load_owned_artifact(store, artifact_id)
    references = store.list_references(artifact_id=artifact_id, user_id=_current_user_id())
    return {
        "artifact": artifact_view(
            artifact,
            references=references,
            **artifact_file_path(artifact),
        )
    }


@router.get("/generated-artifacts/{artifact_id}/file")
def serve_artifact_file(
    artifact_id: str,
    disposition: Literal["inline", "attachment"] = Query(default="inline"),
) -> FileResponse:
    """Serve the artifact's bytes to its owner only.

    Preview (``inline``) serves the thumbnail when available; download
    (``attachment``) always serves the full original with a download
    disposition.  No arbitrary filesystem path or remote URL ever reaches the
    browser — only this authenticated same-user route (§12.3).
    """
    store = _store()
    artifact = _load_owned_artifact(store, artifact_id)
    try:
        if disposition == "inline" and artifact.thumbnail_path:
            path = store.persistence.resolve(artifact.thumbnail_path)
            media_type = "image/jpeg"
            filename = f"{artifact.id}.jpg"
        else:
            path = store.persistence.resolve(artifact.original_path)
            media_type = artifact.mime_type or "application/octet-stream"
            ext = _EXT_BY_MIME.get(media_type.split(";")[0].strip().lower(), "png")
            filename = f"{artifact.id}.{ext}"
    except MediaValidationError as exc:
        raise HTTPException(status_code=404, detail=redact_text(str(exc))) from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Artifact file is missing.")
    content_disposition = (
        f'inline; filename="{filename}"'
        if disposition == "inline"
        else f'attachment; filename="{filename}"'
    )
    return FileResponse(
        path=path,
        media_type=media_type,
        headers={
            "Content-Disposition": content_disposition,
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=3600",
        },
    )


@router.delete("/generated-artifacts/{artifact_id}/references/{reference_id}")
def detach_artifact_reference(
    artifact_id: str, reference_id: str, payload: ReferenceDetach
) -> dict[str, Any]:
    """Detach exactly one context reference from the current conversation (§12.3).

    Uses ``expected_version`` to prevent concurrent overwrites.
    """
    store = _store()
    _load_owned_artifact(store, artifact_id)
    user_id = _current_user_id()
    # Bind the reference to the artifact on the URL path: a same-user reference
    # belonging to another artifact must fail closed without mutating either
    # artifact's references (§12.3).  The response always reflects the path
    # artifact, so deleting through the wrong URL must never be misleading.
    reference = store.load_reference(reference_id)
    if reference is None:
        raise HTTPException(status_code=404, detail="Reference not found.")
    if reference.user_id != user_id:
        raise HTTPException(status_code=404, detail="Reference not found.")
    if reference.artifact_id != artifact_id:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Reference {reference_id} belongs to artifact "
                f"{reference.artifact_id}, not {artifact_id}."
            ),
        )
    try:
        reference = store.delete_reference(
            reference_id,
            expected_version=payload.expected_version,
            user_id=user_id,
        )
    except ArtifactReferenceError as exc:
        raise HTTPException(status_code=409, detail=redact_text(str(exc))) from exc
    artifact = store.load_artifact(artifact_id)
    assert artifact is not None
    references = store.list_references(artifact_id=artifact_id, user_id=_current_user_id())
    return {
        "reference": {
            "id": reference.id,
            "artifact_id": artifact_id,
            "deleted_at": reference.deleted_at,
        },
        "artifact": artifact_view(
            artifact,
            references=references,
            **artifact_file_path(artifact),
        ),
    }


@router.post("/generated-artifacts/{artifact_id}/delete")
def delete_generated_artifact(artifact_id: str, payload: ArtifactDelete) -> dict[str, Any]:
    """Detach the current context reference or remove everywhere (§12.3).

    ``remove_everywhere`` soft-deletes every live reference the user owns and
    requires explicit ``confirmed=True``; the server rechecks the live reference
    count under its own mutation boundary, so a stale frontend count is never
    trusted.
    """
    store = _store()
    artifact = _load_owned_artifact(store, artifact_id)
    try:
        if payload.mode == "detach_current":
            if payload.owner_type is None or not payload.owner_id:
                raise HTTPException(
                    status_code=422,
                    detail="detach_current requires owner_type and owner_id.",
                )
            deleted = store.delete_artifact(
                artifact_id,
                mode="detach_current",
                user_id=_current_user_id(),
                owner_type=ReferenceOwnerType(payload.owner_type),
                owner_id=payload.owner_id,
            )
        else:
            deleted = store.delete_artifact(
                artifact_id,
                mode="remove_everywhere",
                user_id=_current_user_id(),
                confirmed=payload.confirmed,
            )
    except ConfirmationRequired as exc:
        raise HTTPException(status_code=409, detail=redact_text(str(exc))) from exc
    except ArtifactReferenceError as exc:
        raise HTTPException(status_code=409, detail=redact_text(str(exc))) from exc
    references = store.list_references(artifact_id=artifact_id, user_id=_current_user_id())
    return {
        "deleted_references": [r.id for r in deleted],
        "artifact": artifact_view(
            artifact,
            references=references,
            **artifact_file_path(artifact),
        ),
    }


@router.post("/generated-artifacts/gc")
def run_generated_artifact_gc() -> dict[str, Any]:
    """Explicit eligible cleanup for the current user (§12.3).

    Ends the grace period early for zero-reference candidates the user owns.
    Live references always block collection.
    """
    store = _store()
    result = store.run_gc(user_id=_current_user_id(), force=True)
    return {
        "result": {
            "deleted_count": result.deleted_count,
            "freed_bytes": result.freed_bytes,
            "scanned_count": result.scanned_count,
        }
    }


__all__ = ["router"]
