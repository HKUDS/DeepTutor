"""Safe extraction of user-uploaded ZIP archives.

A naive ``ZipFile.extractall`` is unsafe for untrusted uploads: it is
vulnerable to *Zip Slip* (path traversal via ``../`` or absolute member
names), *zip bombs* (tiny archives that decompress to fill the disk), and it
happily writes any file type. This module extracts members one at a time and
puts each through the same ``DocumentValidator`` gate as a direct upload:

* member names are collapsed to a sanitized basename, which defuses Zip Slip
  (no path component survives) and enforces the extension whitelist; with
  ``keep_subdirs`` the member's folders are kept instead, each segment
  sanitized by the same rule as a browser folder upload, and a member with a
  ``..`` segment is refused;
* per-entry uncompressed size, cumulative size, entry count and compression
  ratio are all bounded to defeat zip bombs;
* ``__MACOSX`` resource forks, dotfiles, tool/VCS/trash folders (``.git``,
  ``.ipynb_checkpoints``, ``.Trashes`` …), Windows thumbnail caches,
  directories and nested archives are skipped rather than trusted. Any other
  dot-folder (``.NET Basics/``) is ordinary content.

The extractor is deliberately decoupled from the upload router so it can be
unit-tested in isolation and reused by any ingestion path.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
import errno
import logging
from pathlib import Path
import zipfile

from deeptutor.utils.document_validator import DocumentValidator

logger = logging.getLogger(__name__)

# OS metadata that file managers add to every folder; never user documents.
_SYSTEM_FILE_NAMES = frozenset({"thumbs.db", "desktop.ini"})
# Folders written by the OS, version control or editors. Any other folder that
# starts with a dot (``.NET Basics/``) is course content and is kept.
_SYSTEM_DIR_NAMES = frozenset(
    {"__macosx", ".git", ".svn", ".hg", ".idea", ".vscode", ".ipynb_checkpoints"}
)
# One member's path that cannot exist next to another's (a file where a folder
# must be, or the reverse) or on this filesystem: skip it, keep the archive.
_MEMBER_PATH_ERRNOS = {
    errno.ENOTDIR: "path conflict",
    errno.EEXIST: "path conflict",
    errno.EISDIR: "path conflict",
    errno.ENAMETOOLONG: "path too long",
}


class ArchiveTooLargeError(ValueError):
    """Raised when an archive exceeds the configured extraction limits."""


@dataclass(frozen=True)
class ZipExtractionLimits:
    """Bounds applied while extracting an archive.

    Defaults are intentionally conservative and reuse the upload size cap so a
    zip cannot smuggle in more data than a direct upload would allow.
    """

    max_total_bytes: int = DocumentValidator.MAX_FILE_SIZE
    max_entry_bytes: int = DocumentValidator.MAX_FILE_SIZE
    max_entries: int = 1000
    max_compression_ratio: float = 200.0


@dataclass
class ZipExtractionResult:
    """Outcome of an extraction: written paths and skipped members + reasons."""

    extracted: list[Path] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)


def _is_within(path: Path, root: Path) -> bool:
    """True if ``path`` is ``root`` or lives underneath it."""
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


@contextmanager
def _remove_on_error(paths: list[Path], dirs: list[Path] | None = None) -> Iterator[None]:
    """Delete ``paths`` (then the now-empty ``dirs``) if the block raises.

    The caller rejects the whole archive on any error, so members written
    before the failing one must not stay behind in the target directory, and
    neither must the folders created for them.
    """
    try:
        yield
    except BaseException:
        for path in paths:
            # Best effort: a failed unlink must not mask the original error.
            with suppress(OSError):
                path.unlink(missing_ok=True)
        for directory in reversed(dirs or []):
            with suppress(OSError):
                directory.rmdir()
        raise


def _is_system_member(parts: list[str]) -> bool:
    """True for OS junk: resource forks, dotfiles, tool folders, thumbnail caches."""
    return (
        parts[-1].startswith(".")
        or parts[-1].lower() in _SYSTEM_FILE_NAMES
        or any(
            part.lower() in _SYSTEM_DIR_NAMES or part.startswith(".Trash") for part in parts[:-1]
        )
    )


def make_dirs_recorded(directory: Path, root: Path, created: list[Path]) -> None:
    """Create ``directory`` under ``root``, appending each folder it adds to ``created``.

    The caller removes exactly those folders (deepest first) to undo a member
    or an archive, without touching folders that existed before.
    """
    missing: list[Path] = []
    current = directory
    while current != root and not current.exists():
        missing.append(current)
        current = current.parent
    for folder in reversed(missing):
        folder.mkdir()
        created.append(folder)


def safe_extract_zip(
    zip_path: str | Path,
    target_dir: str | Path,
    *,
    allowed_extensions: set[str],
    limits: ZipExtractionLimits | None = None,
    keep_subdirs: bool = False,
) -> ZipExtractionResult:
    """Extract ``zip_path`` into ``target_dir`` under safe names.

    Args:
        zip_path: Path to the ``.zip`` archive on disk.
        target_dir: Directory that extracted files are written into (created
            if missing). By default files are written flat — subdirectories in
            the archive are dropped, so two members with the same basename
            collide and the later one is skipped as a duplicate. On a
            case-insensitive filesystem, names that differ only in case collide
            the same way.
        allowed_extensions: Extensions a member may have to be extracted.
            ``.zip`` is always excluded to prevent nested-archive recursion.
        limits: Optional size/count bounds; sensible defaults are used.
        keep_subdirs: Keep each member's sanitized folders instead of
            flattening, so ``Week1/Slides.pdf`` and ``Week2/Slides.pdf`` are
            both extracted. A member whose path has a ``..`` segment is skipped
            as an ``"unsafe path"``; an absolute name is re-rooted under
            ``target_dir``.

    Returns:
        A :class:`ZipExtractionResult` listing written paths and skipped
        members (with a reason for each skip).

    Raises:
        ArchiveTooLargeError: If the archive trips a zip-bomb guard.
        zipfile.BadZipFile: If the file is not a valid zip archive.

    When any error propagates, the files this call already wrote are removed
    first, so a rejected archive leaves none of its members behind in
    ``target_dir``. Files this call did not write are not touched.
    """
    limits = limits or ZipExtractionLimits()
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target_root = target_dir.resolve()

    # Never extract nested archives — they are an unbounded-recursion vector.
    extract_extensions = {ext.lower() for ext in allowed_extensions if ext.lower() != ".zip"}

    result = ZipExtractionResult()
    created_dirs: list[Path] = []
    seen_names: set[str] = set()
    total_bytes = 0
    duplicate_reason = (
        "duplicate path in archive" if keep_subdirs else "duplicate name after flattening"
    )

    with (
        zipfile.ZipFile(zip_path) as archive,
        _remove_on_error(result.extracted, created_dirs),
    ):
        members = [info for info in archive.infolist() if not info.is_dir()]
        if len(members) > limits.max_entries:
            raise ArchiveTooLargeError(
                f"Archive has too many entries: {len(members)} > {limits.max_entries}"
            )

        for info in members:
            member = info.filename
            parts = member.replace("\\", "/").split("/")
            basename = parts[-1]

            if _is_system_member(parts):
                result.skipped.append((member, "system file or dotfile"))
                continue
            if basename.lower().endswith(".zip"):
                result.skipped.append((member, "nested archive"))
                continue

            # Zip-bomb guards evaluated against the archive's own metadata
            # *before* writing a single byte.
            if info.file_size > limits.max_entry_bytes:
                raise ArchiveTooLargeError(
                    f"Zip entry too large: {member} ({info.file_size} bytes)"
                )
            if info.compress_size > 0:
                ratio = info.file_size / info.compress_size
                if ratio > limits.max_compression_ratio:
                    raise ArchiveTooLargeError(
                        f"Suspicious compression ratio for {member}: {ratio:.0f}x"
                    )
            if total_bytes + info.file_size > limits.max_total_bytes:
                raise ArchiveTooLargeError(
                    f"Archive exceeds total size limit of {limits.max_total_bytes} bytes"
                )

            # Validate + sanitize using the same gate as direct uploads. This
            # collapses any path (defusing Zip Slip) and enforces the
            # extension whitelist and per-file size.
            try:
                safe_name = DocumentValidator.validate_upload_safety(
                    basename, info.file_size, allowed_extensions=extract_extensions
                )
            except ValueError as exc:
                result.skipped.append((member, str(exc)))
                continue

            rel_dir = ""
            if keep_subdirs:
                try:
                    rel_dir = DocumentValidator.sanitize_relative_dir("/".join(parts[:-1]))
                except ValueError:
                    result.skipped.append((member, "unsafe path"))
                    continue
            rel_name = f"{rel_dir}/{safe_name}" if rel_dir else safe_name

            if rel_name in seen_names:
                result.skipped.append((member, duplicate_reason))
                continue

            destination = (target_root / rel_name).resolve()
            if not _is_within(destination, target_root):  # defense in depth
                result.skipped.append((member, "path escapes target directory"))
                continue

            # On a case-insensitive filesystem (the Windows and macOS default)
            # ``readme.md`` is the ``README.md`` this call already wrote: the
            # same flattening collision, not a pre-existing file to refuse.
            member_dirs: list[Path] = []
            try:
                if destination.exists() and any(destination.samefile(p) for p in result.extracted):
                    result.skipped.append((member, duplicate_reason))
                    continue

                make_dirs_recorded(destination.parent, target_root, member_dirs)
                written = _extract_member(archive, info, destination, limits.max_entry_bytes)
            except OSError as exc:
                # A path that clashes with another member, or one over-long
                # name (a CJK folder title past 255 bytes), is that member's
                # problem, not a reason to drop the archive. A regular file
                # already at the destination is still refused: it is never
                # overwritten. Anything else (disk full, permissions) aborts.
                reason = _MEMBER_PATH_ERRNOS.get(exc.errno)
                if reason is None or (
                    isinstance(exc, FileExistsError) and not destination.is_dir()
                ):
                    created_dirs.extend(member_dirs)
                    raise
                for directory in reversed(member_dirs):
                    with suppress(OSError):
                        directory.rmdir()
                result.skipped.append((member, reason))
                continue
            created_dirs.extend(member_dirs)
            if written > info.file_size:
                # Decompressed more than the header declared → treat as a bomb.
                destination.unlink(missing_ok=True)
                raise ArchiveTooLargeError(
                    f"Zip entry decompressed past its declared size: {member}"
                )

            total_bytes += written
            seen_names.add(rel_name)
            result.extracted.append(destination)

    return result


def _extract_member(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    destination: Path,
    max_entry_bytes: int,
    chunk_size: int = 1 << 16,
) -> int:
    """Stream a single member to ``destination`` with a hard byte budget.

    Returns the number of bytes written. If the member decompresses past
    ``max_entry_bytes`` the partial output is removed and the byte count
    returned still exceeds the limit so the caller can detect the overflow.
    """
    written = 0
    with archive.open(info) as source:
        # Acquire exclusively before registering cleanup, then close before
        # unlinking (required by Windows and by buffered flush failures).
        sink = open(destination, "xb")
        with _remove_on_error([destination]), sink:
            while True:
                chunk = source.read(chunk_size)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_entry_bytes:
                    sink.write(chunk)
                    return written  # signal overflow; caller cleans up
                sink.write(chunk)
    return written
