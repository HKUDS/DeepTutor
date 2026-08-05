"""Content-addressed, atomic media persistence (MED-01).

Implements the success-path guarantees of design §12.1:

1. receive raw bytes
2. stage into a same-volume temp file
3. validate magic / allowed MIME / byte cap / pixel cap / decode integrity
4. compute SHA-256
5. atomically rename into the content-addressed path (dedup on existing file)
6. derive a thumbnail
7. (metadata + references are written by :class:`MediaStore`)

Any failure raises before the caller can record a ``succeeded`` job, and
leaves no half-written target behind.  Validation is intentionally fail-closed:
unknown magic, MIME mismatch, over-limit files and undecodable images are all
rejected before anything is committed.
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
import tempfile

from deeptutor.services.media.config import MediaLimits
from deeptutor.services.media.models import MediaValidationError, SavedMedia

logger = logging.getLogger(__name__)

_EXT_BY_MIME: dict[str, str] = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
}

_MAGIC_BY_MIME: tuple[tuple[str, bytes, bytes | None], ...] = (
    ("image/png", b"\x89PNG\r\n\x1a\n", None),
    ("image/jpeg", b"\xff\xd8\xff", None),
    ("image/gif", b"GIF8", None),
    # WebP is RIFF....WEBP; the 8-byte RIFF header plus the 4-byte chunk tag.
    ("image/webp", b"RIFF", b"WEBP"),
)


def _sniff_mime(data: bytes) -> str:
    """Return the MIME type implied by the file magic, or ``""`` if unknown."""
    for mime, magic, trailer in _MAGIC_BY_MIME:
        if not data.startswith(magic):
            continue
        if trailer is not None and data[8:12] != trailer:
            continue
        return mime
    return ""


def image_info(data: bytes) -> tuple[str, int, int] | None:
    """Return ``(sniffed_mime, width, height)`` from a header-only parse.

    ``None`` when the bytes do not start with a recognised image magic or the
    dimensions cannot be read from the header.  This is the same dependency-free
    parse the persistence path uses and is the public seam MED-02 validation /
    safe-download use *before* anything is decompressed (pixel caps must be
    enforced before a decode, §12.1).
    """
    sniffed = _sniff_mime(data)
    if not sniffed:
        return None
    parser = _DIMENSION_PARSERS.get(sniffed)
    if parser is None:
        return None
    dims = parser(data)  # type: ignore[operator]
    if dims is None:
        return None
    return sniffed, dims[0], dims[1]


def _extension(mime_type: str) -> str:
    return _EXT_BY_MIME.get(mime_type.split(";")[0].strip().lower(), "png")


# ── dependency-free dimension parsing (fallback when Pillow is absent) ──────


def _png_dimensions(data: bytes) -> tuple[int, int] | None:
    if len(data) >= 24:
        width = int.from_bytes(data[16:20], "big")
        height = int.from_bytes(data[20:24], "big")
        if width and height:
            return width, height
    return None


def _gif_dimensions(data: bytes) -> tuple[int, int] | None:
    if len(data) >= 10:
        width = int.from_bytes(data[6:8], "little")
        height = int.from_bytes(data[8:10], "little")
        if width and height:
            return width, height
    return None


def _jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    # Scan markers for a SOF0..SOF15 segment, which carries the frame size.
    index = 2
    while index + 9 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        if marker == 0xFF or marker in (0x00, 0x01) or 0xD0 <= marker <= 0xD9:
            index += 2
            continue
        length = int.from_bytes(data[index + 2 : index + 4], "big")
        if marker in (
            0xC0,
            0xC1,
            0xC2,
            0xC3,
            0xC5,
            0xC6,
            0xC7,
            0xC9,
            0xCA,
            0xCB,
            0xCD,
            0xCE,
            0xCF,
        ):
            if index + 9 <= len(data):
                height = int.from_bytes(data[index + 5 : index + 7], "big")
                width = int.from_bytes(data[index + 7 : index + 9], "big")
                return width, height
            return None
        index += 2 + length
    return None


def _webp_dimensions(data: bytes) -> tuple[int, int] | None:
    if len(data) < 30 or data[0:4] != b"RIFF" or data[8:12] != b"WEBP":
        return None
    chunk = data[12:16]
    if chunk == b"VP8 " and len(data) >= 30:
        width = int.from_bytes(data[26:28], "little") & 0x3FFF
        height = int.from_bytes(data[28:30], "little") & 0x3FFF
        return (width, height) if width and height else None
    if chunk == b"VP8L" and len(data) >= 25:
        bits = int.from_bytes(data[21:25], "little")
        width = (bits & 0x3FFF) + 1
        height = ((bits >> 14) & 0x3FFF) + 1
        return width, height
    if chunk == b"VP8X" and len(data) >= 30:
        width = int.from_bytes(data[24:27], "little") + 1
        height = int.from_bytes(data[27:30], "little") + 1
        return width, height
    return None


_DIMENSION_PARSERS: dict[str, object] = {
    "image/png": _png_dimensions,
    "image/jpeg": _jpeg_dimensions,
    "image/webp": _webp_dimensions,
    "image/gif": _gif_dimensions,
}


class _PillowUnavailable(MediaValidationError):
    """Internal marker: Pillow could not be imported at all.

    The header-based dimension parser is only used as a fallback in this case;
    a Pillow decode failure is fail-closed and never silently downgraded.
    """


class MediaPersistence:
    """Owns the ``originals/``, ``thumbnails/`` and ``tmp/`` directories.

    On-disk layout under the media root::

        originals/<sha256[:2]>/<sha256>.<ext>
        thumbnails/<sha256[:2]>/<sha256>.jpg
        tmp/...

    ``tmp`` shares the volume so :func:`os.replace` is atomic.
    """

    def __init__(self, root: Path, limits: MediaLimits) -> None:
        self._root = Path(root)
        self._limits = limits
        self._originals = self._root / "originals"
        self._thumbnails = self._root / "thumbnails"
        self._tmp = self._root / "tmp"
        self._originals.mkdir(parents=True, exist_ok=True)
        self._thumbnails.mkdir(parents=True, exist_ok=True)
        self._tmp.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    def resolve(self, relative_path: str) -> Path:
        """Resolve a stored relative path under the media root, refusing escapes."""
        candidate = (self._root / relative_path).resolve()
        try:
            candidate.relative_to(self._root.resolve())
        except ValueError as exc:
            raise MediaValidationError(
                f"stored media path escapes media root: {relative_path!r}"
            ) from exc
        return candidate

    def save_media(self, data: bytes, *, mime_type: str) -> SavedMedia:
        """Validate *data* and atomically persist it content-addressed.

        Raises :class:`MediaValidationError` (or ``OSError`` for storage
        failures) on any problem.  A successful return means the original file
        is committed on disk and a thumbnail has been derived (best-effort).
        """
        if not data:
            raise MediaValidationError("Refusing to persist empty media payload.")
        if len(data) > self._limits.max_file_bytes:
            raise MediaValidationError(
                f"Media payload of {len(data)} bytes exceeds per-file limit "
                f"{self._limits.max_file_bytes}."
            )

        sniffed = _sniff_mime(data)
        if not sniffed:
            raise MediaValidationError("Unrecognized image magic; refusing to persist.")
        declared = (mime_type or "").split(";")[0].strip().lower()
        if declared and declared != sniffed:
            raise MediaValidationError(
                f"MIME mismatch: declared {declared!r}, magic sniffed {sniffed!r}."
            )
        if not self._limits.allows_mime(sniffed):
            raise MediaValidationError(f"MIME {sniffed!r} is not allowed.")

        width, height = self._read_dimensions(data, sniffed)
        pixels = width * height
        if pixels > self._limits.max_pixels:
            raise MediaValidationError(
                f"Image {width}x{height} exceeds pixel limit {self._limits.max_pixels}."
            )

        sha256 = hashlib.sha256(data).hexdigest()
        ext = _extension(sniffed)
        original_rel = f"originals/{sha256[:2]}/{sha256}.{ext}"
        original_abs = self._root / original_rel
        created = not original_abs.exists()

        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=str(self._tmp), delete=False) as handle:
                tmp_path = Path(handle.name)
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            if created:
                original_abs.parent.mkdir(parents=True, exist_ok=True)
                os.replace(tmp_path, original_abs)
                tmp_path = None
            else:
                tmp_path.unlink(missing_ok=True)
                tmp_path = None
            thumbnail_rel = self._make_thumbnail(original_abs, sha256, sniffed)
            return SavedMedia(
                sha256=sha256,
                mime_type=sniffed,
                width=width,
                height=height,
                size_bytes=len(data),
                original_path=original_rel,
                thumbnail_path=thumbnail_rel,
                created_original=created,
            )
        except MediaValidationError:
            raise
        except OSError:
            # Never leave a partial target behind.
            if created:
                original_abs.unlink(missing_ok=True)
            raise
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)

    def remove_media(self, saved: SavedMedia) -> None:
        """Best-effort removal of the files referenced by *saved*.

        Only safe for files this save actually created (``created_original``);
        callers must never pass a dedup hit here.
        """
        paths = [saved.thumbnail_path]
        if saved.created_original:
            paths.insert(0, saved.original_path)
        for relative in paths:
            if not relative:
                continue
            try:
                path = self.resolve(relative)
                path.unlink(missing_ok=True)
            except (MediaValidationError, OSError):
                logger.debug("cleanup of %s failed", relative, exc_info=True)

    # ── internal helpers ─────────────────────────────────────────────────────

    def _read_dimensions(self, data: bytes, mime_type: str) -> tuple[int, int]:
        try:
            return self._dimensions_with_pillow(data)
        except _PillowUnavailable:
            parser = _DIMENSION_PARSERS.get(mime_type)
            if parser is not None:
                dims = parser(data)  # type: ignore[operator]
                if dims is not None:
                    return dims
            raise MediaValidationError(
                f"Unable to determine image dimensions for {mime_type!r}."
            ) from None

    @staticmethod
    def _dimensions_with_pillow(data: bytes) -> tuple[int, int]:
        """Decode + verify via Pillow; raises :class:`MediaValidationError`."""
        try:
            from io import BytesIO

            from PIL import Image
        except Exception as exc:  # Pillow not installed
            raise _PillowUnavailable(str(exc)) from exc
        try:
            with Image.open(BytesIO(data)) as image:
                width, height = image.size
                image.verify()
            return int(width), int(height)
        except Exception as exc:
            raise MediaValidationError(f"Image decode/verification failed: {exc}") from exc

    def _make_thumbnail(self, original_abs: Path, sha256: str, _mime_type: str) -> str:
        """Derive a JPEG thumbnail; returns a relative path or ``""`` on failure."""
        try:
            from PIL import Image
        except Exception:
            logger.warning("Pillow unavailable; skipping thumbnail for %s", sha256)
            return ""
        thumbnail_rel = f"thumbnails/{sha256[:2]}/{sha256}.jpg"
        thumbnail_abs = self._root / thumbnail_rel
        if thumbnail_abs.exists():
            return thumbnail_rel
        tmp = thumbnail_abs.parent / f"{thumbnail_abs.name}.tmp"
        try:
            with Image.open(original_abs) as image:
                image.load()
                image.thumbnail(
                    (
                        self._limits.thumbnail_max_dimension,
                        self._limits.thumbnail_max_dimension,
                    ),
                    Image.Resampling.LANCZOS,
                )
                thumbnail_abs.parent.mkdir(parents=True, exist_ok=True)
                with tmp.open("wb") as handle:
                    image.convert("RGB").save(handle, format="JPEG", quality=82)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp, thumbnail_abs)
        except Exception:
            logger.warning("thumbnail generation failed for %s", sha256, exc_info=True)
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            return ""
        return thumbnail_rel


__all__ = ["MediaPersistence", "image_info"]
