"""On-disk store for reading materials and their annotations.

Layout, one directory per extracted content::

    <root>/<content_id>/
        manifest.json        # MaterialManifest
        outline.json         # OutlineEntry rows (document's own, or synthesised)
        units/0001.txt       # one file per locator
        raw/<filename>       # the original bytes, for the faithful viewer
        annotations/<material_id>.json
        positions/<material_id>.json

One file per unit is the point of the layout: ``read_material(locator=12)``
opens one small file instead of deserialising the whole document, so a 600-page
PDF costs the same per read as a 3-page one.

``content_id`` is the content hash, so extracted units and source bytes are
shared. Catalog ``material_id`` values identify independent titles, annotations,
and reading positions over that shared content.

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
import sqlite3
import threading
import time
from typing import Any, Iterator, Literal, Mapping, Sequence
import uuid

from deeptutor.reading.extract import extract_material, synthesise_outline
from deeptutor.reading.models import (
    MAX_TEXT_SELECTOR_CHARS,
    Annotation,
    MaterialManifest,
    MaterialNotFound,
    OutlineEntry,
    ReadingBookmark,
    ReadingError,
    ReadingPosition,
    ReadingUpgradeConflict,
    TextPositionSelector,
    TextQuoteSelector,
    UnitReference,
)
from deeptutor.services.file_io import atomic_write_text as _atomic_write
from deeptutor.services.path_service import get_path_service

logger = logging.getLogger(__name__)

MANIFEST_NAME = "manifest.json"
OUTLINE_NAME = "outline.json"
ANNOTATIONS_NAME = "annotations.json"
POSITION_NAME = "position.json"
ANNOTATIONS_DIR = "annotations"
POSITIONS_DIR = "positions"
BOOKMARKS_DIR = "bookmarks"
# A ceiling rather than a design limit: bookmarks are a short list a reader
# scans, and the file is rewritten whole on every change.
MAX_BOOKMARKS = 200
UNIT_REFS_NAME = "unit_refs.json"
UNITS_DIR = "units"
RAW_DIR = "raw"
ASSETS_DIR = "assets"
REVISIONS_DIR = "revisions"

# Both content hashes and separately minted catalog ids are path-safe. Content
# directories themselves remain hashes only.
_CONTENT_ID_RE = re.compile(r"^[0-9a-f]{8,64}$")
_MATERIAL_ID_RE = re.compile(r"^(?:[0-9a-f]{8,64}|rm_[0-9a-f]{12})$")
_ID_LENGTH = 16

# Hard ceiling on how much unit text one tool call may return, so a model asking
# for "1-400" cannot blow the turn's context budget. The tool reports the
# truncation rather than silently trimming.
MAX_READ_CHARS = 60_000


def _normalise_selector_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _find_quote_span(text: str, selector: TextQuoteSelector) -> tuple[int, int] | None:
    """Resolve a quote while preserving offsets into the unnormalised source."""

    words = re.findall(r"\S+", selector.exact)
    if not words:
        return None
    pattern = re.compile(r"\s+".join(re.escape(word) for word in words))
    for match in pattern.finditer(text):
        span = (match.start(), match.end())
        if _quote_context_matches(text, span, selector):
            return span
    return None


def _quote_context_matches(
    text: str,
    span: tuple[int, int],
    selector: TextQuoteSelector,
) -> bool:
    wanted_prefix = _normalise_selector_text(selector.prefix)
    wanted_suffix = _normalise_selector_text(selector.suffix)
    preceding = _normalise_selector_text(text[: span[0]])
    following = _normalise_selector_text(text[span[1] :])
    return (not wanted_prefix or preceding.endswith(wanted_prefix)) and (
        not wanted_suffix or following.startswith(wanted_suffix)
    )


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
        return get_path_service().get_workspace_feature_dir("reading")

    def _dir(self, material_id: str) -> Path:
        return self.root / self._content_id(material_id)

    @staticmethod
    def _validate_id(material_id: str) -> str:
        candidate = str(material_id or "").strip().lower()
        if not _MATERIAL_ID_RE.match(candidate):
            raise ReadingError(f"invalid material id: {material_id!r}")
        return candidate

    def _catalog_row(self, material_id: str) -> sqlite3.Row | None:
        db_path = self.root / "_catalog.sqlite3"
        if not db_path.is_file():
            return None
        try:
            with sqlite3.connect(db_path, timeout=30) as conn:
                conn.row_factory = sqlite3.Row
                return conn.execute(
                    "SELECT * FROM reading_materials WHERE material_id = ?",
                    (material_id,),
                ).fetchone()
        except sqlite3.Error:
            logger.warning(
                "Could not resolve reading catalog material %s", material_id, exc_info=True
            )
            return None

    def _content_id(self, material_id: str) -> str:
        resolved_id = self._validate_id(material_id)
        row = self._catalog_row(resolved_id)
        content_id = str(row["content_id"] if row else resolved_id).strip().lower()
        if not _CONTENT_ID_RE.fullmatch(content_id):
            raise ReadingError(f"invalid content id for material {material_id!r}")
        return content_id

    def _state_path(self, material_id: str, state_dir: str) -> Path:
        resolved_id = self._validate_id(material_id)
        return self._dir(resolved_id) / state_dir / f"{resolved_id}.json"

    def _legacy_state_path(self, material_id: str, filename: str) -> Path | None:
        resolved_id = self._validate_id(material_id)
        content_id = self._content_id(resolved_id)
        return self.root / content_id / filename if resolved_id == content_id else None

    @staticmethod
    def _unit_file(material_dir: Path, locator: int) -> Path:
        return material_dir / UNITS_DIR / f"{locator:04d}.txt"

    @contextmanager
    def _locked(self, material_id: str) -> Iterator[None]:
        lock_id = self._content_id(material_id)
        with self._locks_guard:
            lock = self._locks.get(lock_id)
            if lock is None:
                lock = threading.RLock()
                self._locks[lock_id] = lock
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
                wants_epub_upgrade = (
                    path.suffix.lower() == ".epub" and existing.render_mode != "epub"
                )
                if not wants_epub_upgrade:
                    return existing
                if self.annotations(material_id):
                    raise ReadingUpgradeConflict(
                        "This EPUB was imported by the legacy text reader and has annotations. "
                        "Export those annotations before replacing it with the source-faithful version."
                    )

            extraction = extract_material(path)
            material_dir = self._dir(material_id)
            stage_dir = self.root / f".{material_id}.{uuid.uuid4().hex[:8]}.staging"
            backup_dir = self.root / f".{material_id}.{uuid.uuid4().hex[:8]}.backup"
            units_dir = stage_dir / UNITS_DIR
            units_dir.mkdir(parents=True, exist_ok=True)

            for index, unit in enumerate(extraction.units, start=1):
                self._unit_file(stage_dir, index).write_text(unit, encoding="utf-8")

            if extraction.render_mode != "text":
                raw_dir = stage_dir / RAW_DIR
                raw_dir.mkdir(parents=True, exist_ok=True)
                raw_path = raw_dir / _safe_filename(display_name, fallback=path.name)
                raw_path.write_bytes(data)

            # A PDF page's first text line is not a table of contents. It is
            # often a figure caption, running header, or reference entry, so
            # presenting those labels as document structure is actively
            # misleading. PDFs either keep their native bookmarks or expose no
            # outline; the client can still offer an honest page navigator.
            outline = (
                extraction.outline
                if extraction.outline or extraction.render_mode == "pdf"
                else synthesise_outline(extraction.units)
            )
            _atomic_write(
                stage_dir / OUTLINE_NAME,
                json.dumps([entry.to_dict() for entry in outline], ensure_ascii=False),
            )
            _atomic_write(
                stage_dir / UNIT_REFS_NAME,
                json.dumps([entry.to_dict() for entry in extraction.unit_refs], ensure_ascii=False),
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
                # Compatibility: old clients route this boolean directly to
                # pdf.js. EPUB dispatch is carried by ``render_mode`` instead.
                has_raw_view=extraction.render_mode == "pdf",
                render_mode=extraction.render_mode,
            )
            # Manifest last: its presence is the "this material is usable"
            # signal, so it must not appear before the units it describes.
            _atomic_write(
                stage_dir / MANIFEST_NAME,
                json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2),
            )

            # A repair or compatible re-ingest keeps user-owned state. EPUB
            # legacy upgrades with annotations were rejected above because
            # their old locators cannot be mapped safely to the spine.
            state_names: tuple[str, ...] = (ANNOTATIONS_NAME, POSITION_NAME)
            state_dirs: tuple[str, ...] = (
                ANNOTATIONS_DIR,
                POSITIONS_DIR,
                BOOKMARKS_DIR,
            )
            if existing is not None and existing.render_mode != "epub":
                # A legacy text-reader position can point past the shorter
                # source-faithful spine. Annotations are protected above;
                # the viewport safely resets to chapter one — which has to
                # drop the per-material viewports too, not just the legacy
                # file, or the stale locator simply survives in the new path.
                state_names = (ANNOTATIONS_NAME,)
                # A bookmark is a place the reader chose, so it is kept for the
                # same reason an annotation is; only the automatic viewport
                # resets when the spine changes under it.
                state_dirs = (ANNOTATIONS_DIR, BOOKMARKS_DIR)
            for state_name in state_names:
                source_state = material_dir / state_name
                if source_state.is_file():
                    shutil.copy2(source_state, stage_dir / state_name)
            for state_dir in state_dirs:
                source_state_dir = material_dir / state_dir
                if source_state_dir.is_dir():
                    shutil.copytree(
                        source_state_dir,
                        stage_dir / state_dir,
                        dirs_exist_ok=True,
                    )

            # Install the fully written directory in one swap. If the second
            # rename fails, put the previous material back before surfacing the
            # error; readers never observe a half-written unit set.
            try:
                if material_dir.exists():
                    os.replace(material_dir, backup_dir)
                try:
                    os.replace(stage_dir, material_dir)
                except Exception:
                    if backup_dir.exists() and not material_dir.exists():
                        os.replace(backup_dir, material_dir)
                    raise
            finally:
                shutil.rmtree(stage_dir, ignore_errors=True)
                shutil.rmtree(backup_dir, ignore_errors=True)
            return manifest

    def ingest_units(
        self,
        material_id: str,
        *,
        filename: str,
        units: Sequence[str],
        unit: str = "section",
        title: str = "",
        mime: str = "text/markdown",
        extractor: str = "pre-extracted",
        render_mode: str = "text",
        raw_data: bytes | None = None,
        outline: Sequence[OutlineEntry] | None = None,
        unit_refs: Sequence[UnitReference] = (),
        content_format: Literal["plain_text", "web_markdown"] = "plain_text",
        source_type: str = "upload",
        source_url: str = "",
        assets: Mapping[str, bytes] | None = None,
        carry_source: bool = False,
    ) -> MaterialManifest:
        """Install trusted, already-extracted units (web pages and transcripts).

        The regular :meth:`ingest` path owns local document parsing. URL and
        media importers already have structured text plus, optionally, playable
        bytes; this entrypoint gives them the same atomic on-disk contract
        without creating fake temporary document formats.
        """
        material_id = self._validate_id(material_id)
        content_id = self._content_id(material_id)
        clean_units = tuple(str(value).strip() for value in units if str(value).strip())
        if not clean_units:
            raise ReadingError(f"{filename}: no readable content was extracted")
        if unit not in {"page", "chapter", "slide", "section", "segment"}:
            raise ReadingError(f"unsupported reading unit: {unit}")
        if render_mode not in {"text", "pdf", "epub", "video", "audio"}:
            raise ReadingError(f"unsupported render mode: {render_mode}")
        if content_format not in {"plain_text", "web_markdown"}:
            raise ReadingError(f"unsupported content format: {content_format}")
        remote_video = render_mode == "video" and extractor.startswith(("youtube-", "bilibili-"))
        carried = carry_source and self._has_raw(material_id)
        if render_mode != "text" and not raw_data and not remote_video and not carried:
            raise ReadingError(f"{render_mode} materials require playable source bytes")

        display_name = (filename or "material").strip() or "material"
        with self._locked(material_id):
            existing = self._load_manifest(content_id)
            material_dir = self._dir(material_id)
            stage_dir = self.root / f".{material_id}.{uuid.uuid4().hex[:8]}.staging"
            backup_dir = self.root / f".{material_id}.{uuid.uuid4().hex[:8]}.backup"
            (stage_dir / UNITS_DIR).mkdir(parents=True, exist_ok=True)
            for index, text in enumerate(clean_units, start=1):
                self._unit_file(stage_dir, index).write_text(text, encoding="utf-8")

            if assets:
                assets_dir = stage_dir / ASSETS_DIR
                assets_dir.mkdir(parents=True, exist_ok=True)
                for name, data in assets.items():
                    safe_name = _safe_filename(str(name), fallback="asset")
                    (assets_dir / safe_name).write_bytes(bytes(data))
            elif carry_source:
                _carry_dir(material_dir / ASSETS_DIR, stage_dir / ASSETS_DIR)

            if raw_data is not None:
                raw_dir = stage_dir / RAW_DIR
                raw_dir.mkdir(parents=True, exist_ok=True)
                (raw_dir / _safe_filename(display_name, fallback="material")).write_bytes(raw_data)
            elif carry_source:
                # Re-ingesting the *same* bytes with better text — a transcript
                # replacing its placeholder. Linking beats re-reading a
                # multi-hundred-megabyte upload back through memory.
                _carry_dir(material_dir / RAW_DIR, stage_dir / RAW_DIR)

            resolved_outline = tuple(outline or synthesise_outline(clean_units))
            _atomic_write(
                stage_dir / OUTLINE_NAME,
                json.dumps([entry.to_dict() for entry in resolved_outline], ensure_ascii=False),
            )
            _atomic_write(
                stage_dir / UNIT_REFS_NAME,
                json.dumps([entry.to_dict() for entry in unit_refs], ensure_ascii=False),
            )
            manifest = MaterialManifest(
                material_id=content_id,
                filename=display_name,
                unit=unit,  # type: ignore[arg-type]
                unit_count=len(clean_units),
                mime=mime,
                title=(title or Path(display_name).stem).strip(),
                source_hash=content_id,
                extractor=extractor,
                byte_size=(
                    len(raw_data)
                    if raw_data is not None
                    else (existing.byte_size if carry_source and existing else 0)
                ),
                char_count=sum(len(value) for value in clean_units),
                created_at=existing.created_at if existing else time.time(),
                has_raw_view=render_mode == "pdf",
                render_mode=render_mode,  # type: ignore[arg-type]
                content_format=content_format,
                source_type=source_type,
                source_url=source_url,
                revision=(existing.revision + 1 if existing else 1),
            )
            _atomic_write(
                stage_dir / MANIFEST_NAME,
                json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2),
            )
            if existing is not None and material_dir.is_dir():
                previous_revisions = material_dir / REVISIONS_DIR
                if previous_revisions.is_dir():
                    shutil.copytree(
                        previous_revisions,
                        stage_dir / REVISIONS_DIR,
                        dirs_exist_ok=True,
                    )
                revision_dir = stage_dir / REVISIONS_DIR / f"{existing.revision:06d}"
                if not revision_dir.exists():
                    revision_dir.mkdir(parents=True, exist_ok=True)
                    for filename in (MANIFEST_NAME, OUTLINE_NAME, UNIT_REFS_NAME):
                        source = material_dir / filename
                        if source.is_file():
                            shutil.copy2(source, revision_dir / filename)
                    for dirname in (UNITS_DIR, ASSETS_DIR):
                        source_dir = material_dir / dirname
                        if source_dir.is_dir():
                            shutil.copytree(source_dir, revision_dir / dirname)
            for state_name in (ANNOTATIONS_NAME, POSITION_NAME):
                source_state = material_dir / state_name
                if source_state.is_file():
                    shutil.copy2(source_state, stage_dir / state_name)
            for state_dir in (ANNOTATIONS_DIR, POSITIONS_DIR, BOOKMARKS_DIR):
                source_state_dir = material_dir / state_dir
                if source_state_dir.is_dir():
                    shutil.copytree(
                        source_state_dir,
                        stage_dir / state_dir,
                        dirs_exist_ok=True,
                    )
            try:
                if material_dir.exists():
                    os.replace(material_dir, backup_dir)
                try:
                    os.replace(stage_dir, material_dir)
                except Exception:
                    if backup_dir.exists() and not material_dir.exists():
                        os.replace(backup_dir, material_dir)
                    raise
            finally:
                shutil.rmtree(stage_dir, ignore_errors=True)
                shutil.rmtree(backup_dir, ignore_errors=True)
            return self.manifest(material_id)

    def revisions(self, material_id: str) -> list[MaterialManifest]:
        """List immutable prior manifests, oldest first."""
        self.manifest(material_id)
        root = self._dir(material_id) / REVISIONS_DIR
        if not root.is_dir():
            return []
        rows: list[MaterialManifest] = []
        for child in sorted(root.iterdir()):
            if not child.is_dir() or not re.fullmatch(r"\d{6}", child.name):
                continue
            data = _read_json(child / MANIFEST_NAME)
            if isinstance(data, dict):
                rows.append(MaterialManifest.from_dict(data))
        return rows

    def revision_unit_text(self, material_id: str, revision: int, locator: int) -> str:
        """Read a unit from a preserved prior web-snapshot revision."""
        self.manifest(material_id)
        if revision < 1 or locator < 1:
            raise ReadingError("revision and locator must be positive")
        revision_dir = self._dir(material_id) / REVISIONS_DIR / f"{revision:06d}"
        data = _read_json(revision_dir / MANIFEST_NAME)
        if not isinstance(data, dict):
            raise MaterialNotFound(f"revision {revision} not found")
        manifest = MaterialManifest.from_dict(data)
        if locator > manifest.unit_count:
            raise ReadingError(
                f"{manifest.unit} {locator} is out of range for revision {revision}."
            )
        path = self._unit_file(revision_dir, locator)
        if not path.is_file():
            raise MaterialNotFound(f"revision {revision} unit {locator} not found")
        return path.read_text(encoding="utf-8")

    def _is_complete(self, material_id: str, manifest: MaterialManifest) -> bool:
        """Whether a previously ingested material is still fully on disk."""
        material_dir = self._dir(material_id)
        if manifest.unit_count <= 0:
            return False
        if not self._unit_file(material_dir, manifest.unit_count).exists():
            return False
        if manifest.render_mode != "text" and self._find_raw(material_dir) is None:
            return False
        return True

    # -- read -------------------------------------------------------------

    def _load_manifest(self, material_id: str) -> MaterialManifest | None:
        resolved_id = self._validate_id(material_id)
        data = _read_json(self._dir(resolved_id) / MANIFEST_NAME)
        if not isinstance(data, dict):
            return None
        manifest = MaterialManifest.from_dict(data)
        if not manifest.material_id:
            return None
        row = self._catalog_row(resolved_id)
        if row is None:
            return dataclass_replace(manifest, material_id=resolved_id)
        render_mode = str(row["render_mode"] or manifest.render_mode)
        return dataclass_replace(
            manifest,
            material_id=resolved_id,
            filename=str(row["filename"] or manifest.filename),
            title=str(row["title"] or manifest.title),
            mime=str(row["mime"] or manifest.mime),
            render_mode=render_mode,  # type: ignore[arg-type]
            has_raw_view=render_mode == "pdf",
            created_at=float(row["created_at"] or manifest.created_at),
        )

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
            if not child.is_dir() or not _CONTENT_ID_RE.fullmatch(child.name):
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
        if isinstance(rows, list):
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
            if manifest.render_mode == "pdf":
                # Migrate legacy PDF imports in place at read time: older
                # versions persisted one synthesised row per page. Returning
                # no outline here immediately removes those false contents
                # without requiring users to re-import their files.
                return [] if all(entry.synthesised for entry in entries) else entries
            if entries:
                return entries
        if manifest.render_mode == "pdf":
            return []
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
        if manifest.render_mode == "text":
            return None
        return self._find_raw(self._dir(material_id))

    def _has_raw(self, material_id: str) -> bool:
        """Whether original bytes are already on disk, without loading them."""
        try:
            content_id = self._content_id(material_id)
        except ReadingError:
            return False
        return self._find_raw(self._dir(content_id)) is not None

    def unit_references(self, material_id: str) -> list[UnitReference]:
        """Source-native addresses aligned with the numeric locator space."""
        manifest = self.manifest(material_id)
        rows = _read_json(self._dir(material_id) / UNIT_REFS_NAME)
        if not isinstance(rows, list):
            return [UnitReference(locator=index) for index in range(1, manifest.unit_count + 1)]
        refs = [UnitReference.from_dict(row) for row in rows if isinstance(row, dict)]
        return [row for row in refs if 1 <= row.locator <= manifest.unit_count]

    def position(self, material_id: str) -> ReadingPosition:
        """Return the last viewport, defaulting to the first locator."""
        self.manifest(material_id)
        state_path = self._state_path(material_id, POSITIONS_DIR)
        row = _read_json(state_path)
        if row is None and not state_path.exists():
            legacy_path = self._legacy_state_path(material_id, POSITION_NAME)
            row = _read_json(legacy_path) if legacy_path is not None else None
        return ReadingPosition.from_dict(row) if isinstance(row, dict) else ReadingPosition()

    def save_position(self, material_id: str, position: ReadingPosition) -> ReadingPosition:
        """Validate and atomically persist a material viewport."""
        manifest = self.manifest(material_id)
        if not 1 <= position.locator <= manifest.unit_count:
            raise ReadingError(
                f"{manifest.unit} {position.locator} is out of range — "
                f"this material has {manifest.unit_count}."
            )
        if len(position.source_anchor) > 4096:
            raise ReadingError("source anchor is too long")
        if not 0.0 <= position.percentage <= 1.0:
            raise ReadingError("position percentage must be between 0 and 1")
        stored = dataclass_replace(position, updated_at=time.time())
        with self._locked(material_id):
            _atomic_write(
                self._state_path(material_id, POSITIONS_DIR),
                json.dumps(stored.to_dict(), ensure_ascii=False, indent=2),
            )
        return stored

    @staticmethod
    def _find_raw(material_dir: Path) -> Path | None:
        raw_dir = material_dir / RAW_DIR
        if not raw_dir.is_dir():
            return None
        for candidate in sorted(raw_dir.iterdir()):
            if candidate.is_file():
                return candidate
        return None

    def asset_path(self, material_id: str, asset_name: str) -> Path | None:
        """Resolve one generated raster without permitting traversal.

        Web snapshots name their images by content hash; media imports store a
        single poster frame under a fixed name. Both are server-generated, and
        the pattern is what keeps a request from walking out of the directory.
        """
        self.manifest(material_id)
        name = str(asset_name or "").strip().lower()
        if not re.fullmatch(r"(?:[0-9a-f]{20}|cover)\.(?:png|jpg|gif|webp)", name):
            return None
        path = self._dir(material_id) / ASSETS_DIR / name
        return path if path.is_file() else None

    @contextmanager
    def staged_delete(self, material_id: str) -> Iterator[bool]:
        """Stage a recoverable material deletion around catalog cleanup.

        The catalog and content store cannot share one database transaction.
        Moving the material aside first gives their coordinator a rollback
        point: if catalog cleanup fails, the content is restored before the
        error reaches the caller. A successful boundary permanently removes
        the staged directory and its EPUB pairings.
        """

        material_dir = self._dir(material_id)
        if not material_dir.is_dir():
            yield False
            return
        staged_dir = self.root / f".{material_id}.{uuid.uuid4().hex[:8]}.deleting"
        with self._locked(material_id):
            os.replace(material_dir, staged_dir)
            try:
                yield True
            except BaseException:
                os.replace(staged_dir, material_dir)
                raise
            else:
                shutil.rmtree(staged_dir, ignore_errors=True)
                from deeptutor.reading.epub_bilingual import (
                    delete_epub_pairings_for_material,
                )

                delete_epub_pairings_for_material(self, material_id)

    def delete(self, material_id: str) -> bool:
        with self.staged_delete(material_id) as removed:
            return removed

    def delete_material_state(self, material_id: str, *, content_id: str | None = None) -> None:
        """Remove only one catalog material's state, preserving shared content."""
        resolved_id = self._validate_id(material_id)
        resolved_content = str(content_id or "").strip().lower() or self._content_id(resolved_id)
        if not _CONTENT_ID_RE.fullmatch(resolved_content):
            raise ReadingError(f"invalid content id for material {material_id!r}")
        content_dir = self.root / resolved_content
        with self._locked(resolved_content):
            for state_dir in (ANNOTATIONS_DIR, POSITIONS_DIR):
                state_path = content_dir / state_dir / f"{resolved_id}.json"
                state_path.unlink(missing_ok=True)
                try:
                    (content_dir / state_dir).rmdir()
                except OSError:
                    pass
        from deeptutor.reading.epub_bilingual import delete_epub_pairings_for_material

        delete_epub_pairings_for_material(self, resolved_id)

    # -- annotations ------------------------------------------------------

    def annotations(self, material_id: str) -> list[Annotation]:
        """All annotations, ordered by locator then creation time."""
        self.manifest(material_id)
        state_path = self._state_path(material_id, ANNOTATIONS_DIR)
        rows = _read_json(state_path)
        if rows is None and not state_path.exists():
            legacy_path = self._legacy_state_path(material_id, ANNOTATIONS_NAME)
            rows = _read_json(legacy_path) if legacy_path is not None else None
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
            self._state_path(material_id, ANNOTATIONS_DIR),
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
        if len(annotation.source_anchor) > 4096:
            raise ReadingError("source anchor is too long")
        quote_selectors = [
            selector for selector in annotation.selectors if isinstance(selector, TextQuoteSelector)
        ]
        position_selectors = [
            selector
            for selector in annotation.selectors
            if isinstance(selector, TextPositionSelector)
        ]
        if len(quote_selectors) > 1 or len(position_selectors) > 1:
            raise ReadingError("annotations may contain at most one selector of each type")
        quote_selector = quote_selectors[0] if quote_selectors else None
        position_selector = position_selectors[0] if position_selectors else None
        if annotation.selectors:
            unit_text = self.unit_text(material_id, annotation.locator)
        else:
            unit_text = ""
        position_text = ""
        if position_selector:
            if position_selector.end > len(unit_text):
                raise ReadingError("TextPositionSelector extends past this reading unit")
            if position_selector.end - position_selector.start > MAX_TEXT_SELECTOR_CHARS:
                raise ReadingError("TextPositionSelector span is too long")
            position_text = unit_text[position_selector.start : position_selector.end]
        if quote_selector:
            normalised_exact = _normalise_selector_text(quote_selector.exact)
            if not normalised_exact:
                raise ReadingError("TextQuoteSelector exact text is empty")
            if annotation.quote and _normalise_selector_text(annotation.quote) != normalised_exact:
                raise ReadingError("annotation quote does not match its TextQuoteSelector")
            if position_selector:
                if _normalise_selector_text(position_text) != normalised_exact:
                    raise ReadingError("text quote and position selectors describe different text")
                if not _quote_context_matches(
                    unit_text,
                    (position_selector.start, position_selector.end),
                    quote_selector,
                ):
                    raise ReadingError("TextQuoteSelector context does not match this reading unit")
                canonical_exact = position_text
            else:
                span = _find_quote_span(unit_text, quote_selector)
                if span is None:
                    raise ReadingError("TextQuoteSelector does not occur in this reading unit")
                canonical_exact = unit_text[slice(*span)]
            canonical_quote = dataclass_replace(quote_selector, exact=canonical_exact)
            annotation = dataclass_replace(
                annotation,
                quote=canonical_exact,
                selectors=tuple(
                    canonical_quote if selector is quote_selector else selector
                    for selector in annotation.selectors
                ),
            )
        elif position_selector:
            if annotation.quote and _normalise_selector_text(
                annotation.quote
            ) != _normalise_selector_text(position_text):
                raise ReadingError("annotation quote does not match its TextPositionSelector")
            annotation = dataclass_replace(annotation, quote=position_text)
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
                    material_revision=manifest.revision,
                    created_at=stored.created_at or now,
                    updated_at=now,
                )
                existing.append(stored)
            else:
                stored = dataclass_replace(
                    stored,
                    material_revision=existing[index].material_revision,
                    created_at=existing[index].created_at or now,
                    updated_at=now,
                )
                existing[index] = stored
            self._write_annotations(material_id, existing)
            return stored

    # -- bookmarks ---------------------------------------------------------

    def bookmarks(self, material_id: str) -> list[ReadingBookmark]:
        """Every kept place in this material, in reading order."""
        self.manifest(material_id)
        rows = _read_json(self._state_path(material_id, BOOKMARKS_DIR))
        if not isinstance(rows, list):
            return []
        parsed = [
            ReadingBookmark.from_dict(row)
            for row in rows
            if isinstance(row, dict) and row.get("bookmark_id")
        ]
        return sorted(parsed, key=lambda row: (row.locator, row.created_at))

    def add_bookmark(
        self,
        material_id: str,
        locator: int,
        label: str = "",
        source_anchor: str = "",
    ) -> ReadingBookmark:
        """Keep one place, or return the one already kept for that locator.

        Idempotent per locator on purpose: the affordance is a toggle on the
        reader's own toolbar, so the honest answer to "bookmark this page"
        when the page is already bookmarked is the existing bookmark, not a
        second identical row in the list.
        """
        manifest = self.manifest(material_id)
        target = int(locator)
        if not 1 <= target <= manifest.unit_count:
            raise ReadingError(
                f"{manifest.unit} {target} is out of range — "
                f"this material has {manifest.unit_count}."
            )
        trimmed = str(label or "").strip()[:200]
        anchor_value = str(source_anchor or "")[:4096]
        with self._locked(material_id):
            existing = self.bookmarks(material_id)
            for row in existing:
                if row.locator == target:
                    return row
            if len(existing) >= MAX_BOOKMARKS:
                raise ReadingError(
                    f"this material already has {MAX_BOOKMARKS} bookmarks — "
                    "remove one before adding another."
                )
            created = ReadingBookmark(
                bookmark_id=f"bm_{uuid.uuid4().hex[:12]}",
                locator=target,
                label=trimmed,
                source_anchor=anchor_value,
            )
            self._write_bookmarks(material_id, [*existing, created])
            return created

    def delete_bookmark(self, material_id: str, bookmark_id: str) -> bool:
        self.manifest(material_id)
        target = str(bookmark_id or "").strip()
        if not target:
            return False
        with self._locked(material_id):
            existing = self.bookmarks(material_id)
            remaining = [row for row in existing if row.bookmark_id != target]
            if len(remaining) == len(existing):
                return False
            self._write_bookmarks(material_id, remaining)
            return True

    def _write_bookmarks(self, material_id: str, rows: Sequence[ReadingBookmark]) -> None:
        _atomic_write(
            self._state_path(material_id, BOOKMARKS_DIR),
            json.dumps([row.to_dict() for row in rows], ensure_ascii=False, indent=2),
        )

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


def _carry_dir(source: Path, target: Path) -> None:
    """Bring a previous revision's directory into the staging copy.

    Hard links first: the payload here is the untouched original upload, so
    copying it would double a large file on disk for no reason. Falls back to a
    real copy across filesystems, where linking is not available.
    """
    if not source.is_dir():
        return
    target.mkdir(parents=True, exist_ok=True)
    for entry in source.iterdir():
        if not entry.is_file():
            continue
        destination = target / entry.name
        if destination.exists():
            continue
        try:
            os.link(entry, destination)
        except OSError:
            shutil.copy2(entry, destination)


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
