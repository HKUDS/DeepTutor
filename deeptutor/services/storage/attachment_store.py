"""Persistent storage for chat attachments.

The chat turn runtime writes the bytes of every uploaded attachment here
*before* the document extractor runs. Once persisted, the URL is recorded on
the message and the in-memory base64 is dropped (extractor still clears it
for office docs to save DB space). The frontend later fetches the original
file via the :mod:`deeptutor.api.routers.attachments` endpoint to render a
preview.

Design goals
------------

* **Local disk by default**: works in single-container Docker setups (the
  ``data/user`` volume is already mounted) and on plain Linux servers without
  any extra infrastructure.
* **Pluggable**: a thin :class:`AttachmentStore` protocol leaves room for an
  S3 / MinIO / GCS backend without touching call-sites.
* **Path-safe**: filenames coming over the WS are sanitised; resolved paths
  must remain inside the configured root.

The on-disk layout is::

    {root}/{session_id}/{attachment_id}_{filename}

The ``attachment_id`` prefix prevents collisions when the same filename is
uploaded twice in the same session.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
import shutil
from typing import Protocol, runtime_checkable
from urllib.parse import quote

from deeptutor.partners.helpers import safe_filename
from deeptutor.services.config import load_system_settings
from deeptutor.services.path_service import get_path_service

logger = logging.getLogger(__name__)


_LEGACY_SUBPATH = ("workspace", "chat", "attachments")
_VISIBLE_SUBPATH = ("chat", "attachments")
# Public route prefix served by deeptutor.api.routers.attachments
_PUBLIC_URL_PREFIX = "/files/attachments"


def _coerce_filename(filename: str) -> str:
    """Reduce *filename* to a safe basename.

    * Strips any directory components (defends against ``../`` traversal).
    * Replaces filesystem-unsafe characters via the existing ``safe_filename``
      helper (already used by the matrix tutorbot uploads).
    * Falls back to ``"file"`` if the result is empty.
    """
    base = os.path.basename(filename or "")
    cleaned = safe_filename(base)
    return cleaned or "file"


@runtime_checkable
class AttachmentStore(Protocol):
    """Storage backend for chat attachments.

    Implementations must be safe to call from an asyncio context. The default
    :class:`LocalDiskAttachmentStore` uses ``run_in_executor`` to keep blocking
    disk I/O off the event loop.
    """

    async def put(
        self,
        *,
        session_id: str,
        attachment_id: str,
        filename: str,
        data: bytes,
        mime_type: str = "",
    ) -> str:
        """Persist *data* and return a public URL the frontend can fetch.

        The returned URL is relative to the API origin (e.g.
        ``"/files/attachments/<sid>/<aid>/<name>"``). Raising on failure is
        fine — callers log the error and proceed without ``url``.
        """

    async def delete_session(self, session_id: str) -> None:
        """Best-effort cleanup of all attachments for *session_id*."""

    async def delete_attachment(self, session_id: str, attachment_id: str) -> None:
        """Best-effort cleanup of a single attachment identified by *attachment_id*."""

    def resolve_path(self, *, session_id: str, attachment_id: str, filename: str) -> Path | None:
        """Return the absolute path on disk for an attachment, or ``None``
        if it does not exist or escapes the storage root.

        Used by the static router to serve files; remote-storage backends can
        return ``None`` and the router will then fall back to a redirect.
        """


class LocalDiskAttachmentStore:
    """Default :class:`AttachmentStore` backend writing to local disk.

    New uploads live in the selected content workspace's ``chat/attachments``
    directory so workspace tools can discover them. Older uploads remain
    readable from the previous application-data location until materialized.
    """

    def __init__(self, root: Path | None = None, *, legacy_root: Path | None = None) -> None:
        if root is None:
            root = _attachment_root()
        self._root = root
        self._legacy_root = legacy_root if legacy_root != root else None

    @property
    def root(self) -> Path:
        return self._root

    def _stored_filename(self, attachment_id: str, filename: str) -> str:
        return f"{attachment_id}_{_coerce_filename(filename)}"

    def _session_dir(self, session_id: str) -> Path:
        sid = _coerce_filename(session_id)
        return self._root / sid

    def _safe_join(self, session_id: str, name: str) -> Path | None:
        """Join *name* under the session dir and confirm the result stays
        inside ``self._root``. Returns ``None`` if traversal is detected.
        """
        session_dir = self._session_dir(session_id)
        raw_candidate = session_dir / name
        if session_dir.is_symlink() or raw_candidate.is_symlink():
            return None
        # Resolve the candidate even if it doesn't exist yet — prevents a
        # symlink-based attack that would point outside the root once created.
        candidate = raw_candidate.resolve()
        try:
            candidate.relative_to(self._root.resolve())
        except ValueError:
            return None
        return candidate

    async def put(
        self,
        *,
        session_id: str,
        attachment_id: str,
        filename: str,
        data: bytes,
        mime_type: str = "",
    ) -> str:
        del mime_type  # not needed for local disk
        stored = self._stored_filename(attachment_id, filename)
        target = self._safe_join(session_id, stored)
        if target is None:
            raise ValueError(f"refusing to write attachment outside storage root: {stored!r}")

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._write_sync, target, data)

        # The router uses the same _coerce_filename rules to look up the file,
        # so the public URL must use the sanitised pieces. Each path segment
        # is percent-encoded so spaces/Unicode/punctuation in filenames flow
        # through fetch / <iframe> consistently across browsers.
        sid = quote(_coerce_filename(session_id), safe="")
        aid = quote(attachment_id, safe="")
        name = quote(_coerce_filename(filename), safe="")
        from deeptutor.services.workspace.context import workspace_url

        return workspace_url(f"{_PUBLIC_URL_PREFIX}/{sid}/{aid}/{name}")

    @staticmethod
    def _write_sync(target: Path, data: bytes) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        # Atomic-ish write: write to .tmp then rename. Avoids exposing a
        # half-written file via the static handler.
        tmp = target.with_suffix(target.suffix + ".tmp")
        try:
            with tmp.open("wb") as fh:
                fh.write(data)
            os.replace(tmp, target)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass

    async def delete_session(self, session_id: str) -> None:
        loop = asyncio.get_running_loop()
        roots = (self._root, self._legacy_root) if self._legacy_root else (self._root,)
        for root in roots:
            session_dir = LocalDiskAttachmentStore(root)._session_dir(session_id)
            if session_dir.exists() and not session_dir.is_symlink():
                await loop.run_in_executor(None, self._rmtree_sync, session_dir)

    async def delete_attachment(self, session_id: str, attachment_id: str) -> None:
        loop = asyncio.get_running_loop()
        roots = (self._root, self._legacy_root) if self._legacy_root else (self._root,)
        for root in roots:
            session_dir = LocalDiskAttachmentStore(root)._session_dir(session_id)
            if session_dir.exists() and not session_dir.is_symlink():
                await loop.run_in_executor(
                    None, self._delete_attachment_sync, session_dir, attachment_id
                )

    @staticmethod
    def _rmtree_sync(path: Path) -> None:
        try:
            shutil.rmtree(path)
        except OSError as exc:
            logger.warning("failed to clean up attachment dir %s: %s", path, exc)

    @staticmethod
    def _delete_attachment_sync(session_dir: Path, attachment_id: str) -> None:
        prefix = f"{attachment_id}_"
        for entry in session_dir.iterdir():
            if entry.name.startswith(prefix):
                try:
                    entry.unlink()
                except OSError as exc:
                    logger.warning("failed to delete attachment file %s: %s", entry, exc)
        try:
            if session_dir.exists() and not any(session_dir.iterdir()):
                session_dir.rmdir()
        except OSError as exc:
            logger.warning("failed to remove empty attachment dir %s: %s", session_dir, exc)

    def resolve_path(self, *, session_id: str, attachment_id: str, filename: str) -> Path | None:
        stored = self._stored_filename(attachment_id, filename)
        target = self._safe_join(session_id, stored)
        if target is not None and target.is_file():
            return target
        if self._legacy_root is None:
            return None
        legacy = LocalDiskAttachmentStore(self._legacy_root)
        target = legacy._safe_join(session_id, stored)
        return target if target is not None and target.is_file() else None

    async def materialize_session(self, session_id: str) -> None:
        """Move earlier uploads into the selected workspace before tool discovery."""
        if self._legacy_root is None:
            return
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._materialize_session_sync, session_id)

    def _materialize_session_sync(self, session_id: str) -> None:
        legacy = LocalDiskAttachmentStore(self._legacy_root)
        source_dir = legacy._session_dir(session_id)
        if not source_dir.is_dir() or source_dir.is_symlink():
            return
        destination_dir = self._session_dir(session_id)
        for source in source_dir.iterdir():
            if source.is_symlink() or not source.is_file():
                continue
            destination = self._safe_join(session_id, source.name)
            if destination is None or destination.exists():
                continue
            destination_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
        try:
            source_dir.rmdir()
        except OSError:
            pass

    def materialize_all_sessions(self) -> None:
        """Bring legacy uploads into this workspace before data migration."""
        if self._legacy_root is None or not self._legacy_root.is_dir():
            return
        for entry in self._legacy_root.iterdir():
            if entry.is_dir() and not entry.is_symlink():
                self._materialize_session_sync(entry.name)


_stores: dict[tuple[str, str], AttachmentStore] = {}


def get_attachment_store() -> AttachmentStore:
    """Return the process-wide :class:`AttachmentStore`.

    Today this is always a :class:`LocalDiskAttachmentStore`; future S3/MinIO
    backends can be selected here based on an env var.
    """
    root = _attachment_root()
    legacy_root = _legacy_attachment_root()
    key = (str(root), str(legacy_root))
    if key not in _stores:
        _stores[key] = LocalDiskAttachmentStore(root=root, legacy_root=legacy_root)
    return _stores[key]


def _attachment_root() -> Path:
    from deeptutor.services.workspace.context import current_workspace_id, get_workspace_scope

    override = str(load_system_settings().get("chat_attachment_dir") or "").strip()
    if override and not current_workspace_id():
        return Path(override).expanduser().resolve()
    scope = get_workspace_scope()
    if scope is not None and scope.workspace_id:
        content_root = scope.content_root
    else:
        from deeptutor.services.workspace import get_content_workspace_service

        content_root = get_content_workspace_service().general_binding().root
    from deeptutor.services.workspace.models import WorkspaceError

    directory = content_root
    for component in _VISIBLE_SUBPATH:
        directory = directory / component
        if directory.is_symlink():
            raise WorkspaceError("Chat attachment directories cannot be symbolic links.")
    return directory.resolve()


def _legacy_attachment_root() -> Path:
    return get_path_service().get_user_root().joinpath(*_LEGACY_SUBPATH).resolve()


def reset_attachment_store() -> None:
    """Reset the singleton — only meant for tests."""
    _stores.clear()
