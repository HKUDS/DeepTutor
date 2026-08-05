"""Safe API views for media jobs, artifacts and quota (MED-03).

These serializers define exactly what the browser may see (§11.3/§14): stable
sanitized status codes and safe ids only, sanitized (already redacted) error
copy, artifact provenance without private resource URLs or base64 payloads, and
authenticated same-user file endpoints instead of raw filesystem paths.

``original_path``/``thumbnail_path`` (server-side relative paths) are never
exposed; the frontend always loads image bytes through the authenticated
``file`` route below.
"""

from __future__ import annotations

import time
from typing import Any

from deeptutor.services.media.models import (
    GeneratedArtifact,
    ImageGenerationJob,
    QuotaInfo,
)
from deeptutor.services.media.redaction import redact_text

#: Maximum length of an error message we will echo back to the browser.  The
#: worker already truncates persisted errors to 500 chars and redacts secrets;
#: this keeps the surface small and stable for the card layout.
_MAX_ERROR_CHARS = 300


def _elapsed_seconds(job: ImageGenerationJob, *, now: float | None = None) -> float:
    """Wall-clock time since the job started (0 when it has not started)."""
    if not job.started_at:
        return 0.0
    end = job.finished_at or (time.time() if now is None else now)
    return max(0.0, round(end - job.started_at, 1))


def _sanitized_error(job: ImageGenerationJob) -> str:
    """Stable, sanitized error copy — never a raw provider error body.

    The worker already redacts before persisting; this re-runs the sanitizer on
    output so a legacy/corrupt record can never leak a credential to the
    browser (defense in depth, §14).
    """
    text = redact_text((job.sanitized_error or "").strip())
    if len(text) > _MAX_ERROR_CHARS:
        text = f"{text[:_MAX_ERROR_CHARS]}…"
    return text


def job_card(job: ImageGenerationJob) -> dict[str, Any]:
    """Serialize a job for the browser (safe fields only)."""
    return {
        "id": job.id,
        "status": job.status.value,
        "status_version": job.status_version,
        "operation": job.operation.value,
        "prompt": job.original_prompt,
        "provider": job.provider,
        "profile": job.profile,
        "protocol": job.protocol,
        "model": job.model,
        "session_id": job.session_id,
        "turn_id": job.turn_id,
        "tool_call_id": job.tool_call_id,
        "error_code": job.error_code,
        "sanitized_error": _sanitized_error(job),
        "created_at": job.created_at,
        "started_at": job.started_at,
        "updated_at": job.updated_at,
        "finished_at": job.finished_at,
        "elapsed_seconds": _elapsed_seconds(job),
        "poll_after": job.poll_after,
        "deadline_at": job.deadline_at,
        "attempt_count": job.attempt_count,
        "artifact_ids": list(job.artifact_ids),
        "retry_of_job_id": job.retry_of_job_id,
        # Provider/remote ids are deliberately omitted: the browser needs only
        # the lifecycle facts above, and "safe IDs only" (§11.3) keeps remote
        # diagnostics server-side.
    }


def artifact_file_path(artifact: GeneratedArtifact) -> dict[str, str]:
    """The authenticated routes that serve an artifact's bytes.

    The browser never receives a filesystem path or a provider URL — only this
    same-user route.  ``preview_url`` (inline) serves the thumbnail when one
    exists; ``download_url`` (attachment) always serves the full original with a
    download disposition.
    """
    return {
        "preview_url": f"/api/v1/generated-artifacts/{artifact.id}/file?disposition=inline",
        "download_url": f"/api/v1/generated-artifacts/{artifact.id}/file?disposition=attachment",
    }


def artifact_view(
    artifact: GeneratedArtifact,
    *,
    references: list[Any],
    preview_url: str | None = None,
    download_url: str | None = None,
) -> dict[str, Any]:
    """Serialize one artifact for the browser, including its live references.

    ``references`` must already be scoped to the artifact and (for the listing)
    the current user; the caller is responsible for ownership filtering.
    """
    live = [r for r in references if r.is_live]
    return {
        "id": artifact.id,
        "job_id": artifact.job_id,
        "session_id": artifact.session_id,
        "turn_id": artifact.turn_id,
        "provider": artifact.provider,
        "profile": artifact.profile,
        "protocol": artifact.protocol,
        "model": artifact.model,
        "operation": artifact.operation.value,
        "original_prompt": artifact.original_prompt,
        "revised_prompt": artifact.revised_prompt,
        "sha256": artifact.sha256,
        "mime_type": artifact.mime_type,
        "width": artifact.width,
        "height": artifact.height,
        "size_bytes": artifact.size_bytes,
        "created_at": artifact.created_at,
        "gc_candidate_since": artifact.gc_candidate_since,
        "is_gc_candidate": artifact.is_gc_candidate,
        "reference_count": len(live),
        "references": [
            {
                "id": r.id,
                "owner_type": r.owner_type.value,
                "owner_id": r.owner_id,
                "version": r.version,
                "created_at": r.created_at,
                "is_live": r.is_live,
            }
            for r in references
        ],
        "preview_url": preview_url,
        "download_url": download_url,
    }


def quota_view(info: QuotaInfo) -> dict[str, Any]:
    """Serialize quota so the settings surface can render used/limit/reclaimable."""
    return {
        "used_bytes": info.used_bytes,
        "limit_bytes": info.limit_bytes,
        "reclaimable_bytes": info.reclaimable_bytes,
        "file_count": info.file_count,
        "remaining_bytes": info.remaining_bytes,
    }


__all__ = [
    "artifact_file_path",
    "artifact_view",
    "job_card",
    "quota_view",
]
