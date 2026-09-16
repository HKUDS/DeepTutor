"""Persistent File Library — reusable file storage across conversations (issue #1437).

Architecture
------------
Files are stored on disk under a library root (default:
``data/user/workspace/library/files``).  The SQLite database tracks metadata:
id (UUID), sha256, filename, mime_type, size_bytes, library_path (relative
to root), created_at, updated_at, is_deleted, deleted_at.

Deduplication: content is identified by SHA-256.  When ``add_file`` is called,
we compute the hash of the incoming bytes and check if an active (non-deleted)
entry with that hash already exists.  If so, we return the existing entry
without storing a duplicate file on disk.

Soft delete: ``delete_file`` sets ``is_deleted=1`` and records
``deleted_at``.  The file on disk is NOT removed — it can be restored.
``hard_delete_file`` first requires soft-delete, then permanently removes
both the database row and the file from disk.

Listing and search both return only non-deleted entries.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
import hashlib
import logging
import os
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, Iterator
import uuid

from deeptutor.services.path_service import get_path_service

logger = logging.getLogger(__name__)

# Default subpath under the user root for library files
_LIBRARY_FILES_SUBDIR = ("workspace", "library", "files")
_LIBRARY_DB_SUBDIR = ("workspace", "library")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Schema migrations
# ---------------------------------------------------------------------------

_SCHEMA_VERSION = 1

_MIGRATIONS: list[tuple[int, str]] = [
    # (version, sql)
]


def _current_schema_version(conn) -> int:
    try:
        row = conn.execute("PRAGMA user_version").fetchone()
        return row[0] if row else 0
    except Exception:
        return 0


def _run_migrations(conn) -> None:
    version = _current_schema_version(conn)
    for target_version, sql in _MIGRATIONS:
        if target_version <= version:
            continue
        conn.executescript(sql)
    conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")


# ---------------------------------------------------------------------------
# FileLibraryStore
# ---------------------------------------------------------------------------


class FileLibraryStore:
    """Persistent file library store.

    Stores file metadata in a SQLite database and files on disk under a
    configurable root directory.

    Parameters
    ----------
    db_path : Path
        Path to the SQLite database file.
    root : Path, optional
        Root directory for stored files.  Defaults to
        ``data/user/workspace/library/files`` under the path service root.
    """

    def __init__(self, db_path: Path, root: Path | None = None) -> None:
        if root is None:
            root = get_path_service().get_user_root().joinpath(*_LIBRARY_FILES_SUBDIR).resolve()
        self._root = root
        self._db_path = db_path
        # Serializes the check-then-write-then-insert sequence in
        # _add_file_sync so concurrent uploads of identical content cannot
        # both miss the dedup lookup and create duplicate rows/files.
        self._add_lock = threading.Lock()
        self._init_db()

    # ------------------------------------------------------------------
    # Database helpers
    # ------------------------------------------------------------------

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:

        conn = sqlite3.connect(str(self._db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:

        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS library_files (
                    id TEXT PRIMARY KEY,
                    sha256 TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    mime_type TEXT NOT NULL DEFAULT '',
                    size_bytes INTEGER NOT NULL DEFAULT 0,
                    library_path TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    is_deleted INTEGER NOT NULL DEFAULT 0,
                    deleted_at REAL
                )
                """
            )
            # A plain index isn't enough to prevent duplicate active rows for
            # the same content — enforce it at the DB layer too (belt and
            # suspenders alongside the _add_lock in _add_file_sync, which is
            # the primary guard within a single process).
            conn.execute("DROP INDEX IF EXISTS idx_library_sha256")
            try:
                conn.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_library_sha256_active "
                    "ON library_files(sha256) WHERE is_deleted = 0"
                )
            except sqlite3.IntegrityError:
                logger.warning(
                    "Could not create unique active-sha256 index on %s: "
                    "duplicate active rows already exist",
                    self._db_path,
                )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_library_is_deleted ON library_files(is_deleted)"
            )
            conn.commit()

    # ------------------------------------------------------------------
    # File I/O helpers
    # ------------------------------------------------------------------

    def _file_path(self, library_path: str) -> Path:
        """Return the absolute Path for a relative library_path."""
        return (self._root / library_path).resolve()

    def _ensure_root(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)

    def _write_file(self, library_path: str, data: bytes) -> None:
        target = self._file_path(library_path)
        self._ensure_root()
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

    def _delete_file(self, library_path: str) -> None:
        target = self._file_path(library_path)
        if target.exists():
            try:
                target.unlink()
            except OSError as exc:
                logger.warning("failed to delete library file %s: %s", target, exc)
            # Try to remove now-empty parent dirs up to (but not including) root
            try:
                for parent in target.parents:
                    if parent == self._root or not parent.is_relative_to(self._root):
                        break
                    if parent.is_dir() and not any(parent.iterdir()):
                        parent.rmdir()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Public API — add / get / delete
    # ------------------------------------------------------------------

    async def add_file(
        self,
        *,
        data: bytes,
        filename: str,
        mime_type: str = "",
    ) -> dict[str, Any]:
        """Add a file to the library, deduplicating by content hash.

        If an active entry with the same SHA-256 already exists, returns that
        entry without storing a duplicate.  Otherwise stores the file on disk
        and creates a new database entry.
        """
        return await asyncio.to_thread(self._add_file_sync, data, filename, mime_type)

    def _add_file_sync(
        self,
        data: bytes,
        filename: str,
        mime_type: str,
    ) -> dict[str, Any]:

        sha = _sha256(data)
        now = time.time()

        with self._add_lock, self._connect() as conn:
            # Check for existing active entry with same hash
            existing = conn.execute(
                "SELECT * FROM library_files WHERE sha256 = ? AND is_deleted = 0",
                (sha,),
            ).fetchone()
            if existing is not None:
                return self._row_to_entry(dict(existing))

            # Generate unique id and path
            file_id = str(uuid.uuid4())
            ext = Path(filename).suffix or ""
            library_path = f"{file_id}{ext}"

            # Ensure directory exists and write atomically
            self._ensure_root()
            self._write_file(library_path, data)

            try:
                conn.execute(
                    """
                    INSERT INTO library_files
                        (id, sha256, filename, mime_type, size_bytes, library_path,
                         created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (file_id, sha, filename, mime_type, len(data), library_path, now, now),
                )
                conn.commit()
            except sqlite3.IntegrityError:
                # Lost a race against the partial unique index — the
                # in-process _add_lock only serializes this process, so a
                # second worker process could still get here first. Discard
                # the file we just wrote and return the winning entry.
                self._delete_file(library_path)
                winner = conn.execute(
                    "SELECT * FROM library_files WHERE sha256 = ? AND is_deleted = 0",
                    (sha,),
                ).fetchone()
                if winner is not None:
                    return self._row_to_entry(dict(winner))
                raise

            return {
                "id": file_id,
                "sha256": sha,
                "filename": filename,
                "mime_type": mime_type,
                "size_bytes": len(data),
                "library_path": library_path,
                "created_at": now,
                "updated_at": now,
                "is_deleted": False,
                "deleted_at": None,
            }

    async def get_file(self, file_id: str) -> dict[str, Any] | None:
        """Return the entry for *file_id*, or None if not found."""
        return await asyncio.to_thread(self._get_file_sync, file_id)

    def _get_file_sync(self, file_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM library_files WHERE id = ?",
                (file_id,),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_entry(dict(row))

    async def delete_file(self, file_id: str) -> bool:
        """Soft-delete a library entry (sets is_deleted=1)."""
        return await asyncio.to_thread(self._delete_file_sync, file_id)

    def _delete_file_sync(self, file_id: str) -> bool:
        now = time.time()
        with self._connect() as conn:
            # Idempotent: return True whether the file was freshly deleted or already deleted.
            exists = conn.execute("SELECT 1 FROM library_files WHERE id = ?", (file_id,)).fetchone()
            if exists is None:
                return False
            conn.execute(
                "UPDATE library_files SET is_deleted = 1, deleted_at = ?, updated_at = ? WHERE id = ? AND is_deleted = 0",
                (now, now, file_id),
            )
            conn.commit()
            return True

    async def hard_delete_file(self, file_id: str) -> bool:
        """Permanently delete — only succeeds for already-soft-deleted entries."""
        return await asyncio.to_thread(self._hard_delete_file_sync, file_id)

    def _hard_delete_file_sync(self, file_id: str) -> bool:
        with self._connect() as conn:
            # Must be soft-deleted first
            row = conn.execute(
                "SELECT library_path FROM library_files WHERE id = ? AND is_deleted = 1",
                (file_id,),
            ).fetchone()
            if row is None:
                return False

            library_path = row["library_path"]

            # Delete from DB
            conn.execute("DELETE FROM library_files WHERE id = ?", (file_id,))
            conn.commit()

        # Delete file from disk (outside the with-block so we don't hold the conn)
        self._delete_file(library_path)
        return True

    async def restore_file(self, file_id: str) -> bool:
        """Restore a soft-deleted entry (clears is_deleted)."""
        return await asyncio.to_thread(self._restore_file_sync, file_id)

    def _restore_file_sync(self, file_id: str) -> bool:
        now = time.time()
        with self._connect() as conn:
            # Idempotent: return True if the file exists (whether already active or restored).
            exists = conn.execute("SELECT 1 FROM library_files WHERE id = ?", (file_id,)).fetchone()
            if exists is None:
                return False
            conn.execute(
                "UPDATE library_files SET is_deleted = 0, deleted_at = NULL, updated_at = ? WHERE id = ? AND is_deleted = 1",
                (now, file_id),
            )
            conn.commit()
            return True

    # ------------------------------------------------------------------
    # Listing and search
    # ------------------------------------------------------------------

    async def list_files(
        self,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List active library entries, newest first."""
        return await asyncio.to_thread(self._list_files_sync, limit, offset)

    def _list_files_sync(self, limit: int, offset: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM library_files
                WHERE is_deleted = 0
                ORDER BY created_at DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
            return [self._row_to_entry(dict(row)) for row in rows]

    async def search_files(self, query: str) -> list[dict[str, Any]]:
        """Search library entries by filename (case-insensitive substring)."""
        return await asyncio.to_thread(self._search_files_sync, query.strip())

    def _search_files_sync(self, query: str) -> list[dict[str, Any]]:
        if not query:
            return []
        pattern = f"%{query}%"
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM library_files
                WHERE is_deleted = 0 AND filename LIKE ?
                ORDER BY created_at DESC, id DESC
                """,
                (pattern,),
            ).fetchall()
            return [self._row_to_entry(dict(row)) for row in rows]

    # ------------------------------------------------------------------
    # Path resolution
    # ------------------------------------------------------------------

    def resolve_path(self, file_id: str) -> Path | None:
        """Return the absolute Path to the stored file, or None if not found / deleted."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT library_path FROM library_files WHERE id = ? AND is_deleted = 0",
                (file_id,),
            ).fetchone()
            if row is None:
                return None
            path = self._file_path(row["library_path"])
            if not path.is_file():
                return None
            return path

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_entry(row: dict[str, Any]) -> dict[str, Any]:
        """Convert a sqlite3.Row dict to a clean entry dict."""
        return {
            "id": row["id"],
            "sha256": row["sha256"],
            "filename": row["filename"],
            "mime_type": row["mime_type"],
            "size_bytes": row["size_bytes"],
            "library_path": row["library_path"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "is_deleted": bool(row["is_deleted"]),
            "deleted_at": row["deleted_at"],
        }


# ---------------------------------------------------------------------------
# Process-wide singleton
# ---------------------------------------------------------------------------

_instances: dict[str, FileLibraryStore] = {}


def get_file_library_store() -> FileLibraryStore:
    """Return the FileLibraryStore singleton scoped to the current user.

    ``get_path_service().get_user_root()`` is resolved on every call (it is
    request-scoped via a contextvar — see ``deeptutor.multi_user.paths``) and
    the instance cache is keyed by that resolved root, mirroring
    ``get_attachment_store`` in ``attachment_store.py``. Caching under a
    constant key here would pin every user to whichever user's request
    happened to populate the cache first.
    """
    user_root = get_path_service().get_user_root()
    key = str(user_root)
    if key not in _instances:
        db_dir = user_root.joinpath(*_LIBRARY_DB_SUBDIR)
        db_dir.mkdir(parents=True, exist_ok=True)
        db_path = db_dir / "library.db"
        root = user_root.joinpath(*_LIBRARY_FILES_SUBDIR).resolve()
        _instances[key] = FileLibraryStore(db_path=db_path, root=root)
    return _instances[key]


def reset_file_library_store() -> None:
    """Clear the process-wide singleton (for testing)."""
    _instances.clear()
