"""
Co-Writer Document Storage
==========================

Per-document directory + manifest persistence with atomic writes.

Layout (relative to ``data/user/workspace/co-writer/``)::

    documents/
    ├── doc_{doc_id}/
    │   └── manifest.json   # { id, title, content, created_at, updated_at }
    └── doc_{doc_id2}/
        └── manifest.json
"""

from __future__ import annotations

from contextlib import contextmanager
import json
import logging
from pathlib import Path
import re
import shutil
import threading
import time
from typing import Any
import uuid

from pydantic import BaseModel, Field

from deeptutor.notes.blocks import blocks_to_markdown, validate_blocks
from deeptutor.services.file_io import atomic_write_text as _atomic_write_text
from deeptutor.services.path_service import get_path_service

logger = logging.getLogger(__name__)


class CoWriterDocument(BaseModel):
    """Lightweight document model for Co-Writer projects."""

    id: str
    title: str = ""
    content: str = ""
    blocks: list[dict[str, Any]] | None = None
    schema_version: int = 1
    revision: int = 0
    parent_id: str | None = None
    icon: str = ""
    cover: str = ""
    pinned: bool = False
    applied_suggestion_ids: list[str] = Field(default_factory=list)
    created_at: float = Field(default_factory=lambda: time.time())
    updated_at: float = Field(default_factory=lambda: time.time())


class CoWriterDocumentSummary(BaseModel):
    """Summary view (without full content) used for list endpoints."""

    id: str
    title: str
    created_at: float
    updated_at: float
    preview: str = ""
    parent_id: str | None = None
    icon: str = ""
    cover: str = ""
    pinned: bool = False
    revision: int = 0


def _atomic_write_json(path: Path, payload: Any) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    _atomic_write_text(path, text)


def _read_json(path: Path) -> Any | None:
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(f"Failed to read JSON {path}: {exc}")
        return None


def _derive_title(content: str, fallback: str = "Untitled draft") -> str:
    """Pick a title from the first heading line; fallback otherwise."""
    if not content:
        return fallback
    for raw in content.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            stripped = line.lstrip("#").strip()
            if stripped:
                return stripped[:120]
        return line[:120]
    return fallback


_FENCE = re.compile(r"^\s*(```|~~~)")
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_TAG = re.compile(r"</?[A-Za-z][^>]*>")
_LINE_MARK = re.compile(r"^(?:#{1,6}\s+|>\s?|[-*+]\s+\[[ xX]\]\s+|[-*+]\s+|\d+[.)]\s+)+")
_EMPHASIS = re.compile(r"(\*\*|__|~~|`)")
_RULE = re.compile(r"^\s*([-*_]\s*){3,}$")
_TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{2,}")


def _plain_lines(content: str) -> list[str]:
    """Readable text of a markdown body: what a list card shows, not its syntax."""
    lines: list[str] = []
    fenced = False
    for raw in content.splitlines():
        if _FENCE.match(raw):
            fenced = not fenced
            continue
        if fenced or _RULE.match(raw) or _TABLE_RULE.match(raw):
            continue
        line = raw.strip()
        if line.startswith("|"):
            line = " · ".join(cell.strip() for cell in line.strip("|").split("|") if cell.strip())
        line = _TAG.sub("", _LINK.sub(r"\1", _IMAGE.sub("", line))).strip()
        line = _LINE_MARK.sub("", line)
        line = _EMPHASIS.sub("", line).replace("$$", "").strip()
        if line:
            lines.append(line)
    return lines


def _build_preview(content: str, limit: int = 160, title: str = "") -> str:
    if not content:
        return ""
    lines = _plain_lines(content)
    # A page usually opens with its own title as a heading; the card shows it already.
    if lines and title and lines[0].strip().casefold() == title.strip().casefold():
        lines = lines[1:]
    cleaned = "  ".join(lines)
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit].rstrip() + "…"


class RevisionConflict(ValueError):
    """A write was based on a revision that is no longer current."""


_STORE_LOCK = threading.RLock()


class CoWriterStorage:
    """File-system backed store for Co-Writer documents."""

    def __init__(self, path_service=None) -> None:
        self._path_service = path_service

    @property
    def path_service(self):
        if self._path_service is not None:
            return self._path_service
        return get_path_service()

    # ── Path helpers ─────────────────────────────────────────────────────

    def docs_root(self) -> Path:
        return self.path_service.get_co_writer_docs_dir()

    def doc_root(self, doc_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{8,32}", doc_id):
            raise ValueError("Invalid page ID")
        return self.path_service.get_co_writer_doc_root(doc_id)

    def manifest_path(self, doc_id: str) -> Path:
        self.doc_root(doc_id)
        return self.path_service.get_co_writer_doc_manifest(doc_id)

    def ensure_root(self) -> Path:
        root = self.docs_root()
        root.mkdir(parents=True, exist_ok=True)
        return root

    def ensure_doc_root(self, doc_id: str) -> Path:
        root = self.doc_root(doc_id)
        root.mkdir(parents=True, exist_ok=True)
        return root

    def doc_exists(self, doc_id: str) -> bool:
        return self.manifest_path(doc_id).exists()

    # ── CRUD ─────────────────────────────────────────────────────────────

    def list_doc_ids(self) -> list[str]:
        root = self.docs_root()
        if not root.exists():
            return []
        ids: list[str] = []
        for child in root.iterdir():
            if child.is_dir() and child.name.startswith("doc_"):
                ids.append(child.name[len("doc_") :])
        return ids

    def list_documents(self) -> list[CoWriterDocumentSummary]:
        summaries: list[CoWriterDocumentSummary] = []
        for doc_id in self.list_doc_ids():
            doc = self.load_document(doc_id)
            if doc is None:
                continue
            summaries.append(
                CoWriterDocumentSummary(
                    id=doc.id,
                    title=doc.title or _derive_title(doc.content),
                    created_at=doc.created_at,
                    updated_at=doc.updated_at,
                    preview=_build_preview(doc.content, title=doc.title),
                    parent_id=doc.parent_id,
                    icon=doc.icon,
                    cover=doc.cover,
                    pinned=doc.pinned,
                    revision=doc.revision,
                )
            )
        summaries.sort(key=lambda s: s.updated_at, reverse=True)
        return summaries

    def create_document(
        self,
        *,
        title: str | None = None,
        content: str = "",
        blocks: list[dict[str, Any]] | None = None,
        parent_id: str | None = None,
    ) -> CoWriterDocument:
        with self.locked():
            if parent_id and self.load_document(parent_id) is None:
                raise ValueError("Parent page does not exist")
            if blocks is not None:
                content = blocks_to_markdown(validate_blocks(blocks))
            doc_id = uuid.uuid4().hex[:12]
            # Avoid extremely unlikely collisions.
            while self.doc_exists(doc_id):
                doc_id = uuid.uuid4().hex[:12]

            now = time.time()
            resolved_title = (title or "").strip() or _derive_title(content, "Untitled draft")
            document = CoWriterDocument(
                id=doc_id,
                title=resolved_title,
                content=content,
                blocks=blocks,
                parent_id=parent_id,
                created_at=now,
                updated_at=now,
            )
            self._write(document)
            return document

    def load_document(self, doc_id: str) -> CoWriterDocument | None:
        data = _read_json(self.manifest_path(doc_id))
        if data is None:
            return None
        try:
            return CoWriterDocument.model_validate(data)
        except Exception as exc:
            logger.warning(f"Failed to validate Co-Writer document {doc_id}: {exc}")
            return None

    @contextmanager
    def locked(self):
        # One lock covers hierarchy changes as well as document compare-and-swap.
        # Keep the lock outside doc directories, which may be deleted.
        with _STORE_LOCK:
            lock_path = self.ensure_root() / ".write.lock"
            with lock_path.open("a+b") as handle:
                try:
                    import fcntl
                except ImportError:
                    import msvcrt

                    handle.write(b"0")
                    handle.flush()
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                    try:
                        yield
                    finally:
                        handle.seek(0)
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                    try:
                        yield
                    finally:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def update_document(
        self,
        doc_id: str,
        *,
        title: str | None = None,
        content: str | None = None,
        blocks: list[dict[str, Any]] | None = None,
        expected_revision: int | None = None,
        **metadata,
    ) -> CoWriterDocument | None:
        with self.locked():
            document = self.load_document(doc_id)
            if document is None:
                return None
            if expected_revision is not None and document.revision != expected_revision:
                raise RevisionConflict("This page changed elsewhere. Reload before saving.")
            if (
                blocks is not None or (document.blocks is not None and content is not None)
            ) and expected_revision is None:
                raise RevisionConflict("Block pages require expected_revision.")
            if document.blocks is not None and content is not None and blocks is None:
                raise RevisionConflict("Edit this page through its block editor.")
            previous_blocks = document.blocks or []
            if blocks is not None:
                validate_blocks(blocks)
                if document.blocks is None:
                    backup = self.doc_root(doc_id) / "legacy.md"
                    if not backup.exists():
                        _atomic_write_text(backup, document.content)
                document.blocks = blocks
                content = blocks_to_markdown(blocks)
            if content is not None:
                document.content = content
                if title is None and (not document.title or document.title == "Untitled draft"):
                    document.title = _derive_title(content, document.title or "Untitled draft")
            if title is not None:
                document.title = title.strip() or _derive_title(document.content)
            if "parent_id" in metadata:
                parent = metadata["parent_id"] or None
                cursor, seen = parent, {doc_id}
                while cursor:
                    if cursor in seen:
                        raise ValueError("Pages cannot contain themselves")
                    seen.add(cursor)
                    ancestor = self.load_document(cursor)
                    if ancestor is None:
                        raise ValueError("Parent page does not exist")
                    cursor = ancestor.parent_id
                document.parent_id = parent
            for key in ("icon", "cover", "pinned"):
                if key in metadata:
                    setattr(document, key, metadata[key])
            document.revision += 1
            document.updated_at = time.time()
            self._write(document)
            if blocks is not None:
                from deeptutor.notes.proposals import refresh_review_anchors

                refresh_review_anchors(self, doc_id, blocks, previous_blocks)
            return document

    def delete_document(self, doc_id: str) -> bool:
        with self.locked():
            document = self.load_document(doc_id)
            if document is None:
                return False
            # Preserve children by promoting them to the deleted page's parent.
            for summary in self.list_documents():
                if summary.parent_id == doc_id:
                    child = self.load_document(summary.id)
                    child.parent_id = document.parent_id
                    child.revision += 1
                    self._write(child)
            shutil.rmtree(self.doc_root(doc_id))
            return True

    # ── Internal ─────────────────────────────────────────────────────────

    def _write(self, document: CoWriterDocument) -> None:
        self.ensure_doc_root(document.id)
        _atomic_write_json(self.manifest_path(document.id), document.model_dump(mode="json"))


_storages: dict[str, CoWriterStorage] = {}


def get_co_writer_storage() -> CoWriterStorage:
    key = str(get_path_service().workspace_root.resolve())
    if key not in _storages:
        _storages[key] = CoWriterStorage()
    return _storages[key]


__all__ = [
    "CoWriterDocument",
    "CoWriterDocumentSummary",
    "CoWriterStorage",
    "get_co_writer_storage",
]
