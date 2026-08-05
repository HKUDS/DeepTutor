"""Data models for the persistent media runtime (MED-01).

These are the durable records defined in the approved design §10.5, §11.3 and
§12: :class:`ImageGenerationJob`, :class:`GeneratedArtifact`,
:class:`ArtifactReference`, plus the small transfer/result values the store and
worker exchange.  Every persisted record follows the repository's
``ConfigDict(extra="ignore")`` convention so legacy JSON loads cleanly and new
defaulted fields never break old records.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ImageJobStatus(str, Enum):
    """Lifecycle of an asynchronous image-generation job (§11.2)."""

    QUEUED = "queued"
    RUNNING = "running"
    POLLING = "polling"
    VALIDATING = "validating"
    SAVING = "saving"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    CANCELLED_UNCONFIRMED = "cancelled_unconfirmed"
    TIMED_OUT = "timed_out"
    UNKNOWN = "unknown"


#: States that never resume work and are never automatically retried.
TERMINAL_JOB_STATUSES: frozenset[ImageJobStatus] = frozenset(
    {
        ImageJobStatus.SUCCEEDED,
        ImageJobStatus.FAILED,
        ImageJobStatus.CANCELLED,
        ImageJobStatus.CANCELLED_UNCONFIRMED,
        ImageJobStatus.TIMED_OUT,
        ImageJobStatus.UNKNOWN,
    }
)

#: States that hold an in-flight provider execution or a local save, and so
#: consume a per-user concurrency slot.
ACTIVE_JOB_STATUSES: frozenset[ImageJobStatus] = frozenset(
    {
        ImageJobStatus.QUEUED,
        ImageJobStatus.RUNNING,
        ImageJobStatus.POLLING,
        ImageJobStatus.VALIDATING,
        ImageJobStatus.SAVING,
        ImageJobStatus.CANCEL_REQUESTED,
    }
)


class ArtifactOperation(str, Enum):
    """What the generating job was asked to do (§10.1)."""

    GENERATE = "generate"
    EDIT = "edit"


class ReferenceOwnerType(str, Enum):
    """Contexts that can hold a live reference to an artifact (§10.5)."""

    SESSION = "session"
    MESSAGE = "message"
    NOTEBOOK = "notebook"
    LEARNING_MATERIAL = "learning_material"
    KNOWLEDGE_CARD = "knowledge_card"


class ImageGenerationJob(BaseModel):
    """Persisted image-generation job record (§11.3)."""

    model_config = ConfigDict(extra="ignore")

    id: str
    user_id: str = ""
    session_id: str = ""
    turn_id: str = ""
    tool_call_id: str = ""
    status: ImageJobStatus = ImageJobStatus.QUEUED
    status_version: int = 0
    operation: ArtifactOperation = ArtifactOperation.GENERATE
    original_prompt: str = ""
    provider: str = ""
    profile: str = ""
    protocol: str = ""
    model: str = ""
    #: Frozen request facts (prompt, size, quality, count, source ids).  Never
    #: contains credentials; secrets stay server-side and are not persisted.
    request_snapshot: dict[str, Any] = Field(default_factory=dict)
    request_hash: str = ""
    idempotency_key: str = ""
    source_artifact_ids: list[str] = Field(default_factory=list)
    mask_artifact_id: str = ""
    continuation_job_id: str = ""
    remote_response_id: str = ""
    remote_job_id: str = ""
    artifact_ids: list[str] = Field(default_factory=list)
    retry_of_job_id: str = ""
    connect_timeout_seconds: int = 20
    read_timeout_seconds: int = 1800
    deadline_at: float = 0.0
    #: Absolute epoch time the next poll is due (§11.4); 0.0 when not polling.
    poll_after: float = 0.0
    #: Current poll backoff delay in seconds (2s start, 15s cap).  Stored so a
    #: restart can keep backing off instead of restarting at 2s.
    poll_delay_seconds: float = 0.0
    attempt_count: int = 0
    error_code: str = ""
    sanitized_error: str = ""
    created_at: float = Field(default_factory=time.time)
    started_at: float = 0.0
    updated_at: float = Field(default_factory=time.time)
    finished_at: float = 0.0

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_JOB_STATUSES


class GeneratedArtifact(BaseModel):
    """Persisted media artifact with full provenance (§10.5)."""

    model_config = ConfigDict(extra="ignore")

    id: str
    user_id: str = ""
    job_id: str = ""
    session_id: str = ""
    turn_id: str = ""
    tool_call_id: str = ""
    provider: str = ""
    profile: str = ""
    protocol: str = ""
    model: str = ""
    original_prompt: str = ""
    revised_prompt: str = ""
    operation: ArtifactOperation = ArtifactOperation.GENERATE
    parent_artifact_ids: list[str] = Field(default_factory=list)
    mask_sha256: str = ""
    continuation_job_id: str = ""
    remote_response_id: str = ""
    remote_asset_id: str = ""
    sha256: str
    mime_type: str = "image/png"
    width: int = 0
    height: int = 0
    size_bytes: int = 0
    #: Content-addressed relative paths under the media root.  ``original_path``
    #: is derived from ``sha256``; ``thumbnail_path`` may be empty when
    #: thumbnail generation is unavailable (Pillow missing / failure).
    original_path: str = ""
    thumbnail_path: str = ""
    #: Timestamp the artifact entered the GC grace period (0 = still
    #: referenced / not a candidate).  Re-adding a reference clears it.
    gc_candidate_since: float = 0.0
    created_at: float = Field(default_factory=time.time)

    @property
    def is_gc_candidate(self) -> bool:
        return self.gc_candidate_since > 0


class ArtifactReference(BaseModel):
    """A soft-deletable reference from one owner context to an artifact (§10.5)."""

    model_config = ConfigDict(extra="ignore")

    id: str
    artifact_id: str
    user_id: str = ""
    owner_type: ReferenceOwnerType
    owner_id: str
    #: Optimistic-concurrency version; deletion uses ``expected_version``.
    version: int = 0
    created_at: float = Field(default_factory=time.time)
    #: 0.0 == live; >0 == soft-deleted (audit history kept).
    deleted_at: float = 0.0

    @property
    def is_live(self) -> bool:
        return self.deleted_at == 0.0


@dataclass(frozen=True)
class MediaInput:
    """One provider-produced image awaiting local persistence.

    Returned by a :class:`~deeptutor.services.media.worker.JobExecutor`
    implementation (supplied by MED-02 adapters) and consumed by the worker's
    atomic save pipeline.
    """

    data: bytes
    mime_type: str = "image/png"
    remote_response_id: str = ""
    remote_asset_id: str = ""
    revised_prompt: str = ""


@dataclass(frozen=True)
class BackgroundSubmit:
    """A provider acknowledged an asynchronous job without producing images.

    Returned by an executor's ``run`` (MED-02) when a background submit has
    been accepted and the worker must persist the remote identity and switch
    the job to ``polling`` (§11.5).  The caller never supplies these remote
    identities — they are the provider's own ids returned by the adapter.
    """

    remote_response_id: str = ""
    remote_job_id: str = ""
    #: Seconds to wait before the first poll (provider hint, clamped by the
    #: scheduler to the configured backoff window).
    poll_after: float = 2.0


@dataclass(frozen=True)
class PollOutcome:
    """Result of one background ``poll`` call (§11.5).

    Exactly one of ``media`` or ``poll_after`` is meaningful:

    * ``media`` non-empty -> the remote job is complete; persist the images.
    * ``poll_after`` > 0     -> still running; poll again after the delay.
    * both empty             -> a provider error surfaced as an exception; the
      worker fails the job rather than guessing.
    """

    media: list[MediaInput] = field(default_factory=list)
    poll_after: float = 0.0


@dataclass(frozen=True)
class SavedMedia:
    """Result of a successful content-addressed save (§12.1)."""

    sha256: str
    mime_type: str
    width: int
    height: int
    size_bytes: int
    original_path: str
    thumbnail_path: str
    #: False when the content-addressed file already existed (SHA-256 dedup);
    #: cleanup must never remove dedup-shared files.
    created_original: bool = True


class QuotaInfo(BaseModel):
    """Snapshot of a user's media quota (§12.3)."""

    model_config = ConfigDict(extra="ignore")

    used_bytes: int
    limit_bytes: int
    reclaimable_bytes: int
    file_count: int = 0

    @property
    def remaining_bytes(self) -> int:
        return max(0, self.limit_bytes - self.used_bytes)


class GcResult(BaseModel):
    """Outcome of a GC pass (§12.3)."""

    model_config = ConfigDict(extra="ignore")

    deleted_count: int = 0
    freed_bytes: int = 0
    scanned_count: int = 0


# ── errors ───────────────────────────────────────────────────────────────────


class MediaError(RuntimeError):
    """Base class for persistent-media failures."""


class MediaValidationError(MediaError):
    """Rejected media bytes (magic, MIME, size, pixels, decode)."""


class MediaConfigError(MediaError):
    """A queued job names a profile/model that no longer resolves in the model
    catalog; execution fails closed rather than guessing a provider (§11.3)."""


class AmbiguousSubmitError(MediaError):
    """A submit POST may have been accepted by the provider but the outcome is
    unknown (read timeout, partial write, disconnect after request acceptance).

    With no remote id to reconcile, the worker transitions the job to
    ``unknown`` — never a generic ``failed`` that invites a duplicate user
    retry, and never an automatic re-submit (§11.5)."""


class TransientPollError(MediaError):
    """A transient retrieve/read failure for a background job that already has a
    durable remote id.

    The worker keeps the job ``polling`` with bounded backoff until the deadline
    instead of failing it, so a still-running remote job is never abandoned and
    a duplicate user retry is never invited (§11.5)."""


class QuotaExceededError(MediaError):
    """The per-user media quota would be exceeded.

    Carries the numbers the UI needs for a recoverable error card: bytes used,
    the configured limit, and how many bytes are reclaimable via GC.
    """

    def __init__(
        self,
        *,
        used_bytes: int,
        limit_bytes: int,
        reclaimable_bytes: int,
        message: str | None = None,
    ) -> None:
        self.used_bytes = used_bytes
        self.limit_bytes = limit_bytes
        self.reclaimable_bytes = reclaimable_bytes
        text = message or (
            "Media quota exceeded: used={used} limit={limit} reclaimable={reclaimable}".format(
                used=used_bytes, limit=limit_bytes, reclaimable=reclaimable_bytes
            )
        )
        super().__init__(text)


class JobStateError(MediaError):
    """Invalid job state transition or status-version conflict."""


class JobConcurrencyError(MediaError):
    """The per-user in-flight job limit is exhausted."""


class ArtifactReferenceError(MediaError):
    """Reference conflicts (version mismatch, missing artifact)."""


class ConfirmationRequired(MediaError):
    """A destructive operation (``remove_everywhere``) needs explicit confirmation."""


ReferenceOwnerTypeLiteral = Literal[
    "session", "message", "notebook", "learning_material", "knowledge_card"
]


__all__ = [
    "ACTIVE_JOB_STATUSES",
    "TERMINAL_JOB_STATUSES",
    "AmbiguousSubmitError",
    "ArtifactOperation",
    "ArtifactReference",
    "ArtifactReferenceError",
    "BackgroundSubmit",
    "ConfirmationRequired",
    "GcResult",
    "GeneratedArtifact",
    "ImageGenerationJob",
    "ImageJobStatus",
    "JobConcurrencyError",
    "JobStateError",
    "MediaConfigError",
    "MediaError",
    "MediaInput",
    "MediaValidationError",
    "PollOutcome",
    "QuotaExceededError",
    "QuotaInfo",
    "ReferenceOwnerType",
    "ReferenceOwnerTypeLiteral",
    "SavedMedia",
    "TransientPollError",
]
