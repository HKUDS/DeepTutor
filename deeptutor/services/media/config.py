"""Persistent media runtime configuration (MED-01).

Defaults for artifact persistence, thumbnails, references, garbage collection
and per-user disk quota.  The values are plain dataclasses so tests and the
settings layer can override them without coupling this task to a new settings
file; a future task can read the same knobs from ``data/user/settings``.
"""

from __future__ import annotations

from dataclasses import dataclass

#: MIME types the media store accepts.  Image-generation providers return
#: PNG/JPEG/WebP/GIF; anything else is rejected before anything is written.
DEFAULT_ALLOWED_MIME_TYPES: tuple[str, ...] = (
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/gif",
)

_MIB = 1024 * 1024
_GB = 1024 * 1024 * 1024


@dataclass(frozen=True)
class MediaLimits:
    """Enforcement-ready media policy limits.

    All values are read at call time by :class:`MediaStore` /
    :class:`MediaPersistence`; tests construct small limits directly so quota
    and GC behaviour can be exercised without filling real disk space.
    """

    #: Maximum bytes for a single generated image.
    max_file_bytes: int = 20 * _MIB
    #: Maximum pixel count (width * height) for a single generated image.
    max_pixels: int = 4096 * 4096
    #: Per-user total quota in bytes.  Quota counts logical artifact bytes
    #: (each ``GeneratedArtifact`` record contributes its ``size_bytes``),
    #: which is deliberately conservative for SHA-256-deduplicated content.
    max_user_bytes: int = 1 * _GB
    #: Maximum in-flight (non-terminal) image jobs per user.
    max_concurrent_jobs: int = 4
    #: Longest edge for generated JPEG thumbnails.
    thumbnail_max_dimension: int = 512
    #: Grace period before an unreferenced artifact becomes collectable by the
    #: automatic GC sweep.  Explicit (user-invoked) GC skips this wait.
    grace_period_seconds: float = 7 * 24 * 3600.0
    #: Accepted image MIME types.
    allowed_mime_types: tuple[str, ...] = DEFAULT_ALLOWED_MIME_TYPES

    def allows_mime(self, mime_type: str) -> bool:
        normalized = (mime_type or "").split(";")[0].strip().lower()
        return normalized in self.allowed_mime_types


__all__ = ["DEFAULT_ALLOWED_MIME_TYPES", "MediaLimits"]
