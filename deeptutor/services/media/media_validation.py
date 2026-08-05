"""Execution-time media input validation shared by the MED-02 adapters.

The worker validates *ownership* of source/mask/continuation references at
submission time (§10.1).  The adapters additionally enforce the *content*
rules that need the persisted bytes: the mask must be an image of exactly the
same pixel dimensions as the target source, and every input payload must pass
the §12.1 media policy before it is handed to the store.
"""

from __future__ import annotations

from dataclasses import dataclass

from deeptutor.services.media.config import MediaLimits
from deeptutor.services.media.models import (
    ImageGenerationJob,
    MediaError,
    MediaValidationError,
)
from deeptutor.services.media.persistence import image_info
from deeptutor.services.media.safe_download import validate_media_bytes
from deeptutor.services.media.store import MediaStore


@dataclass(frozen=True)
class LoadedImage:
    """Persisted artifact bytes plus their header-derived dimensions."""

    data: bytes
    mime_type: str
    width: int
    height: int

    def dimensions(self) -> tuple[int, int]:
        return self.width, self.height


def load_artifact_bytes(
    store: MediaStore,
    artifact_id: str,
    *,
    user_id: str,
    limits: MediaLimits,
    label: str,
) -> LoadedImage:
    """Load an artifact's persisted bytes and validate them (§12.2).

    Ownership is re-checked server-side even though the worker already did:
    the adapter must never trust a caller-supplied id that snuck past an older
    code path.
    """
    artifact = store.load_artifact(artifact_id)
    if artifact is None:
        raise MediaError(f"{label} artifact not found: {artifact_id}")
    if artifact.user_id != user_id:
        raise MediaError(
            f"{label} artifact {artifact_id} belongs to user {artifact.user_id!r}, not {user_id!r}"
        )
    try:
        path = store.persistence.resolve(artifact.original_path)
        data = path.read_bytes()
    except OSError as exc:
        raise MediaError(f"Could not read {label} artifact media: {exc}") from exc
    info = image_info(data)
    if info is None:
        raise MediaValidationError(f"{label} artifact has unreadable media.")
    return LoadedImage(
        data=data,
        mime_type=info[0],
        width=info[1],
        height=info[2],
    )


def validate_mask_dimensions(source: LoadedImage, mask: LoadedImage) -> None:
    """Mask dimensions must exactly equal the target source (§10.1)."""
    if mask.dimensions() != source.dimensions():
        raise MediaValidationError(
            f"Mask dimensions {mask.width}x{mask.height} must equal the source "
            f"image dimensions {source.width}x{source.height}."
        )


def validate_edit_inputs(
    store: MediaStore,
    job: ImageGenerationJob,
    *,
    limits: MediaLimits,
) -> tuple[list[LoadedImage], LoadedImage | None]:
    """Load and validate the source/mask inputs for an edit job.

    Returns ``(sources, mask)``.  At least one source is required; a mask, when
    present, must match the *first* source's dimensions.  Every payload passes
    the full §12.1 policy (magic, MIME, size, pixels, decode) before it is used.
    """
    if not job.source_artifact_ids:
        raise MediaError("edit requires at least one owned source artifact")
    sources: list[LoadedImage] = []
    for artifact_id in job.source_artifact_ids:
        loaded = load_artifact_bytes(
            store, artifact_id, user_id=job.user_id, limits=limits, label="source"
        )
        validate_media_bytes(loaded.data, limits=limits)
        sources.append(loaded)
    mask: LoadedImage | None = None
    if job.mask_artifact_id:
        mask = load_artifact_bytes(
            store, job.mask_artifact_id, user_id=job.user_id, limits=limits, label="mask"
        )
        validate_media_bytes(mask.data, limits=limits)
        validate_mask_dimensions(sources[0], mask)
    return sources, mask


__all__ = [
    "LoadedImage",
    "load_artifact_bytes",
    "validate_edit_inputs",
    "validate_mask_dimensions",
]
