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
* **Content-addressed**: identical payloads share one blob object via
  :class:`ContentAddressedBlobStore` (#1138). Session paths stay stable
  ``{id}_{filename}`` hard-links (or copies) so ``/files/attachments/...``
  URLs do not change.

The on-disk layout is::

    {root}/{session_id}/{attachment_id}_{filename}
    {root}/{session_id}/{attachment_id}_{filename}.cas.json   # digest sidecar
    {blob_root}/objects/<ab>/<sha256>
    {blob_root}/refs/<ab>/<sha256>.json
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Protocol, runtime_checkable
from urllib.parse import quote

from deeptutor.partners.helpers import safe_filename
from deeptutor.services.config import load_system_settings
from deeptutor.services.path_service import get_path_service
from deeptutor.services.storage.blob_store import ContentAddressedBlobStore

logger = logging.getLogger(__name__)


_DEFAULT_SUBPATH = ("workspace", "chat", "attachments")
_DEFAULT_BLOB_SUBPATH = ("workspace", "chat", "attachment_blobs")
# Public route prefix served by deeptutor.api.routers.attachments
_PUBLIC_URL_PREFIX = "/files/attachments"
_CAS_SUFFIX = ".cas.json"


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


def _attachment_label(session_id: str, attachment_id: str) -> str:
    return f"attachment:{_coerce_filename(session_id)}:{attachment_id}"


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

    The root directory defaults to ``data/user/workspace/chat/attachments``
    under the project root (matching :class:`PathService`'s public outputs).
    Override via ``data/user/settings/system.json`` ``chat_attachment_dir``.

    Bytes are stored once in a sibling content-addressed blob catalog
    (``chat_attachment_blob_dir`` / ``workspace/chat/attachment_blobs``).
    """

    def __init__(
        self,
        root: Path | None = None,
        *,
        blob_store: ContentAddressedBlobStore | None = None,
    ) -> None:
        if root is None:
            root = _attachment_root()
        self._root = root
        self._blobs = blob_store or ContentAddressedBlobStore(_blob_root(self._root))

    @property
    def root(self) -> Path:
        return self._root

    @property
    def blob_store(self) -> ContentAddressedBlobStore:
        return self._blobs

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

        label = _attachment_label(session_id, attachment_id)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._put_sync, target, data, label)

        # The router uses the same _coerce_filename rules to look up the file,
        # so the public URL must use the sanitised pieces. Each path segment
        # is percent-encoded so spaces/Unicode/punctuation in filenames flow
        # through fetch / <iframe> consistently across browsers.
        sid = quote(_coerce_filename(session_id), safe="")
        aid = quote(attachment_id, safe="")
        name = quote(_coerce_filename(filename), safe="")
        return f"{_PUBLIC_URL_PREFIX}/{sid}/{aid}/{name}"

    def _put_sync(self, target: Path, data: bytes, label: str) -> None:
        digest = self._blobs.put(data, label=label)
        mode = self._blobs.link_or_copy(digest, target)
        sidecar = Path(str(target) + _CAS_SUFFIX)
        payload = {"sha256": digest, "label": label, "materialize": mode}
        tmp = sidecar.with_suffix(sidecar.suffix + ".tmp")
        try:
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.replace(tmp, sidecar)
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
        await loop.run_in_executor(None, self._delete_session_sync, session_dir)

    async def delete_attachment(self, session_id: str, attachment_id: str) -> None:
        session_dir = self._session_dir(session_id)
        if not session_dir.exists():
            return
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._delete_attachment_sync, session_dir, attachment_id)

    def _delete_session_sync(self, session_dir: Path) -> None:
        import shutil

        if session_dir.is_dir():
            for entry in list(session_dir.iterdir()):
                if entry.name.endswith(_CAS_SUFFIX):
                    continue
                if entry.is_file():
                    self._release_file(entry)
        try:
            shutil.rmtree(session_dir)
        except OSError as exc:
            logger.warning("failed to clean up attachment dir %s: %s", session_dir, exc)

    def _delete_attachment_sync(self, session_dir: Path, attachment_id: str) -> None:
        prefix = f"{attachment_id}_"
        for entry in list(session_dir.iterdir()):
            if entry.name.endswith(_CAS_SUFFIX):
                continue
            if entry.name.startswith(prefix):
                self._release_file(entry)
                try:
                    entry.unlink(missing_ok=True)
                except OSError as exc:
                    logger.warning("failed to delete attachment file %s: %s", entry, exc)
                sidecar = Path(str(entry) + _CAS_SUFFIX)
                try:
                    sidecar.unlink(missing_ok=True)
                except OSError as exc:
                    logger.warning("failed to delete attachment sidecar %s: %s", sidecar, exc)
        try:
            if session_dir.exists() and not any(session_dir.iterdir()):
                session_dir.rmdir()
        except OSError as exc:
            logger.warning("failed to remove empty attachment dir %s: %s", session_dir, exc)

    def _release_file(self, entry: Path) -> None:
        sidecar = Path(str(entry) + _CAS_SUFFIX)
        digest: str | None = None
        label: str | None = None
        if sidecar.is_file():
            try:
                raw = json.loads(sidecar.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    digest = str(raw.get("sha256") or "").strip() or None
                    label = str(raw.get("label") or "").strip() or None
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("failed to read CAS sidecar %s: %s", sidecar, exc)
        if label:
            self._blobs.release(label, digest=digest)

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
    root = _attachment_root()
    key = str(root)
    if key not in _stores:
        _stores[key] = LocalDiskAttachmentStore(root=root)
    return _stores[key]


def _attachment_root() -> Path:
    override = str(load_system_settings().get("chat_attachment_dir") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return get_path_service().get_user_root().joinpath(*_DEFAULT_SUBPATH).resolve()


def _blob_root(attachment_root: Path | None = None) -> Path:
    override = str(load_system_settings().get("chat_attachment_blob_dir") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if attachment_root is not None:
        # Prefer a sibling of the attachments directory so a custom
        # ``chat_attachment_dir`` still keeps blobs next to session files.
        return (Path(attachment_root).resolve().parent / "attachment_blobs").resolve()
    return get_path_service().get_user_root().joinpath(*_DEFAULT_BLOB_SUBPATH).resolve()


def reset_attachment_store() -> None:
    """Reset the singleton — only meant for tests."""
    _stores.clear()
