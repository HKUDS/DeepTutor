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
from typing import Protocol, runtime_checkable
from urllib.parse import quote

from deeptutor.services.path_service import get_path_service
from deeptutor.tutorbot.utils.helpers import safe_filename

logger = logging.getLogger(__name__)


_ATTACHMENT_DIR_ENV = "CHAT_ATTACHMENT_DIR"
_DEFAULT_SUBPATH = ("workspace", "chat", "attachments")
# Public route prefix served by deeptutor.api.routers.attachments
_PUBLIC_URL_PREFIX = "/api/attachments"


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
        ``"/api/attachments/<sid>/<aid>/<name>"``). Raising on failure is
        fine — callers log the error and proceed without ``url``.
        """

    async def delete_session(self, session_id: str) -> None:
        """Best-effort cleanup of all attachments for *session_id*."""

    def resolve_path(self, *, session_id: str, attachment_id: str, filename: str) -> Path | None:
        """Return the absolute path on disk for an attachment, or ``None``
        if it does not exist or escapes the storage root.

        Used by the static router to serve files; remote-storage backends can
        return ``None`` and the router will then fall back to a redirect.
        """


class LocalDiskAttachmentStore:
    """Default :class:`AttachmentStore` backend writing to local disk.

    The root directory defaults to ``data/user/workspace/chat/attachments``
    under the project root (matching :class:`PathService`'s public outputs).
    Override via ``$CHAT_ATTACHMENT_DIR`` (absolute path).
    """

    def __init__(self, root: Path | None = None) -> None:
        if root is None:
            override = os.environ.get(_ATTACHMENT_DIR_ENV, "").strip()
            if override:
                root = Path(override).expanduser().resolve()
            else:
                root = (get_path_service().get_user_root().joinpath(*_DEFAULT_SUBPATH)).resolve()
        self._root = root

    @property
    def root(self) -> Path:
        return self._root

    def _stored_filename(self, attachment_id: str, filename: str) -> str:
        return f"{attachment_id}_{_coerce_filename(filename)}"

    def _session_dir(self, session_id: str) -> Path:
        sid = _coerce_filename(session_id)
        return (self._root / sid).resolve()

    def _safe_join(self, session_id: str, name: str) -> Path | None:
        """Join *name* under the session dir and confirm the result stays
        inside ``self._root``. Returns ``None`` if traversal is detected.
        """
        session_dir = self._session_dir(session_id)
        # Resolve the candidate even if it doesn't exist yet — prevents a
        # symlink-based attack that would point outside the root once created.
        candidate = (session_dir / name).resolve()
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
        return f"{_PUBLIC_URL_PREFIX}/{sid}/{aid}/{name}"

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
        session_dir = self._session_dir(session_id)
        if not session_dir.exists():
            return
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._rmtree_sync, session_dir)

    @staticmethod
    def _rmtree_sync(path: Path) -> None:
        import shutil

        try:
            shutil.rmtree(path)
        except OSError as exc:
            logger.warning("failed to clean up attachment dir %s: %s", path, exc)

    def resolve_path(self, *, session_id: str, attachment_id: str, filename: str) -> Path | None:
        stored = self._stored_filename(attachment_id, filename)
        target = self._safe_join(session_id, stored)
        if target is None or not target.is_file():
            return None
        return target


_stores: dict[str, AttachmentStore] = {}


def get_attachment_store() -> AttachmentStore:
    """Return the process-wide :class:`AttachmentStore`.

    Today this is always a :class:`LocalDiskAttachmentStore`; future S3/MinIO
    backends can be selected here based on an env var.
    """
    override = os.environ.get(_ATTACHMENT_DIR_ENV, "").strip()
    root = (
        Path(override).expanduser().resolve()
        if override
        else get_path_service().get_user_root().joinpath(*_DEFAULT_SUBPATH).resolve()
    )
    key = str(root)
    if key not in _stores:
        _stores[key] = LocalDiskAttachmentStore(root=root)
    return _stores[key]


def reset_attachment_store() -> None:
    """Reset the singleton — only meant for tests."""
    _stores.clear()
