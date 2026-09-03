"""Content-addressed blob store with labelled reference counting.

Used by chat attachments (#1138, stage 1) so identical uploads share one
on-disk object. Reading / knowledge-base stores can adopt the same catalog
later without changing the digest / label contract.

Layout under ``root``::

    objects/<ab>/<sha256>          # raw bytes
    refs/<ab>/<sha256>.json        # {"labels": [...], "size": N}

Hard-link (or copy fallback) materialises a consumer path while the blob
object remains the single copy of the bytes.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import threading
from typing import Any

logger = logging.getLogger(__name__)

_HEX = frozenset("0123456789abcdef")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ContentAddressedBlobStore:
    """SHA-256 object store with per-label refcounts."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._objects = self._root / "objects"
        self._refs = self._root / "refs"
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    @property
    def root(self) -> Path:
        return self._root

    def _digest_lock(self, digest: str) -> threading.Lock:
        with self._locks_guard:
            lock = self._locks.get(digest)
            if lock is None:
                lock = threading.Lock()
                self._locks[digest] = lock
            return lock

    def _shard(self, digest: str) -> str:
        digest = digest.lower().strip()
        if len(digest) != 64 or any(ch not in _HEX for ch in digest):
            raise ValueError(f"invalid sha256 digest: {digest!r}")
        return digest[:2]

    def object_path(self, digest: str) -> Path:
        shard = self._shard(digest)
        return self._objects / shard / digest.lower()

    def refs_path(self, digest: str) -> Path:
        shard = self._shard(digest)
        return self._refs / shard / f"{digest.lower()}.json"

    def _read_refs(self, digest: str) -> dict[str, Any]:
        path = self.refs_path(digest)
        if not path.is_file():
            return {"labels": [], "size": 0}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("corrupt blob refs %s: %s", path, exc)
            return {"labels": [], "size": 0}
        labels = raw.get("labels") if isinstance(raw, dict) else None
        size = raw.get("size") if isinstance(raw, dict) else 0
        if not isinstance(labels, list):
            labels = []
        cleaned = [str(item) for item in labels if str(item or "").strip()]
        return {"labels": cleaned, "size": int(size or 0)}

    def _write_refs(self, digest: str, payload: dict[str, Any]) -> None:
        path = self.refs_path(digest)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        try:
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, path)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass

    def _write_object(self, digest: str, data: bytes) -> Path:
        target = self.object_path(digest)
        if target.is_file() and target.stat().st_size == len(data):
            return target
        target.parent.mkdir(parents=True, exist_ok=True)
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
        return target

    def put(self, data: bytes, *, label: str) -> str:
        """Store *data* (or reuse an existing object) and attach *label*."""
        label = str(label or "").strip()
        if not label:
            raise ValueError("blob label must be non-empty")
        digest = sha256_hex(data)
        with self._digest_lock(digest):
            self._write_object(digest, data)
            meta = self._read_refs(digest)
            labels = list(meta["labels"])
            if label not in labels:
                labels.append(label)
            self._write_refs(digest, {"labels": labels, "size": len(data)})
        return digest

    def labels_for(self, digest: str) -> tuple[str, ...]:
        return tuple(self._read_refs(digest)["labels"])

    def release(self, label: str, *, digest: str | None = None) -> list[str]:
        """Drop *label* from matching blobs; delete objects whose refcount hits zero.

        When *digest* is provided only that object is touched; otherwise the
        refs tree is scanned (used for recovery if a sidecar is missing).

        Returns digests whose objects were removed.
        """
        label = str(label or "").strip()
        if not label:
            return []
        if digest:
            return self._release_one(digest, label)
        if not self._refs.exists():
            return []
        removed: list[str] = []
        for refs_file in self._refs.glob("*/*.json"):
            candidate = refs_file.stem
            if len(candidate) != 64:
                continue
            removed.extend(self._release_one(candidate, label))
        return removed

    def _release_one(self, digest: str, label: str) -> list[str]:
        with self._digest_lock(digest):
            meta = self._read_refs(digest)
            labels = [item for item in meta["labels"] if item != label]
            if len(labels) == len(meta["labels"]):
                return []
            refs_file = self.refs_path(digest)
            if labels:
                self._write_refs(digest, {"labels": labels, "size": meta["size"]})
                return []
            try:
                refs_file.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("failed to remove blob refs %s: %s", refs_file, exc)
            obj = self.object_path(digest)
            try:
                obj.unlink(missing_ok=True)
                return [digest.lower()]
            except OSError as exc:
                logger.warning("failed to remove blob object %s: %s", obj, exc)
                return []
    def link_or_copy(self, digest: str, dest: Path) -> str:
        """Materialise *digest* at *dest* via hard link, else copy.

        Returns ``"link"`` or ``"copy"``.
        """
        src = self.object_path(digest)
        if not src.is_file():
            raise FileNotFoundError(f"blob object missing for {digest}")
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            dest.unlink()
        try:
            os.link(src, dest)
            return "link"
        except OSError as exc:
            logger.debug("hardlink unavailable for %s → %s (%s); copying", src, dest, exc)
            shutil.copy2(src, dest)
            return "copy"

    def object_count(self) -> int:
        if not self._objects.exists():
            return 0
        return sum(1 for path in self._objects.glob("*/*") if path.is_file())


__all__ = ["ContentAddressedBlobStore", "sha256_hex"]
