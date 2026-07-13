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

import json
import logging
import os
from pathlib import Path
import shutil
import time
from typing import Any
import uuid

from pydantic import BaseModel, Field

from deeptutor.services.path_service import get_path_service

logger = logging.getLogger(__name__)


class CoWriterDocument(BaseModel):
    """Lightweight document model for Co-Writer projects."""

    id: str
    title: str = ""
    content: str = ""
    created_at: float = Field(default_factory=lambda: time.time())
    updated_at: float = Field(default_factory=lambda: time.time())


class CoWriterDocumentSummary(BaseModel):
    """Summary view (without full content) used for list endpoints."""

    id: str
    title: str
    created_at: float
    updated_at: float
    preview: str = ""


def _atomic_write_text(path: Path, text: str) -> None:
    """Write *text* to *path* atomically (write-temp + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass
    os.replace(tmp, path)


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


def _build_preview(content: str, limit: int = 160) -> str:
    if not content:
        return ""
    cleaned = "\n".join(line.strip() for line in content.splitlines() if line.strip())
    cleaned = cleaned.replace("\n", "  ")
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit].rstrip() + "…"


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
        return self.path_service.get_co_writer_doc_root(doc_id)

    def manifest_path(self, doc_id: str) -> Path:
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
                    preview=_build_preview(doc.content),
                )
            )
        summaries.sort(key=lambda s: s.updated_at, reverse=True)
        return summaries

    def create_document(
        self,
        *,
        title: str | None = None,
        content: str = "",
    ) -> CoWriterDocument:
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

    def update_document(
        self,
        doc_id: str,
        *,
        title: str | None = None,
        content: str | None = None,
    ) -> CoWriterDocument | None:
        document = self.load_document(doc_id)
        if document is None:
            return None
        if title is not None:
            document.title = title.strip() or _derive_title(
                content if content is not None else document.content
            )
        if content is not None:
            document.content = content
            if title is None:
                # Keep title in sync with the first heading when the user
                # never set an explicit title (or kept the default).
                derived = _derive_title(content, document.title or "Untitled draft")
                if not document.title or document.title == "Untitled draft":
                    document.title = derived
        document.updated_at = time.time()
        self._write(document)
        return document

    def delete_document(self, doc_id: str) -> bool:
        root = self.doc_root(doc_id)
        if not root.exists():
            return False
        shutil.rmtree(root, ignore_errors=True)
        return not root.exists()

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
