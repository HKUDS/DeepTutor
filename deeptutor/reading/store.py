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
    BilingualGroup,
    MaterialManifest,
    MaterialNotFound,
    OutlineEntry,
    ReadingError,
    ReadingPosition,
    ReadingUpgradeConflict,
    TextQuoteSelector,
    UnitReference,
)
from deeptutor.reading.sources import ReadingSourcePayload

logger = logging.getLogger(__name__)

MANIFEST_NAME = "manifest.json"
OUTLINE_NAME = "outline.json"
ANNOTATIONS_NAME = "annotations.json"
POSITION_NAME = "position.json"
UNIT_REFS_NAME = "unit_refs.json"
BILINGUAL_UNITS_NAME = "bilingual_units.json"
UNITS_DIR = "units"
RAW_DIR = "raw"
REVISIONS_DIR = "revisions"
ASSETS_DIR = "_snapshot_assets"

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
        from deeptutor.multi_user.paths import get_current_path_service

        return get_current_path_service().get_workspace_feature_dir("reading")  # type: ignore[arg-type]

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
                wants_epub_upgrade = (
                    path.suffix.lower() == ".epub" and existing.render_mode != "epub"
                )
                if not wants_epub_upgrade:
                    return existing
                # Legacy text imports can now be repaired safely. Quote anchors
                # migrate when unique; ambiguous marks are retained for review.

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

            outline = extraction.outline or synthesise_outline(extraction.units)
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
                created_at=existing.created_at if existing else time.time(),
                # Compatibility: old clients route this boolean directly to
                # pdf.js. EPUB dispatch is carried by ``render_mode`` instead.
                has_raw_view=extraction.render_mode == "pdf",
                render_mode=extraction.render_mode,
                content_format=(
                    extraction.render_mode
                    if extraction.render_mode in ("pdf", "epub")
                    else (
                        "markdown"
                        if Path(display_name).suffix.lower() in {".md", ".markdown"}
                        else "plain_text"
                    )
                ),
            )
            # Manifest last: its presence is the "this material is usable"
            # signal, so it must not appear before the units it describes.
            _atomic_write(
                stage_dir / MANIFEST_NAME,
                json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2),
            )

            old_annotations = self.annotations(material_id) if existing else []
            old_outline = self.outline(material_id) if existing else []
            # A repair or compatible re-ingest keeps user-owned state.
            for state_name in (ANNOTATIONS_NAME, POSITION_NAME):
                source_state = material_dir / state_name
                if source_state.is_file():
                    shutil.copy2(source_state, stage_dir / state_name)

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
            if existing:
                self._write_annotations(
                    material_id,
                    self._migrate_annotations(
                        old_annotations,
                        extraction.units,
                        "",
                        old_outline=old_outline,
                        new_outline=outline,
                    ),
                )
                self._migrate_progress(
                    material_id,
                    existing,
                    manifest,
                    old_outline=old_outline,
                    new_outline=outline,
                )
            return manifest

    def ingest_source(self, payload: ReadingSourcePayload) -> MaterialManifest:
        """Persist a URL/KB source under a stable id with immutable revisions.

        The stable id is derived from provenance rather than content.  A changed
        snapshot therefore updates the existing reading item, while the content
        hash remains the revision id.  Uploads keep using :meth:`ingest`.
        """
        if payload.source_type == "upload":
            raise ReadingError("upload sources must use ingest()")
        if not payload.source_ref.strip():
            raise ReadingError("reading source has no stable reference")
        if not payload.units or not any(unit.strip() for unit in payload.units):
            raise ReadingError(f"{payload.filename}: no readable text was extracted")

        material_id = content_hash(f"{payload.source_type}\0{payload.source_ref}".encode("utf-8"))
        revision_id = payload.content_hash
        material_dir = self._dir(material_id)

        with self._locked(material_id):
            existing = self._load_manifest(material_id)
            if existing is not None and existing.revision_id == revision_id:
                return existing

            previous_revision = existing.revision_id if existing else ""
            old_outline = self.outline(material_id) if existing else []
            if existing and previous_revision:
                self._snapshot_active_revision(material_id, previous_revision)

            manifest = MaterialManifest(
                material_id=material_id,
                filename=payload.filename,
                unit=payload.unit,
                unit_count=len(payload.units),
                mime=payload.mime,
                title=payload.title,
                source_hash=revision_id,
                extractor=payload.extractor,
                byte_size=len(payload.raw_bytes),
                char_count=sum(len(unit) for unit in payload.units),
                created_at=existing.created_at if existing else time.time(),
                has_raw_view=payload.has_raw_view,
                render_mode=payload.render_mode,
                source_type=payload.source_type,
                source_ref=payload.source_ref,
                source_url=payload.source_url,
                kb_name=payload.kb_name,
                kb_path=payload.kb_path,
                revision_id=revision_id,
                captured_at=payload.captured_at,
                previous_revision_id=previous_revision,
                tutorial_available=payload.tutorial_available,
                navigation_kind=payload.navigation_kind,
                content_format=payload.content_format,
                bilingual_available=bool(
                    payload.bilingual_groups
                    or payload.bilingual_languages
                    or payload.bilingual_pairing_ids
                ),
                bilingual_languages=payload.bilingual_languages,
                bilingual_pairing_ids=payload.bilingual_pairing_ids,
            )
            old_annotations = self.annotations(material_id) if existing else []
            new_outline = list(payload.outline or synthesise_outline(payload.units))
            self._write_active_payload(material_dir, manifest, payload)
            for asset in payload.snapshot_assets:
                asset_dir = self.root / ASSETS_DIR
                asset_dir.mkdir(parents=True, exist_ok=True)
                target = asset_dir / asset.asset_id
                if not target.exists():
                    target.write_bytes(asset.data)
                _atomic_write(asset_dir / f"{asset.asset_id}.mime", asset.mime)
            if existing:
                self._write_annotations(
                    material_id,
                    self._migrate_annotations(
                        old_annotations,
                        payload.units,
                        revision_id,
                        old_outline=old_outline,
                        new_outline=new_outline,
                    ),
                )
                self._migrate_progress(
                    material_id,
                    existing,
                    manifest,
                    old_outline=old_outline,
                    new_outline=new_outline,
                )
            self._snapshot_active_revision(material_id, revision_id)
            return manifest

    def _write_active_payload(
        self,
        material_dir: Path,
        manifest: MaterialManifest,
        payload: ReadingSourcePayload,
    ) -> None:
        units_dir = material_dir / UNITS_DIR
        if units_dir.exists():
            shutil.rmtree(units_dir, ignore_errors=True)
        units_dir.mkdir(parents=True, exist_ok=True)
        for index, unit in enumerate(payload.units, start=1):
            self._unit_file(material_dir, index).write_text(unit, encoding="utf-8")

        if (material_dir / RAW_DIR).exists():
            shutil.rmtree(material_dir / RAW_DIR, ignore_errors=True)
        if payload.render_mode != "text" and payload.raw_bytes:
            raw_dir = material_dir / RAW_DIR
            raw_dir.mkdir(parents=True, exist_ok=True)
            (raw_dir / _safe_filename(payload.filename, fallback="material")).write_bytes(
                payload.raw_bytes
            )

        outline = payload.outline or synthesise_outline(payload.units)
        _atomic_write(
            material_dir / OUTLINE_NAME,
            json.dumps([entry.to_dict() for entry in outline], ensure_ascii=False),
        )
        _atomic_write(
            material_dir / UNIT_REFS_NAME,
            json.dumps([entry.to_dict() for entry in payload.unit_refs], ensure_ascii=False),
        )
        if payload.bilingual_groups:
            _atomic_write(
                material_dir / BILINGUAL_UNITS_NAME,
                json.dumps(
                    [row.to_dict() for row in payload.bilingual_groups],
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        else:
            (material_dir / BILINGUAL_UNITS_NAME).unlink(missing_ok=True)
        _atomic_write(
            material_dir / MANIFEST_NAME,
            json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2),
        )

    def _snapshot_active_revision(self, material_id: str, revision_id: str) -> None:
        if not revision_id or not _MATERIAL_ID_RE.match(revision_id):
            return
        material_dir = self._dir(material_id)
        revision_dir = material_dir / REVISIONS_DIR / revision_id
        revision_dir.mkdir(parents=True, exist_ok=True)
        for name in (
            MANIFEST_NAME,
            OUTLINE_NAME,
            UNIT_REFS_NAME,
            ANNOTATIONS_NAME,
            POSITION_NAME,
            BILINGUAL_UNITS_NAME,
        ):
            source = material_dir / name
            if source.is_file():
                shutil.copy2(source, revision_dir / name)
        source_units = material_dir / UNITS_DIR
        target_units = revision_dir / UNITS_DIR
        if source_units.is_dir() and not target_units.exists():
            shutil.copytree(source_units, target_units)
        source_raw = material_dir / RAW_DIR
        target_raw = revision_dir / RAW_DIR
        if source_raw.is_dir() and not target_raw.exists():
            shutil.copytree(source_raw, target_raw)

    @staticmethod
    def _migrate_annotations(
        annotations: Sequence[Annotation],
        units: Sequence[str],
        revision_id: str,
        *,
        old_outline: Sequence[OutlineEntry] = (),
        new_outline: Sequence[OutlineEntry] = (),
    ) -> list[Annotation]:
        migrated: list[Annotation] = []
        for row in annotations:
            quote_selector = next(
                (selector for selector in row.selectors if isinstance(selector, TextQuoteSelector)),
                None,
            )
            quote = (quote_selector.exact if quote_selector else row.quote).strip()
            preferred = ReadingStore._matching_outline_range(
                row.locator,
                old_outline,
                new_outline,
                len(units),
            )
            matches = ReadingStore._annotation_quote_matches(
                units,
                quote,
                quote_selector,
                preferred,
            )
            if len(matches) != 1 and preferred is not None:
                matches = ReadingStore._annotation_quote_matches(
                    units,
                    quote,
                    quote_selector,
                    None,
                )
            if len(matches) == 1:
                locator, start = matches[0]
                unit = units[locator - 1]
                end = start + len(quote)
                migrated.append(
                    dataclass_replace(
                        row,
                        locator=locator,
                        rects=(),
                        source_anchor="",
                        selectors=(
                            TextQuoteSelector(
                                exact=quote,
                                prefix=unit[max(0, start - 32) : start],
                                suffix=unit[end : end + 32],
                            ),
                        ),
                        revision_id=revision_id,
                        migration_status="migrated",
                        updated_at=time.time(),
                    )
                )
            else:
                migrated.append(
                    dataclass_replace(
                        row,
                        locator=min(max(1, row.locator), len(units)),
                        rects=(),
                        source_anchor="",
                        selectors=(quote_selector,) if quote_selector else (),
                        revision_id=revision_id,
                        migration_status="needs_review",
                        updated_at=time.time(),
                    )
                )
        return migrated

    @staticmethod
    def _annotation_quote_matches(
        units: Sequence[str],
        quote: str,
        selector: TextQuoteSelector | None,
        allowed: range | None,
    ) -> list[tuple[int, int]]:
        """Find exact quote occurrences, using W3C context to disambiguate."""

        if not quote:
            return []
        exact: list[tuple[int, int]] = []
        contextual: list[tuple[int, int]] = []
        for locator, unit in enumerate(units, start=1):
            if allowed is not None and locator not in allowed:
                continue
            start = 0
            while True:
                start = unit.find(quote, start)
                if start < 0:
                    break
                exact.append((locator, start))
                end = start + len(quote)
                prefix_matches = not selector or not selector.prefix or unit[:start].endswith(
                    selector.prefix
                )
                suffix_matches = not selector or not selector.suffix or unit[end:].startswith(
                    selector.suffix
                )
                if prefix_matches and suffix_matches:
                    contextual.append((locator, start))
                start = end or start + 1
        # Context is a refinement, not a reason to lose an otherwise unique
        # exact match when Markdown punctuation changed around the quote.
        return contextual or exact

    def _migrate_progress(
        self,
        material_id: str,
        old: MaterialManifest,
        new: MaterialManifest,
        *,
        old_outline: Sequence[OutlineEntry] = (),
        new_outline: Sequence[OutlineEntry] = (),
    ) -> None:
        position = self.position(material_id)
        if position.locator == 1 and not position.source_anchor and position.percentage == 0.0:
            return
        old_locator = max(1, position.locator)
        preferred = self._matching_outline_range(
            old_locator,
            old_outline,
            new_outline,
            new.unit_count,
        )
        if preferred:
            old_section = self._outline_range(old_locator, old_outline, old.unit_count)
            old_offset = old_locator - (old_section.start if old_section else old_locator)
            old_span = len(old_section) if old_section else 1
            section_ratio = old_offset / max(1, old_span - 1)
            migrated_locator = min(
                preferred.stop - 1,
                preferred.start + round(section_ratio * max(0, len(preferred) - 1)),
            )
        else:
            ratio = (old_locator - 1) / max(1, old.unit_count - 1)
            migrated_locator = min(
                new.unit_count,
                max(1, round(ratio * max(0, new.unit_count - 1)) + 1),
            )
        self.save_position(
            material_id,
            ReadingPosition(
                locator=migrated_locator,
                # Renderer-native anchors are revision-specific. Retaining
                # one could silently jump to the wrong paragraph after sync.
                source_anchor="",
                percentage=position.percentage,
            ),
        )

    @staticmethod
    def _outline_range(
        locator: int,
        outline: Sequence[OutlineEntry],
        unit_count: int,
    ) -> range | None:
        ordered = sorted(
            (row for row in outline if 1 <= row.locator <= unit_count),
            key=lambda row: row.locator,
        )
        active_index = next(
            (
                index
                for index in range(len(ordered) - 1, -1, -1)
                if ordered[index].locator <= locator
            ),
            None,
        )
        if active_index is None:
            return None
        start = ordered[active_index].locator
        stop = (
            ordered[active_index + 1].locator if active_index + 1 < len(ordered) else unit_count + 1
        )
        return range(start, max(start + 1, stop))

    @staticmethod
    def _matching_outline_range(
        old_locator: int,
        old_outline: Sequence[OutlineEntry],
        new_outline: Sequence[OutlineEntry],
        new_unit_count: int,
    ) -> range | None:
        old_rows = sorted(old_outline, key=lambda row: row.locator)
        old_row = next(
            (row for row in reversed(old_rows) if row.locator <= old_locator),
            None,
        )
        if old_row is None:
            return None
        candidates: list[OutlineEntry] = []
        if old_row.source_url:
            candidates = [row for row in new_outline if row.source_url == old_row.source_url]
        if len(candidates) != 1:
            candidates = [
                row
                for row in new_outline
                if row.title == old_row.title and row.level == old_row.level
            ]
        if len(candidates) != 1:
            return None
        return ReadingStore._outline_range(
            candidates[0].locator,
            new_outline,
            new_unit_count,
        )

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
                            source_url=str(row.get("source_url") or ""),
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
        if manifest.render_mode == "text":
            return None
        return self._find_raw(self._dir(material_id))

    def snapshot_asset(self, asset_id: str) -> tuple[Path, str]:
        candidate = str(asset_id or "").lower()
        if not re.fullmatch(r"[0-9a-f]{64}", candidate):
            raise ReadingError("invalid snapshot asset id")
        path = self.root / ASSETS_DIR / candidate
        if not path.is_file():
            raise MaterialNotFound("snapshot asset not found")
        try:
            mime = (self.root / ASSETS_DIR / f"{candidate}.mime").read_text(
                encoding="utf-8"
            )
        except OSError:
            mime = "application/octet-stream"
        return path, mime.strip()

    def unit_references(self, material_id: str) -> list[UnitReference]:
        """Source-native addresses aligned with the numeric locator space."""
        manifest = self.manifest(material_id)
        rows = _read_json(self._dir(material_id) / UNIT_REFS_NAME)
        if not isinstance(rows, list):
            return [UnitReference(locator=index) for index in range(1, manifest.unit_count + 1)]
        refs = [UnitReference.from_dict(row) for row in rows if isinstance(row, dict)]
        return [row for row in refs if 1 <= row.locator <= manifest.unit_count]

    def bilingual_groups(self, material_id: str, locator: int) -> list[BilingualGroup]:
        """Return validated alignment groups for one access-checked locator."""
        manifest = self.manifest(material_id)
        if not 1 <= locator <= manifest.unit_count:
            raise ReadingError(
                f"{manifest.unit} {locator} is out of range — "
                f"this material has {manifest.unit_count}."
            )
        rows = _read_json(self._dir(material_id) / BILINGUAL_UNITS_NAME)
        if not isinstance(rows, list):
            return []
        parsed = [BilingualGroup.from_dict(row) for row in rows if isinstance(row, dict)]
        return [row for row in parsed if row.locator == locator]

    def position(self, material_id: str) -> ReadingPosition:
        """Return the last viewport, defaulting to the first locator."""
        self.manifest(material_id)
        row = _read_json(self._dir(material_id) / POSITION_NAME)
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
                self._dir(material_id) / POSITION_NAME,
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

    def delete(self, material_id: str) -> bool:
        material_dir = self._dir(material_id)
        if not material_dir.is_dir():
            return False
        with self._locked(material_id):
            shutil.rmtree(material_dir, ignore_errors=True)
        return not material_dir.exists()

    # -- revisions / progress -------------------------------------------

    def revisions(self, material_id: str) -> list[MaterialManifest]:
        """Return all stored revisions, newest capture first."""
        current = self.manifest(material_id)
        if current.source_type == "upload":
            return [current]
        revision_root = self._dir(material_id) / REVISIONS_DIR
        found: dict[str, MaterialManifest] = {current.revision_id: current}
        if revision_root.is_dir():
            for child in revision_root.iterdir():
                data = _read_json(child / MANIFEST_NAME)
                if isinstance(data, dict):
                    item = MaterialManifest.from_dict(data)
                    if item.revision_id:
                        found[item.revision_id] = item
        return sorted(found.values(), key=lambda row: row.captured_at, reverse=True)

    def switch_revision(self, material_id: str, revision_id: str) -> MaterialManifest:
        """Make a stored revision active without deleting the current one."""
        current = self.manifest(material_id)
        if current.source_type == "upload":
            raise ReadingError("uploaded materials do not have revisions")
        revision = self._validate_id(revision_id)
        if revision == current.revision_id:
            return current
        source_dir = self._dir(material_id) / REVISIONS_DIR / revision
        data = _read_json(source_dir / MANIFEST_NAME)
        if not isinstance(data, dict):
            raise MaterialNotFound(f"revision {revision_id!r} not found")

        with self._locked(material_id):
            self._snapshot_active_revision(material_id, current.revision_id)
            material_dir = self._dir(material_id)
            for dirname in (UNITS_DIR, RAW_DIR):
                target = material_dir / dirname
                if target.exists():
                    shutil.rmtree(target, ignore_errors=True)
                source = source_dir / dirname
                if source.is_dir():
                    shutil.copytree(source, target)
            for name in (
                OUTLINE_NAME,
                UNIT_REFS_NAME,
                ANNOTATIONS_NAME,
                POSITION_NAME,
                BILINGUAL_UNITS_NAME,
            ):
                source = source_dir / name
                target = material_dir / name
                if source.is_file():
                    shutil.copy2(source, target)
                else:
                    target.unlink(missing_ok=True)
            manifest = MaterialManifest.from_dict(data)
            _atomic_write(
                material_dir / MANIFEST_NAME,
                json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2),
            )
            return manifest

    def repair_legacy_epub(
        self, material_id: str, legacy_root: Path | None = None
    ) -> MaterialManifest:
        """Upgrade a text-only EPUB in place using one exact-hash legacy source.

        The search is deliberately deterministic: no match or more than one
        match is surfaced for explicit user choice instead of guessing.
        """
        manifest = self.manifest(material_id)
        is_legacy = manifest.filename.lower().endswith(".epub") and (
            manifest.render_mode == "text" or self.raw_path(material_id) is None
        )
        if not is_legacy:
            return manifest
        root = legacy_root or self.root.parent / "immersive_reading"
        if not root.is_dir():
            raise ReadingError(
                "The legacy EPUB library could not be found. Choose the original EPUB to repair this material."
            )
        expected = manifest.source_hash or manifest.material_id
        matches: list[Path] = []
        for candidate in root.rglob("original.epub"):
            try:
                digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
            except OSError:
                continue
            if (
                digest == expected
                or digest.startswith(expected)
                or digest.startswith(manifest.material_id)
            ):
                matches.append(candidate)
        if not matches:
            raise ReadingError(
                "No matching original EPUB was found. Choose the original EPUB to repair this material."
            )
        if len(matches) != 1:
            raise ReadingUpgradeConflict(
                "More than one matching original EPUB was found. Choose which original EPUB should repair this material."
            )
        return self.ingest(matches[0], filename=manifest.filename)

    def link_source_to_kb(self, material_id: str, *, kb_name: str) -> MaterialManifest:
        """Associate an online snapshot with a KB without changing its identity.

        Saving a page after reading it must not recreate the material (which
        would strand its position and annotations). The KB owns subsequent
        sync; the reader only records the relationship on every stored copy of
        the active revision.
        """
        current = self.manifest(material_id)
        if current.source_type != "url_snapshot":
            raise ReadingError("Only web-page snapshots can be saved to a knowledge base.")
        linked = dataclass_replace(current, kb_name=str(kb_name or "").strip())
        with self._locked(material_id):
            _atomic_write(
                self._dir(material_id) / MANIFEST_NAME,
                json.dumps(linked.to_dict(), ensure_ascii=False, indent=2),
            )
            revision_manifest = (
                self._dir(material_id) / REVISIONS_DIR / linked.revision_id / MANIFEST_NAME
            )
            if revision_manifest.parent.is_dir():
                _atomic_write(
                    revision_manifest,
                    json.dumps(linked.to_dict(), ensure_ascii=False, indent=2),
                )
        return linked

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
        if len(annotation.source_anchor) > 4096:
            raise ReadingError("source anchor is too long")
        quote_selector = next(
            (
                selector
                for selector in annotation.selectors
                if isinstance(selector, TextQuoteSelector)
            ),
            None,
        )
        if quote_selector and annotation.quote and quote_selector.exact != annotation.quote:
            raise ReadingError("annotation quote does not match its TextQuoteSelector")
        if quote_selector and not annotation.quote:
            annotation = dataclass_replace(annotation, quote=quote_selector.exact)
        with self._locked(material_id):
            existing = self.annotations(material_id)
            stored = annotation
            if not stored.annotation_id:
                stored = dataclass_replace(stored, annotation_id=uuid.uuid4().hex[:12])
            if not stored.revision_id:
                stored = dataclass_replace(stored, revision_id=manifest.revision_id)
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
    "ASSETS_DIR",
    "BILINGUAL_UNITS_NAME",
    "MANIFEST_NAME",
    "MAX_READ_CHARS",
    "OUTLINE_NAME",
    "RAW_DIR",
    "REVISIONS_DIR",
    "UNITS_DIR",
    "ReadingStore",
    "content_hash",
]
