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
import uuid

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


class LearningPlanConflictError(LearningStoreError):
    """Raised when a durable learning-plan operation loses its per-plan claim."""


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
                        updated_at REAL NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS mastery_path_sessions (
                        path_id TEXT NOT NULL REFERENCES mastery_paths(path_id) ON DELETE CASCADE,
                        session_id TEXT NOT NULL,
                        owns_path INTEGER NOT NULL DEFAULT 0,
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

                    CREATE TABLE IF NOT EXISTS mastery_learning_plans (
                        plan_id TEXT PRIMARY KEY,
                        owner_id TEXT NOT NULL,
                        state TEXT NOT NULL,
                        input_json TEXT NOT NULL,
                        context_path_id TEXT NOT NULL DEFAULT '',
                        selected_session_ids_json TEXT NOT NULL DEFAULT '[]',
                        draft_json TEXT NOT NULL DEFAULT '',
                        operation_kind TEXT NOT NULL DEFAULT '',
                        operation_token TEXT NOT NULL DEFAULT '',
                        operation_revision INTEGER NOT NULL DEFAULT 0,
                        created_at REAL NOT NULL,
                        updated_at REAL NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS mastery_planning_session_messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        plan_id TEXT NOT NULL REFERENCES mastery_learning_plans(plan_id)
                            ON DELETE CASCADE,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        created_at REAL NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_mastery_planning_session_messages
                        ON mastery_planning_session_messages(plan_id, id);
                    CREATE TABLE IF NOT EXISTS mastery_planning_sessions (
                        planning_session_id TEXT PRIMARY KEY,
                        owner_id TEXT NOT NULL,
                        plan_id TEXT,
                        state TEXT NOT NULL DEFAULT 'open',
                        created_at REAL NOT NULL,
                        updated_at REAL NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS mastery_route_drafts (
                        draft_id TEXT PRIMARY KEY,
                        owner_id TEXT NOT NULL,
                        plan_id TEXT,
                        plan_revision INTEGER NOT NULL DEFAULT 0,
                        version INTEGER NOT NULL,
                        draft_json TEXT NOT NULL,
                        created_at REAL NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_mastery_route_drafts_plan
                        ON mastery_route_drafts(plan_id, version);
                    """
                )
                columns = {
                    row["name"]
                    for row in conn.execute("PRAGMA table_info(mastery_learning_plans)").fetchall()
                }
                if "owner_id" not in columns:
                    conn.execute(
                        "ALTER TABLE mastery_learning_plans ADD COLUMN owner_id TEXT NOT NULL DEFAULT 'local-admin'"
                    )
                if "brief_json" not in columns:
                    conn.execute(
                        "ALTER TABLE mastery_learning_plans ADD COLUMN brief_json TEXT NOT NULL DEFAULT '{}'"
                    )
                if "brief_revision" not in columns:
                    conn.execute(
                        "ALTER TABLE mastery_learning_plans ADD COLUMN brief_revision INTEGER NOT NULL DEFAULT 0"
                    )
                if "existing_path_id" not in columns:
                    conn.execute(
                        "ALTER TABLE mastery_learning_plans ADD COLUMN existing_path_id TEXT NOT NULL DEFAULT ''"
                    )
                if "operation_kind" not in columns:
                    conn.execute(
                        "ALTER TABLE mastery_learning_plans ADD COLUMN operation_kind TEXT NOT NULL DEFAULT ''"
                    )
                if "operation_token" not in columns:
                    conn.execute(
                        "ALTER TABLE mastery_learning_plans ADD COLUMN operation_token TEXT NOT NULL DEFAULT ''"
                    )
                if "operation_revision" not in columns:
                    conn.execute(
                        "ALTER TABLE mastery_learning_plans ADD COLUMN operation_revision INTEGER NOT NULL DEFAULT 0"
                    )
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

    # ── Learning plan planning ──────────────────────────────────────────────

    def create_learning_plan(
        self,
        plan_id: str,
        input_data: dict[str, Any],
        *,
        owner_id: str,
        context_path_id: str = "",
        selected_session_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Persist a learning plan independently from ordinary study sessions."""
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO mastery_learning_plans (
                    plan_id, owner_id, state, input_json, context_path_id,
                    selected_session_ids_json, draft_json, brief_json, created_at, updated_at
                ) VALUES (?, ?, 'discussing', ?, ?, ?, '', ?, ?, ?)
                """,
                (
                    plan_id,
                    owner_id,
                    json.dumps(input_data, ensure_ascii=False),
                    context_path_id,
                    json.dumps(selected_session_ids or [], ensure_ascii=False),
                    json.dumps(input_data, ensure_ascii=False),
                    now,
                    now,
                ),
            )
        return self.get_learning_plan(plan_id, owner_id=owner_id) or {}

    def get_learning_plan(self, plan_id: str, *, owner_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM mastery_learning_plans WHERE plan_id = ? AND owner_id = ?",
                (plan_id, owner_id),
            ).fetchone()
            if row is None:
                return None
            messages = conn.execute(
                """
                SELECT role, content, created_at
                FROM mastery_planning_session_messages WHERE plan_id = ? ORDER BY id
                """,
                (plan_id,),
            ).fetchall()
        payload = dict(row)
        return {
            "plan_id": payload["plan_id"],
            "state": payload["state"],
            "input": json.loads(payload["input_json"]),
            "context_path_id": payload["context_path_id"],
            "selected_session_ids": json.loads(payload["selected_session_ids_json"]),
            "draft": json.loads(payload["draft_json"]) if payload["draft_json"] else None,
            "brief": json.loads(payload.get("brief_json") or "{}"),
            "brief_revision": int(payload.get("brief_revision") or 0),
            "existing_path_id": payload.get("existing_path_id") or "",
            "messages": [dict(message) for message in messages],
            "created_at": payload["created_at"],
            "updated_at": payload["updated_at"],
        }

    def append_planning_session_message(
        self, plan_id: str, role: str, content: str, *, owner_id: str
    ) -> None:
        now = time.time()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT state, draft_json FROM mastery_learning_plans WHERE plan_id = ? AND owner_id = ?",
                (plan_id, owner_id),
            ).fetchone()
            if row is None:
                raise KeyError(plan_id)
            # A draft is a proposal, not an approved plan. Keep that fact in
            # the durable conversation, and invalidate draft readiness only
            # when the learner actually starts a new discussion turn.
            if role == "user" and row["state"] == "draft_ready" and row["draft_json"]:
                marker = (
                    "A new route sketch was generated as a temporary draft. It is not approved; "
                    "use it only as context for further planning."
                )
                conn.execute(
                    """
                    INSERT INTO mastery_planning_session_messages (plan_id, role, content, created_at)
                    SELECT ?, 'assistant', ?, ?
                    WHERE NOT EXISTS (
                        SELECT 1 FROM mastery_planning_session_messages
                        WHERE plan_id = ? AND role = 'assistant' AND content = ?
                    )
                    """,
                    (plan_id, marker, now, plan_id, marker),
                )
                conn.execute(
                    "UPDATE mastery_learning_plans SET state = 'settled' WHERE plan_id = ?",
                    (plan_id,),
                )
            conn.execute(
                """
                INSERT INTO mastery_planning_session_messages (plan_id, role, content, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (plan_id, role, content, now),
            )
            conn.execute(
                "UPDATE mastery_learning_plans SET updated_at = ? WHERE plan_id = ?",
                (now, plan_id),
            )

    def settle_learning_plan(
        self, plan_id: str, input_data: dict[str, Any], *, owner_id: str
    ) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT state, operation_kind FROM mastery_learning_plans WHERE plan_id = ? AND owner_id = ?",
                (plan_id, owner_id),
            ).fetchone()
            if row is None:
                raise KeyError(plan_id)
            expected_state = str(row["state"])
            if row["operation_kind"]:
                raise LearningPlanConflictError(
                    "Learning plan is busy; retry after the current operation"
                )
            if expected_state != "discussing":
                raise ValueError(f"Cannot settle learning plan in state {expected_state!r}")
            cursor = conn.execute(
                """
                UPDATE mastery_learning_plans
                SET state = 'settled', input_json = ?, brief_json = ?, brief_revision = brief_revision + 1,
                    existing_path_id = ?, updated_at = ?
                WHERE plan_id = ? AND owner_id = ? AND state = ? AND operation_kind = ''
                """,
                (
                    json.dumps(input_data, ensure_ascii=False),
                    json.dumps(input_data, ensure_ascii=False),
                    str(input_data.get("existing_path_id") or ""),
                    time.time(),
                    plan_id,
                    owner_id,
                    expected_state,
                ),
            )
            if cursor.rowcount != 1:
                current = conn.execute(
                    "SELECT state, operation_kind FROM mastery_learning_plans WHERE plan_id = ? AND owner_id = ?",
                    (plan_id, owner_id),
                ).fetchone()
                if current is None:
                    raise KeyError(plan_id)
                if current["operation_kind"]:
                    raise LearningPlanConflictError(
                        "Learning plan is busy; retry after the current operation"
                    )
                raise ValueError(f"Cannot settle learning plan in state {current['state']!r}")
        return self.get_learning_plan(plan_id, owner_id=owner_id) or {}

    def update_learning_plan_brief(
        self, plan_id: str, brief: dict[str, Any], *, owner_id: str
    ) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT state, operation_kind FROM mastery_learning_plans WHERE plan_id = ? AND owner_id = ?",
                (plan_id, owner_id),
            ).fetchone()
            if row is None:
                raise KeyError(plan_id)
            expected_state = str(row["state"])
            if row["operation_kind"]:
                raise LearningPlanConflictError(
                    "Learning plan is busy; retry after the current operation"
                )
            if expected_state == "draft_ready":
                raise ValueError("Cannot update a plan after a route draft is ready")
            cursor = conn.execute(
                """
                UPDATE mastery_learning_plans
                SET brief_json = ?, input_json = ?, brief_revision = brief_revision + 1,
                    existing_path_id = ?, state = 'settled', updated_at = ?
                WHERE plan_id = ? AND owner_id = ? AND state = ? AND operation_kind = ''
                """,
                (
                    json.dumps(brief, ensure_ascii=False),
                    json.dumps(brief, ensure_ascii=False),
                    str(brief.get("existing_path_id") or ""),
                    time.time(),
                    plan_id,
                    owner_id,
                    expected_state,
                ),
            )
            if cursor.rowcount != 1:
                current = conn.execute(
                    "SELECT state, operation_kind FROM mastery_learning_plans WHERE plan_id = ? AND owner_id = ?",
                    (plan_id, owner_id),
                ).fetchone()
                if current is None:
                    raise KeyError(plan_id)
                if current["operation_kind"]:
                    raise LearningPlanConflictError(
                        "Learning plan is busy; retry after the current operation"
                    )
                if current["state"] == "draft_ready":
                    raise ValueError("Cannot update a plan after a route draft is ready")
                raise LearningPlanConflictError(
                    "Learning plan changed concurrently; retry the update"
                )
        return self.get_learning_plan(plan_id, owner_id=owner_id) or {}

    def revise_learning_plan_brief(
        self, plan_id: str, brief: dict[str, Any], *, owner_id: str
    ) -> dict[str, Any]:
        """Save an AI-proposed brief without settling or changing a route."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT state, operation_kind FROM mastery_learning_plans WHERE plan_id = ? AND owner_id = ?",
                (plan_id, owner_id),
            ).fetchone()
            if row is None:
                raise KeyError(plan_id)
            conn.execute(
                """
                UPDATE mastery_learning_plans
                SET brief_json = ?, brief_revision = brief_revision + 1,
                    state = CASE WHEN state = 'draft_ready' THEN 'settled' ELSE state END,
                    updated_at = ?
                WHERE plan_id = ? AND owner_id = ?
                """,
                (json.dumps(brief, ensure_ascii=False), time.time(), plan_id, owner_id),
            )
        return self.get_learning_plan(plan_id, owner_id=owner_id) or {}

    def create_planning_session(
        self, planning_session_id: str, *, owner_id: str, plan_id: str = ""
    ) -> dict[str, Any]:
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO mastery_planning_sessions
                    (planning_session_id, owner_id, plan_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (planning_session_id, owner_id, plan_id, now, now),
            )
        return self.get_planning_session(planning_session_id, owner_id=owner_id) or {}

    def get_planning_session(
        self, planning_session_id: str, *, owner_id: str
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM mastery_planning_sessions WHERE planning_session_id = ? AND owner_id = ?",
                (planning_session_id, owner_id),
            ).fetchone()
        return dict(row) if row else None

    def save_route_draft_version(
        self,
        draft_id: str,
        draft: dict[str, Any],
        *,
        owner_id: str,
        plan_id: str = "",
        plan_revision: int = 0,
    ) -> None:
        with self._connect() as conn:
            version = int(
                conn.execute(
                    "SELECT COALESCE(MAX(version), 0) + 1 FROM mastery_route_drafts WHERE plan_id = ? AND owner_id = ?",
                    (plan_id, owner_id),
                ).fetchone()[0]
            )
            conn.execute(
                """
                INSERT INTO mastery_route_drafts
                    (draft_id, owner_id, plan_id, plan_revision, version, draft_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    draft_id,
                    owner_id,
                    plan_id,
                    int(plan_revision),
                    version,
                    json.dumps(draft, ensure_ascii=False),
                    time.time(),
                ),
            )

    def begin_learning_plan_route_generation(
        self, plan_id: str, *, owner_id: str, force: bool = False
    ) -> tuple[str, dict[str, Any] | None, dict[str, Any] | None]:
        """Durably claim one route-generation slot, or return a reusable draft.

        The claim lives in SQLite rather than process memory, so separate API
        workers cannot both invoke the generator for the same plan.
        """
        token = uuid.uuid4().hex
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT state, draft_json, brief_revision, operation_kind FROM mastery_learning_plans "
                "WHERE plan_id = ? AND owner_id = ?",
                (plan_id, owner_id),
            ).fetchone()
            if row is None:
                raise KeyError(plan_id)
            if row["state"] == "draft_ready" and not force:
                conn.commit()
                return "", json.loads(row["draft_json"]), None
            if row["state"] not in {"settled", "draft_ready"}:
                conn.rollback()
                raise ValueError(f"Cannot generate a draft from state {row['state']!r}")
            if row["operation_kind"]:
                conn.rollback()
                raise LearningPlanConflictError(
                    "Learning plan is busy; retry after the current operation"
                )
            conn.execute(
                """UPDATE mastery_learning_plans
                SET operation_kind = 'generation', operation_token = ?, operation_revision = ?, updated_at = ?
                WHERE plan_id = ? AND owner_id = ?""",
                (token, int(row["brief_revision"]), time.time(), plan_id, owner_id),
            )
            conn.commit()
        claimed = self.get_learning_plan(plan_id, owner_id=owner_id) or {}
        return token, None, claimed

    def save_generated_learning_plan_route_draft(
        self, plan_id: str, draft: dict[str, Any], *, owner_id: str, token: str
    ) -> dict[str, Any]:
        """Commit a generated draft only if its durable claim is still current."""
        with self._connect() as conn:
            cursor = conn.execute(
                """UPDATE mastery_learning_plans
                SET state = 'draft_ready', draft_json = ?, operation_kind = '', operation_token = '',
                    operation_revision = 0, updated_at = ?
                WHERE plan_id = ? AND owner_id = ? AND operation_kind = 'generation'
                  AND operation_token = ? AND operation_revision = brief_revision
                  AND state IN ('settled', 'draft_ready')""",
                (json.dumps(draft, ensure_ascii=False), time.time(), plan_id, owner_id, token),
            )
            if cursor.rowcount != 1:
                raise LearningPlanConflictError("Route generation became stale; the plan changed")
            version = int(
                conn.execute(
                    "SELECT COALESCE(MAX(version), 0) + 1 FROM mastery_route_drafts WHERE plan_id = ? AND owner_id = ?",
                    (plan_id, owner_id),
                ).fetchone()[0]
            )
            conn.execute(
                """INSERT INTO mastery_route_drafts
                (draft_id, owner_id, plan_id, plan_revision, version, draft_json, created_at)
                SELECT ?, ?, ?, brief_revision, ?, ?, ? FROM mastery_learning_plans
                WHERE plan_id = ? AND owner_id = ?""",
                (
                    f"draft_{uuid.uuid4().hex}",
                    owner_id,
                    plan_id,
                    version,
                    json.dumps(draft, ensure_ascii=False),
                    time.time(),
                    plan_id,
                    owner_id,
                ),
            )
        return self.get_learning_plan(plan_id, owner_id=owner_id) or {}

    def abandon_learning_plan_operation(self, plan_id: str, *, owner_id: str, token: str) -> None:
        """Release a failed LLM operation only if no newer operation replaced it."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE mastery_learning_plans SET operation_kind = '', operation_token = '', operation_revision = 0 "
                "WHERE plan_id = ? AND owner_id = ? AND operation_token = ?",
                (plan_id, owner_id, token),
            )

    def begin_learning_plan_turn(
        self, plan_id: str, content: str, *, owner_id: str
    ) -> tuple[str, dict[str, Any]]:
        """Append a user turn and claim its ordered assistant completion slot."""
        token = uuid.uuid4().hex
        now = time.time()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT state, draft_json, operation_kind FROM mastery_learning_plans "
                "WHERE plan_id = ? AND owner_id = ?",
                (plan_id, owner_id),
            ).fetchone()
            if row is None:
                raise KeyError(plan_id)
            if row["state"] not in {"discussing", "settled", "draft_ready"}:
                conn.rollback()
                raise ValueError("Learning plan is no longer open for discussion")
            if row["operation_kind"] == "planning_turn":
                conn.rollback()
                raise LearningPlanConflictError(
                    "A planning message is already being processed; retry it"
                )
            if row["state"] == "draft_ready" and row["draft_json"]:
                marker = "A new route sketch was generated as a temporary draft. It is not approved; use it only as context for further planning."
                conn.execute(
                    "INSERT INTO mastery_planning_session_messages (plan_id, role, content, created_at) "
                    "SELECT ?, 'assistant', ?, ? WHERE NOT EXISTS (SELECT 1 FROM mastery_planning_session_messages WHERE plan_id = ? AND role = 'assistant' AND content = ?)",
                    (plan_id, marker, now, plan_id, marker),
                )
            conn.execute(
                "INSERT INTO mastery_planning_session_messages (plan_id, role, content, created_at) VALUES (?, 'user', ?, ?)",
                (plan_id, content, now),
            )
            # A user message cancels a generation claim. Its eventual compare-
            # and-swap cannot mark this newer discussion draft-ready.
            conn.execute(
                """UPDATE mastery_learning_plans
                SET state = CASE WHEN state = 'draft_ready' THEN 'settled' ELSE state END,
                    operation_kind = 'planning_turn', operation_token = ?, operation_revision = brief_revision,
                    updated_at = ? WHERE plan_id = ? AND owner_id = ?""",
                (token, now, plan_id, owner_id),
            )
            conn.commit()
        return token, self.get_learning_plan(plan_id, owner_id=owner_id) or {}

    def complete_learning_plan_turn(
        self,
        plan_id: str,
        assistant_reply: str,
        revised_brief: dict[str, Any] | None,
        *,
        owner_id: str,
        token: str,
    ) -> dict[str, Any]:
        """Atomically append the ordered reply and its optional brief revision."""
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT brief_revision FROM mastery_learning_plans WHERE plan_id = ? AND owner_id = ? "
                "AND operation_kind = 'planning_turn' AND operation_token = ? "
                "AND operation_revision = brief_revision",
                (plan_id, owner_id, token),
            ).fetchone()
            if row is None:
                conn.rollback()
                raise LearningPlanConflictError(
                    "Planning reply became stale; reload the discussion"
                )
            now = time.time()
            conn.execute(
                "INSERT INTO mastery_planning_session_messages (plan_id, role, content, created_at) VALUES (?, 'assistant', ?, ?)",
                (plan_id, assistant_reply, now),
            )
            if revised_brief is None:
                conn.execute(
                    "UPDATE mastery_learning_plans SET operation_kind = '', operation_token = '', operation_revision = 0, updated_at = ? WHERE plan_id = ? AND owner_id = ?",
                    (now, plan_id, owner_id),
                )
            else:
                conn.execute(
                    """UPDATE mastery_learning_plans
                    SET brief_json = ?, brief_revision = brief_revision + 1, state = 'settled',
                        operation_kind = '', operation_token = '', operation_revision = 0, updated_at = ?
                    WHERE plan_id = ? AND owner_id = ?""",
                    (json.dumps(revised_brief, ensure_ascii=False), now, plan_id, owner_id),
                )
            conn.commit()
        return self.get_learning_plan(plan_id, owner_id=owner_id) or {}

    def save_learning_plan_route_draft(
        self, plan_id: str, draft: dict[str, Any], *, owner_id: str, force: bool = False
    ) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT state, operation_kind FROM mastery_learning_plans WHERE plan_id = ? AND owner_id = ?",
                (plan_id, owner_id),
            ).fetchone()
            if row is None:
                raise KeyError(plan_id)
            if row["state"] == "draft_ready" and not force:
                return self.get_learning_plan(plan_id, owner_id=owner_id) or {}
            if row["state"] not in {"settled", "draft_ready"}:
                raise ValueError(f"Cannot generate a draft from state {row['state']!r}")
            conn.execute(
                """
                UPDATE mastery_learning_plans
                SET state = 'draft_ready', draft_json = ?, updated_at = ?
                WHERE plan_id = ? AND owner_id = ?
                """,
                (json.dumps(draft, ensure_ascii=False), time.time(), plan_id, owner_id),
            )
        return self.get_learning_plan(plan_id, owner_id=owner_id) or {}

    def update_learning_plan_route_draft(
        self, plan_id: str, draft: dict[str, Any], *, owner_id: str
    ) -> dict[str, Any]:
        """Persist a learner edit while retaining the plan-owned draft history."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT state, brief_revision, operation_kind FROM mastery_learning_plans WHERE plan_id = ? AND owner_id = ?",
                (plan_id, owner_id),
            ).fetchone()
            if row is None:
                raise KeyError(plan_id)
            if row["operation_kind"]:
                raise LearningPlanConflictError(
                    "Learning plan is busy; retry after the current operation"
                )
            if row["state"] != "draft_ready":
                raise ValueError(f"Cannot edit a draft in state {row['state']!r}")
            now = time.time()
            cursor = conn.execute(
                """
                UPDATE mastery_learning_plans
                SET draft_json = ?, updated_at = ?
                WHERE plan_id = ? AND owner_id = ? AND state = 'draft_ready' AND operation_kind = ''
                """,
                (json.dumps(draft, ensure_ascii=False), now, plan_id, owner_id),
            )
            if cursor.rowcount != 1:
                current = conn.execute(
                    "SELECT state, operation_kind FROM mastery_learning_plans WHERE plan_id = ? AND owner_id = ?",
                    (plan_id, owner_id),
                ).fetchone()
                if current is None:
                    raise KeyError(plan_id)
                if current["operation_kind"]:
                    raise LearningPlanConflictError(
                        "Learning plan is busy; retry after the current operation"
                    )
                raise ValueError(f"Cannot edit a draft in state {current['state']!r}")
            conn.execute(
                """
                INSERT INTO mastery_planning_session_messages (plan_id, role, content, created_at)
                SELECT ?, 'assistant', ?, ?
                WHERE NOT EXISTS (
                    SELECT 1 FROM mastery_planning_session_messages
                    WHERE plan_id = ? AND content = ?
                )
                """,
                (
                    plan_id,
                    "A new route sketch was generated as a temporary draft. It is not approved; "
                    "use it only as context for further planning.",
                    now,
                    plan_id,
                    "A new route sketch was generated as a temporary draft. It is not approved; "
                    "use it only as context for further planning.",
                ),
            )
            version = int(
                conn.execute(
                    "SELECT COALESCE(MAX(version), 0) + 1 FROM mastery_route_drafts WHERE plan_id = ? AND owner_id = ?",
                    (plan_id, owner_id),
                ).fetchone()[0]
            )
            conn.execute(
                """
                INSERT INTO mastery_route_drafts
                    (draft_id, owner_id, plan_id, plan_revision, version, draft_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"draft_{uuid.uuid4().hex}",
                    owner_id,
                    plan_id,
                    int(row["brief_revision"]),
                    version,
                    json.dumps(draft, ensure_ascii=False),
                    now,
                ),
            )
        return self.get_learning_plan(plan_id, owner_id=owner_id) or {}

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
        path_id = self._validate_id(path_id)
        self._import_legacy_if_needed(path_id)
        session_id = str(session_id or "").strip()
        if not session_id:
            raise ValueError("session_id must not be empty")
        now = time.time()
        current_revision = 0
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
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
                        path_id, session_id, owns_path, created_at, last_seen_at
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(path_id, session_id) DO UPDATE SET
                        owns_path = MAX(mastery_path_sessions.owns_path, excluded.owns_path),
                        last_seen_at = excluded.last_seen_at
                    """,
                    (path_id, session_id, int(owns_path), now, now),
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

    def list_paths_for_session(self, session_id: str) -> list[dict[str, Any]]:
        session_id = str(session_id or "").strip()
        if not session_id:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT path_id, owns_path, created_at, last_seen_at
                FROM mastery_path_sessions
                WHERE session_id = ? ORDER BY last_seen_at DESC
                """,
                (session_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def detach_session(self, session_id: str, *, delete_owned_orphans: bool = True) -> list[str]:
        """Remove a session association and optionally delete owned orphan paths."""
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
                rows = conn.execute(
                    "SELECT path_id, owns_path FROM mastery_path_sessions WHERE session_id = ?",
                    (session_id,),
                ).fetchall()
                conn.execute("DELETE FROM mastery_path_leases WHERE session_id = ?", (session_id,))
                conn.execute(
                    "DELETE FROM mastery_path_sessions WHERE session_id = ?", (session_id,)
                )
                if delete_owned_orphans:
                    if not rows:
                        # Compatibility for pre-association data, where an
                        # ad-hoc path was implicitly named after its session.
                        # All new turns create an explicit binding, so this
                        # narrow fallback cannot delete a newly shared path.
                        legacy = conn.execute(
                            "SELECT 1 FROM mastery_paths WHERE path_id = ?",
                            (session_id,),
                        ).fetchone()
                        if legacy is not None:
                            conn.execute(
                                "DELETE FROM mastery_paths WHERE path_id = ?",
                                (session_id,),
                            )
                            deleted_paths.append(session_id)
                    for row in rows:
                        if not bool(row["owns_path"]):
                            continue
                        path_id = str(row["path_id"])
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
