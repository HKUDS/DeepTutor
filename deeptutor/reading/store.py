"""On-disk store for reading materials and their annotations.

Layout, one directory per material::

    <root>/<material_id>/
        manifest.json        # MaterialManifest
        outline.json         # OutlineEntry rows (document's own, or synthesised)
        units/0001.txt       # one file per locator
        raw/<filename>       # the original bytes, for the faithful viewer
        annotations.json     # Annotation rows

One file per unit is the point of the layout: ``read_material(locator=12)``
opens one small file instead of deserialising the whole document, so a 600-page
PDF costs the same per read as a 3-page one.

``material_id`` is the content hash, which makes re-uploading the same file a
no-op that lands the user back on their existing annotations instead of a fresh
empty copy.

Writes go through :func:`_atomic_write` (temp file in the same directory, then
``os.replace``) under a per-material re-entrant lock, so a concurrent annotation
save and export can never observe a half-written JSON file — the failure mode
that produced the corrupted-notebook reports.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace as dataclass_replace
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import shutil
import threading
import time
from typing import Any, Iterator, Sequence
import uuid

from deeptutor.reading.extract import extract_material, synthesise_outline
from deeptutor.reading.models import (
    Annotation,
    MaterialManifest,
    MaterialNotFound,
    OutlineEntry,
    ReadingError,
)

logger = logging.getLogger(__name__)

MANIFEST_NAME = "manifest.json"
OUTLINE_NAME = "outline.json"
ANNOTATIONS_NAME = "annotations.json"
UNITS_DIR = "units"
RAW_DIR = "raw"

# Material ids are content hashes, so this is both an id validator and the
# traversal guard for every path built from a caller-supplied id.
_MATERIAL_ID_RE = re.compile(r"^[0-9a-f]{8,64}$")
_ID_LENGTH = 16

# Hard ceiling on how much unit text one tool call may return, so a model asking
# for "1-400" cannot blow the turn's context budget. The tool reports the
# truncation rather than silently trimming.
MAX_READ_CHARS = 60_000


def _atomic_write(path: Path, payload: str) -> None:
    """Write *payload* to *path* atomically within the same directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.{uuid.uuid4().hex[:8]}.tmp"
    try:
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError):
        logger.warning("Unreadable reading-store file: %s", path, exc_info=True)
        return None


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:_ID_LENGTH]


class ReadingStore:
    """Materials and annotations for one user's workspace."""

    def __init__(self, root: Path | str | None = None) -> None:
        self._root_override = Path(root) if root is not None else None
        self._locks_guard = threading.Lock()
        self._locks: dict[str, threading.RLock] = {}

    # -- paths ------------------------------------------------------------

    @property
    def root(self) -> Path:
        """The materials root, resolved lazily.

        Lazy so tests (and the pure-engine tests especially) can construct a
        store against a temp dir without booting the path service, and so a
        per-user path service installed after construction is still honoured.
        """
        if self._root_override is not None:
            return self._root_override
        from deeptutor.services.path_service import PathService

        return PathService.get_instance().get_workspace_feature_dir("reading")

    def _dir(self, material_id: str) -> Path:
        return self.root / self._validate_id(material_id)

    @staticmethod
    def _validate_id(material_id: str) -> str:
        candidate = str(material_id or "").strip().lower()
        if not _MATERIAL_ID_RE.match(candidate):
            raise ReadingError(f"invalid material id: {material_id!r}")
        return candidate

    @staticmethod
    def _unit_file(material_dir: Path, locator: int) -> Path:
        return material_dir / UNITS_DIR / f"{locator:04d}.txt"

    @contextmanager
    def _locked(self, material_id: str) -> Iterator[None]:
        with self._locks_guard:
            lock = self._locks.get(material_id)
            if lock is None:
                lock = threading.RLock()
                self._locks[material_id] = lock
        with lock:
            yield

    # -- ingest -----------------------------------------------------------

    def ingest(self, source: Path | str, *, filename: str | None = None) -> MaterialManifest:
        """Extract *source* into the store and return its manifest.

        Idempotent on content: a file whose hash is already present is not
        re-extracted, and its annotations are left untouched.
        """
        path = Path(source)
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise ReadingError(f"{path.name}: could not be read ({exc})") from exc
        if not data:
            raise ReadingError(f"{path.name} is empty")

        material_id = content_hash(data)
        display_name = (filename or path.name).strip() or path.name

        with self._locked(material_id):
            existing = self._load_manifest(material_id)
            if existing is not None and self._is_complete(material_id, existing):
                return existing

            extraction = extract_material(path)
            material_dir = self._dir(material_id)
            units_dir = material_dir / UNITS_DIR
            # A previous partial ingest (crash between unit writes) must not
            # leave stale units behind that would read as real content.
            if units_dir.exists():
                shutil.rmtree(units_dir, ignore_errors=True)
            units_dir.mkdir(parents=True, exist_ok=True)

            for index, unit in enumerate(extraction.units, start=1):
                self._unit_file(material_dir, index).write_text(unit, encoding="utf-8")

            raw_path: Path | None = None
            if extraction.has_raw_view:
                raw_dir = material_dir / RAW_DIR
                raw_dir.mkdir(parents=True, exist_ok=True)
                raw_path = raw_dir / _safe_filename(display_name, fallback=path.name)
                raw_path.write_bytes(data)

            outline = extraction.outline or synthesise_outline(extraction.units)
            _atomic_write(
                material_dir / OUTLINE_NAME,
                json.dumps([entry.to_dict() for entry in outline], ensure_ascii=False),
            )

            manifest = MaterialManifest(
                material_id=material_id,
                filename=display_name,
                unit=extraction.unit,
                unit_count=len(extraction.units),
                mime=_guess_mime(display_name),
                title=extraction.title or Path(display_name).stem,
                source_hash=material_id,
                extractor=extraction.extractor,
                byte_size=len(data),
                char_count=extraction.char_count,
                created_at=time.time(),
                has_raw_view=raw_path is not None,
            )
            # Manifest last: its presence is the "this material is usable"
            # signal, so it must not appear before the units it describes.
            _atomic_write(
                material_dir / MANIFEST_NAME,
                json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2),
            )
            return manifest

    def _is_complete(self, material_id: str, manifest: MaterialManifest) -> bool:
        """Whether a previously ingested material is still fully on disk."""
        material_dir = self._dir(material_id)
        if manifest.unit_count <= 0:
            return False
        if not self._unit_file(material_dir, manifest.unit_count).exists():
            return False
        if manifest.has_raw_view and self._find_raw(material_dir) is None:
            return False
        return True

    # -- read -------------------------------------------------------------

    def _load_manifest(self, material_id: str) -> MaterialManifest | None:
        data = _read_json(self._dir(material_id) / MANIFEST_NAME)
        if not isinstance(data, dict):
            return None
        manifest = MaterialManifest.from_dict(data)
        return manifest if manifest.material_id else None

    def manifest(self, material_id: str) -> MaterialManifest:
        manifest = self._load_manifest(material_id)
        if manifest is None:
            raise MaterialNotFound(f"material {material_id!r} not found")
        return manifest

    def exists(self, material_id: str) -> bool:
        try:
            return self._load_manifest(material_id) is not None
        except ReadingError:
            return False

    def list_materials(self) -> list[MaterialManifest]:
        """All usable materials, newest first. Unreadable dirs are skipped."""
        root = self.root
        if not root.is_dir():
            return []
        found: list[MaterialManifest] = []
        for child in root.iterdir():
            if not child.is_dir() or not _MATERIAL_ID_RE.match(child.name):
                continue
            manifest = self._load_manifest(child.name)
            if manifest is not None:
                found.append(manifest)
        return sorted(found, key=lambda m: m.created_at, reverse=True)

    def unit_text(self, material_id: str, locator: int) -> str:
        """Text of one unit. Raises when the locator is out of range."""
        manifest = self.manifest(material_id)
        if not 1 <= locator <= manifest.unit_count:
            raise ReadingError(
                f"{manifest.unit} {locator} is out of range — "
                f"this material has {manifest.unit_count}."
            )
        path = self._unit_file(self._dir(material_id), locator)
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""
        except OSError as exc:
            raise ReadingError(f"could not read {manifest.unit} {locator} ({exc})") from exc

    def read_units(
        self,
        material_id: str,
        locators: Sequence[int],
        *,
        max_chars: int = MAX_READ_CHARS,
    ) -> tuple[list[tuple[int, str]], bool]:
        """Read several units in ascending order, bounded by *max_chars*.

        Returns ``(rows, truncated)``. Bounding here rather than at the tool
        keeps every caller (tool, API, export) honest about the same ceiling,
        and ``truncated`` lets the caller say so out loud instead of silently
        dropping evidence.
        """
        manifest = self.manifest(material_id)
        wanted = sorted({int(loc) for loc in locators if 1 <= int(loc) <= manifest.unit_count})
        rows: list[tuple[int, str]] = []
        budget = max(0, int(max_chars))
        truncated = False
        for locator in wanted:
            text = self.unit_text(material_id, locator)
            if len(text) > budget:
                if budget > 0:
                    rows.append((locator, text[:budget]))
                truncated = True
                break
            rows.append((locator, text))
            budget -= len(text)
        if len(wanted) < len({int(loc) for loc in locators}):
            truncated = True
        return rows, truncated

    def outline(self, material_id: str) -> list[OutlineEntry]:
        """The material's outline, rebuilt from units if the file is missing."""
        manifest = self.manifest(material_id)
        rows = _read_json(self._dir(material_id) / OUTLINE_NAME)
        if isinstance(rows, list) and rows:
            entries: list[OutlineEntry] = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                try:
                    entries.append(
                        OutlineEntry(
                            locator=int(row["locator"]),
                            title=str(row.get("title") or ""),
                            level=max(1, int(row.get("level") or 1)),
                            synthesised=bool(row.get("synthesised")),
                        )
                    )
                except (KeyError, TypeError, ValueError):
                    continue
            if entries:
                return entries
        units = tuple(
            self.unit_text(material_id, locator) for locator in range(1, manifest.unit_count + 1)
        )
        return list(synthesise_outline(units))

    def iter_units(self, material_id: str) -> Iterator[tuple[int, str]]:
        """Stream every unit in order — for search and export."""
        manifest = self.manifest(material_id)
        for locator in range(1, manifest.unit_count + 1):
            yield locator, self.unit_text(material_id, locator)

    def raw_path(self, material_id: str) -> Path | None:
        """The stored original file, or None for text-only materials."""
        manifest = self.manifest(material_id)
        if not manifest.has_raw_view:
            return None
        return self._find_raw(self._dir(material_id))

    @staticmethod
    def _find_raw(material_dir: Path) -> Path | None:
        raw_dir = material_dir / RAW_DIR
        if not raw_dir.is_dir():
            return None
        for candidate in sorted(raw_dir.iterdir()):
            if candidate.is_file():
                return candidate
        return None

    def delete(self, material_id: str) -> bool:
        material_dir = self._dir(material_id)
        if not material_dir.is_dir():
            return False
        with self._locked(material_id):
            shutil.rmtree(material_dir, ignore_errors=True)
        return not material_dir.exists()

    # -- annotations ------------------------------------------------------

    def annotations(self, material_id: str) -> list[Annotation]:
        """All annotations, ordered by locator then creation time."""
        self.manifest(material_id)
        rows = _read_json(self._dir(material_id) / ANNOTATIONS_NAME)
        if not isinstance(rows, list):
            return []
        parsed = [
            Annotation.from_dict(row)
            for row in rows
            if isinstance(row, dict) and row.get("annotation_id")
        ]
        return sorted(parsed, key=lambda a: (a.locator, a.created_at))

    def _write_annotations(self, material_id: str, rows: Sequence[Annotation]) -> None:
        _atomic_write(
            self._dir(material_id) / ANNOTATIONS_NAME,
            json.dumps([row.to_dict() for row in rows], ensure_ascii=False, indent=2),
        )

    def save_annotation(self, material_id: str, annotation: Annotation) -> Annotation:
        """Insert or update one annotation and return the stored row.

        Read-modify-write under the material lock, so two rapid highlights from
        the same reader cannot clobber each other.
        """
        manifest = self.manifest(material_id)
        if not 1 <= annotation.locator <= manifest.unit_count:
            raise ReadingError(
                f"{manifest.unit} {annotation.locator} is out of range — "
                f"this material has {manifest.unit_count}."
            )
        with self._locked(material_id):
            existing = self.annotations(material_id)
            stored = annotation
            if not stored.annotation_id:
                stored = dataclass_replace(stored, annotation_id=uuid.uuid4().hex[:12])
            now = time.time()
            index = next(
                (i for i, row in enumerate(existing) if row.annotation_id == stored.annotation_id),
                None,
            )
            if index is None:
                stored = dataclass_replace(
                    stored,
                    created_at=stored.created_at or now,
                    updated_at=now,
                )
                existing.append(stored)
            else:
                stored = dataclass_replace(
                    stored,
                    created_at=existing[index].created_at or now,
                    updated_at=now,
                )
                existing[index] = stored
            self._write_annotations(material_id, existing)
            return stored

    def delete_annotation(self, material_id: str, annotation_id: str) -> bool:
        self.manifest(material_id)
        target = str(annotation_id or "").strip()
        if not target:
            return False
        with self._locked(material_id):
            existing = self.annotations(material_id)
            remaining = [row for row in existing if row.annotation_id != target]
            if len(remaining) == len(existing):
                return False
            self._write_annotations(material_id, remaining)
            return True


def _safe_filename(name: str, *, fallback: str) -> str:
    """A filesystem-safe basename for the stored original.

    The display name is echoed back in downloads, so it is sanitised rather
    than trusted: no directory parts, no traversal, bounded length.
    """
    base = Path(str(name or "")).name.strip()
    base = re.sub(r"[\x00-\x1f]", "", base)
    base = base.replace(os.sep, "_")
    if os.altsep:
        base = base.replace(os.altsep, "_")
    base = base.strip(". ") or Path(fallback).name or "material"
    return base[:180]


def _guess_mime(filename: str) -> str:
    import mimetypes

    mime, _ = mimetypes.guess_type(filename)
    return mime or "application/octet-stream"


__all__ = [
    "ANNOTATIONS_NAME",
    "MANIFEST_NAME",
    "MAX_READ_CHARS",
    "OUTLINE_NAME",
    "RAW_DIR",
    "UNITS_DIR",
    "ReadingStore",
    "content_hash",
]
