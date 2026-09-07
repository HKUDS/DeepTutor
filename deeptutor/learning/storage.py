"""Transactional persistence for Mastery Path aggregates.

The original implementation rewrote one JSON file per path.  A process-local
lock made each individual replace atomic, but two sessions could still load
the same revision and silently overwrite one another.  This module keeps the
public ``LearningStore`` API while moving the source of truth to a small,
workspace-scoped SQLite database with real compare-and-swap semantics.

Legacy ``<path-id>.json`` files are imported lazily and archived under
``.legacy/``.  ``LearningProgress.pending_question`` remains synchronized for
compatibility while the durable ``mastery_interactions`` table owns the
question lifecycle and idempotency record.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
import hashlib
import json
import logging
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, TypeVar

from pydantic import ValidationError

from deeptutor.learning.models import (
    InteractionStatus,
    LearningProgress,
    MasteryEvent,
    MasteryInteraction,
    MasteryPathLease,
    MasteryTopic,
    TopicMetadata,
    TopicSource,
)
from deeptutor.services.file_io import atomic_write_text as _atomic_write_text
from deeptutor.services.path_service import get_path_service

logger = logging.getLogger(__name__)

_schema_lock = threading.RLock()
_initialized_db_paths: set[Path] = set()
_T = TypeVar("_T")
_ACTIVE_INTERACTION_STATES = (
    InteractionStatus.REGISTERED.value,
    InteractionStatus.AWAITING_INPUT.value,
    InteractionStatus.ANSWERED.value,
)
_ALLOWED_INTERACTION_TRANSITIONS: dict[InteractionStatus, frozenset[InteractionStatus]] = {
    InteractionStatus.REGISTERED: frozenset(InteractionStatus),
    InteractionStatus.AWAITING_INPUT: frozenset(
        {
            InteractionStatus.AWAITING_INPUT,
            InteractionStatus.ANSWERED,
            InteractionStatus.GRADED,
            InteractionStatus.ABANDONED,
        }
    ),
    InteractionStatus.ANSWERED: frozenset(
        {
            InteractionStatus.ANSWERED,
            InteractionStatus.GRADED,
            InteractionStatus.ABANDONED,
        }
    ),
    InteractionStatus.GRADED: frozenset({InteractionStatus.GRADED}),
    InteractionStatus.ABANDONED: frozenset({InteractionStatus.ABANDONED}),
}


class LearningStoreError(RuntimeError):
    """Base error for durable mastery state operations."""


class LearningConflictError(LearningStoreError):
    """Raised when a stale aggregate revision attempts to overwrite a path."""

    def __init__(self, path_id: str, expected: int, actual: int) -> None:
        self.path_id = path_id
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"Mastery path {path_id!r} changed concurrently "
            f"(expected revision {expected}, current revision {actual})"
        )


class PathLeaseConflictError(LearningStoreError):
    """Raised when another turn already owns a path's mutation lease."""

    def __init__(self, lease: MasteryPathLease) -> None:
        self.lease = lease
        super().__init__(
            f"Mastery path {lease.path_id!r} is active in session {lease.session_id!r} "
            f"(turn {lease.turn_id!r})"
        )


class LearningTransaction:
    """Unit-of-work over one locked ``LearningProgress`` aggregate.

    Domain services mutate :attr:`progress`, call :meth:`touch`, update any
    interaction rows, and enqueue public events.  The store commits all of it
    with one revision bump or rolls everything back.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        progress: LearningProgress,
        *,
        created: bool,
    ) -> None:
        self._conn = conn
        self.progress = progress
        self.base_revision = int(progress.version)
        self.changed = created
        self._events: list[tuple[str, dict[str, Any], str, str]] = []
        if created:
            self.emit("path.created", {})

    def touch(self) -> None:
        self.changed = True

    def emit(
        self,
        event_type: str,
        payload: dict[str, Any] | None = None,
        *,
        session_id: str = "",
        turn_id: str = "",
    ) -> None:
        event_name = str(event_type or "").strip()
        if not event_name:
            raise ValueError("event_type must not be empty")
        self.changed = True
        self._events.append(
            (event_name, dict(payload or {}), str(session_id or ""), str(turn_id or ""))
        )

    @property
    def events(self) -> list[tuple[str, dict[str, Any], str, str]]:
        return list(self._events)

    @staticmethod
    def _interaction_from_row(row: sqlite3.Row | None) -> MasteryInteraction | None:
        if row is None:
            return None
        return MasteryInteraction(
            interaction_id=row["interaction_id"],
            path_id=row["path_id"],
            question=json.loads(row["question_json"]),
            status=InteractionStatus(row["status"]),
            session_id=row["session_id"] or "",
            turn_id=row["turn_id"] or "",
            user_answer=row["user_answer"] or "",
            result=json.loads(row["result_json"] or "{}"),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )

    def get_interaction(self, interaction_id: str) -> MasteryInteraction | None:
        row = self._conn.execute(
            "SELECT * FROM mastery_interactions WHERE interaction_id = ? AND path_id = ?",
            (str(interaction_id), self.progress.book_id),
        ).fetchone()
        return self._interaction_from_row(row)

    def active_interaction(self) -> MasteryInteraction | None:
        placeholders = ",".join("?" for _ in _ACTIVE_INTERACTION_STATES)
        row = self._conn.execute(
            f"""
            SELECT * FROM mastery_interactions
            WHERE path_id = ? AND status IN ({placeholders})
            ORDER BY created_at DESC LIMIT 1
            """,  # nosec B608 - placeholders is a generated "?,?" list; every value is bound
            (self.progress.book_id, *_ACTIVE_INTERACTION_STATES),
        ).fetchone()
        return self._interaction_from_row(row)

    def put_interaction(self, interaction: MasteryInteraction) -> None:
        if interaction.path_id != self.progress.book_id:
            raise ValueError("interaction path_id does not match transaction path")
        existing = self._conn.execute(
            "SELECT path_id, status FROM mastery_interactions WHERE interaction_id = ?",
            (interaction.interaction_id,),
        ).fetchone()
        if existing is not None and str(existing["path_id"]) != interaction.path_id:
            raise ValueError(
                f"interaction_id {interaction.interaction_id!r} already belongs to another path"
            )
        if existing is not None:
            current_status = InteractionStatus(existing["status"])
            if interaction.status not in _ALLOWED_INTERACTION_TRANSITIONS[current_status]:
                raise LearningStoreError(
                    f"Invalid mastery interaction transition: "
                    f"{current_status.value} -> {interaction.status.value}"
                )
        now = time.time()
        interaction.updated_at = now
        self._conn.execute(
            """
            INSERT INTO mastery_interactions (
                interaction_id, path_id, status, question_json, session_id,
                turn_id, user_answer, result_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(interaction_id) DO UPDATE SET
                status = excluded.status,
                question_json = excluded.question_json,
                session_id = excluded.session_id,
                turn_id = excluded.turn_id,
                user_answer = excluded.user_answer,
                result_json = excluded.result_json,
                updated_at = excluded.updated_at
            """,
            (
                interaction.interaction_id,
                interaction.path_id,
                interaction.status.value,
                json.dumps(interaction.question.model_dump(mode="json"), ensure_ascii=False),
                interaction.session_id,
                interaction.turn_id,
                interaction.user_answer,
                json.dumps(interaction.result, ensure_ascii=False),
                interaction.created_at,
                now,
            ),
        )
        self.touch()

    def abandon_active_interactions(self) -> int:
        placeholders = ",".join("?" for _ in _ACTIVE_INTERACTION_STATES)
        cursor = self._conn.execute(
            f"""
            UPDATE mastery_interactions
            SET status = ?, updated_at = ?
            WHERE path_id = ? AND status IN ({placeholders})
            """,  # nosec B608 - placeholders is a generated "?,?" list; every value is bound
            (
                InteractionStatus.ABANDONED.value,
                time.time(),
                self.progress.book_id,
                *_ACTIVE_INTERACTION_STATES,
            ),
        )
        if cursor.rowcount:
            self.touch()
        return int(cursor.rowcount)

    def put_topic(self, metadata: TopicMetadata, sources: list[TopicSource]) -> None:
        """Persist product metadata and the ordered source set in this unit."""

        if metadata.path_id != self.progress.book_id:
            raise ValueError("topic metadata path_id does not match transaction path")
        now = time.time()
        metadata.updated_at = now
        self._conn.execute(
            """
            INSERT INTO mastery_topic_meta (
                path_id, goal, description, emoji, map_seed, status,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(path_id) DO UPDATE SET
                goal = excluded.goal,
                description = excluded.description,
                emoji = excluded.emoji,
                map_seed = excluded.map_seed,
                status = excluded.status,
                updated_at = excluded.updated_at
            """,
            (
                metadata.path_id,
                metadata.goal,
                metadata.description,
                metadata.emoji,
                int(metadata.map_seed),
                metadata.status,
                metadata.created_at,
                now,
            ),
        )
        self._conn.execute(
            "DELETE FROM mastery_topic_sources WHERE path_id = ?",
            (metadata.path_id,),
        )
        for position, source in enumerate(sorted(sources, key=lambda item: item.position)):
            self._conn.execute(
                """
                INSERT INTO mastery_topic_sources (
                    source_id, path_id, kind, external_id, label, excerpt,
                    position, available, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source.id,
                    metadata.path_id,
                    source.kind.value,
                    source.source_id,
                    source.label,
                    source.excerpt,
                    position,
                    int(source.available),
                    json.dumps(source.metadata, ensure_ascii=False),
                    source.created_at,
                ),
            )
        self.touch()
        self.emit(
            "topic.updated",
            {"source_count": len(sources), "status": metadata.status},
        )


class LearningStore:
    """Workspace-scoped transactional store for Mastery Path state."""

    _DB_FILENAME = "mastery.sqlite3"

    def __init__(self, root: Path | None = None) -> None:
        if root is None:
            # Explicit roots are used by tests and SDK callers as direct store
            # directories.  The app-owned default is the only location that
            # participates in the one-way workspace V1 → V2 migration.
            from deeptutor.learning.migration import prepare_mastery_v2_root

            learning_root = get_path_service().get_workspace_dir() / "learning"
            self._root = prepare_mastery_v2_root(learning_root)
        else:
            self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._initialized = False
        self._ensure_initialized()

    @property
    def db_path(self) -> Path:
        return Path(self._root) / self._DB_FILENAME

    @property
    def event_scope(self) -> str:
        """Stable workspace identity used by the process-local wake-up hub."""

        return str(Path(self._root).resolve())

    def _path(self, book_id: str) -> Path:
        """Return the legacy JSON location after validating the public id."""
        self._validate_id(book_id)
        return Path(self._root) / f"{book_id}.json"

    @staticmethod
    def _validate_id(book_id: str) -> str:
        value = str(book_id or "")
        if not value or "/" in value or "\\" in value or ".." in value or ":" in value:
            raise ValueError(f"Invalid book_id: {book_id!r}")
        return value

    def _ensure_initialized(self) -> None:
        db_path = self.db_path.resolve()
        if self.db_path.exists() and (
            getattr(self, "_initialized", False) or db_path in _initialized_db_paths
        ):
            self._initialized = True
            return
        with _schema_lock:
            if self.db_path.exists() and db_path in _initialized_db_paths:
                self._initialized = True
                return
            Path(self._root).mkdir(parents=True, exist_ok=True)
            with self._connect(initialize=False) as conn:
                conn.executescript(
                    """
                    PRAGMA journal_mode = WAL;

                    CREATE TABLE IF NOT EXISTS mastery_paths (
                        path_id TEXT PRIMARY KEY,
                        state_json TEXT NOT NULL,
                        revision INTEGER NOT NULL,
                        created_at REAL NOT NULL,
                        updated_at REAL NOT NULL,
                        owner_session_id TEXT NOT NULL DEFAULT ''
                    );

                    -- Membership, not history: at most one row per session.
                    -- The unique index below is what makes a conversation
                    -- claimed by two paths structurally impossible.
                    CREATE TABLE IF NOT EXISTS mastery_path_sessions (
                        path_id TEXT NOT NULL REFERENCES mastery_paths(path_id) ON DELETE CASCADE,
                        session_id TEXT NOT NULL,
                        created_at REAL NOT NULL,
                        last_seen_at REAL NOT NULL,
                        PRIMARY KEY(path_id, session_id)
                    );
                    CREATE INDEX IF NOT EXISTS idx_mastery_sessions_session
                        ON mastery_path_sessions(session_id, last_seen_at DESC);

                    CREATE TABLE IF NOT EXISTS mastery_interactions (
                        interaction_id TEXT PRIMARY KEY,
                        path_id TEXT NOT NULL REFERENCES mastery_paths(path_id) ON DELETE CASCADE,
                        status TEXT NOT NULL,
                        question_json TEXT NOT NULL,
                        session_id TEXT NOT NULL DEFAULT '',
                        turn_id TEXT NOT NULL DEFAULT '',
                        user_answer TEXT NOT NULL DEFAULT '',
                        result_json TEXT NOT NULL DEFAULT '{}',
                        created_at REAL NOT NULL,
                        updated_at REAL NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_mastery_interactions_path
                        ON mastery_interactions(path_id, created_at DESC);
                    CREATE UNIQUE INDEX IF NOT EXISTS uq_mastery_one_active_interaction
                        ON mastery_interactions(path_id)
                        WHERE status IN ('registered', 'awaiting_input', 'answered');

                    CREATE TABLE IF NOT EXISTS mastery_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        path_id TEXT NOT NULL REFERENCES mastery_paths(path_id) ON DELETE CASCADE,
                        revision INTEGER NOT NULL,
                        event_type TEXT NOT NULL,
                        payload_json TEXT NOT NULL DEFAULT '{}',
                        session_id TEXT NOT NULL DEFAULT '',
                        turn_id TEXT NOT NULL DEFAULT '',
                        created_at REAL NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_mastery_events_path_revision
                        ON mastery_events(path_id, revision, id);

                    CREATE TABLE IF NOT EXISTS mastery_path_leases (
                        path_id TEXT PRIMARY KEY REFERENCES mastery_paths(path_id) ON DELETE CASCADE,
                        session_id TEXT NOT NULL,
                        turn_id TEXT NOT NULL UNIQUE,
                        acquired_at REAL NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS mastery_topic_meta (
                        path_id TEXT PRIMARY KEY REFERENCES mastery_paths(path_id) ON DELETE CASCADE,
                        goal TEXT NOT NULL DEFAULT '',
                        description TEXT NOT NULL DEFAULT '',
                        emoji TEXT NOT NULL DEFAULT '🧭',
                        map_seed INTEGER NOT NULL DEFAULT 0,
                        status TEXT NOT NULL DEFAULT 'active',
                        created_at REAL NOT NULL,
                        updated_at REAL NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS mastery_topic_sources (
                        source_id TEXT PRIMARY KEY,
                        path_id TEXT NOT NULL REFERENCES mastery_paths(path_id) ON DELETE CASCADE,
                        kind TEXT NOT NULL,
                        external_id TEXT NOT NULL DEFAULT '',
                        label TEXT NOT NULL,
                        excerpt TEXT NOT NULL DEFAULT '',
                        position INTEGER NOT NULL DEFAULT 0,
                        available INTEGER NOT NULL DEFAULT 1,
                        metadata_json TEXT NOT NULL DEFAULT '{}',
                        created_at REAL NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_mastery_topic_sources_path
                        ON mastery_topic_sources(path_id, position);
                    """
                )
                self._converge_single_membership(conn)
                # V2 metadata is a persisted part of every topic, not a
                # runtime-only fallback. Existing V1 paths receive neutral,
                # deterministic metadata during schema initialization; their
                # learning state and session bindings remain untouched.
                legacy_topics = conn.execute(
                    """
                    SELECT path_id, created_at, updated_at
                    FROM mastery_paths
                    WHERE path_id NOT IN (SELECT path_id FROM mastery_topic_meta)
                    """
                ).fetchall()
                for row in legacy_topics:
                    path_id = str(row["path_id"])
                    conn.execute(
                        """
                        INSERT INTO mastery_topic_meta (
                            path_id, goal, description, emoji, map_seed, status,
                            created_at, updated_at
                        ) VALUES (?, '', '', '🧭', ?, 'active', ?, ?)
                        """,
                        (
                            path_id,
                            self._default_map_seed(path_id),
                            float(row["created_at"]),
                            float(row["updated_at"]),
                        ),
                    )
                conn.commit()
            self._initialized = True
            _initialized_db_paths.add(db_path)

    @staticmethod
    def _converge_single_membership(conn: sqlite3.Connection) -> None:
        """Bring an existing database onto the one-path-per-conversation rule.

        Two things used to live in ``mastery_path_sessions``: which path a
        conversation is *on*, and which conversation a scratch path belongs
        *to*. Because the second one has to survive, nothing ever deleted a
        row — so a conversation that moved to another path (``mastery_switch``,
        or simply being reopened from another topic's screen) stayed listed
        under the path it had left, and both topics went on claiming it.

        The two are separated here: ownership moves onto the path it is a
        property of, membership keeps only the most recent row per session,
        and a unique index makes the old shape unrepresentable from now on.
        Every step is idempotent, so this runs on each schema initialization.
        """

        columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(mastery_paths)")}
        if "owner_session_id" not in columns:
            conn.execute(
                "ALTER TABLE mastery_paths ADD COLUMN owner_session_id TEXT NOT NULL DEFAULT ''"
            )
        binding_columns = {
            str(row["name"]) for row in conn.execute("PRAGMA table_info(mastery_path_sessions)")
        }
        if "owns_path" in binding_columns:
            # The owning session is the one that created the scratch path, so
            # the earliest claim wins if a database somehow carries several.
            conn.execute(
                """
                UPDATE mastery_paths SET owner_session_id = (
                    SELECT b.session_id FROM mastery_path_sessions b
                    WHERE b.path_id = mastery_paths.path_id AND b.owns_path = 1
                    ORDER BY b.created_at ASC LIMIT 1
                )
                WHERE owner_session_id = '' AND EXISTS (
                    SELECT 1 FROM mastery_path_sessions b
                    WHERE b.path_id = mastery_paths.path_id AND b.owns_path = 1
                )
                """
            )
        conn.execute(
            """
            DELETE FROM mastery_path_sessions
            WHERE rowid NOT IN (
                SELECT rowid FROM (
                    SELECT rowid, ROW_NUMBER() OVER (
                        PARTITION BY session_id ORDER BY last_seen_at DESC, rowid DESC
                    ) AS rank FROM mastery_path_sessions
                ) WHERE rank = 1
            )
            """
        )
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_mastery_sessions_membership
                ON mastery_path_sessions(session_id)
            """
        )

    @contextmanager
    def _connect(self, *, initialize: bool = True) -> Iterator[sqlite3.Connection]:
        if initialize:
            self._ensure_initialized()
        conn = sqlite3.connect(self.db_path, timeout=30.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        try:
            yield conn
        finally:
            conn.close()

    @staticmethod
    def _progress_from_row(row: sqlite3.Row) -> LearningProgress:
        progress = LearningProgress.model_validate(json.loads(row["state_json"]))
        progress.version = int(row["revision"])
        return progress

    @staticmethod
    def _progress_payload(progress: LearningProgress, revision: int, updated_at: float) -> str:
        persisted = progress.model_copy(deep=True)
        persisted.version = revision
        persisted.updated_at = updated_at
        return json.dumps(persisted.model_dump(mode="json"), ensure_ascii=False)

    def _archive_legacy(self, path: Path) -> None:
        if not path.exists():
            return
        archive_dir = Path(self._root) / ".legacy"
        archive_dir.mkdir(parents=True, exist_ok=True)
        target = archive_dir / path.name
        if target.exists():
            target = archive_dir / f"{path.stem}.{int(time.time() * 1000)}{path.suffix}"
        try:
            path.replace(target)
        except OSError:
            # The committed SQLite row remains authoritative.  A later delete
            # removes any unarchived copy so it cannot resurrect the path.
            pass

    @staticmethod
    def _quarantine_failed_legacy(path: Path) -> Path | None:
        failed_dir = path.parent / "archive" / "failed"
        failed_dir.mkdir(parents=True, exist_ok=True)
        target = failed_dir / path.name
        if target.exists():
            target = failed_dir / f"{path.stem}.{int(time.time() * 1000)}{path.suffix}"
        try:
            path.replace(target)
        except OSError:
            logger.exception("Could not quarantine corrupt legacy mastery file %s", path)
            return None
        return target

    def import_legacy_json(self, legacy_path: Path, *, archive: bool = True) -> bool:
        """Import one V1 JSON aggregate into this store exactly once.

        ``legacy_path`` may live outside the store root.  That small public
        boundary lets the workspace migration merge still-live V1 JSON files
        into an already-created V2 database without teaching the migration
        module about the SQLite schema.  The committed row always wins over a
        duplicate JSON file.  ``archive=False`` is reserved for callers that
        have already made their own durable archive copy.

        Returns ``True`` when this call inserted a new aggregate.
        """

        legacy_path = Path(legacy_path)
        if legacy_path.suffix != ".json":
            raise ValueError(f"Legacy mastery path must be a JSON file: {legacy_path}")
        try:
            path_id = self._validate_id(legacy_path.stem)
        except ValueError:
            quarantined = self._quarantine_failed_legacy(legacy_path)
            logger.exception(
                "Rejected legacy mastery file with invalid id path=%s quarantine=%s",
                legacy_path,
                quarantined,
            )
            return False
        if not legacy_path.exists():
            return False
        with self._connect() as conn:
            if conn.execute("SELECT 1 FROM mastery_paths WHERE path_id = ?", (path_id,)).fetchone():
                if archive:
                    self._archive_legacy(legacy_path)
                return False
        try:
            legacy_text = legacy_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            # A concurrent process may have committed and archived the same
            # legacy file after our existence check. Its SQLite row is already
            # authoritative; only fail if neither representation now exists.
            with self._connect() as conn:
                imported = conn.execute(
                    "SELECT 1 FROM mastery_paths WHERE path_id = ?", (path_id,)
                ).fetchone()
            if imported is not None:
                return False
            raise
        except (OSError, UnicodeError):
            quarantined = self._quarantine_failed_legacy(legacy_path)
            logger.exception(
                "Could not read legacy mastery file path=%s quarantine=%s",
                legacy_path,
                quarantined,
            )
            return False
        try:
            data = json.loads(legacy_text)
            progress = LearningProgress.model_validate(data)
            if progress.book_id != path_id:
                raise ValueError(
                    f"Legacy mastery path id mismatch: expected {path_id!r}, "
                    f"got {progress.book_id!r}"
                )
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError):
            quarantined = self._quarantine_failed_legacy(legacy_path)
            logger.exception(
                "Quarantined corrupt legacy mastery file path=%s quarantine=%s",
                legacy_path,
                quarantined,
            )
            return False
        now = time.time()
        revision = max(1, int(progress.version or 0))
        payload = self._progress_payload(progress, revision, now)
        inserted = False
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO mastery_paths (
                        path_id, state_json, revision, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (path_id, payload, revision, progress.created_at, now),
                )
                if conn.execute("SELECT changes()").fetchone()[0]:
                    inserted = True
                    conn.execute(
                        """
                        INSERT INTO mastery_events (
                            path_id, revision, event_type, payload_json, created_at
                        ) VALUES (?, ?, 'path.migrated', '{}', ?)
                        """,
                        (path_id, revision, now),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        if archive:
            self._archive_legacy(legacy_path)
        return inserted

    def _import_legacy_if_needed(self, book_id: str) -> None:
        path_id = self._validate_id(book_id)
        self.import_legacy_json(self._path(path_id))

    def load(self, book_id: str) -> LearningProgress | None:
        path_id = self._validate_id(book_id)
        self._import_legacy_if_needed(path_id)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM mastery_paths WHERE path_id = ?", (path_id,)
            ).fetchone()
        return self._progress_from_row(row) if row is not None else None

    def save(self, progress: LearningProgress) -> None:
        path_id = self._validate_id(progress.book_id)
        self._import_legacy_if_needed(path_id)
        now = time.time()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT revision, created_at FROM mastery_paths WHERE path_id = ?",
                    (path_id,),
                ).fetchone()
                if row is None:
                    if int(progress.version) != 0:
                        raise LearningConflictError(path_id, int(progress.version), 0)
                    revision = 1
                    conn.execute(
                        """
                        INSERT INTO mastery_paths (
                            path_id, state_json, revision, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            path_id,
                            self._progress_payload(progress, revision, now),
                            revision,
                            progress.created_at,
                            now,
                        ),
                    )
                    event_type = "path.created"
                else:
                    actual = int(row["revision"])
                    expected = int(progress.version)
                    if actual != expected:
                        raise LearningConflictError(path_id, expected, actual)
                    revision = actual + 1
                    cursor = conn.execute(
                        """
                        UPDATE mastery_paths
                        SET state_json = ?, revision = ?, updated_at = ?
                        WHERE path_id = ? AND revision = ?
                        """,
                        (
                            self._progress_payload(progress, revision, now),
                            revision,
                            now,
                            path_id,
                            expected,
                        ),
                    )
                    if cursor.rowcount != 1:
                        current = conn.execute(
                            "SELECT revision FROM mastery_paths WHERE path_id = ?", (path_id,)
                        ).fetchone()
                        raise LearningConflictError(
                            path_id, expected, int(current["revision"]) if current else 0
                        )
                    event_type = "path.saved"
                conn.execute(
                    """
                    INSERT INTO mastery_events (
                        path_id, revision, event_type, payload_json, created_at
                    ) VALUES (?, ?, ?, '{}', ?)
                    """,
                    (path_id, revision, event_type, now),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        progress.version = revision
        progress.updated_at = now
        from deeptutor.learning.event_hub import publish_topic_signal

        publish_topic_signal(
            path_id,
            revision,
            event_type,
            scope=self.event_scope,
        )

    @contextmanager
    def transaction(
        self,
        book_id: str,
        *,
        create: bool = False,
    ) -> Iterator[LearningTransaction]:
        """Lock one path, run a unit of work, and commit one revision.

        ``BEGIN IMMEDIATE`` serializes writers before state is read.  The final
        update still carries a revision predicate so CAS remains an explicit,
        testable invariant rather than an incidental property of SQLite.
        """
        path_id = self._validate_id(book_id)
        self._import_legacy_if_needed(path_id)
        committed_revision: int | None = None
        committed_reason = "topic.changed"
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            tx: LearningTransaction | None = None
            try:
                row = conn.execute(
                    "SELECT * FROM mastery_paths WHERE path_id = ?", (path_id,)
                ).fetchone()
                created = row is None
                if created:
                    if not create:
                        raise KeyError(path_id)
                    progress = LearningProgress(book_id=path_id)
                    conn.execute(
                        """
                        INSERT INTO mastery_paths (
                            path_id, state_json, revision, created_at, updated_at
                        ) VALUES (?, ?, 0, ?, ?)
                        """,
                        (
                            path_id,
                            self._progress_payload(progress, 0, progress.updated_at),
                            progress.created_at,
                            progress.updated_at,
                        ),
                    )
                else:
                    progress = self._progress_from_row(row)
                tx = LearningTransaction(conn, progress, created=created)
                yield tx
                if tx.changed:
                    now = time.time()
                    revision = tx.base_revision + 1
                    cursor = conn.execute(
                        """
                        UPDATE mastery_paths
                        SET state_json = ?, revision = ?, updated_at = ?
                        WHERE path_id = ? AND revision = ?
                        """,
                        (
                            self._progress_payload(tx.progress, revision, now),
                            revision,
                            now,
                            path_id,
                            tx.base_revision,
                        ),
                    )
                    if cursor.rowcount != 1:
                        current = conn.execute(
                            "SELECT revision FROM mastery_paths WHERE path_id = ?", (path_id,)
                        ).fetchone()
                        raise LearningConflictError(
                            path_id,
                            tx.base_revision,
                            int(current["revision"]) if current else 0,
                        )
                    for event_type, payload, session_id, turn_id in tx.events:
                        conn.execute(
                            """
                            INSERT INTO mastery_events (
                                path_id, revision, event_type, payload_json,
                                session_id, turn_id, created_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                path_id,
                                revision,
                                event_type,
                                json.dumps(payload, ensure_ascii=False),
                                session_id,
                                turn_id,
                                now,
                            ),
                        )
                    committed_revision = revision
                    if tx.events:
                        committed_reason = tx.events[-1][0]
                    tx.progress.version = revision
                    tx.progress.updated_at = now
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        if committed_revision is not None:
            from deeptutor.learning.event_hub import publish_topic_signal

            publish_topic_signal(
                path_id,
                committed_revision,
                committed_reason,
                scope=self.event_scope,
            )

    def mutate(
        self,
        book_id: str,
        mutation: Callable[[LearningTransaction], _T],
        *,
        create: bool = False,
    ) -> tuple[LearningProgress, _T]:
        with self.transaction(book_id, create=create) as tx:
            result = mutation(tx)
        return tx.progress, result

    def delete(self, book_id: str) -> None:
        path_id = self._validate_id(book_id)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute("DELETE FROM mastery_paths WHERE path_id = ?", (path_id,))
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        legacy = self._path(path_id)
        if legacy.exists():
            legacy.unlink()
        archive_dir = Path(self._root) / ".legacy"
        if archive_dir.exists():
            # ``abc`` must never delete an archived ``abcd`` path. Timestamped
            # migration copies use the exact ``abc.<millis>.json`` prefix.
            for archived in archive_dir.glob("*.json"):
                if archived.stem == path_id or archived.stem.startswith(f"{path_id}."):
                    archived.unlink(missing_ok=True)
        from deeptutor.learning.event_hub import publish_topic_signal

        publish_topic_signal(
            path_id,
            0,
            "topic.deleted",
            scope=self.event_scope,
        )

    def exists(self, book_id: str) -> bool:
        path_id = self._validate_id(book_id)
        with self._connect() as conn:
            if conn.execute("SELECT 1 FROM mastery_paths WHERE path_id = ?", (path_id,)).fetchone():
                return True
        return self._path(path_id).exists()

    def list_all(self) -> list[str]:
        with self._connect() as conn:
            stored = {
                str(row["path_id"])
                for row in conn.execute("SELECT path_id FROM mastery_paths").fetchall()
            }
        legacy = {
            path.stem for path in Path(self._root).glob("*.json") if not path.name.startswith(".")
        }
        return sorted(stored | legacy)

    # ---- product topic metadata -----------------------------------------

    @staticmethod
    def _default_map_seed(path_id: str) -> int:
        return int.from_bytes(hashlib.sha256(path_id.encode("utf-8")).digest()[:4], "big")

    def put_topic(self, metadata: TopicMetadata, sources: list[TopicSource]) -> MasteryTopic:
        path_id = self._validate_id(metadata.path_id)
        normalized = metadata.model_copy(deep=True)
        normalized.path_id = path_id
        if normalized.map_seed == 0:
            normalized.map_seed = self._default_map_seed(path_id)
        ordered = [source.model_copy(deep=True) for source in sources]
        for index, source in enumerate(ordered):
            source.position = index

        def apply(tx: LearningTransaction) -> None:
            tx.put_topic(normalized, ordered)

        self.mutate(path_id, apply)
        topic = self.get_topic(path_id)
        if topic is None:  # pragma: no cover - transaction guarantees the row
            raise LearningStoreError(f"Failed to persist topic {path_id!r}")
        return topic

    def get_topic(
        self,
        path_id: str,
        *,
        progress: LearningProgress | None = None,
    ) -> MasteryTopic | None:
        path_id = self._validate_id(path_id)
        if progress is None:
            progress = self.load(path_id)
        elif progress.book_id != path_id:
            raise ValueError("progress does not belong to the requested topic")
        if progress is None:
            return None
        with self._connect() as conn:
            meta_row = conn.execute(
                "SELECT * FROM mastery_topic_meta WHERE path_id = ?", (path_id,)
            ).fetchone()
            source_rows = conn.execute(
                """
                SELECT * FROM mastery_topic_sources
                WHERE path_id = ? ORDER BY position ASC, created_at ASC
                """,
                (path_id,),
            ).fetchall()
        return self._topic_from_rows(path_id, progress, meta_row, source_rows)

    def _topic_from_rows(
        self,
        path_id: str,
        progress: LearningProgress,
        meta_row: sqlite3.Row | None,
        source_rows: list[sqlite3.Row],
    ) -> MasteryTopic:
        if meta_row is None:
            metadata = TopicMetadata(
                path_id=path_id,
                map_seed=self._default_map_seed(path_id),
                created_at=progress.created_at,
                updated_at=progress.updated_at,
            )
        else:
            metadata = TopicMetadata(
                path_id=path_id,
                goal=meta_row["goal"] or "",
                description=meta_row["description"] or "",
                emoji=meta_row["emoji"] or "🧭",
                map_seed=int(meta_row["map_seed"] or self._default_map_seed(path_id)),
                status=meta_row["status"] or "active",
                created_at=float(meta_row["created_at"]),
                updated_at=float(meta_row["updated_at"]),
            )
        sources = [
            TopicSource(
                id=row["source_id"],
                kind=row["kind"],
                source_id=row["external_id"] or "",
                label=row["label"],
                excerpt=row["excerpt"] or "",
                position=int(row["position"]),
                available=bool(row["available"]),
                metadata=json.loads(row["metadata_json"] or "{}"),
                created_at=float(row["created_at"]),
            )
            for row in source_rows
        ]
        return MasteryTopic(metadata=metadata, sources=sources)

    def list_topic_snapshots(
        self,
        *,
        status: str = "active",
    ) -> list[
        tuple[
            LearningProgress,
            MasteryTopic,
            int,
            MasteryInteraction | None,
        ]
    ]:
        """Read the atlas in a constant number of bounded SQLite queries."""

        with self._connect() as conn:
            progress_rows = conn.execute(
                """
                SELECT p.* FROM mastery_paths p
                JOIN mastery_topic_meta m ON m.path_id = p.path_id
                WHERE m.status = ?
                ORDER BY p.updated_at DESC
                """,
                (status,),
            ).fetchall()
            meta_rows = {
                str(row["path_id"]): row
                for row in conn.execute(
                    "SELECT * FROM mastery_topic_meta WHERE status = ?",
                    (status,),
                ).fetchall()
            }
            source_rows: dict[str, list[sqlite3.Row]] = {}
            for row in conn.execute(
                """
                SELECT s.* FROM mastery_topic_sources s
                JOIN mastery_topic_meta m ON m.path_id = s.path_id
                WHERE m.status = ?
                ORDER BY s.path_id, s.position ASC, s.created_at ASC
                """,
                (status,),
            ).fetchall():
                source_rows.setdefault(str(row["path_id"]), []).append(row)
            session_counts = {
                str(row["path_id"]): int(row["session_count"])
                for row in conn.execute(
                    """
                    SELECT b.path_id, COUNT(*) AS session_count
                    FROM mastery_path_sessions b
                    JOIN mastery_topic_meta m ON m.path_id = b.path_id
                    WHERE m.status = ?
                    GROUP BY b.path_id
                    """,
                    (status,),
                ).fetchall()
            }
            placeholders = ",".join("?" for _ in _ACTIVE_INTERACTION_STATES)
            active_rows = {
                str(row["path_id"]): row
                for row in conn.execute(
                    f"""
                    SELECT i.* FROM mastery_interactions i
                    JOIN mastery_topic_meta m ON m.path_id = i.path_id
                    WHERE m.status = ? AND i.status IN ({placeholders})
                    """,  # nosec B608 - generated placeholders; values remain bound
                    (status, *_ACTIVE_INTERACTION_STATES),
                ).fetchall()
            }

        snapshots = []
        for progress_row in progress_rows:
            path_id = str(progress_row["path_id"])
            progress = self._progress_from_row(progress_row)
            snapshots.append(
                (
                    progress,
                    self._topic_from_rows(
                        path_id,
                        progress,
                        meta_rows.get(path_id),
                        source_rows.get(path_id, []),
                    ),
                    session_counts.get(path_id, 0),
                    LearningTransaction._interaction_from_row(active_rows.get(path_id)),
                )
            )
        return snapshots

    @staticmethod
    def default_db_path() -> Path:
        """Where the app-owned store's database is, creating nothing.

        Constructing a store runs the V1 to V2 migration and writes the schema,
        which is the right thing for anyone about to read or teach a path and
        the wrong thing for a per-turn gate asking "does this learner have any
        mastery topics at all?". That gate probes this path first, so a learner
        who has never opened a topic never gets a store created for them.
        """
        from deeptutor.learning.migration import mastery_v2_root

        learning_root = get_path_service().get_workspace_dir() / "learning"
        return mastery_v2_root(learning_root) / LearningStore._DB_FILENAME

    def has_active_topics(self) -> bool:
        """Whether any named, unarchived topic exists.

        Deliberately not ``len(list_topic_snapshots())``: that walk loads every
        path's state, metadata, sources and open interaction to answer a
        yes/no question a single indexed row settles.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM mastery_topic_meta WHERE status = 'active' LIMIT 1"
            ).fetchone()
        return row is not None

    # ---- explicit path/session ownership ---------------------------------

    def bind_session(self, path_id: str, session_id: str, *, owns_path: bool = False) -> None:
        """Make ``path_id`` the one path this conversation is on.

        Membership is exclusive and always current: a conversation that moves
        to another path stops being listed under the one it left, so two
        topics can never both claim it. ``owns_path`` is the separate,
        permanent fact that this conversation *created* the path — recorded on
        the path itself, so deleting the conversation still takes its scratch
        path with it after the conversation has moved on.
        """
        path_id = self._validate_id(path_id)
        self._import_legacy_if_needed(path_id)
        session_id = str(session_id or "").strip()
        if not session_id:
            raise ValueError("session_id must not be empty")
        now = time.time()
        current_revision = 0
        released_path_id = ""
        released_revision = 0
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                previous = conn.execute(
                    "SELECT path_id FROM mastery_path_sessions WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                if previous is not None and str(previous["path_id"]) != path_id:
                    released_path_id = str(previous["path_id"])
                    conn.execute(
                        "DELETE FROM mastery_path_sessions WHERE session_id = ?",
                        (session_id,),
                    )
                    released_row = conn.execute(
                        "SELECT revision FROM mastery_paths WHERE path_id = ?",
                        (released_path_id,),
                    ).fetchone()
                    released_revision = int(released_row["revision"]) if released_row else 0
                row = conn.execute(
                    "SELECT 1 FROM mastery_paths WHERE path_id = ?", (path_id,)
                ).fetchone()
                if row is None:
                    progress = LearningProgress(book_id=path_id)
                    progress.version = 1
                    progress.updated_at = now
                    conn.execute(
                        """
                        INSERT INTO mastery_paths (
                            path_id, state_json, revision, created_at, updated_at
                        ) VALUES (?, ?, 1, ?, ?)
                        """,
                        (
                            path_id,
                            json.dumps(progress.model_dump(mode="json"), ensure_ascii=False),
                            progress.created_at,
                            now,
                        ),
                    )
                    conn.execute(
                        """
                        INSERT INTO mastery_events (
                            path_id, revision, event_type, payload_json, created_at
                        ) VALUES (?, 1, 'path.created', '{}', ?)
                        """,
                        (path_id, now),
                    )
                conn.execute(
                    """
                    INSERT INTO mastery_path_sessions (
                        path_id, session_id, created_at, last_seen_at
                    ) VALUES (?, ?, ?, ?)
                    ON CONFLICT(path_id, session_id) DO UPDATE SET
                        last_seen_at = excluded.last_seen_at
                    """,
                    (path_id, session_id, now, now),
                )
                if owns_path:
                    # Granted once and never transferred: a path has exactly
                    # one creator, whatever conversations pass through later.
                    conn.execute(
                        """
                        UPDATE mastery_paths SET owner_session_id = ?
                        WHERE path_id = ? AND owner_session_id = ''
                        """,
                        (session_id, path_id),
                    )
                current_revision = int(
                    conn.execute(
                        "SELECT revision FROM mastery_paths WHERE path_id = ?", (path_id,)
                    ).fetchone()["revision"]
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        from deeptutor.learning.event_hub import publish_topic_signal

        publish_topic_signal(
            path_id,
            current_revision,
            "session.bound",
            scope=self.event_scope,
        )
        if released_path_id:
            # The path it left lost a conversation from its list; its screen
            # is as stale as the one it joined.
            publish_topic_signal(
                released_path_id,
                released_revision,
                "session.released",
                scope=self.event_scope,
            )

    def list_session_ids(self, path_id: str) -> list[str]:
        path_id = self._validate_id(path_id)
        self._import_legacy_if_needed(path_id)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT session_id FROM mastery_path_sessions
                WHERE path_id = ? ORDER BY last_seen_at DESC
                """,
                (path_id,),
            ).fetchall()
        return [str(row["session_id"]) for row in rows]

    def path_id_for_session(self, session_id: str) -> str:
        """The one path this conversation is on, or ``""`` when it is on none."""
        session_id = str(session_id or "").strip()
        if not session_id:
            return ""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT path_id FROM mastery_path_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return str(row["path_id"]) if row is not None else ""

    @staticmethod
    def _is_scratch_state(state_json: Any) -> bool:
        """Whether a path never got a curriculum, and so is only a scratchpad.

        A conversation that starts tutoring without naming a topic gets a path
        of its own to write into. Until something is built there it is part of
        the conversation and dies with it; once it holds objectives it is a
        course the learner can return to from anywhere, and outlives whichever
        conversation happened to create it.
        """
        try:
            state = json.loads(str(state_json or "{}"))
        except (TypeError, ValueError):
            return False
        modules = state.get("modules") if isinstance(state, dict) else None
        if not isinstance(modules, list):
            return True
        return not any(
            isinstance(module, dict) and module.get("knowledge_points") for module in modules
        )

    def detach_session(self, session_id: str, *, delete_owned_orphans: bool = True) -> list[str]:
        """Forget this conversation, and delete the scratch path it created.

        Deleting a conversation deletes what only it could see. Its membership
        goes unconditionally; the path goes with it only when this conversation
        created it, nothing was ever built there, and no other conversation has
        since moved onto it.
        """
        session_id = str(session_id or "").strip()
        if not session_id:
            return []
        # Pre-association ad-hoc paths used the session id as their JSON key.
        # Import that exact legacy candidate before applying the fallback below.
        try:
            self._import_legacy_if_needed(session_id)
        except ValueError:
            pass
        deleted_paths: list[str] = []
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                # Ownership is a property of the path. The second clause covers
                # data written before it was: an ad-hoc path was then named
                # after the conversation that opened it.
                owned = conn.execute(
                    """
                    SELECT path_id, state_json FROM mastery_paths
                    WHERE owner_session_id = ?
                       OR (owner_session_id = '' AND path_id = ?)
                    """,
                    (session_id, session_id),
                ).fetchall()
                conn.execute("DELETE FROM mastery_path_leases WHERE session_id = ?", (session_id,))
                conn.execute(
                    "DELETE FROM mastery_path_sessions WHERE session_id = ?", (session_id,)
                )
                if delete_owned_orphans:
                    for row in owned:
                        path_id = str(row["path_id"])
                        if not self._is_scratch_state(row["state_json"]):
                            continue
                        remaining = conn.execute(
                            "SELECT 1 FROM mastery_path_sessions WHERE path_id = ? LIMIT 1",
                            (path_id,),
                        ).fetchone()
                        if remaining is None:
                            conn.execute("DELETE FROM mastery_paths WHERE path_id = ?", (path_id,))
                            deleted_paths.append(path_id)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        for path_id in deleted_paths:
            legacy = self._path(path_id)
            if legacy.exists():
                legacy.unlink()
        return deleted_paths

    # ---- one active mutating turn per path -------------------------------

    @staticmethod
    def _lease_from_row(row: sqlite3.Row | None) -> MasteryPathLease | None:
        if row is None:
            return None
        return MasteryPathLease(
            path_id=row["path_id"],
            session_id=row["session_id"],
            turn_id=row["turn_id"],
            acquired_at=float(row["acquired_at"]),
        )

    def get_path_lease(self, path_id: str) -> MasteryPathLease | None:
        path_id = self._validate_id(path_id)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM mastery_path_leases WHERE path_id = ?", (path_id,)
            ).fetchone()
        return self._lease_from_row(row)

    def acquire_path_lease(
        self,
        path_id: str,
        session_id: str,
        turn_id: str,
        *,
        bind_session: bool = True,
    ) -> MasteryPathLease:
        path_id = self._validate_id(path_id)
        session_id = str(session_id or "").strip()
        turn_id = str(turn_id or "").strip()
        if not session_id or not turn_id:
            raise ValueError("session_id and turn_id are required for a path lease")
        if bind_session:
            self.bind_session(path_id, session_id, owns_path=False)
        else:
            # Administrative mutations need exclusion without creating a fake
            # conversation association.
            with self.transaction(path_id, create=True):
                pass
        now = time.time()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT * FROM mastery_path_leases WHERE path_id = ?", (path_id,)
                ).fetchone()
                existing = self._lease_from_row(row)
                if existing is not None and existing.turn_id != turn_id:
                    raise PathLeaseConflictError(existing)
                conn.execute(
                    """
                    INSERT INTO mastery_path_leases (path_id, session_id, turn_id, acquired_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(path_id) DO UPDATE SET
                        session_id = excluded.session_id,
                        turn_id = excluded.turn_id,
                        acquired_at = excluded.acquired_at
                    """,
                    (path_id, session_id, turn_id, now),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return MasteryPathLease(
            path_id=path_id, session_id=session_id, turn_id=turn_id, acquired_at=now
        )

    def release_leases_for_turn(self, turn_id: str) -> str:
        """Release whatever path *turn_id* currently holds; return that path id.

        ``turn_id`` is unique across the lease table, so a turn holds at most
        one path — which makes this the only release that stays correct when a
        turn changes paths mid-flight. Releasing by the path id the turn *began*
        with would free the wrong one and leak the other.
        """
        turn_id = str(turn_id or "").strip()
        if not turn_id:
            return ""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT path_id FROM mastery_path_leases WHERE turn_id = ?", (turn_id,)
            ).fetchone()
            if row is None:
                return ""
            conn.execute("DELETE FROM mastery_path_leases WHERE turn_id = ?", (turn_id,))
            conn.commit()
        return str(row["path_id"])

    def release_path_lease(self, path_id: str, *, turn_id: str | None = None) -> bool:
        path_id = self._validate_id(path_id)
        with self._connect() as conn:
            if turn_id:
                cursor = conn.execute(
                    "DELETE FROM mastery_path_leases WHERE path_id = ? AND turn_id = ?",
                    (path_id, str(turn_id)),
                )
            else:
                cursor = conn.execute(
                    "DELETE FROM mastery_path_leases WHERE path_id = ?", (path_id,)
                )
            conn.commit()
        return bool(cursor.rowcount)

    # ---- durable interaction/event reads --------------------------------

    def get_interaction(self, path_id: str, interaction_id: str) -> MasteryInteraction | None:
        path_id = self._validate_id(path_id)
        self._import_legacy_if_needed(path_id)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM mastery_interactions
                WHERE path_id = ? AND interaction_id = ?
                """,
                (path_id, str(interaction_id)),
            ).fetchone()
        return LearningTransaction._interaction_from_row(row)

    def get_active_interaction(self, path_id: str) -> MasteryInteraction | None:
        path_id = self._validate_id(path_id)
        self._import_legacy_if_needed(path_id)
        placeholders = ",".join("?" for _ in _ACTIVE_INTERACTION_STATES)
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT * FROM mastery_interactions
                WHERE path_id = ? AND status IN ({placeholders})
                ORDER BY created_at DESC LIMIT 1
                """,  # nosec B608 - placeholders is a generated "?,?" list; every value is bound
                (path_id, *_ACTIVE_INTERACTION_STATES),
            ).fetchone()
        return LearningTransaction._interaction_from_row(row)

    def list_interactions(self, path_id: str, *, limit: int = 200) -> list[MasteryInteraction]:
        """Question/answer transactions for a path, most recent first.

        The aggregate keeps only the *current* question; the durable history of
        what was asked lives here, which is what lets a review surface the
        actual prompts behind an objective's attempts.
        """
        path_id = self._validate_id(path_id)
        self._import_legacy_if_needed(path_id)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM mastery_interactions
                WHERE path_id = ?
                ORDER BY created_at DESC, rowid DESC
                LIMIT ?
                """,
                (path_id, max(1, int(limit))),
            ).fetchall()
        interactions = (LearningTransaction._interaction_from_row(row) for row in rows)
        return [interaction for interaction in interactions if interaction is not None]

    def list_events(self, path_id: str, *, after_revision: int = 0) -> list[MasteryEvent]:
        path_id = self._validate_id(path_id)
        self._import_legacy_if_needed(path_id)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM mastery_events
                WHERE path_id = ? AND revision > ?
                ORDER BY revision ASC, id ASC
                """,
                (path_id, max(0, int(after_revision))),
            ).fetchall()
        return [
            MasteryEvent(
                id=int(row["id"]),
                path_id=row["path_id"],
                revision=int(row["revision"]),
                event_type=row["event_type"],
                payload=json.loads(row["payload_json"] or "{}"),
                session_id=row["session_id"] or "",
                turn_id=row["turn_id"] or "",
                created_at=float(row["created_at"]),
            )
            for row in rows
        ]


__all__ = [
    "LearningConflictError",
    "LearningStore",
    "LearningStoreError",
    "LearningTransaction",
    "PathLeaseConflictError",
    "_atomic_write_text",
]
