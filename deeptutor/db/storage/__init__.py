"""Object storage interface for user files and assets.

ROADMAP Phase 3 asks for an "object storage interface for files and assets".
The interface already existed in spirit — :mod:`deeptutor.services.storage`
has an ``AttachmentStore`` protocol with a local-disk implementation — but it
was not a general abstraction and had no key-based backend, so it could not be
pointed at S3/MinIO later without touching every call-site.

This module is that abstraction. It is deliberately narrow: five operations,
all key-based, no filesystem assumptions in the signature.

.. code-block:: python

    store = get_object_store()          # local disk by default
    key = store.put(data, namespace="user-files", suffix=".pdf")
    data = store.get(key)
    store.delete(key)

The key returned by :meth:`ObjectStore.put` is what
``user_files.storage_path`` stores. It is **relative** and **content-addressed**
when a hash is available, so the same bytes stored twice cost one object, and
moving from local disk to a bucket is a config change plus a copy, never a
schema change.

Why content-addressed
---------------------
A deduplicating key is what makes ``uq_user_files_content`` meaningful and what
keeps storage growth proportional to distinct content rather than upload
count. Two students uploading the same textbook PDF store it once.

What is deliberately *not* here
-------------------------------
No presigned URLs, no multipart, no lifecycle rules. Those are backend
features; exposing them on the interface would force every backend to
implement them. The HTTP layer asks for bytes, or hands the browser a
``/files/...`` route that streams from the backend.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import logging
import os
from pathlib import Path
import shutil
import tempfile
from typing import Protocol, runtime_checkable
from urllib.parse import urlsplit

from deeptutor.runtime.home import get_runtime_home

logger = logging.getLogger(__name__)

#: Where local-disk objects live, relative to the runtime home.
LOCAL_STORE_SUBDIR = ("data", "system", "objects")


class ObjectNotFound(KeyError):
    """The key does not resolve to a stored object."""


class ObjectStoreError(RuntimeError):
    """An operation failed for a reason other than a miss."""


class ObjectKeyError(ValueError):
    """The supplied key would escape the store (path traversal or absolute)."""


def content_key(data: bytes, *, suffix: str = "") -> str:
    """Return the content-addressed key for *data*.

    Sharded two levels (``ab/cd/abcdef...``) because a flat directory with
    hundreds of thousands of entries degrades on ext4 and on any object store
    whose console paginates by prefix.
    """
    digest = hashlib.sha256(data).hexdigest()
    if suffix and not suffix.startswith("."):
        suffix = "." + suffix
    return f"{digest[:2]}/{digest[2:4]}/{digest}{suffix}"


@runtime_checkable
class ObjectStore(Protocol):
    """Minimal blob store. All methods are synchronous and thread-safe."""

    def put(self, data: bytes, *, namespace: str, key: str | None = None) -> str:
        """Store *data* under *namespace*, return the full key.

        ``key=None`` means content-addressed: the returned key is derived from
        the bytes, so putting identical bytes twice is a no-op.
        """

    def get(self, key: str) -> bytes: ...

    def exists(self, key: str) -> bool: ...

    def delete(self, key: str) -> bool:
        """Remove the object. Returns False when it was already absent."""

    def size(self, key: str) -> int: ...

    def open_path(self, key: str) -> Path:
        """Return a local path for *key*, materialising it if the backend is remote.

        Used by streaming responses and by the document parsers, which need a
        real file. The returned path is *read-only* from the caller's point of
        view.
        """


def _validate_key(key: str) -> str:
    if not key or key.startswith(("/", "\\")):
        raise ObjectKeyError(f"object key must be relative, got {key!r}")
    normalized = key.replace("\\", "/")
    parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ObjectKeyError(f"object key contains an unsafe segment: {key!r}")
    return normalized


@dataclass
class LocalDiskObjectStore:
    """Default backend: the runtime home on local disk.

    Chosen as the default because the documented single-container deployment
    already mounts ``data/``, and because tests must run without network. The
    interface is what makes replacing it possible; the default is what makes
    Phase 3 shippable today.
    """

    root: Path | None = None
    namespace_prefix: str = ""

    def __post_init__(self) -> None:
        if self.root is None:
            self.root = get_runtime_home().joinpath(*LOCAL_STORE_SUBDIR)
        self.root = Path(self.root)

    def _full(self, key: str) -> Path:
        safe = _validate_key(key)
        candidate = (self.root / safe).resolve()  # type: ignore[operator]
        root_resolved = self.root.resolve()  # type: ignore[union-attr]
        if root_resolved not in candidate.parents and candidate != root_resolved:
            raise ObjectKeyError(f"object key escapes the store root: {key!r}")
        return candidate

    def put(self, data: bytes, *, namespace: str, key: str | None = None) -> str:
        ns = _validate_key(namespace) if namespace else ""
        relative = key if key is not None else content_key(data)
        relative = _validate_key(relative)
        full_key = f"{ns}/{relative}" if ns else relative
        target = self._full(full_key)
        if key is None and target.exists() and target.stat().st_size == len(data):
            # Content-addressed no-op. Only safe when the key was *derived from*
            # the content: same key implies same bytes. Applying this shortcut to
            # a caller-supplied key would silently keep stale data whenever an
            # overwrite happened to be the same length, which is a data-loss bug
            # rather than an optimisation.
            return full_key
        target.parent.mkdir(parents=True, exist_ok=True)
        # Atomic replace: a reader never sees a half-written object, and a
        # failed write leaves no partial file behind.
        handle, tmp_name = tempfile.mkstemp(dir=str(target.parent), prefix=".tmp-")
        try:
            with os.fdopen(handle, "wb") as fh:
                fh.write(data)
            os.replace(tmp_name, target)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
        return full_key

    def get(self, key: str) -> bytes:
        try:
            return self._full(key).read_bytes()
        except FileNotFoundError as exc:
            raise ObjectNotFound(key) from exc
        except OSError as exc:
            raise ObjectStoreError(f"cannot read {key!r}: {exc}") from exc

    def exists(self, key: str) -> bool:
        try:
            return self._full(key).is_file()
        except ObjectKeyError:
            return False

    def delete(self, key: str) -> bool:
        path = self._full(key)
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise ObjectStoreError(f"cannot delete {key!r}: {exc}") from exc

    def size(self, key: str) -> int:
        try:
            return self._full(key).stat().st_size
        except FileNotFoundError as exc:
            raise ObjectNotFound(key) from exc

    def open_path(self, key: str) -> Path:
        path = self._full(key)
        if not path.is_file():
            raise ObjectNotFound(key)
        return path

    # -- operational helpers ------------------------------------------------

    def total_size(self) -> int:
        if not self.root.is_dir():  # type: ignore[union-attr]
            return 0
        return sum(p.stat().st_size for p in self.root.rglob("*") if p.is_file())  # type: ignore[union-attr]

    def purge(self) -> None:
        """Delete everything. Test helper; never wired to a route."""
        if self.root and self.root.is_dir():  # type: ignore[union-attr]
            shutil.rmtree(self.root, ignore_errors=True)


def _store_from_env() -> ObjectStore:
    """Resolve the configured backend.

    ``DEEPTUTOR_OBJECT_STORE_URL`` accepts:

    * unset or ``local://`` → local disk under the runtime home
    * ``file:///abs/path``  → local disk at that path

    Any other scheme is a configuration error rather than a silent fallback: an
    ``s3://`` URL that quietly wrote to local disk would lose data on the next
    container restart, and that is exactly the class of bug this layer exists to
    prevent.
    """
    raw = (os.getenv("DEEPTUTOR_OBJECT_STORE_URL") or "").strip()
    if not raw or raw == "local://":
        return LocalDiskObjectStore()
    parts = urlsplit(raw)
    if parts.scheme in {"file", "local"}:
        path = parts.path or parts.netloc
        if not path:
            raise ObjectStoreError("file:// object store URL has no path")
        return LocalDiskObjectStore(root=Path(path))
    raise ObjectStoreError(
        f"unsupported object store scheme {parts.scheme!r}; "
        "only local:// and file:// are implemented"
    )


_CACHED: ObjectStore | None = None


def get_object_store() -> ObjectStore:
    global _CACHED
    if _CACHED is None:
        _CACHED = _store_from_env()
    return _CACHED


def reset_object_store(store: ObjectStore | None = None) -> None:
    """Drop the cache, optionally pinning *store* (used by tests)."""
    global _CACHED
    _CACHED = store
