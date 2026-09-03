"""One-way workspace migration for the Mastery Path V2 store.

V1 kept its SQLite database and lazily imported JSON files directly under the
workspace ``learning`` directory.  V2 owns a dedicated ``learning/mastery``
directory.  The migration deliberately archives first, copies the archived
database into the V2 location, and only then removes the live V1 artifacts.

Nothing in this module ever reads an existing ``learning/archive`` directory.
It is a recovery surface for humans, not a runtime fallback.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import threading
import time
import uuid

from deeptutor.services.file_io import atomic_write_text

logger = logging.getLogger(__name__)

_migration_lock = threading.RLock()
_V1_DB_NAME = "mastery.sqlite3"
_V2_DIR_NAME = "mastery"
_ARCHIVE_DIR_NAME = "archive"
_MANIFEST_NAME = "migration.json"
_LOCK_NAME = ".mastery-v2-migration.lock"
_STAGING_NAME = ".v1-migration-in-progress"
_COUNTED_TABLES = (
    "mastery_paths",
    "mastery_path_sessions",
    "mastery_events",
    "mastery_interactions",
    "mastery_path_leases",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _checkpoint_database(path: Path) -> None:
    """Fold a V1 WAL into the database before taking the archive copy."""

    if not path.exists():
        logger.debug("Mastery migration checkpoint skipped: database missing path=%s", path)
        return
    conn = sqlite3.connect(path, timeout=30.0)
    try:
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
        conn.commit()
    finally:
        conn.close()


def _row_counts(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        existing = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        return {
            table: int(
                conn.execute(
                    f'SELECT COUNT(*) FROM "{table}"'  # nosec B608 - a table constant
                ).fetchone()[0]
            )
            for table in _COUNTED_TABLES
            if table in existing
        }
    finally:
        conn.close()


def _copy_atomic(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.parent / f".{target.name}.tmp-{uuid.uuid4().hex}"
    try:
        shutil.copy2(source, temp)
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)


def _unique_archive_dir(archive_root: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    candidate = archive_root / f"v1-{stamp}"
    suffix = 1
    while candidate.exists():
        candidate = archive_root / f"v1-{stamp}-{suffix}"
        suffix += 1
    return candidate


@contextmanager
def _process_lock(root: Path):
    """Serialize migration across app/server processes, not just threads."""

    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / _LOCK_NAME
    with lock_path.open("a+b") as handle:
        if sys.platform == "win32":  # pragma: no cover - exercised by Windows builds
            import msvcrt

            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _copy_json_archive(source: Path, archive_json_root: Path) -> None:
    """Archive a live JSON without overwriting an older lazy-import copy."""

    archive_json_root.mkdir(parents=True, exist_ok=True)
    target = archive_json_root / source.name
    if target.exists() and _sha256(target) != _sha256(source):
        target = archive_json_root / "live" / source.name
        logger.info(
            "Mastery migration preserved conflicting legacy JSON source=%s target=%s",
            source,
            target,
        )
    if not target.exists():
        _copy_atomic(source, target)
        logger.info("Mastery migration archived legacy JSON source=%s target=%s", source, target)
    else:
        logger.debug("Mastery migration JSON archive already exists target=%s", target)


def _finish_staging_archive(archive_root: Path, staging: Path) -> None:
    if not staging.exists():
        logger.debug("Mastery migration finalization skipped: staging directory missing")
        return
    final_dir = _unique_archive_dir(archive_root)
    os.replace(staging, final_dir)
    logger.info("Mastery migration archive finalized target=%s", final_dir)


def mastery_v2_root(learning_root: Path) -> Path:
    """Where the V2 store lives under *learning_root*, creating nothing.

    Split out of the migration so a caller can ask "is there a mastery store
    at all?" without running one. :func:`prepare_mastery_v2_root` is the only
    thing allowed to create or move files.
    """

    return Path(learning_root) / _V2_DIR_NAME


def _prepare_mastery_v2_root(learning_root: Path) -> Path:
    """Return the V2 store root, archiving/copying a V1 workspace once.

    The migration owns a process lock and a deterministic staging archive.
    Consequently a crash can leave both the source and target in place; the
    next startup resumes idempotently instead of trusting a partially-created
    V2 directory.  Finalized archives are never enumerated or read.
    """

    root = Path(learning_root)
    v2_root = mastery_v2_root(root)
    v2_db = v2_root / _V1_DB_NAME

    with _migration_lock:
        with _process_lock(root):
            legacy_db = root / _V1_DB_NAME
            legacy_json_dir = root / ".legacy"
            live_json = sorted(path for path in root.glob("*.json") if path.is_file())
            has_legacy_json = legacy_json_dir.is_dir() and any(
                path.is_file() for path in legacy_json_dir.rglob("*")
            )
            archive_root = root / _ARCHIVE_DIR_NAME
            staging = archive_root / _STAGING_NAME
            has_v1_artifacts = legacy_db.exists() or has_legacy_json or bool(live_json)

            if not has_v1_artifacts and not staging.exists():
                v2_root.mkdir(parents=True, exist_ok=True)
                logger.debug("Mastery migration skipped: no V1 artifacts source=%s", root)
                return v2_root

            archive_root.mkdir(parents=True, exist_ok=True)
            if staging.exists():
                logger.info("Mastery migration resuming staged run source=%s", root)
            else:
                logger.info("Mastery migration starting source=%s target=%s", root, v2_root)
            staging.mkdir(parents=True, exist_ok=True)
            started_at = time.time()
            archived_db = staging / _V1_DB_NAME

            if legacy_db.exists() and not archived_db.exists():
                _checkpoint_database(legacy_db)
                _copy_atomic(legacy_db, archived_db)
                logger.info(
                    "Mastery migration archived V1 database source=%s target=%s",
                    legacy_db,
                    archived_db,
                )
            if not v2_db.exists() and archived_db.exists():
                _copy_atomic(archived_db, v2_db)
                logger.info(
                    "Mastery migration seeded V2 database source=%s target=%s",
                    archived_db,
                    v2_db,
                )
            else:
                v2_root.mkdir(parents=True, exist_ok=True)
                logger.debug("Mastery migration retained existing V2 database target=%s", v2_db)

            archive_json_dir = staging / "legacy-json"
            if has_legacy_json:
                shutil.copytree(
                    legacy_json_dir,
                    archive_json_dir,
                    dirs_exist_ok=True,
                )
                logger.info(
                    "Mastery migration archived lazy-import JSON source=%s target=%s",
                    legacy_json_dir,
                    archive_json_dir,
                )

            # Import directly through the store boundary so migration never
            # duplicates the schema or aggregate serialization rules.  Each
            # source is archived before it is read into V2 and remains live
            # until every import and the manifest have committed.
            if live_json:
                from deeptutor.learning.storage import LearningStore

                target_store = LearningStore(root=v2_root)
                for source in live_json:
                    _copy_json_archive(source, archive_json_dir)
                    imported = target_store.import_legacy_json(source, archive=False)
                    outcome = "imported" if imported else "skipped_or_quarantined"
                    logger.info(
                        "Mastery migration processed live JSON source=%s outcome=%s",
                        source,
                        outcome,
                    )

            legacy_json_count = (
                sum(1 for path in archive_json_dir.rglob("*") if path.is_file())
                if archive_json_dir.exists()
                else 0
            )
            manifest = {
                "format_version": 2,
                "migration": "mastery-path-v1-to-v2",
                "migrated_at": started_at,
                "source": str(root),
                "target": str(v2_root),
                "database_sha256": _sha256(archived_db) if archived_db.exists() else "",
                "row_counts": _row_counts(v2_db),
                "legacy_json_count": legacy_json_count,
            }
            atomic_write_text(
                staging / _MANIFEST_NAME,
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            )
            logger.info(
                "Mastery migration manifest written path=%s row_counts=%s legacy_json_count=%d",
                staging / _MANIFEST_NAME,
                manifest["row_counts"],
                legacy_json_count,
            )

            # Archive + target + manifest are durable. Remove only the exact
            # V1 artifacts, then atomically publish the completed archive.
            legacy_db.unlink(missing_ok=True)
            (root / f"{_V1_DB_NAME}-wal").unlink(missing_ok=True)
            (root / f"{_V1_DB_NAME}-shm").unlink(missing_ok=True)
            for source in live_json:
                source.unlink(missing_ok=True)
            if legacy_json_dir.exists():
                shutil.rmtree(legacy_json_dir)
            _finish_staging_archive(archive_root, staging)
            logger.info("Mastery migration completed source=%s target=%s", root, v2_root)
            return v2_root


def prepare_mastery_v2_root(learning_root: Path) -> Path:
    """Return the V2 store root and log any migration crash before re-raising."""

    try:
        return _prepare_mastery_v2_root(learning_root)
    except Exception:
        logger.exception("Mastery migration failed source=%s", learning_root)
        raise


__all__ = ["mastery_v2_root", "prepare_mastery_v2_root"]
