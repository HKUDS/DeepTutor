"""Provider-neutral request/result contract and shared adapter helpers (MED-02).

The one :class:`ImageGenerationRequest` shape is what every adapter consumes
(§10.1): operation, prompt, profile/model, source artifacts, optional mask,
continuation job, size/quality/count and provider options.  ``generate`` never
carries source/mask/continuation; ``edit`` requires at least one owned source
or an owned continuation (§10.1).  A provider that cannot satisfy the requested
operation raises :class:`UnsupportedOperationError` — it must never silently
fall back to a generate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from deeptutor.services.media.adapter_config import AdapterRuntimeConfig
from deeptutor.services.media.models import (
    ArtifactOperation,
    BackgroundSubmit,
    ImageGenerationJob,
    MediaError,
    MediaInput,
)

#: Stable error code for a requested operation a provider cannot perform.
UNSUPPORTED_OPERATION = "unsupported_operation"


def is_ambiguous_transport_failure(exc: Exception) -> bool:
    """True when a transport failure happened *after* the request may have been
    accepted, so the provider's outcome is unknown (§11.5).

    Read-phase / response-phase failures (read timeout, connection dropped
    while reading, write timeout, partial write, unexpected protocol close) and
    socket-level disconnects after request acceptance are ambiguous: the
    provider may be processing the job and may bill for it.  Definite
    pre-connect/unaccepted failures (DNS failure, connection refused, connect
    timeout) return ``False`` so the worker can keep them as ordinary failures.
    """
    if isinstance(
        exc,
        (
            httpx.ReadTimeout,
            httpx.ReadError,
            httpx.WriteTimeout,
            httpx.WriteError,
            httpx.RemoteProtocolError,
            BrokenPipeError,
            ConnectionResetError,
        ),
    ):
        return True
    return False


class UnsupportedOperationError(MediaError):
    """The provider/profile cannot perform the requested operation.

    Raised instead of silently degrading (e.g. an edit becoming a generate).
    The worker persists it as ``error_code="unsupported_operation"``.
    """

    def __init__(self, operation: str, *, detail: str = "") -> None:
        message = (
            f"The configured image provider does not support {operation!r}."
            if not detail
            else f"The configured image provider does not support {operation!r}: {detail}"
        )
        super().__init__(message)


@dataclass(frozen=True)
class ImageGenerationRequest:
    """Provider-neutral request handed to every MED-02 adapter (§10.1)."""

    operation: ArtifactOperation
    prompt: str
    profile_id: str = ""
    request_model: str = ""
    source_artifact_ids: list[str] = field(default_factory=list)
    mask_artifact_id: str = ""
    continuation_job_id: str = ""
    size: str = ""
    quality: str = ""
    count: int = 1
    provider_options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AdapterResult:
    """Provider-neutral adapter result (§10.1).

    ``media`` are the validated payloads awaiting local persistence; remote ids
    and the revised prompt are provenance only (they are persisted by the
    worker on the artifact records, never the client-supplied values).
    """

    media: list[MediaInput] = field(default_factory=list)
    remote_response_id: str = ""
    remote_job_id: str = ""
    revised_prompt: str = ""


def request_from_job(job: ImageGenerationJob) -> ImageGenerationRequest:
    """Build the provider-neutral request from a durable job record.

    Only trusted job fields are used; any caller-supplied remote/continuation
    identity was already stripped by the worker's snapshot sanitizer, so the
    adapter can never act on a client-injected remote id (§10.1).
    """
    snapshot = job.request_snapshot or {}
    return ImageGenerationRequest(
        operation=job.operation,
        prompt=job.original_prompt,
        profile_id=job.profile,
        request_model=job.model,
        source_artifact_ids=list(job.source_artifact_ids),
        mask_artifact_id=job.mask_artifact_id,
        continuation_job_id=job.continuation_job_id,
        size=str(snapshot.get("size") or ""),
        quality=str(snapshot.get("quality") or ""),
        count=int(snapshot.get("count") or 1),
        provider_options=dict(snapshot.get("provider_options") or {}),
    )


def raise_for_status(response: Any, action: str) -> None:
    """Raise a provider error carrying only the status, never the body.

    Provider error bodies are untrusted and may embed keys, signed URLs or
    base64 payloads; they are deliberately not propagated (§10.5/§14).
    """
    if response.status_code < 400:
        return
    raise MediaError(f"{action} failed with HTTP {response.status_code}.")


__all__ = [
    "UNSUPPORTED_OPERATION",
    "AdapterResult",
    "ImageGenerationRequest",
    "UnsupportedOperationError",
    "is_ambiguous_transport_failure",
    "raise_for_status",
    "request_from_job",
    "AdapterRuntimeConfig",
    "BackgroundSubmit",
]
