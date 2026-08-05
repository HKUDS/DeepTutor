"""MED-01 focused tests: atomic file persistence, SHA-256, thumbnails, validation."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from deeptutor.services.media.config import MediaLimits
from deeptutor.services.media.models import MediaValidationError
from deeptutor.services.media.persistence import MediaPersistence
from tests.services.media._media_helpers import make_png


@pytest.fixture
def persistence(tmp_path: Path) -> MediaPersistence:
    return MediaPersistence(root=tmp_path / "media", limits=MediaLimits())


def test_save_media_is_content_addressed_with_thumbnail(persistence: MediaPersistence) -> None:
    data = make_png(8, 8)
    saved = persistence.save_media(data, mime_type="image/png")

    assert saved.sha256 == hashlib.sha256(data).hexdigest()
    assert saved.width == 8 and saved.height == 8
    assert saved.size_bytes == len(data)
    assert saved.mime_type == "image/png"
    assert saved.created_original is True

    original = persistence.resolve(saved.original_path)
    assert original.exists()
    assert original.read_bytes() == data
    assert original.parent.name == saved.sha256[:2]

    assert saved.thumbnail_path
    thumbnail = persistence.resolve(saved.thumbnail_path)
    assert thumbnail.exists()
    assert thumbnail.suffix == ".jpg"


def test_save_media_dedupes_by_sha256(persistence: MediaPersistence) -> None:
    data = make_png(4, 4)
    first = persistence.save_media(data, mime_type="image/png")
    second = persistence.save_media(data, mime_type="image/png")

    assert first.created_original is True
    assert second.created_original is False
    assert first.original_path == second.original_path
    # Only one physical file exists for the deduped content.
    matches = list((persistence.root / "originals").rglob(f"{first.sha256}.png"))
    assert len(matches) == 1


def test_save_media_rejects_empty_payload(persistence: MediaPersistence) -> None:
    with pytest.raises(MediaValidationError, match="empty"):
        persistence.save_media(b"", mime_type="image/png")


def test_save_media_rejects_oversized_file(tmp_path: Path) -> None:
    persistence = MediaPersistence(root=tmp_path / "media", limits=MediaLimits(max_file_bytes=16))
    with pytest.raises(MediaValidationError, match="per-file limit"):
        persistence.save_media(make_png(8, 8), mime_type="image/png")


def test_save_media_rejects_unknown_magic(persistence: MediaPersistence) -> None:
    with pytest.raises(MediaValidationError, match="magic"):
        persistence.save_media(b"this is not an image at all", mime_type="image/png")


def test_save_media_rejects_mime_mismatch(persistence: MediaPersistence) -> None:
    data = make_png(8, 8)
    with pytest.raises(MediaValidationError, match="MIME mismatch"):
        persistence.save_media(data, mime_type="image/jpeg")


def test_save_media_rejects_disallowed_mime(tmp_path: Path) -> None:
    persistence = MediaPersistence(
        root=tmp_path / "media",
        limits=MediaLimits(allowed_mime_types=("image/png",)),
    )
    # GIF magic but not allowed by the configured policy.
    gif = b"GIF89a" + b"\x00" * 20
    with pytest.raises(MediaValidationError, match="not allowed"):
        persistence.save_media(gif, mime_type="image/gif")


def test_save_media_rejects_oversized_pixels(tmp_path: Path) -> None:
    persistence = MediaPersistence(root=tmp_path / "media", limits=MediaLimits(max_pixels=16))
    # 8x8 = 64 pixels > 16
    with pytest.raises(MediaValidationError, match="pixel limit"):
        persistence.save_media(make_png(8, 8), mime_type="image/png")


def test_save_media_rejects_truncated_image(persistence: MediaPersistence) -> None:
    # PNG magic is valid, but the payload is far too short to decode.
    truncated = make_png(8, 8)[:8]
    with pytest.raises(MediaValidationError, match="decode|dimensions"):
        persistence.save_media(truncated, mime_type="image/png")


def test_resolve_refuses_path_escape(persistence: MediaPersistence) -> None:
    with pytest.raises(MediaValidationError, match="escapes"):
        persistence.resolve("../outside.png")
