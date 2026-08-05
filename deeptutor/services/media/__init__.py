"""Persistent media runtime: image jobs, generated artifacts, references, GC.

MED-01 scope — durable :class:`ImageGenerationJob`, :class:`GeneratedArtifact`
and :class:`ArtifactReference` records, content-addressed atomic media
persistence, SHA-256 deduplication, thumbnails, soft-deleted references, GC
with a grace period, and per-user disk quota.  Provider adapters are out of
scope here; the :class:`~deeptutor.services.media.worker.JobExecutor` protocol
is the seam MED-02 adapters plug into.
"""

from __future__ import annotations

from deeptutor.services.media.adapters import MediaAdapterRouter
from deeptutor.services.media.adapters.base import (
    AdapterResult,
    ImageGenerationRequest,
    UnsupportedOperationError,
)
from deeptutor.services.media.config import DEFAULT_ALLOWED_MIME_TYPES, MediaLimits
from deeptutor.services.media.models import (
    ACTIVE_JOB_STATUSES,
    TERMINAL_JOB_STATUSES,
    AmbiguousSubmitError,
    ArtifactOperation,
    ArtifactReference,
    ArtifactReferenceError,
    ConfirmationRequired,
    GcResult,
    GeneratedArtifact,
    ImageGenerationJob,
    ImageJobStatus,
    JobConcurrencyError,
    JobStateError,
    MediaConfigError,
    MediaError,
    MediaInput,
    MediaValidationError,
    QuotaExceededError,
    QuotaInfo,
    ReferenceOwnerType,
    SavedMedia,
    TransientPollError,
)
from deeptutor.services.media.persistence import MediaPersistence, image_info
from deeptutor.services.media.safe_download import (
    SafeDownloader,
    SafeDownloadError,
    SSRFBlockedError,
)
from deeptutor.services.media.scheduler import MediaScheduler
from deeptutor.services.media.store import MediaStore, default_media_root
from deeptutor.services.media.worker import ImageGenerationJobWorker, JobExecutor

__all__ = [
    "ACTIVE_JOB_STATUSES",
    "TERMINAL_JOB_STATUSES",
    "AdapterResult",
    "AmbiguousSubmitError",
    "ArtifactOperation",
    "ArtifactReference",
    "ArtifactReferenceError",
    "ConfirmationRequired",
    "DEFAULT_ALLOWED_MIME_TYPES",
    "GcResult",
    "GeneratedArtifact",
    "ImageGenerationJob",
    "ImageGenerationJobWorker",
    "ImageGenerationRequest",
    "ImageJobStatus",
    "JobConcurrencyError",
    "JobExecutor",
    "JobStateError",
    "MediaAdapterRouter",
    "MediaConfigError",
    "MediaError",
    "MediaInput",
    "MediaLimits",
    "MediaPersistence",
    "MediaScheduler",
    "MediaStore",
    "MediaValidationError",
    "QuotaExceededError",
    "QuotaInfo",
    "ReferenceOwnerType",
    "SSRFBlockedError",
    "SafeDownloadError",
    "SafeDownloader",
    "SavedMedia",
    "TransientPollError",
    "UnsupportedOperationError",
    "default_media_root",
    "image_info",
]
