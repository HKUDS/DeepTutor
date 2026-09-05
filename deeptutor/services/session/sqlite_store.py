"""
SQLite-backed unified chat session store.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import sqlite3
import time
from typing import Any
import uuid

try:  # POSIX is the supported production target; fallback keeps Windows dev usable.
    import fcntl
except ImportError:  # pragma: no cover - exercised only on Windows
    fcntl = None  # type: ignore[assignment]

from deeptutor.services.path_service import get_path_service
from deeptutor.utils.secret_files import ensure_private_directory, ensure_private_file

from .ask_user_trace import select_ask_user_events
from .event_preview import MAX_TRACE_PREVIEW_EVENTS, compact_trace_preview
from .provider_response_state import redact_private_message_metadata
from .workspace_preferences import upgrade_workspace_preferences


def _json_dumps(value: Any) -> str:
    # default=str: a single non-serializable object inside an event payload
    # (e.g. a dataclass smuggled into tool args) must degrade to its repr,
    # never kill message/event persistence for the whole turn.
    return json.dumps(value, ensure_ascii=False, default=str)


def _escape_like(value: str) -> str:
    """Escape LIKE wildcards so a search term matches itself literally."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@contextmanager
def _migration_lock(db_path: Path) -> Iterator[None]:
    """Serialize idempotent schema upgrades across worker processes."""
    lock_path = db_path.with_name(f"{db_path.name}.migrate.lock")
    with lock_path.open("a+b") as lock_file:
        if fcntl is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


# Sentinel so ``add_message`` can distinguish "caller wants the legacy
# auto-pick-latest-message default" from "caller explicitly wants the
# message attached at the session root (parent = NULL)". Both surface as
# ``None`` in the public ``parent_message_id`` arg, which is why we need
# a sentinel separate from None.
class _Unset:
    pass


_PARENT_AUTO = _Unset()


def _json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


# Imported conversations share the session tables with native chats but carry
# this id prefix as their discriminator (see ``SQLiteSessionStore._WHERE_*``).
_IMPORTED_ID_PREFIX = "imported_"
_ID_SAFE = re.compile(r"[^A-Za-z0-9_-]")
ASSESSMENT_SOURCES = frozenset({"deep_question", "mastery_path", "immersive_reading", "book"})
SCORE_TRENDS = frozenset({"new", "improved", "declined", "unchanged"})
ACTIVE_TURN_STATUSES = frozenset({"queued", "running", "waiting_input"})
TERMINAL_TURN_STATUSES = frozenset({"completed", "failed", "cancelled"})
ALL_TURN_STATUSES = ACTIVE_TURN_STATUSES | TERMINAL_TURN_STATUSES


def make_imported_session_id(source: str, external_id: str) -> str:
    """Build a deterministic, dedup-friendly id for an imported conversation.

    ``source`` (e.g. ``claude_code``/``codex``) namespaces the original
    session uuid so two tools that happen to reuse an id never collide; the
    determinism is what makes re-importing the same folder idempotent.
    """
    src = _ID_SAFE.sub("-", (source or "external").strip()) or "external"
    ext = _ID_SAFE.sub("-", (external_id or "").strip()) or uuid.uuid4().hex
    return f"{_IMPORTED_ID_PREFIX}{src}_{ext}"


@dataclass
class TurnRecord:
    id: str
    session_id: str
    capability: str
    status: str
    error: str
    created_at: float
    updated_at: float
    finished_at: float | None
    last_seq: int = 0
    owner_id: str = ""
    fencing_token: int = 0
    state_version: int = 1
    failure_code: str = ""
    retryable: bool = False
    assistant_message_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "turn_id": self.id,
            "session_id": self.session_id,
            "capability": self.capability,
            "status": self.status,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "finished_at": self.finished_at,
            "last_seq": self.last_seq,
            "owner_id": self.owner_id,
            "fencing_token": self.fencing_token,
            "state_version": self.state_version,
            "failure_code": self.failure_code,
            "retryable": self.retryable,
            "assistant_message_id": self.assistant_message_id,
        }


@dataclass(frozen=True)
class QuestionBankQuery:
    """One question-bank listing request.

    A value object instead of a widening positional signature: the store's
    ``_run`` helper only forwards positional args, so every new filter used
    to mean another parameter threaded through three layers. Callers build
    a query, the store reads it — adding a filter never changes an arity.

    ``category_id`` and ``uncategorized`` are mutually exclusive views of the
    same axis; when both are supplied the explicit category wins, because a
    caller asking for one category always means "show me that category".
    """

    category_id: int | None = None
    uncategorized: bool = False
    bookmarked: bool | None = None
    is_correct: bool | None = None
    source: str = ""
    material_id: str = ""
    section_id: str = ""
    resolved: bool | None = None
    score_trend: str = ""
    search: str = ""
    session_id: str | None = None
    session_ids: Sequence[str] | None = None
    sort: str = "recent"
    limit: int = 50
    offset: int = 0

    def normalized(self) -> "QuestionBankQuery":
        """Clamp untrusted inputs into the ranges the SQL below assumes."""
        return QuestionBankQuery(
            category_id=self.category_id,
            uncategorized=self.uncategorized and self.category_id is None,
            bookmarked=self.bookmarked,
            is_correct=self.is_correct,
            source=(self.source or "").strip()
            if (self.source or "").strip() in ASSESSMENT_SOURCES
            else "",
            material_id=(self.material_id or "").strip(),
            section_id=(self.section_id or "").strip(),
            resolved=self.resolved,
            score_trend=(self.score_trend or "").strip()
            if (self.score_trend or "").strip() in SCORE_TRENDS
            else "",
            search=(self.search or "").strip()[:200],
            session_id=self.session_id,
            session_ids=None if self.session_ids is None else tuple(self.session_ids),
            sort="oldest" if self.sort == "oldest" else "recent",
            limit=max(1, min(int(self.limit), 500)),
            offset=max(0, int(self.offset)),
        )


class SQLiteSessionStore:
    """Persist unified chat sessions and messages in a SQLite database."""

    def __init__(self, db_path: Path | None = None) -> None:
        path_service = get_path_service()
        self.db_path = db_path or path_service.get_chat_history_db()
        ensure_private_directory(self.db_path.parent)
        self._migrate_legacy_db(path_service)
        self._lock = asyncio.Lock()
        with _migration_lock(self.db_path):
            self._initialize()
        ensure_private_file(self.db_path)

    def _migrate_legacy_db(self, path_service) -> None:
        """Move the legacy ``data/chat_history.db`` into ``data/user/`` once."""
        legacy_path = path_service.project_root / "data" / "chat_history.db"
        if self.db_path.exists() or not legacy_path.exists() or legacy_path == self.db_path:
            return
        try:
            os.replace(legacy_path, self.db_path)
        except OSError:
            # Fall back to leaving the legacy DB in place if an OS-level move
            # is not possible; the new DB path will be initialized empty.
            pass

    def _initialize(self) -> None:
        with self._connect() as conn:
            # WAL permits readers while another worker commits a turn/event
            # batch.  It is persistent for this database once enabled.
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL DEFAULT 'New conversation',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    compressed_summary TEXT DEFAULT '',
                    summary_up_to_msg_id INTEGER DEFAULT 0,
                    preferences_json TEXT DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL DEFAULT '',
                    capability TEXT DEFAULT '',
                    events_json TEXT DEFAULT '',
                    attachments_json TEXT DEFAULT '',
                    metadata_json TEXT DEFAULT '{}',
                    created_at REAL NOT NULL,
                    -- Edit-branching: NULL for the first message in a session;
                    -- otherwise the immediately preceding message on the path
                    -- this row continues. Siblings (same parent) are alternate
                    -- branches the user can switch between.
                    parent_message_id INTEGER
                );

                CREATE INDEX IF NOT EXISTS idx_messages_session_created
                    ON messages(session_id, created_at, id);
                -- ``idx_messages_parent`` is created after the
                -- parent_message_id migration runs (see below). Putting it
                -- in this script would fail on legacy DBs where the column
                -- gets added by ALTER TABLE further down.

                CREATE INDEX IF NOT EXISTS idx_sessions_updated_at
                    ON sessions(updated_at DESC);

                CREATE TABLE IF NOT EXISTS turns (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    capability TEXT DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'running',
                    error TEXT DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    finished_at REAL,
                    owner_id TEXT DEFAULT '',
                    fencing_token INTEGER NOT NULL DEFAULT 0,
                    state_version INTEGER NOT NULL DEFAULT 1,
                    failure_code TEXT DEFAULT '',
                    retryable INTEGER NOT NULL DEFAULT 0,
                    assistant_message_id INTEGER
                );

                CREATE INDEX IF NOT EXISTS idx_turns_session_updated
                    ON turns(session_id, updated_at DESC);

                CREATE INDEX IF NOT EXISTS idx_turns_session_status
                    ON turns(session_id, status, updated_at DESC);

                CREATE TABLE IF NOT EXISTS turn_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    turn_id TEXT NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
                    seq INTEGER NOT NULL,
                    type TEXT NOT NULL,
                    source TEXT DEFAULT '',
                    stage TEXT DEFAULT '',
                    content TEXT DEFAULT '',
                    metadata_json TEXT DEFAULT '',
                    timestamp REAL NOT NULL,
                    created_at REAL NOT NULL,
                    UNIQUE(turn_id, seq)
                );

                CREATE INDEX IF NOT EXISTS idx_turn_events_turn_seq
                    ON turn_events(turn_id, seq);

                CREATE TABLE IF NOT EXISTS notebook_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    turn_id TEXT NOT NULL DEFAULT '',
                    question_id TEXT NOT NULL,
                    question TEXT NOT NULL,
                    question_type TEXT DEFAULT '',
                    options_json TEXT DEFAULT '{}',
                    correct_answer TEXT DEFAULT '',
                    explanation TEXT DEFAULT '',
                    difficulty TEXT DEFAULT '',
                    user_answer TEXT DEFAULT '',
                    user_answer_images_json TEXT DEFAULT '[]',
                    source TEXT NOT NULL DEFAULT 'deep_question',
                    material_id TEXT NOT NULL DEFAULT '',
                    material_title TEXT NOT NULL DEFAULT '',
                    section_id TEXT NOT NULL DEFAULT '',
                    section_title TEXT NOT NULL DEFAULT '',
                    score_trend TEXT NOT NULL DEFAULT 'new',
                    is_correct INTEGER DEFAULT 0,
                    resolved INTEGER DEFAULT 0,
                    bookmarked INTEGER DEFAULT 0,
                    followup_session_id TEXT DEFAULT '',
                    ai_judgment TEXT DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(session_id, turn_id, question_id)
                );

                CREATE INDEX IF NOT EXISTS idx_notebook_entries_session
                    ON notebook_entries(session_id, created_at DESC);

                CREATE INDEX IF NOT EXISTS idx_notebook_entries_bookmarked
                    ON notebook_entries(bookmarked, created_at DESC);

                CREATE TABLE IF NOT EXISTS notebook_categories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS notebook_entry_categories (
                    entry_id INTEGER NOT NULL REFERENCES notebook_entries(id) ON DELETE CASCADE,
                    category_id INTEGER NOT NULL REFERENCES notebook_categories(id) ON DELETE CASCADE,
                    PRIMARY KEY (entry_id, category_id)
                );
                """
            )
            columns = {row[1] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
            if "preferences_json" not in columns:
                conn.execute("ALTER TABLE sessions ADD COLUMN preferences_json TEXT DEFAULT '{}'")
            self._migrate_workspace_preferences(conn)
            if "kind" in columns:
                try:
                    conn.execute("ALTER TABLE sessions DROP COLUMN kind")
                except sqlite3.OperationalError:
                    # Older SQLite builds may not support DROP COLUMN. The
                    # application no longer reads or writes this legacy field.
                    pass
            message_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(messages)").fetchall()
            }
            if "metadata_json" not in message_columns:
                conn.execute("ALTER TABLE messages ADD COLUMN metadata_json TEXT DEFAULT '{}'")
            if "parent_message_id" not in message_columns:
                conn.execute("ALTER TABLE messages ADD COLUMN parent_message_id INTEGER")
                # Backfill: for every existing session, treat the message stream
                # as a single linear path — each row's parent is the previous
                # row (by id) in the same session. Rows with no predecessor stay
                # NULL. We do this per session in pure Python to avoid relying
                # on window functions, which older SQLite builds may not have.
                sessions_rows = conn.execute("SELECT id FROM sessions").fetchall()
                for srow in sessions_rows:
                    prev_id: int | None = None
                    msg_rows = conn.execute(
                        "SELECT id FROM messages WHERE session_id = ? ORDER BY id ASC",
                        (srow[0],),
                    ).fetchall()
                    for mrow in msg_rows:
                        if prev_id is not None:
                            conn.execute(
                                "UPDATE messages SET parent_message_id = ? WHERE id = ?",
                                (prev_id, mrow[0]),
                            )
                        prev_id = mrow[0]
            # Always ensure the parent-lookup index exists — covers both
            # the legacy-migration case (just added the column) and the
            # fresh-DB case (created above without the index inline).
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_parent "
                "ON messages(session_id, parent_message_id)"
            )
            self._migrate_notebook_entries_add_turn_id(conn)
            self._migrate_notebook_entries_add_user_answer_images(conn)
            self._migrate_notebook_entries_add_ai_judgment(conn)
            self._migrate_notebook_entries_add_assessment_review(conn)
            self._migrate_turn_runtime_columns(conn)
            conn.commit()

    @staticmethod
    def _migrate_workspace_preferences(conn: sqlite3.Connection) -> int:
        """Backfill the explicit workspace discriminator without reordering history."""

        migrated = 0
        rows = conn.execute("SELECT id, preferences_json FROM sessions").fetchall()
        for row in rows:
            current = _json_loads(row["preferences_json"], {})
            if not isinstance(current, dict):
                continue
            upgraded = upgrade_workspace_preferences(current)
            if upgraded == current:
                continue
            conn.execute(
                "UPDATE sessions SET preferences_json = ? WHERE id = ?",
                (_json_dumps(upgraded), row["id"]),
            )
            migrated += 1
        return migrated

    def _migrate_workspace_preferences_sync(self) -> int:
        """Run the idempotent data migration under the cross-process lock."""

        with _migration_lock(self.db_path), self._connect() as conn:
            migrated = self._migrate_workspace_preferences(conn)
            conn.commit()
        return migrated

    async def migrate_workspace_preferences(self) -> int:
        """Upgrade legacy Reading/Mastery session metadata for this user scope."""

        return await self._run(self._migrate_workspace_preferences_sync)

    @staticmethod
    def _migrate_turn_runtime_columns(conn: sqlite3.Connection) -> None:
        """Upgrade legacy turn rows to the v2 concurrency contract.

        A partial unique index is the durable last line of defence against two
        processes starting work for the same session.  Legacy databases may
        already contain duplicate running rows, so resolve those deterministically
        before creating the index.
        """
        columns = {row[1] for row in conn.execute("PRAGMA table_info(turns)").fetchall()}
        additions = {
            "owner_id": "TEXT DEFAULT ''",
            "fencing_token": "INTEGER NOT NULL DEFAULT 0",
            "state_version": "INTEGER NOT NULL DEFAULT 1",
            "failure_code": "TEXT DEFAULT ''",
            "retryable": "INTEGER NOT NULL DEFAULT 0",
        }
        for name, definition in additions.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE turns ADD COLUMN {name} {definition}")
        if "assistant_message_id" not in columns:
            conn.execute("ALTER TABLE turns ADD COLUMN assistant_message_id INTEGER")
            # v1.6.3 already persisted DONE with the assistant row id. Recover
            # those links once so old traces can be served from turn_events.
            conn.execute(
                """
                UPDATE turns
                SET assistant_message_id = (
                    SELECT m.id
                    FROM messages AS m, json_each(m.events_json) AS event
                    WHERE m.session_id = turns.session_id
                      AND m.role = 'assistant'
                      AND json_extract(event.value, '$.type') = 'done'
                      AND json_extract(event.value, '$.turn_id') = turns.id
                      AND json_extract(event.value, '$.metadata.assistant_message_id') IS NOT NULL
                    LIMIT 1
                )
                WHERE assistant_message_id IS NULL
                """
            )
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_turns_assistant_message
            ON turns(assistant_message_id)
            WHERE assistant_message_id IS NOT NULL
            """
        )

        duplicate_rows = conn.execute(
            """
            SELECT id, session_id
            FROM turns
            WHERE status IN ('queued', 'running', 'waiting_input')
            ORDER BY session_id, updated_at DESC, id DESC
            """
        ).fetchall()
        seen_sessions: set[str] = set()
        now = time.time()
        for row in duplicate_rows:
            session_id = str(row["session_id"])
            if session_id not in seen_sessions:
                seen_sessions.add(session_id)
                continue
            conn.execute(
                """
                UPDATE turns
                SET status = 'failed', error = ?, failure_code = ?,
                    updated_at = ?, finished_at = ?, state_version = state_version + 1
                WHERE id = ?
                """,
                (
                    "Duplicate active turn resolved during migration",
                    "migration_duplicate_running",
                    now,
                    now,
                    row["id"],
                ),
            )
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_turns_one_active_session
            ON turns(session_id)
            WHERE status IN ('queued', 'running', 'waiting_input')
            """
        )

    @staticmethod
    def _migrate_notebook_entries_add_turn_id(conn: sqlite3.Connection) -> None:
        """Add ``turn_id`` to legacy notebook_entries and re-scope the UNIQUE
        constraint to ``(session_id, turn_id, question_id)``.

        The old unique constraint conflated quizzes generated in the same chat
        (issue #487): regenerating a quiz with the same positional
        ``question_id`` (e.g. ``q_1``) would collide with the previous quiz's
        notebook entries and the UI hydrated stale answers. Scoping by
        ``turn_id`` keeps each quiz isolated.
        """
        notebook_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(notebook_entries)").fetchall()
        }
        if not notebook_cols:
            return
        if "turn_id" not in notebook_cols:
            conn.execute("ALTER TABLE notebook_entries ADD COLUMN turn_id TEXT NOT NULL DEFAULT ''")
        # SQLite stores table-level UNIQUE constraints as auto-indexes whose
        # names start with ``sqlite_autoindex_notebook_entries_``; the columns
        # they cover live in PRAGMA index_info. Detect whether any existing
        # auto-index still covers only (session_id, question_id) and, if so,
        # rebuild the table to swap in the new scope.
        needs_rebuild = False
        for idx_row in conn.execute("PRAGMA index_list(notebook_entries)").fetchall():
            idx_name = idx_row[1]
            if not idx_name.startswith("sqlite_autoindex_notebook_entries_"):
                continue
            cols = [r[2] for r in conn.execute(f"PRAGMA index_info({idx_name})").fetchall()]
            if cols == ["session_id", "question_id"]:
                needs_rebuild = True
                break
        if not needs_rebuild:
            return
        conn.executescript(
            """
            CREATE TABLE notebook_entries_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                turn_id TEXT NOT NULL DEFAULT '',
                question_id TEXT NOT NULL,
                question TEXT NOT NULL,
                question_type TEXT DEFAULT '',
                options_json TEXT DEFAULT '{}',
                correct_answer TEXT DEFAULT '',
                explanation TEXT DEFAULT '',
                difficulty TEXT DEFAULT '',
                user_answer TEXT DEFAULT '',
                is_correct INTEGER DEFAULT 0,
                bookmarked INTEGER DEFAULT 0,
                followup_session_id TEXT DEFAULT '',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                UNIQUE(session_id, turn_id, question_id)
            );

            INSERT INTO notebook_entries_new (
                id, session_id, turn_id, question_id, question, question_type,
                options_json, correct_answer, explanation, difficulty,
                user_answer, is_correct, bookmarked, followup_session_id,
                created_at, updated_at
            )
            SELECT
                id, session_id, COALESCE(turn_id, ''), question_id, question,
                question_type, options_json, correct_answer, explanation,
                difficulty, user_answer, is_correct, bookmarked,
                followup_session_id, created_at, updated_at
            FROM notebook_entries;

            DROP TABLE notebook_entries;
            ALTER TABLE notebook_entries_new RENAME TO notebook_entries;

            CREATE INDEX IF NOT EXISTS idx_notebook_entries_session
                ON notebook_entries(session_id, created_at DESC);

            CREATE INDEX IF NOT EXISTS idx_notebook_entries_bookmarked
                ON notebook_entries(bookmarked, created_at DESC);
            """
        )

    @staticmethod
    def _migrate_notebook_entries_add_user_answer_images(
        conn: sqlite3.Connection,
    ) -> None:
        """Back-fill ``user_answer_images_json`` on legacy DBs.

        The column stores a JSON array of ``{id, url, filename, mime_type}``
        records for image attachments uploaded as part of the learner's
        answer. The bytes themselves live in the AttachmentStore; we only
        keep references in the row so notebook_entries stays lean.
        """
        cols = {row[1] for row in conn.execute("PRAGMA table_info(notebook_entries)").fetchall()}
        if not cols:
            return
        if "user_answer_images_json" not in cols:
            conn.execute(
                "ALTER TABLE notebook_entries ADD COLUMN user_answer_images_json TEXT DEFAULT '[]'"
            )

    @staticmethod
    def _migrate_notebook_entries_add_ai_judgment(
        conn: sqlite3.Connection,
    ) -> None:
        """Back-fill ``ai_judgment`` on legacy DBs.

        Stores the latest AI-judge text per entry as plain markdown. Empty
        string means the learner has not run the AI judge for this entry
        yet.
        """
        cols = {row[1] for row in conn.execute("PRAGMA table_info(notebook_entries)").fetchall()}
        if not cols:
            return
        if "ai_judgment" not in cols:
            conn.execute("ALTER TABLE notebook_entries ADD COLUMN ai_judgment TEXT DEFAULT ''")

    @staticmethod
    def _migrate_notebook_entries_add_assessment_review(
        conn: sqlite3.Connection,
    ) -> None:
        """Add provenance and review-state columns without rewriting history."""
        cols = {row[1] for row in conn.execute("PRAGMA table_info(notebook_entries)").fetchall()}
        if not cols:
            return
        additions = {
            "source": "TEXT NOT NULL DEFAULT 'deep_question'",
            "material_id": "TEXT NOT NULL DEFAULT ''",
            "material_title": "TEXT NOT NULL DEFAULT ''",
            "section_id": "TEXT NOT NULL DEFAULT ''",
            "section_title": "TEXT NOT NULL DEFAULT ''",
            "score_trend": "TEXT NOT NULL DEFAULT 'new'",
            "resolved": "INTEGER DEFAULT 0",
        }
        for name, definition in additions.items():
            if name not in cols:
                conn.execute(f"ALTER TABLE notebook_entries ADD COLUMN {name} {definition}")
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_notebook_entries_review
            ON notebook_entries(source, material_id, resolved, created_at DESC)
            """
        )

    async def _run(self, fn, *args):
        async with self._lock:
            return await asyncio.to_thread(fn, *args)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        # sqlite3.Connection's own context manager commits/rolls back but does
        # NOT close the connection — so naked `with sqlite3.connect(...)` leaks
        # one FD per call until GC. Wrap it so each call site gets both
        # transaction semantics and deterministic close. The inner `with conn`
        # commits on clean exit and rolls back on exception, so call sites do
        # NOT need an explicit conn.commit() (any remaining ones are no-ops).
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _create_session_sync(
        self,
        title: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        resolved_id = session_id or f"unified_{int(now * 1000)}_{uuid.uuid4().hex[:8]}"
        resolved_title = (title or "New conversation").strip() or "New conversation"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions (
                    id, title, created_at, updated_at,
                    compressed_summary, summary_up_to_msg_id
                )
                VALUES (?, ?, ?, ?, '', 0)
                """,
                (resolved_id, resolved_title[:100], now, now),
            )
            conn.commit()
        return {
            "id": resolved_id,
            "session_id": resolved_id,
            "title": resolved_title[:100],
            "created_at": now,
            "updated_at": now,
            "compressed_summary": "",
            "summary_up_to_msg_id": 0,
        }

    async def create_session(
        self,
        title: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        return await self._run(self._create_session_sync, title, session_id)

    def _get_session_sync(self, session_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    s.id,
                    s.title,
                    s.created_at,
                    s.updated_at,
                    s.compressed_summary,
                    s.summary_up_to_msg_id,
                    s.preferences_json,
                    COALESCE(
                        (
                            SELECT t.status
                            FROM turns t
                            WHERE t.session_id = s.id
                            ORDER BY t.updated_at DESC
                            LIMIT 1
                        ),
                        'idle'
                    ) AS status,
                    COALESCE(
                        (
                            SELECT t.id
                            FROM turns t
                            WHERE t.session_id = s.id
                              AND t.status IN ('queued', 'running', 'waiting_input')
                            ORDER BY t.updated_at DESC
                            LIMIT 1
                        ),
                        ''
                    ) AS active_turn_id,
                    COALESCE(
                        (
                            SELECT t.capability
                            FROM turns t
                            WHERE t.session_id = s.id
                            ORDER BY t.updated_at DESC
                            LIMIT 1
                        ),
                        ''
                    ) AS capability
                FROM sessions
                s
                WHERE s.id = ?
                """,
                (session_id,),
            ).fetchone()
        if not row:
            return None
        payload = dict(row)
        payload["session_id"] = payload["id"]
        payload["preferences"] = _json_loads(payload.pop("preferences_json", ""), {})
        return payload

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        return await self._run(self._get_session_sync, session_id)

    async def ensure_session(
        self,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        if session_id:
            session = await self.get_session(session_id)
            if session is not None:
                return session
        return await self.create_session()

    @staticmethod
    def _serialize_turn(row: sqlite3.Row) -> dict[str, Any]:
        return TurnRecord(
            id=row["id"],
            session_id=row["session_id"],
            capability=row["capability"] or "",
            status=row["status"] or "running",
            error=row["error"] or "",
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            finished_at=row["finished_at"],
            last_seq=row["last_seq"] if "last_seq" in row.keys() else 0,
            owner_id=row["owner_id"] if "owner_id" in row.keys() else "",
            fencing_token=(int(row["fencing_token"] or 0) if "fencing_token" in row.keys() else 0),
            state_version=(int(row["state_version"] or 1) if "state_version" in row.keys() else 1),
            failure_code=(row["failure_code"] or "" if "failure_code" in row.keys() else ""),
            retryable=(bool(row["retryable"]) if "retryable" in row.keys() else False),
            assistant_message_id=(
                row["assistant_message_id"] if "assistant_message_id" in row.keys() else None
            ),
        ).to_dict()

    def _begin_turn_sync(
        self,
        session_id: str,
        capability: str = "",
        turn_id: str | None = None,
        owner_id: str = "",
        fencing_token: int = 0,
    ) -> dict[str, Any]:
        now = time.time()
        resolved_turn_id = turn_id or f"turn_{int(now * 1000)}_{uuid.uuid4().hex[:10]}"
        try:
            with self._connect() as conn:
                # Serialize the active-turn check and insert across processes.
                conn.execute("BEGIN IMMEDIATE")
                session = conn.execute(
                    "SELECT id FROM sessions WHERE id = ?", (session_id,)
                ).fetchone()
                if session is None:
                    raise ValueError(f"Session not found: {session_id}")
                active = conn.execute(
                    """
                    SELECT id
                    FROM turns
                    WHERE session_id = ?
                      AND status IN ('queued', 'running', 'waiting_input')
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                    (session_id,),
                ).fetchone()
                if active is not None:
                    raise RuntimeError(f"Session already has an active turn: {active['id']}")
                conn.execute(
                    """
                    INSERT INTO turns (
                        id, session_id, capability, status, error,
                        created_at, updated_at, finished_at, owner_id,
                        fencing_token, state_version, failure_code, retryable
                    ) VALUES (?, ?, ?, 'running', '', ?, ?, NULL, ?, ?, 1, '', 0)
                    """,
                    (
                        resolved_turn_id,
                        session_id,
                        capability or "",
                        now,
                        now,
                        owner_id or "",
                        max(0, int(fencing_token)),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            # The partial unique index wins races where another process inserts
            # after our read but before our insert.
            raise RuntimeError(f"Session already has an active turn: {session_id}") from exc
        return {
            "id": resolved_turn_id,
            "turn_id": resolved_turn_id,
            "session_id": session_id,
            "capability": capability or "",
            "status": "running",
            "error": "",
            "created_at": now,
            "updated_at": now,
            "finished_at": None,
            "last_seq": 0,
            "owner_id": owner_id or "",
            "fencing_token": max(0, int(fencing_token)),
            "state_version": 1,
            "failure_code": "",
            "retryable": False,
        }

    async def begin_turn(
        self,
        session_id: str,
        capability: str = "",
        *,
        turn_id: str | None = None,
        owner_id: str = "",
        fencing_token: int = 0,
    ) -> dict[str, Any]:
        return await self._run(
            self._begin_turn_sync,
            session_id,
            capability,
            turn_id,
            owner_id,
            fencing_token,
        )

    async def create_turn(self, session_id: str, capability: str = "") -> dict[str, Any]:
        return await self.begin_turn(session_id, capability)

    def _get_turn_sync(self, turn_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    t.*,
                    COALESCE((SELECT MAX(seq) FROM turn_events te WHERE te.turn_id = t.id), 0) AS last_seq
                FROM turns t
                WHERE t.id = ?
                """,
                (turn_id,),
            ).fetchone()
        if row is None:
            return None
        return self._serialize_turn(row)

    async def get_turn(self, turn_id: str) -> dict[str, Any] | None:
        return await self._run(self._get_turn_sync, turn_id)

    def _get_active_turn_sync(self, session_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    t.*,
                    COALESCE((SELECT MAX(seq) FROM turn_events te WHERE te.turn_id = t.id), 0) AS last_seq
                FROM turns t
                WHERE t.session_id = ?
                  AND t.status IN ('queued', 'running', 'waiting_input')
                ORDER BY t.updated_at DESC
                LIMIT 1
                """,
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return self._serialize_turn(row)

    async def get_active_turn(self, session_id: str) -> dict[str, Any] | None:
        return await self._run(self._get_active_turn_sync, session_id)

    def _list_active_turns_sync(self, session_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    t.*,
                    COALESCE((SELECT MAX(seq) FROM turn_events te WHERE te.turn_id = t.id), 0) AS last_seq
                FROM turns t
                WHERE t.session_id = ?
                  AND t.status IN ('queued', 'running', 'waiting_input')
                ORDER BY t.updated_at DESC
                """,
                (session_id,),
            ).fetchall()
        return [self._serialize_turn(row) for row in rows]

    async def list_active_turns(self, session_id: str) -> list[dict[str, Any]]:
        return await self._run(self._list_active_turns_sync, session_id)

    def _list_nonterminal_turns_sync(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    t.*,
                    COALESCE((SELECT MAX(seq) FROM turn_events te WHERE te.turn_id = t.id), 0)
                        AS last_seq
                FROM turns t
                WHERE t.status IN ('queued', 'running', 'waiting_input')
                ORDER BY t.updated_at ASC
                """
            ).fetchall()
        return [self._serialize_turn(row) for row in rows]

    async def list_nonterminal_turns(self) -> list[dict[str, Any]]:
        return await self._run(self._list_nonterminal_turns_sync)

    def _transition_turn_sync(
        self,
        turn_id: str,
        status: str,
        expected_status: str | None = None,
        fencing_token: int | None = None,
        error: str = "",
        failure_code: str = "",
        retryable: bool = False,
    ) -> bool:
        if status not in ALL_TURN_STATUSES:
            raise ValueError(f"Unsupported turn status: {status}")
        now = time.time()
        finished_at = now if status in TERMINAL_TURN_STATUSES else None
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = conn.execute(
                "SELECT status, fencing_token FROM turns WHERE id = ?", (turn_id,)
            ).fetchone()
            if current is None:
                return False
            if expected_status is not None and current["status"] != expected_status:
                return False
            if fencing_token is not None and int(current["fencing_token"] or 0) != int(
                fencing_token
            ):
                return False
            if current["status"] in TERMINAL_TURN_STATUSES and current["status"] != status:
                return False
            cur = conn.execute(
                """
                UPDATE turns
                SET status = ?, error = ?, failure_code = ?, updated_at = ?,
                    finished_at = ?, state_version = state_version + 1, retryable = ?
                WHERE id = ?
                """,
                (
                    status,
                    error or "",
                    failure_code or "",
                    now,
                    finished_at,
                    int(bool(retryable)),
                    turn_id,
                ),
            )
        return cur.rowcount > 0

    async def transition_turn(
        self,
        turn_id: str,
        status: str,
        *,
        expected_status: str | None = None,
        fencing_token: int | None = None,
        error: str = "",
        failure_code: str = "",
        retryable: bool = False,
    ) -> bool:
        return await self._run(
            self._transition_turn_sync,
            turn_id,
            status,
            expected_status,
            fencing_token,
            error,
            failure_code,
            retryable,
        )

    async def update_turn_status(self, turn_id: str, status: str, error: str = "") -> bool:
        return await self.transition_turn(turn_id, status, error=error)

    @staticmethod
    def _event_matches_row(event: dict[str, Any], row: sqlite3.Row) -> bool:
        return (
            str(event.get("type", "")) == (row["type"] or "")
            and str(event.get("source", "")) == (row["source"] or "")
            and str(event.get("stage", "")) == (row["stage"] or "")
            and str(event.get("content", "") or "") == (row["content"] or "")
            and (event.get("metadata") or {}) == _json_loads(row["metadata_json"], {})
        )

    @staticmethod
    def _turn_event_row_to_payload(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "type": row["type"],
            "source": row["source"] or "",
            "stage": row["stage"] or "",
            "content": row["content"] or "",
            "metadata": _json_loads(row["metadata_json"], {}),
            "session_id": "",
            "turn_id": row["turn_id"],
            "seq": row["seq"],
            "timestamp": row["timestamp"],
        }

    def _append_turn_events_sync(
        self,
        turn_id: str,
        events: list[dict[str, Any]],
        fencing_token: int | None = None,
    ) -> list[dict[str, Any]]:
        # Batch variant of _append_turn_event_sync: one transaction for the whole
        # post-stream flush instead of one fsync'd commit per event. On slow
        # storage (e.g. NAS spinning disks) per-event commits stretch a turn's
        # finalisation to minutes while the client spinner keeps running.
        now = time.time()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            turn = conn.execute(
                "SELECT id, session_id, fencing_token FROM turns WHERE id = ?", (turn_id,)
            ).fetchone()
            if turn is None:
                raise ValueError(f"Turn not found: {turn_id}")
            if fencing_token is not None and int(turn["fencing_token"] or 0) != int(fencing_token):
                raise RuntimeError(f"Turn lease lost: {turn_id}")
            row = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) AS last_seq FROM turn_events WHERE turn_id = ?",
                (turn_id,),
            ).fetchone()
            next_seq = (int(row["last_seq"]) if row else 0) + 1
            payloads: list[dict[str, Any]] = []
            for event in events:
                provided_seq = int(event.get("seq") or 0)
                if provided_seq > 0:
                    seq = provided_seq
                    next_seq = max(next_seq, provided_seq + 1)
                else:
                    seq = next_seq
                    next_seq += 1
                payload = dict(event)
                payload["seq"] = seq
                payload["turn_id"] = payload.get("turn_id") or turn_id
                payload["session_id"] = payload.get("session_id") or turn["session_id"]
                existing = conn.execute(
                    """
                    SELECT type, source, stage, content, metadata_json, timestamp
                    FROM turn_events WHERE turn_id = ? AND seq = ?
                    """,
                    (turn_id, seq),
                ).fetchone()
                if existing is not None:
                    if not self._event_matches_row(payload, existing):
                        raise ValueError(f"Turn event conflict: {turn_id} seq={seq}")
                    payload["timestamp"] = existing["timestamp"]
                    payloads.append(payload)
                    continue
                timestamp = float(payload.get("timestamp") or now)
                payload["timestamp"] = timestamp
                payloads.append(payload)
                conn.execute(
                    """
                    INSERT INTO turn_events (
                        turn_id, seq, type, source, stage, content,
                        metadata_json, timestamp, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        turn_id,
                        seq,
                        payload.get("type", ""),
                        payload.get("source", ""),
                        payload.get("stage", ""),
                        payload.get("content", "") or "",
                        _json_dumps(payload.get("metadata", {})),
                        timestamp,
                        now,
                    ),
                )
            if events:
                conn.execute(
                    "UPDATE turns SET updated_at = ? WHERE id = ?",
                    (now, turn_id),
                )
        return payloads

    async def append_events(
        self,
        turn_id: str,
        events: list[dict[str, Any]],
        *,
        fencing_token: int | None = None,
    ) -> list[dict[str, Any]]:
        return await self._run(
            self._append_turn_events_sync,
            turn_id,
            events,
            fencing_token,
        )

    async def append_turn_event(self, turn_id: str, event: dict[str, Any]) -> dict[str, Any]:
        payloads = await self.append_events(turn_id, [event])
        return payloads[0]

    async def append_turn_events(
        self, turn_id: str, events: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        return await self.append_events(turn_id, events)

    def _get_turn_events_sync(self, turn_id: str, after_seq: int = 0) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT turn_id, seq, type, source, stage, content, metadata_json, timestamp
                FROM turn_events
                WHERE turn_id = ? AND seq > ?
                ORDER BY seq ASC
                """,
                (turn_id, max(0, int(after_seq))),
            ).fetchall()
            turn = conn.execute("SELECT session_id FROM turns WHERE id = ?", (turn_id,)).fetchone()
        session_id = turn["session_id"] if turn else ""
        return [
            {
                "type": row["type"],
                "source": row["source"] or "",
                "stage": row["stage"] or "",
                "content": row["content"] or "",
                "metadata": _json_loads(row["metadata_json"], {}),
                "session_id": session_id,
                "turn_id": row["turn_id"],
                "seq": row["seq"],
                "timestamp": row["timestamp"],
            }
            for row in rows
        ]

    async def get_turn_events(self, turn_id: str, after_seq: int = 0) -> list[dict[str, Any]]:
        return await self._run(self._get_turn_events_sync, turn_id, after_seq)

    async def get_events(self, turn_id: str, after_seq: int = 0) -> list[dict[str, Any]]:
        return await self.get_turn_events(turn_id, after_seq)

    def _link_turn_message_sync(self, turn_id: str, assistant_message_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE turns
                SET assistant_message_id = ?, updated_at = ?
                WHERE id = ?
                  AND session_id = (SELECT session_id FROM messages WHERE id = ?)
                  AND assistant_message_id IS NULL
                """,
                (int(assistant_message_id), time.time(), turn_id, int(assistant_message_id)),
            )
            conn.commit()
        return cur.rowcount > 0

    async def link_turn_message(self, turn_id: str, assistant_message_id: int) -> bool:
        return await self._run(self._link_turn_message_sync, turn_id, int(assistant_message_id))

    def _get_message_trace_sync(
        self,
        session_id: str,
        message_id: int,
        after_seq: int = 0,
        limit: int | None = None,
    ) -> dict[str, Any] | None:
        row_limit = 500 if limit is None else min(1000, max(1, int(limit)))
        with self._connect() as conn:
            message = conn.execute(
                """
                SELECT m.id, m.role, t.id AS turn_id
                FROM messages AS m
                LEFT JOIN turns AS t ON t.assistant_message_id = m.id
                WHERE m.id = ? AND m.session_id = ?
                """,
                (int(message_id), session_id),
            ).fetchone()
            if message is None:
                return None
            turn_id = message["turn_id"]
            if turn_id is None:
                return {
                    "session_id": session_id,
                    "message_id": int(message_id),
                    "turn_id": None,
                    "events": [],
                    "total": 0,
                    "last_seq": 0,
                    "next_seq": None,
                    "complete": True,
                }
            turn = conn.execute("SELECT session_id FROM turns WHERE id = ?", (turn_id,)).fetchone()
            stats = conn.execute(
                """
                SELECT COUNT(*) AS total, COALESCE(MAX(seq), 0) AS last_seq
                FROM turn_events WHERE turn_id = ?
                """,
                (turn_id,),
            ).fetchone()
            rows = conn.execute(
                """
                SELECT turn_id, seq, type, source, stage, content, metadata_json, timestamp
                FROM turn_events
                WHERE turn_id = ? AND seq > ?
                ORDER BY seq ASC
                LIMIT ?
                """,
                (turn_id, max(0, int(after_seq)), row_limit),
            ).fetchall()
            events = [self._turn_event_row_to_payload(row) for row in rows]
            for event in events:
                event["session_id"] = turn["session_id"] if turn else ""
            last_loaded = events[-1]["seq"] if events else int(after_seq)
            complete = last_loaded >= int(stats["last_seq"])
            return {
                "session_id": session_id,
                "message_id": int(message_id),
                "turn_id": turn_id,
                "events": events,
                "total": int(stats["total"]),
                "last_seq": int(stats["last_seq"]),
                "next_seq": None if complete else last_loaded,
                "complete": complete,
            }

    async def get_message_trace(
        self,
        session_id: str,
        message_id: int | str,
        after_seq: int = 0,
        limit: int | None = None,
    ) -> dict[str, Any] | None:
        try:
            resolved_message_id = int(message_id)
        except (TypeError, ValueError):
            return None
        return await self._run(
            self._get_message_trace_sync,
            session_id,
            resolved_message_id,
            after_seq,
            limit,
        )

    def _update_session_title_sync(self, session_id: str, title: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE sessions
                SET title = ?, updated_at = ?
                WHERE id = ?
                """,
                ((title.strip() or "New conversation")[:100], time.time(), session_id),
            )
            conn.commit()
        return cur.rowcount > 0

    async def update_session_title(self, session_id: str, title: str) -> bool:
        return await self._run(self._update_session_title_sync, session_id, title)

    def _delete_session_sync(self, session_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            conn.commit()
        return cur.rowcount > 0

    async def delete_session(self, session_id: str) -> bool:
        return await self._run(self._delete_session_sync, session_id)

    def _add_message_sync(
        self,
        session_id: str,
        role: str,
        content: str,
        capability: str = "",
        events: list[dict[str, Any]] | None = None,
        attachments: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
        parent_message_id: int | str | None | _Unset = _PARENT_AUTO,
    ) -> int:
        now = time.time()
        with self._connect() as conn:
            session = conn.execute(
                "SELECT id, title FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if session is None:
                raise ValueError(f"Session not found: {session_id}")

            resolved_parent_id: int | None
            if isinstance(parent_message_id, _Unset):
                # Legacy auto-append path: chain off the latest row in the
                # session so the linear thread stays connected.
                last_row = conn.execute(
                    "SELECT id FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT 1",
                    (session_id,),
                ).fetchone()
                resolved_parent_id = int(last_row["id"]) if last_row is not None else None
            else:
                # Caller pinned a parent explicitly — including ``None``,
                # which means "attach at the session root" (used by edits
                # of the very first message in a session).
                resolved_parent_id = (
                    int(parent_message_id) if parent_message_id is not None else None
                )

            cur = conn.execute(
                """
                INSERT INTO messages (
                    session_id, role, content, capability, events_json,
                    attachments_json, metadata_json, created_at, parent_message_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    role,
                    content or "",
                    capability or "",
                    _json_dumps(events or []),
                    _json_dumps(attachments or []),
                    _json_dumps(metadata or {}),
                    now,
                    resolved_parent_id,
                ),
            )

            # Title is no longer derived from the first user message — the
            # turn runtime calls an LLM to generate a real summary title
            # once the first user+assistant pair is complete. Until then
            # the session keeps the default sentinel ``New conversation``
            # which the frontend renders as a breathing "New chat" chip.
            conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (now, session_id),
            )
            conn.commit()
            return int(cur.lastrowid)

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        capability: str = "",
        events: list[dict[str, Any]] | None = None,
        attachments: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
        # ``str`` satisfies SessionStoreProtocol (PocketBase parents are string
        # record ids); on the SQLite backend a non-None parent is always the
        # integer rowid this store itself returned.
        parent_message_id: int | str | None | _Unset = _PARENT_AUTO,
    ) -> int:
        return await self._run(
            self._add_message_sync,
            session_id,
            role,
            content,
            capability,
            events,
            attachments,
            metadata,
            parent_message_id,
        )

    @staticmethod
    def _backfill_import_meta_sync(
        conn: sqlite3.Connection,
        session_id: str,
        current_prefs_json: str | None,
        incoming_prefs: dict[str, Any],
    ) -> bool:
        """Merge agent attribution from a re-import into an existing session's
        ``preferences.import`` block, leaving everything else untouched. Returns
        whether anything changed (so the caller can skip a needless write)."""
        incoming_import = (incoming_prefs or {}).get("import") or {}
        if not incoming_import:
            return False
        prefs = _json_loads(current_prefs_json, {})
        if not isinstance(prefs, dict):
            prefs = {}
        meta = dict(prefs.get("import") or {})
        changed = False
        # Only attribution fields propagate on re-import; source/external_id are
        # part of the dedup identity and never change for a given session.
        for key in ("agent_id", "agent_name", "source_cwd"):
            value = incoming_import.get(key)
            if value and meta.get(key) != value:
                meta[key] = value
                changed = True
        if not changed:
            return False
        prefs["import"] = meta
        conn.execute(
            "UPDATE sessions SET preferences_json = ? WHERE id = ?",
            (_json_dumps(prefs), session_id),
        )
        return True

    def _import_session_sync(
        self,
        session_id: str,
        title: str,
        created_at: float,
        updated_at: float,
        preferences: dict[str, Any],
        messages: list[dict[str, Any]],
    ) -> dict[str, Any]:
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT preferences_json FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if existing is not None:
                # Idempotent on content: a session imported before keeps its
                # (possibly already-continued) state — re-importing the same
                # folder never duplicates rows or clobbers the user's edits.
                # We do, however, backfill agent attribution (agent_id /
                # agent_name) so re-syncing re-tags conversations that were
                # imported before the agent model existed, and an agent rename
                # propagates. This only touches the ``import`` metadata block.
                updated = self._backfill_import_meta_sync(
                    conn, session_id, existing["preferences_json"], preferences
                )
                if updated:
                    conn.commit()
                return {
                    "session_id": session_id,
                    "imported": False,
                    "updated": updated,
                    "message_count": 0,
                }
            safe_title = (title or "").strip()[:100] or "Imported conversation"
            conn.execute(
                """
                INSERT INTO sessions (
                    id, title, created_at, updated_at,
                    compressed_summary, summary_up_to_msg_id, preferences_json
                ) VALUES (?, ?, ?, ?, '', 0, ?)
                """,
                (session_id, safe_title, created_at, updated_at, _json_dumps(preferences or {})),
            )
            prev_id: int | None = None
            count = 0
            for msg in messages:
                cur = conn.execute(
                    """
                    INSERT INTO messages (
                        session_id, role, content, capability, events_json,
                        attachments_json, metadata_json, created_at, parent_message_id
                    ) VALUES (?, ?, ?, '', '[]', '[]', ?, ?, ?)
                    """,
                    (
                        session_id,
                        msg.get("role") or "user",
                        msg.get("content") or "",
                        _json_dumps(msg.get("metadata") or {}),
                        float(msg.get("created_at") or created_at),
                        prev_id,
                    ),
                )
                prev_id = int(cur.lastrowid)
                count += 1
            conn.commit()
        return {"session_id": session_id, "imported": True, "message_count": count}

    async def import_session(
        self,
        session_id: str,
        title: str,
        created_at: float,
        updated_at: float,
        preferences: dict[str, Any] | None,
        messages: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Persist a pre-existing conversation (imported from an external CLI
        such as Claude Code or Codex) as a normal session, so the chat loop can
        re-open and continue it. ``session_id`` must carry the ``imported_``
        prefix (see :data:`_IMPORTED_ID_PREFIX`). Idempotent by id: a session
        already present is left untouched.
        """
        return await self._run(
            self._import_session_sync,
            session_id,
            title,
            created_at,
            updated_at,
            preferences or {},
            messages,
        )

    async def import_legacy_session(
        self,
        session_id: str,
        title: str,
        created_at: float,
        updated_at: float,
        preferences: dict[str, Any],
        messages: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Import one v1 JSON chat without overwriting an existing session."""

        return await self.import_session(
            session_id,
            title,
            created_at,
            updated_at,
            preferences,
            messages,
        )

    def _delete_message_sync(self, message_id: int | str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM messages WHERE id = ?", (int(message_id),))
            conn.commit()
        return cur.rowcount > 0

    async def delete_message(self, message_id: int | str) -> bool:
        return await self._run(self._delete_message_sync, message_id)

    def _delete_turn_by_message_sync(self, session_id: str, message_id: int) -> dict[str, Any]:
        with self._connect() as conn:
            msg = conn.execute(
                """
                SELECT id, session_id, role, attachments_json, created_at
                FROM messages
                WHERE id = ?
                """,
                (int(message_id),),
            ).fetchone()
            if msg is None or msg["session_id"] != session_id:
                return {
                    "deleted": False,
                    "attachment_ids": [],
                    "turn_id": None,
                    "was_running": False,
                }

            role = msg["role"]
            paired_msg = None
            if role == "user":
                paired_msg = conn.execute(
                    """
                    SELECT id, session_id, role, attachments_json, created_at
                    FROM messages
                    WHERE session_id = ? AND role = 'assistant' AND id > ?
                    ORDER BY id ASC
                    LIMIT 1
                    """,
                    (session_id, int(message_id)),
                ).fetchone()
            elif role == "assistant":
                paired_msg = conn.execute(
                    """
                    SELECT id, session_id, role, attachments_json, created_at
                    FROM messages
                    WHERE session_id = ? AND role = 'user' AND id < ?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (session_id, int(message_id)),
                ).fetchone()

            user_msg = msg if role == "user" else paired_msg
            turn_id = None
            was_running = False
            if user_msg is not None:
                user_created_at = user_msg["created_at"]
                turn_row = conn.execute(
                    """
                    SELECT id, status
                    FROM turns
                    WHERE session_id = ? AND created_at >= ?
                    ORDER BY created_at ASC
                    LIMIT 1
                    """,
                    (session_id, user_created_at),
                ).fetchone()
                if turn_row is not None:
                    turn_id = turn_row["id"]
                    was_running = turn_row["status"] == "running"

            if was_running:
                return {
                    "deleted": False,
                    "attachment_ids": [],
                    "turn_id": turn_id,
                    "was_running": True,
                }

            attachment_ids: list[str] = []
            for m in [msg, paired_msg]:
                if m is not None:
                    atts = _json_loads(m["attachments_json"], [])
                    for att in atts:
                        aid = att.get("id") or att.get("attachment_id")
                        if aid:
                            attachment_ids.append(aid)

            if turn_id is not None:
                conn.execute("DELETE FROM turn_events WHERE turn_id = ?", (turn_id,))
                conn.execute("DELETE FROM turns WHERE id = ?", (turn_id,))

            ids_to_delete = [int(message_id)]
            if paired_msg is not None:
                ids_to_delete.append(int(paired_msg["id"]))

            # Splice the deleted rows out of the parent-pointer tree: children
            # of a deleted row inherit its parent, in descending id order so a
            # pair's subtree rides up to the pair's parent in one pass (#912).
            for mid in sorted(ids_to_delete, reverse=True):
                conn.execute(
                    """
                    UPDATE messages
                    SET parent_message_id = (
                        SELECT parent_message_id FROM messages WHERE id = ?
                    )
                    WHERE session_id = ? AND parent_message_id = ?
                    """,
                    (mid, session_id, mid),
                )

            conn.execute(
                f"DELETE FROM messages WHERE id IN ({','.join('?' * len(ids_to_delete))})",  # nosec B608
                tuple(ids_to_delete),
            )

            session_row = conn.execute(
                "SELECT summary_up_to_msg_id FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if session_row is not None:
                summary_up_to = int(session_row["summary_up_to_msg_id"])
                if any(mid <= summary_up_to for mid in ids_to_delete):
                    conn.execute(
                        "UPDATE sessions SET summary_up_to_msg_id = 0 WHERE id = ?",
                        (session_id,),
                    )

            conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (time.time(), session_id),
            )
            conn.commit()

        return {
            "deleted": True,
            "attachment_ids": attachment_ids,
            "turn_id": turn_id,
            "was_running": was_running,
        }

    async def delete_turn_by_message(self, session_id: str, message_id: int) -> dict[str, Any]:
        return await self._run(self._delete_turn_by_message_sync, session_id, message_id)

    def _get_last_message_sync(
        self, session_id: str, role: str | None = None
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            if role is None:
                row = conn.execute(
                    """
                    SELECT id, session_id, role, content, capability, events_json,
                           attachments_json, metadata_json, created_at, parent_message_id
                    FROM messages
                    WHERE session_id = ?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (session_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT id, session_id, role, content, capability, events_json,
                           attachments_json, metadata_json, created_at, parent_message_id
                    FROM messages
                    WHERE session_id = ? AND role = ?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (session_id, role),
                ).fetchone()
        if row is None:
            return None
        return self._serialize_message(row)

    async def get_last_message(
        self, session_id: str, role: str | None = None
    ) -> dict[str, Any] | None:
        return await self._run(self._get_last_message_sync, session_id, role)

    def _serialize_message(
        self,
        row: sqlite3.Row,
        events: list[dict[str, Any]] | None = None,
        trace: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row_keys = row.keys()
        parent_id = row["parent_message_id"] if "parent_message_id" in row_keys else None
        return {
            "id": row["id"],
            "session_id": row["session_id"],
            "role": row["role"],
            "content": row["content"],
            "capability": row["capability"] or "",
            "events": _json_loads(row["events_json"], []) if events is None else events,
            "attachments": _json_loads(row["attachments_json"], []),
            "metadata": _json_loads(row["metadata_json"], {}),
            "created_at": row["created_at"],
            "parent_message_id": int(parent_id) if parent_id is not None else None,
            **({"trace": trace} if trace is not None else {}),
        }

    def _canonical_trace_preview_sync(
        self,
        conn: sqlite3.Connection,
        turn_id: str,
        session_id: str,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        stats = conn.execute(
            """
            SELECT COUNT(*) AS total, COALESCE(MAX(seq), 0) AS last_seq
            FROM turn_events WHERE turn_id = ?
            """,
            (turn_id,),
        ).fetchone()
        # Preview queries stay bounded even for a very long agentic turn. The
        # critical query reserves older terminal/result/ask-user state; the
        # semantic query fills the remaining tail with tool activity.
        columns = "turn_id, seq, type, source, stage, content, metadata_json, timestamp"
        ask_user = """
            json_extract(metadata_json, '$.ask_user') IS NOT NULL
            OR json_extract(metadata_json, '$.ask_user_resolved') IS NOT NULL
            OR json_extract(metadata_json, '$.tool_metadata.ask_user') IS NOT NULL
        """
        conditions = (
            f"type IN ('done', 'error', 'cancelled', 'result') OR {ask_user}",
            f"type IN ('done', 'error', 'cancelled', 'result', 'tool_call', 'tool_result') OR {ask_user}",
        )
        rows_by_seq: dict[int, sqlite3.Row] = {}
        for condition in conditions:
            rows = conn.execute(
                f"""
                SELECT {columns}
                FROM turn_events
                WHERE turn_id = ? AND ({condition})
                ORDER BY seq DESC
                LIMIT ?
                """,
                (turn_id, MAX_TRACE_PREVIEW_EVENTS),
            ).fetchall()
            rows_by_seq.update({int(row["seq"]): row for row in rows})
        events = [self._turn_event_row_to_payload(rows_by_seq[seq]) for seq in sorted(rows_by_seq)]
        for event in events:
            event["session_id"] = session_id
        preview, compacted = compact_trace_preview(events)
        total = int(stats["total"])
        metadata = {
            "turn_id": turn_id,
            "total": total,
            "last_seq": int(stats["last_seq"]),
            "truncated": compacted or total != len(preview),
        }
        return preview, metadata

    def _legacy_trace_preview_sync(
        self, events: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        preview, omitted = compact_trace_preview(events)
        return preview, {
            "turn_id": None,
            "total": len(events),
            "last_seq": max([int(event.get("seq") or 0) for event in events] or [0]),
            "truncated": omitted,
        }

    def _ask_user_events_sync(
        self, conn: sqlite3.Connection, turn_id: str, session_id: str
    ) -> list[dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT turn_id, seq, type, source, stage, content, metadata_json, timestamp
            FROM turn_events
            WHERE turn_id = ?
              AND (
                json_extract(metadata_json, '$.ask_user') IS NOT NULL
                OR json_extract(metadata_json, '$.ask_user_resolved') IS NOT NULL
                OR json_extract(metadata_json, '$.tool_metadata.ask_user') IS NOT NULL
              )
            ORDER BY seq DESC
            LIMIT ?
            """,
            (turn_id, MAX_TRACE_PREVIEW_EVENTS),
        ).fetchall()
        events = [self._turn_event_row_to_payload(row) for row in reversed(rows)]
        for event in events:
            event["session_id"] = session_id
        return events

    def _get_messages_sync(self, session_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT m.id, m.session_id, m.role, m.content, m.capability,
                       m.events_json, m.attachments_json, m.metadata_json,
                       m.created_at, m.parent_message_id, t.id AS trace_turn_id
                FROM messages AS m
                LEFT JOIN turns AS t ON t.assistant_message_id = m.id
                WHERE m.session_id = ?
                ORDER BY m.id ASC
                """,
                (session_id,),
            ).fetchall()
            result: list[dict[str, Any]] = []
            for row in rows:
                turn_id = row["trace_turn_id"]
                if row["role"] == "assistant" and turn_id is not None:
                    events, trace = self._canonical_trace_preview_sync(conn, turn_id, session_id)
                    result.append(self._serialize_message(row, events=events, trace=trace))
                    continue
                legacy_events = _json_loads(row["events_json"], [])
                if row["role"] == "assistant" and isinstance(legacy_events, list):
                    events, trace = self._legacy_trace_preview_sync(legacy_events)
                    result.append(
                        self._serialize_message(
                            row,
                            events=events,
                            trace=trace,
                        )
                    )
                    continue
                result.append(self._serialize_message(row))
        return result

    def _get_message_path_sync(self, session_id: str, leaf_message_id: int) -> list[dict[str, Any]]:
        """Return the chain of messages from the session root down to
        ``leaf_message_id`` (inclusive), in chronological order.

        Used by the turn runtime to build LLM context for a branched
        re-run: only ancestors of the new user message are included, so
        sibling branches at any depth are excluded.
        """
        with self._connect() as conn:
            chain: list[dict[str, Any]] = []
            current: int | None = int(leaf_message_id)
            # Bound the walk defensively in case of corrupted parent pointers.
            safety = 10_000
            while current is not None and safety > 0:
                row = conn.execute(
                    """
                    SELECT id, session_id, role, content, capability, events_json,
                           attachments_json, metadata_json, created_at, parent_message_id
                    FROM messages
                    WHERE id = ? AND session_id = ?
                    """,
                    (current, session_id),
                ).fetchone()
                if row is None:
                    break
                chain.append(self._serialize_message(row))
                parent = row["parent_message_id"]
                current = int(parent) if parent is not None else None
                safety -= 1
        chain.reverse()
        return chain

    async def get_message_path(self, session_id: str, leaf_message_id: int) -> list[dict[str, Any]]:
        return await self._run(self._get_message_path_sync, session_id, int(leaf_message_id))

    async def get_messages(self, session_id: str) -> list[dict[str, Any]]:
        return await self._run(self._get_messages_sync, session_id)

    def _get_messages_for_context_sync(
        self, session_id: str, leaf_message_id: int | None = None
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if leaf_message_id is None:
                rows = conn.execute(
                    """
                    SELECT m.id, m.role, m.content, m.events_json, m.metadata_json, t.id AS turn_id
                    FROM messages AS m
                    LEFT JOIN turns AS t ON t.assistant_message_id = m.id
                    WHERE m.session_id = ?
                      AND m.role IN ('user', 'assistant', 'system')
                    ORDER BY m.id ASC
                    """,
                    (session_id,),
                ).fetchall()
                return [
                    {
                        "id": row["id"],
                        "role": row["role"],
                        "content": row["content"] or "",
                        "events": (
                            self._ask_user_events_sync(conn, row["turn_id"], session_id)
                            if row["turn_id"] is not None
                            else select_ask_user_events(row["events_json"])
                        ),
                        "metadata": _json_loads(row["metadata_json"], {}),
                    }
                    for row in rows
                ]
            # Branch-aware path walk: include only ancestors (+ leaf) so
            # sibling branches at any depth are excluded from LLM context.
            chain: list[dict[str, Any]] = []
            current: int | None = int(leaf_message_id)
            safety = 10_000
            while current is not None and safety > 0:
                row = conn.execute(
                    """
                    SELECT m.id, m.role, m.content, m.events_json, m.metadata_json,
                           m.parent_message_id, t.id AS turn_id
                    FROM messages AS m
                    LEFT JOIN turns AS t ON t.assistant_message_id = m.id
                    WHERE m.id = ? AND m.session_id = ?
                      AND m.role IN ('user', 'assistant', 'system')
                    """,
                    (current, session_id),
                ).fetchone()
                if row is None:
                    break
                chain.append(
                    {
                        "id": row["id"],
                        "role": row["role"],
                        "content": row["content"] or "",
                        "events": (
                            self._ask_user_events_sync(conn, row["turn_id"], session_id)
                            if row["turn_id"] is not None
                            else select_ask_user_events(row["events_json"])
                        ),
                        "metadata": _json_loads(row["metadata_json"], {}),
                    }
                )
                parent = row["parent_message_id"]
                current = int(parent) if parent is not None else None
                safety -= 1
        chain.reverse()
        return chain

    async def get_messages_for_context(
        self, session_id: str, leaf_message_id: int | None = None
    ) -> list[dict[str, Any]]:
        return await self._run(self._get_messages_for_context_sync, session_id, leaf_message_id)

    # Imported conversations live in the same tables as native chats (so the
    # chat loop can re-open and continue them) but carry an ``imported_`` id
    # prefix. That prefix is the discriminator — it travels with the primary
    # key, so we filter on it instead of adding a column + migration.
    _SESSION_SUMMARY_SQL = """
        SELECT
            s.id,
            s.title,
            s.created_at,
            s.updated_at,
            s.compressed_summary,
            s.summary_up_to_msg_id,
            s.preferences_json,
            COUNT(CASE WHEN m.role != 'system' THEN 1 END) AS message_count,
            COALESCE(
                (SELECT t.status FROM turns t WHERE t.session_id = s.id
                 ORDER BY t.updated_at DESC LIMIT 1),
                'idle'
            ) AS status,
            COALESCE(
                (SELECT t.id FROM turns t WHERE t.session_id = s.id
                    AND t.status IN ('queued', 'running', 'waiting_input')
                 ORDER BY t.updated_at DESC LIMIT 1),
                ''
            ) AS active_turn_id,
            COALESCE(
                (SELECT t.capability FROM turns t WHERE t.session_id = s.id
                 ORDER BY t.updated_at DESC LIMIT 1),
                ''
            ) AS capability,
            COALESCE(
                (SELECT m2.content FROM messages m2
                 WHERE m2.session_id = s.id AND m2.role != 'system'
                   AND TRIM(COALESCE(m2.content, '')) != ''
                 ORDER BY m2.id DESC LIMIT 1),
                ''
            ) AS last_message
        FROM sessions s
        LEFT JOIN messages m ON m.session_id = s.id
        {where}
        GROUP BY s.id
        ORDER BY s.updated_at DESC
        LIMIT ? OFFSET ?
    """

    # ``ESCAPE '\'`` makes the underscore in ``imported_`` literal rather than
    # the LIKE single-char wildcard.
    #
    # Reading conversations used to be filtered out here. They were hidden
    # because a flat "Recents" list mixed them in with ordinary chats and
    # clicking one dropped the reader into the generic chat surface without
    # their material — but
    # hiding them meant a learner had no way back to a reading conversation
    # except by reopening its collection. The sidebar now files them under
    # their collection and ``sessionRoute`` sends a click back to the reader,
    # so they belong in the list like everything else.
    _WHERE_NATIVE = r"""
        WHERE s.id NOT LIKE 'imported\_%' ESCAPE '\'
    """
    _WHERE_IMPORTED = r"WHERE s.id LIKE 'imported\_%' ESCAPE '\'"

    def _list_session_summaries_sync(
        self, where_sql: str, limit: int, offset: int
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                self._SESSION_SUMMARY_SQL.format(where=where_sql),
                (limit, offset),
            ).fetchall()
        return [self._session_summary_payload(row) for row in rows]

    @staticmethod
    def _session_summary_payload(row: sqlite3.Row) -> dict[str, Any]:
        payload = dict(row)
        payload["session_id"] = payload["id"]
        payload["preferences"] = _json_loads(payload.pop("preferences_json", ""), {})
        return payload

    def _get_session_summaries_sync(
        self,
        session_ids: list[str],
    ) -> list[dict[str, Any]]:
        ids = list(dict.fromkeys(str(item or "").strip() for item in session_ids))
        ids = [item for item in ids if item]
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        where = f"WHERE s.id IN ({placeholders})"
        with self._connect() as conn:
            rows = conn.execute(
                self._SESSION_SUMMARY_SQL.format(where=where),
                (*ids, len(ids), 0),
            ).fetchall()
        return [self._session_summary_payload(row) for row in rows]

    def _list_sessions_sync(
        self,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        # Native chats only — imported histories surface under their own
        # Space category, not the regular history list.
        return self._list_session_summaries_sync(self._WHERE_NATIVE, limit, offset)

    def _list_imported_sessions_sync(
        self,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        return self._list_session_summaries_sync(self._WHERE_IMPORTED, limit, offset)

    async def list_sessions(
        self,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        return await self._run(self._list_sessions_sync, limit, offset)

    async def get_session_summaries(
        self,
        session_ids: list[str],
    ) -> list[dict[str, Any]]:
        return await self._run(self._get_session_summaries_sync, session_ids)

    async def list_imported_sessions(
        self,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        return await self._run(self._list_imported_sessions_sync, limit, offset)

    def _update_summary_sync(self, session_id: str, summary: str, up_to_msg_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE sessions
                SET compressed_summary = ?, summary_up_to_msg_id = ?, updated_at = updated_at
                WHERE id = ?
                """,
                (summary, max(0, int(up_to_msg_id)), session_id),
            )
            conn.commit()
        return cur.rowcount > 0

    async def update_summary(self, session_id: str, summary: str, up_to_msg_id: int) -> bool:
        return await self._run(self._update_summary_sync, session_id, summary, up_to_msg_id)

    def _update_session_preferences_sync(
        self, session_id: str, preferences: dict[str, Any]
    ) -> bool:
        with self._connect() as conn:
            current = conn.execute(
                "SELECT preferences_json FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if current is None:
                return False
            merged = {
                **_json_loads(current["preferences_json"], {}),
                **(preferences or {}),
            }
            merged = upgrade_workspace_preferences(merged)
            cur = conn.execute(
                """
                UPDATE sessions
                SET preferences_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (_json_dumps(merged), time.time(), session_id),
            )
            conn.commit()
        return cur.rowcount > 0

    async def update_session_preferences(
        self, session_id: str, preferences: dict[str, Any]
    ) -> bool:
        return await self._run(self._update_session_preferences_sync, session_id, preferences)

    async def get_session_with_messages(self, session_id: str) -> dict[str, Any] | None:
        session = await self.get_session(session_id)
        if session is None:
            return None
        session["messages"] = await self.get_messages(session_id)
        redact_private_message_metadata(session["messages"])
        session["active_turns"] = await self.list_active_turns(session_id)
        return session

    # ── Notebook entries ──────────────────────────────────────────────

    def _upsert_notebook_entries_sync(self, session_id: str, items: list[dict[str, Any]]) -> int:
        if not items:
            return 0
        now = time.time()
        with self._connect() as conn:
            if (
                conn.execute("SELECT id FROM sessions WHERE id = ?", (session_id,)).fetchone()
                is None
            ):
                raise ValueError(f"Session not found: {session_id}")
            upserted = 0
            for item in items:
                question = (item.get("question") or "").strip()
                question_id = (item.get("question_id") or "").strip()
                if not question or not question_id:
                    continue
                turn_id = (item.get("turn_id") or "").strip()
                # ``user_answer_images`` is an optional list of records
                # ``[{id, url, filename, mime_type}, …]``. We serialise it
                # here so callers that only know about text don't need to
                # know JSON. ``None`` keeps the existing column value on
                # UPDATE (avoid clobbering stored images on a partial
                # upsert that only changes ``is_correct``).
                images_value = item.get("user_answer_images")
                images_json = _json_dumps(images_value) if isinstance(images_value, list) else None
                source = str(item.get("source") or "deep_question")
                if source not in ASSESSMENT_SOURCES:
                    source = "deep_question"
                is_correct = 1 if item.get("is_correct") else 0
                existing = conn.execute(
                    """
                    SELECT is_correct FROM notebook_entries
                    WHERE session_id = ? AND turn_id = ? AND question_id = ?
                    """,
                    (session_id, turn_id, question_id),
                ).fetchone()
                previous = bool(existing["is_correct"]) if existing is not None else None
                if previous is None or previous == bool(is_correct):
                    score_trend = "new" if previous is None else "unchanged"
                else:
                    score_trend = "improved" if is_correct else "declined"
                provenance = (
                    source,
                    str(item.get("material_id") or ""),
                    str(item.get("material_title") or ""),
                    str(item.get("section_id") or ""),
                    str(item.get("section_title") or ""),
                    score_trend,
                )
                if images_json is None:
                    conn.execute(
                        """
                        INSERT INTO notebook_entries (
                            session_id, turn_id, question_id, question, question_type,
                            options_json, correct_answer, explanation, difficulty,
                            user_answer, user_answer_images_json, source, material_id,
                            material_title, section_id, section_title, score_trend,
                            is_correct, resolved, bookmarked, followup_session_id,
                            created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', ?, ?, ?, ?, ?, ?, ?, ?, 0, '', ?, ?)
                        ON CONFLICT(session_id, turn_id, question_id) DO UPDATE SET
                            question = excluded.question,
                            question_type = excluded.question_type,
                            options_json = excluded.options_json,
                            correct_answer = excluded.correct_answer,
                            explanation = excluded.explanation,
                            difficulty = excluded.difficulty,
                            user_answer = excluded.user_answer,
                            source = excluded.source,
                            material_id = excluded.material_id,
                            material_title = excluded.material_title,
                            section_id = excluded.section_id,
                            section_title = excluded.section_title,
                            score_trend = excluded.score_trend,
                            is_correct = excluded.is_correct,
                            resolved = CASE
                                WHEN excluded.is_correct = 1 THEN 1
                                WHEN excluded.is_correct = 0 AND notebook_entries.is_correct = 1 THEN 0
                                ELSE notebook_entries.resolved
                            END,
                            updated_at = excluded.updated_at
                        """,
                        (
                            session_id,
                            turn_id,
                            question_id,
                            question,
                            item.get("question_type") or "",
                            _json_dumps(item.get("options") or {}),
                            item.get("correct_answer") or "",
                            item.get("explanation") or "",
                            item.get("difficulty") or "",
                            item.get("user_answer") or "",
                            *provenance,
                            is_correct,
                            1 if is_correct else 0,
                            now,
                            now,
                        ),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO notebook_entries (
                            session_id, turn_id, question_id, question, question_type,
                            options_json, correct_answer, explanation, difficulty,
                            user_answer, user_answer_images_json, source, material_id,
                            material_title, section_id, section_title, score_trend,
                            is_correct, resolved, bookmarked, followup_session_id,
                            created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, '', ?, ?)
                        ON CONFLICT(session_id, turn_id, question_id) DO UPDATE SET
                            question = excluded.question,
                            question_type = excluded.question_type,
                            options_json = excluded.options_json,
                            correct_answer = excluded.correct_answer,
                            explanation = excluded.explanation,
                            difficulty = excluded.difficulty,
                            user_answer = excluded.user_answer,
                            source = excluded.source,
                            material_id = excluded.material_id,
                            material_title = excluded.material_title,
                            section_id = excluded.section_id,
                            section_title = excluded.section_title,
                            score_trend = excluded.score_trend,
                            user_answer_images_json = excluded.user_answer_images_json,
                            is_correct = excluded.is_correct,
                            resolved = CASE
                                WHEN excluded.is_correct = 1 THEN 1
                                WHEN excluded.is_correct = 0 AND notebook_entries.is_correct = 1 THEN 0
                                ELSE notebook_entries.resolved
                            END,
                            updated_at = excluded.updated_at
                        """,
                        (
                            session_id,
                            turn_id,
                            question_id,
                            question,
                            item.get("question_type") or "",
                            _json_dumps(item.get("options") or {}),
                            item.get("correct_answer") or "",
                            item.get("explanation") or "",
                            item.get("difficulty") or "",
                            item.get("user_answer") or "",
                            images_json,
                            *provenance,
                            is_correct,
                            1 if is_correct else 0,
                            now,
                            now,
                        ),
                    )
                upserted += 1
            conn.commit()
        return upserted

    async def upsert_notebook_entries(self, session_id: str, items: list[dict[str, Any]]) -> int:
        return await self._run(self._upsert_notebook_entries_sync, session_id, items)

    @staticmethod
    def _serialize_notebook_entry(row: sqlite3.Row) -> dict[str, Any]:
        keys = set(row.keys())
        images: list[dict[str, Any]] = []
        if "user_answer_images_json" in keys:
            raw_images = _json_loads(row["user_answer_images_json"], [])
            if isinstance(raw_images, list):
                images = [r for r in raw_images if isinstance(r, dict)]
        return {
            "id": int(row["id"]),
            "session_id": row["session_id"],
            "session_title": row["session_title"] or "" if "session_title" in keys else "",
            "turn_id": (row["turn_id"] or "") if "turn_id" in keys else "",
            "question_id": row["question_id"] or "",
            "question": row["question"],
            "question_type": row["question_type"] or "",
            "options": _json_loads(row["options_json"], {}),
            "correct_answer": row["correct_answer"] or "",
            "explanation": row["explanation"] or "",
            "difficulty": row["difficulty"] or "",
            "user_answer": row["user_answer"] or "",
            "user_answer_images": images,
            "is_correct": bool(row["is_correct"]),
            "source": (row["source"] or "deep_question") if "source" in keys else "deep_question",
            "material_id": (row["material_id"] or "") if "material_id" in keys else "",
            "material_title": (row["material_title"] or "") if "material_title" in keys else "",
            "section_id": (row["section_id"] or "") if "section_id" in keys else "",
            "section_title": (row["section_title"] or "") if "section_title" in keys else "",
            "score_trend": (row["score_trend"] or "new") if "score_trend" in keys else "new",
            "resolved": bool(row["resolved"]) if "resolved" in keys else bool(row["is_correct"]),
            "bookmarked": bool(row["bookmarked"]),
            "followup_session_id": row["followup_session_id"] or "",
            "ai_judgment": (row["ai_judgment"] or "") if "ai_judgment" in keys else "",
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
        }

    # ---- question bank (notebook_entries) queries -----------------------

    @staticmethod
    def _question_bank_filters(query: QuestionBankQuery) -> tuple[str, str, list[Any]]:
        """Build the ``(join, where, params)`` triple shared by list + count.

        Kept apart from the SELECT so the row query and the COUNT query can
        never drift into filtering different sets — the bug that makes a
        paginated list report a total it does not contain.
        """
        joins: list[str] = []
        conditions: list[str] = []
        params: list[Any] = []

        if query.category_id is not None:
            joins.append(" INNER JOIN notebook_entry_categories ec ON ec.entry_id = n.id")
            conditions.append("ec.category_id = ?")
            params.append(query.category_id)
        elif query.uncategorized:
            conditions.append(
                "NOT EXISTS (SELECT 1 FROM notebook_entry_categories ec WHERE ec.entry_id = n.id)"
            )
        if query.bookmarked is not None:
            conditions.append("n.bookmarked = ?")
            params.append(1 if query.bookmarked else 0)
        if query.is_correct is not None:
            conditions.append("n.is_correct = ?")
            params.append(1 if query.is_correct else 0)
        if query.source:
            conditions.append("n.source = ?")
            params.append(query.source)
        if query.material_id:
            conditions.append("n.material_id = ?")
            params.append(query.material_id)
        if query.section_id:
            conditions.append("n.section_id = ?")
            params.append(query.section_id)
        if query.resolved is not None:
            conditions.append("n.resolved = ?")
            params.append(1 if query.resolved else 0)
        if query.score_trend:
            conditions.append("n.score_trend = ?")
            params.append(query.score_trend)
        if query.session_id is not None:
            conditions.append("n.session_id = ?")
            params.append(query.session_id)
        if query.session_ids is not None:
            # Only the placeholder shape is interpolated; session ids remain
            # bound parameters. ``IN (NULL)`` is the explicit empty-set case.
            placeholders = ",".join("?" for _ in query.session_ids) or "NULL"
            conditions.append(f"n.session_id IN ({placeholders})")
            params.extend(query.session_ids)
        if query.search:
            # ESCAPE so a learner searching for "50%" or "a_b" gets literal
            # matches instead of the wildcards those characters would be.
            needle = f"%{_escape_like(query.search)}%"
            conditions.append(
                "(n.question LIKE ? ESCAPE '\\' OR n.user_answer LIKE ? ESCAPE '\\' "
                "OR n.correct_answer LIKE ? ESCAPE '\\' OR n.explanation LIKE ? ESCAPE '\\')"
            )
            params.extend([needle] * 4)

        join_sql = "".join(joins)
        where_sql = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        return join_sql, where_sql, params

    @staticmethod
    def _load_categories_for(
        conn: sqlite3.Connection, entry_ids: list[int]
    ) -> dict[int, list[dict[str, Any]]]:
        """Fetch every entry's categories in one query (never N+1)."""
        if not entry_ids:
            return {}
        placeholders = ",".join("?" * len(entry_ids))
        rows = conn.execute(
            f"""
            SELECT ec.entry_id, c.id, c.name
            FROM notebook_entry_categories ec
            INNER JOIN notebook_categories c ON c.id = ec.category_id
            WHERE ec.entry_id IN ({placeholders})
            ORDER BY c.name
            """,  # nosec B608 - only `?` placeholders are interpolated; every value binds
            tuple(entry_ids),
        ).fetchall()
        grouped: dict[int, list[dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(int(row["entry_id"]), []).append(
                {"id": row["id"], "name": row["name"]}
            )
        return grouped

    def _list_notebook_entries_sync(self, query: QuestionBankQuery) -> dict[str, Any]:
        query = query.normalized()
        join_sql, where_sql, params = self._question_bank_filters(query)
        order = "ASC" if query.sort == "oldest" else "DESC"
        base = f"""
            SELECT
                n.id, n.session_id, COALESCE(s.title, '') AS session_title,
                n.turn_id, n.question_id, n.question, n.question_type, n.options_json,
                n.correct_answer, n.explanation, n.difficulty,
                n.user_answer, n.user_answer_images_json, n.source, n.material_id,
                n.material_title, n.section_id, n.section_title, n.score_trend,
                n.is_correct, n.resolved, n.bookmarked,
                n.followup_session_id, n.ai_judgment, n.created_at, n.updated_at
            FROM notebook_entries n
            LEFT JOIN sessions s ON s.id = n.session_id{join_sql}
        """  # nosec B608 - join_sql/where_sql are literal fragments; every value binds via ?
        count_sql = (
            # join_sql/where_sql are literal fragments; every value binds via ?
            f"SELECT COUNT(*) AS cnt FROM notebook_entries n{join_sql}{where_sql}"  # nosec B608
        )
        with self._connect() as conn:
            total_row = conn.execute(count_sql, tuple(params)).fetchone()
            total = int(total_row["cnt"]) if total_row else 0
            rows = conn.execute(
                base
                + where_sql
                # ``n.id`` breaks ties: a batch upserted in one call shares a
                # created_at, and an unstable order duplicates/drops rows across pages.
                + f" ORDER BY n.created_at {order}, n.id {order} LIMIT ? OFFSET ?",
                tuple(params) + (query.limit, query.offset),
            ).fetchall()
            items = [self._serialize_notebook_entry(r) for r in rows]
            grouped = self._load_categories_for(conn, [int(i["id"]) for i in items])
        for item in items:
            item["categories"] = grouped.get(int(item["id"]), [])
        return {"items": items, "total": total}

    async def list_notebook_entries(
        self,
        category_id: int | None = None,
        bookmarked: bool | None = None,
        is_correct: bool | None = None,
        limit: int = 50,
        offset: int = 0,
        *,
        session_id: str | None = None,
        session_ids: Sequence[str] | None = None,
        source: str = "",
        material_id: str = "",
        section_id: str = "",
        resolved: bool | None = None,
        score_trend: str = "",
        search: str = "",
        uncategorized: bool = False,
        sort: str = "recent",
    ) -> dict[str, Any]:
        """List question-bank entries. Every row carries its categories."""
        return await self._run(
            self._list_notebook_entries_sync,
            QuestionBankQuery(
                category_id=category_id,
                uncategorized=uncategorized,
                bookmarked=bookmarked,
                is_correct=is_correct,
                source=source,
                material_id=material_id,
                section_id=section_id,
                resolved=resolved,
                score_trend=score_trend,
                search=search,
                session_id=session_id,
                session_ids=session_ids,
                sort=sort,
                limit=limit,
                offset=offset,
            ),
        )

    def _question_bank_stats_sync(self, session_ids: Sequence[str] | None = None) -> dict[str, int]:
        with self._connect() as conn:
            # Same ``None`` vs ``[]`` contract as the listing: absent means "do
            # not scope", empty means "scoped to nothing". The rail's counts sit
            # beside the list, so anything the list excludes must not be counted
            # here either.
            where = ""
            params: list[str] = []
            if session_ids is not None:
                placeholders = ",".join("?" for _ in session_ids) or "NULL"
                where = f"WHERE session_id IN ({placeholders})"
                params = list(session_ids)
            row = conn.execute(
                f"""
                SELECT
                    COUNT(*) AS total,
                    COALESCE(SUM(CASE WHEN is_correct = 0 THEN 1 ELSE 0 END), 0) AS wrong,
                    COALESCE(SUM(CASE WHEN is_correct = 0 AND resolved = 0 THEN 1 ELSE 0 END), 0) AS unresolved,
                    COALESCE(SUM(CASE WHEN bookmarked = 1 THEN 1 ELSE 0 END), 0) AS bookmarked,
                    COALESCE(SUM(
                        CASE WHEN NOT EXISTS (
                            SELECT 1 FROM notebook_entry_categories ec
                            WHERE ec.entry_id = notebook_entries.id
                        ) THEN 1 ELSE 0 END
                    ), 0) AS uncategorized
                FROM notebook_entries
                {where}
                """,  # noqa: S608  # nosec B608 - placeholders only; every value stays bound
                params,
            ).fetchone()
        if row is None:
            return {
                "total": 0,
                "wrong": 0,
                "unresolved": 0,
                "bookmarked": 0,
                "uncategorized": 0,
            }
        return {
            "total": int(row["total"]),
            "wrong": int(row["wrong"]),
            "unresolved": int(row["unresolved"]),
            "bookmarked": int(row["bookmarked"]),
            "uncategorized": int(row["uncategorized"]),
        }

    def has_question_bank_entries(self) -> bool:
        """Whether the bank holds anything at all — the tool's mount gate.

        Deliberately synchronous: tool composition runs inside a sync
        policy function, and a bool probe is one indexed row read. Fails
        closed so a missing/locked db never mounts a tool with no data.
        """
        try:
            with self._connect() as conn:
                row = conn.execute("SELECT 1 FROM notebook_entries LIMIT 1").fetchone()
            return row is not None
        except Exception:
            return False

    async def question_bank_stats(
        self,
        session_ids: Sequence[str] | None = None,
    ) -> dict[str, int]:
        """Counts behind the bank's filter chips (and the agent's overview)."""
        return await self._run(
            self._question_bank_stats_sync,
            None if session_ids is None else tuple(session_ids),
        )

    def _list_question_bank_materials_sync(
        self,
        session_ids: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        where = "material_id != ''"
        params: list[str] = []
        if session_ids is not None:
            placeholders = ",".join("?" for _ in session_ids) or "NULL"
            where += f" AND session_id IN ({placeholders})"
            params.extend(session_ids)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    source,
                    material_id,
                    COALESCE(NULLIF(MAX(material_title), ''), material_id, 'Unnamed material') AS material_title,
                    COUNT(*) AS entry_count,
                    COALESCE(SUM(CASE WHEN is_correct = 0 AND resolved = 0 THEN 1 ELSE 0 END), 0) AS unresolved_count
                FROM notebook_entries
                WHERE {where}
                GROUP BY source, material_id
                ORDER BY material_title COLLATE NOCASE
                """,  # nosec B608 - only placeholder shape is interpolated
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    async def list_question_bank_materials(
        self,
        session_ids: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Distinct materials for review filters, with wrong-review counts."""
        return await self._run(
            self._list_question_bank_materials_sync,
            None if session_ids is None else tuple(session_ids),
        )

    def _get_notebook_entry_sync(self, entry_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    n.*, COALESCE(s.title, '') AS session_title
                FROM notebook_entries n
                LEFT JOIN sessions s ON s.id = n.session_id
                WHERE n.id = ?
                """,
                (entry_id,),
            ).fetchone()
            if row is None:
                return None
            entry = self._serialize_notebook_entry(row)
            cats = conn.execute(
                """
                SELECT c.id, c.name
                FROM notebook_categories c
                INNER JOIN notebook_entry_categories ec ON ec.category_id = c.id
                WHERE ec.entry_id = ?
                ORDER BY c.name
                """,
                (entry_id,),
            ).fetchall()
            entry["categories"] = [{"id": c["id"], "name": c["name"]} for c in cats]
        return entry

    async def get_notebook_entry(self, entry_id: int) -> dict[str, Any] | None:
        return await self._run(self._get_notebook_entry_sync, entry_id)

    def _find_notebook_entry_sync(
        self,
        session_id: str,
        question_id: str,
        turn_id: str | None = None,
    ) -> dict[str, Any] | None:
        # A missing turn_id only ever matches the legacy namespace (rows
        # persisted before turn scoping, migrated with turn_id=''). It must
        # never fall back to other turns' rows: positional question ids
        # (``q_1``..``q_N``) repeat across quizzes in one session, so a
        # cross-turn match would leak a previous quiz's answers into a new
        # quiz (issues #487 / #677).
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT n.*, COALESCE(s.title, '') AS session_title
                FROM notebook_entries n
                LEFT JOIN sessions s ON s.id = n.session_id
                WHERE n.session_id = ?
                  AND n.turn_id = ?
                  AND n.question_id = ?
                """,
                (session_id, turn_id if turn_id is not None else "", question_id),
            ).fetchone()
        if row is None:
            return None
        return self._serialize_notebook_entry(row)

    async def find_notebook_entry(
        self,
        session_id: str,
        question_id: str,
        turn_id: str | None = None,
    ) -> dict[str, Any] | None:
        return await self._run(self._find_notebook_entry_sync, session_id, question_id, turn_id)

    def _update_notebook_entry_sync(self, entry_id: int, updates: dict[str, Any]) -> bool:
        allowed = {
            "bookmarked",
            "followup_session_id",
            "user_answer",
            "is_correct",
            "ai_judgment",
            "resolved",
        }
        fields = {k: v for k, v in updates.items() if k in allowed}
        if not fields:
            return False
        fields["updated_at"] = time.time()
        if "bookmarked" in fields:
            fields["bookmarked"] = 1 if fields["bookmarked"] else 0
        if "is_correct" in fields:
            fields["is_correct"] = 1 if fields["is_correct"] else 0
        if "resolved" in fields:
            fields["resolved"] = 1 if fields["resolved"] else 0
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [entry_id]
        with self._connect() as conn:
            cur = conn.execute(
                f"UPDATE notebook_entries SET {set_clause} WHERE id = ?",  # nosec B608
                tuple(values),
            )
            conn.commit()
        return cur.rowcount > 0

    async def update_notebook_entry(self, entry_id: int, updates: dict[str, Any]) -> bool:
        return await self._run(self._update_notebook_entry_sync, entry_id, updates)

    def _delete_notebook_entry_sync(self, entry_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM notebook_entries WHERE id = ?", (entry_id,))
            conn.commit()
        return cur.rowcount > 0

    async def delete_notebook_entry(self, entry_id: int) -> bool:
        return await self._run(self._delete_notebook_entry_sync, entry_id)

    # ── Notebook categories ────────────────────────────────────────

    @staticmethod
    def _name_taken(conn: sqlite3.Connection, name: str, *, excluding: int | None = None) -> bool:
        """Whether a category already claims this name, ignoring case.

        The table's UNIQUE index is case-sensitive, so "Math" and "math"
        both fit — but they read as one pile to a learner, and the agent
        resolves names case-insensitively, so it would file into the first
        and report a name the learner sees twice in the rail.
        """
        row = conn.execute(
            "SELECT id FROM notebook_categories WHERE name = ? COLLATE NOCASE",
            (name.strip(),),
        ).fetchone()
        return row is not None and (excluding is None or int(row["id"]) != excluding)

    def _create_category_sync(self, name: str) -> dict[str, Any]:
        now = time.time()
        cleaned = name.strip()
        with self._connect() as conn:
            if self._name_taken(conn, cleaned):
                raise ValueError(f"A category named {cleaned!r} already exists.")
            cur = conn.execute(
                "INSERT INTO notebook_categories (name, created_at) VALUES (?, ?)",
                (cleaned, now),
            )
            conn.commit()
        return {"id": int(cur.lastrowid), "name": cleaned, "created_at": now}

    async def create_category(self, name: str) -> dict[str, Any]:
        return await self._run(self._create_category_sync, name)

    def _list_categories_sync(
        self,
        session_ids: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        # The scope narrows the *count*, never the list: a category the learner
        # created still exists inside a course that has not filled it yet, and
        # dropping the row would make it look deleted. Hence the condition rides
        # on the join instead of a WHERE clause.
        join = "LEFT JOIN notebook_entries e ON e.id = ec.entry_id"
        params: list[str] = []
        if session_ids is not None:
            placeholders = ",".join("?" for _ in session_ids) or "NULL"
            join += f" AND e.session_id IN ({placeholders})"
            params = list(session_ids)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT c.id, c.name, c.created_at,
                       COUNT(e.id) AS entry_count
                FROM notebook_categories c
                LEFT JOIN notebook_entry_categories ec ON ec.category_id = c.id
                {join}
                GROUP BY c.id
                ORDER BY c.name
                """,  # noqa: S608  # nosec B608 - placeholders only; every value stays bound
                params,
            ).fetchall()
        return [
            {
                "id": r["id"],
                "name": r["name"],
                "created_at": float(r["created_at"]),
                "entry_count": int(r["entry_count"]),
            }
            for r in rows
        ]

    async def list_categories(
        self,
        session_ids: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        return await self._run(
            self._list_categories_sync,
            None if session_ids is None else tuple(session_ids),
        )

    def _rename_category_sync(self, category_id: int, name: str) -> bool:
        cleaned = name.strip()
        with self._connect() as conn:
            # Without this the UNIQUE index raises straight through the
            # router as a 500; a name clash is a request problem, not a bug.
            if self._name_taken(conn, cleaned, excluding=category_id):
                raise ValueError(f"A category named {cleaned!r} already exists.")
            cur = conn.execute(
                "UPDATE notebook_categories SET name = ? WHERE id = ?",
                (cleaned, category_id),
            )
            conn.commit()
        return cur.rowcount > 0

    async def rename_category(self, category_id: int, name: str) -> bool:
        return await self._run(self._rename_category_sync, category_id, name)

    def _delete_category_sync(self, category_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM notebook_categories WHERE id = ?", (category_id,))
            conn.commit()
        return cur.rowcount > 0

    async def delete_category(self, category_id: int) -> bool:
        return await self._run(self._delete_category_sync, category_id)

    def _add_entry_to_category_sync(self, entry_id: int, category_id: int) -> bool:
        with self._connect() as conn:
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO notebook_entry_categories (entry_id, category_id) VALUES (?, ?)",
                    (entry_id, category_id),
                )
                conn.commit()
            except sqlite3.IntegrityError:
                return False
        return True

    async def add_entry_to_category(self, entry_id: int, category_id: int) -> bool:
        return await self._run(self._add_entry_to_category_sync, entry_id, category_id)

    def _remove_entry_from_category_sync(self, entry_id: int, category_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM notebook_entry_categories WHERE entry_id = ? AND category_id = ?",
                (entry_id, category_id),
            )
            conn.commit()
        return cur.rowcount > 0

    async def remove_entry_from_category(self, entry_id: int, category_id: int) -> bool:
        return await self._run(self._remove_entry_from_category_sync, entry_id, category_id)

    def _get_entry_categories_sync(self, entry_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT c.id, c.name FROM notebook_categories c
                INNER JOIN notebook_entry_categories ec ON ec.category_id = c.id
                WHERE ec.entry_id = ?
                ORDER BY c.name
                """,
                (entry_id,),
            ).fetchall()
        return [{"id": r["id"], "name": r["name"]} for r in rows]

    async def get_entry_categories(self, entry_id: int) -> list[dict[str, Any]]:
        return await self._run(self._get_entry_categories_sync, entry_id)

    def _link_entries_to_category_sync(
        self, entry_ids: list[int], category_id: int, link: bool
    ) -> int:
        """Add/remove many entries to one category in a single transaction.

        Returns the number of links actually changed, so a caller that asked
        to file 20 questions can tell the learner "18 filed, 2 already there"
        instead of claiming a no-op succeeded.
        """
        if not entry_ids:
            return 0
        with self._connect() as conn:
            exists = conn.execute(
                "SELECT 1 FROM notebook_categories WHERE id = ?", (category_id,)
            ).fetchone()
            if exists is None:
                return 0
            placeholders = ",".join("?" * len(entry_ids))
            # Filter to entries that really exist: a stale id from the agent
            # or a concurrently-deleted row must not abort the whole batch.
            known = [
                int(r["id"])
                for r in conn.execute(
                    f"SELECT id FROM notebook_entries WHERE id IN ({placeholders})",  # nosec B608 - only `?` placeholders are interpolated; every value binds
                    tuple(entry_ids),
                ).fetchall()
            ]
            if not known:
                return 0
            if link:
                cur = conn.executemany(
                    "INSERT OR IGNORE INTO notebook_entry_categories "
                    "(entry_id, category_id) VALUES (?, ?)",
                    [(eid, category_id) for eid in known],
                )
            else:
                cur = conn.executemany(
                    "DELETE FROM notebook_entry_categories WHERE entry_id = ? AND category_id = ?",
                    [(eid, category_id) for eid in known],
                )
            return int(cur.rowcount or 0)

    async def link_entries_to_category(
        self, entry_ids: list[int], category_id: int, *, link: bool = True
    ) -> int:
        return await self._run(
            self._link_entries_to_category_sync, list(entry_ids), category_id, link
        )

    def _find_category_by_name_sync(self, name: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, name, created_at FROM notebook_categories "
                "WHERE name = ? COLLATE NOCASE ORDER BY id LIMIT 1",
                (name.strip(),),
            ).fetchone()
        if row is None:
            return None
        return {"id": int(row["id"]), "name": row["name"], "created_at": float(row["created_at"])}

    async def find_category_by_name(self, name: str) -> dict[str, Any] | None:
        """Look a category up by display name — the only handle an agent has."""
        return await self._run(self._find_category_by_name_sync, name)


_instances: dict[str, SQLiteSessionStore] = {}


def get_sqlite_session_store() -> SQLiteSessionStore:
    db_path = get_path_service().get_chat_history_db().resolve()
    key = str(db_path)
    if key not in _instances:
        _instances[key] = SQLiteSessionStore(db_path=db_path)
    return _instances[key]


__all__ = [
    "QuestionBankQuery",
    "SQLiteSessionStore",
    "get_sqlite_session_store",
    "make_imported_session_id",
]
