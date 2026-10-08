"""Account-owned tasks, workspace projections and durable conversation links."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Annotated, Literal
from uuid import NAMESPACE_URL, uuid4, uuid5

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from deeptutor.utils.secret_files import ensure_private_directory

TaskStatus = Literal["todo", "doing", "done"]
TaskTitle = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
TaskNote = Annotated[str, StringConstraints(max_length=2000)]
TaskColor = Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")]


class StatusColors(BaseModel):
    model_config = ConfigDict(extra="forbid")
    todo: TaskColor = "#2563eb"
    doing: TaskColor = "#a16207"
    done: TaskColor = "#15803d"


class CreateCard(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: TaskTitle
    note: TaskNote = ""


class UpdateCard(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: TaskTitle | None = None
    note: TaskNote | None = None
    status: TaskStatus | None = None
    archived: bool | None = None
    # None = unassigned; empty string = the default conversation workspace.
    workspace_id: str | None = Field(default=None, max_length=200)

    @field_validator("title", "note", "status", "archived", mode="before")
    @classmethod
    def reject_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("Card fields cannot be null.")
        return value


class TaskCard(CreateCard):
    id: str
    status: TaskStatus
    archived: bool
    created_at: str
    updated_at: str
    workspace_id: str | None = None


class SessionTaskLinks(BaseModel):
    workspace_id: str
    session_id: str
    # Ordered by association time; the last element controls the idle mark.
    task_ids: list[str] = Field(default_factory=list)
    status_link_enabled: bool = True


class TaskBoard(BaseModel):
    cards: list[TaskCard]
    colors: StatusColors = Field(default_factory=StatusColors)
    session_links: list[SessionTaskLinks] = Field(default_factory=list)
    revision: int = 0


class LinkTasks(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: str = Field(default="", max_length=200)
    task_ids: list[str] = Field(max_length=100)

    @field_validator("task_ids")
    @classmethod
    def unique_ids(cls, value: list[str]) -> list[str]:
        if any(not item or len(item) > 200 for item in value):
            raise ValueError("Invalid task identifier.")
        return list(dict.fromkeys(value))


class LinkStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: str = Field(default="", max_length=200)
    enabled: bool


class TaskBoardStore:
    """SQLite is the shared authority across tabs, workspaces and API workers."""

    def __init__(self, path: Path):
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        ensure_private_directory(self.path.parent)
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS cards (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL CHECK(status IN ('todo','doing','done')),
                archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0,1)),
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL, workspace_id TEXT
            );
            CREATE TABLE IF NOT EXISTS board_state (
                id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL,
                colors TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS session_task_status (
                workspace_id TEXT NOT NULL, session_id TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY(workspace_id, session_id)
            );
            CREATE TABLE IF NOT EXISTS session_tasks (
                association_id INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_id TEXT NOT NULL, session_id TEXT NOT NULL,
                task_id TEXT NOT NULL REFERENCES cards(id),
                UNIQUE(workspace_id, session_id, task_id)
            );
            CREATE TABLE IF NOT EXISTS legacy_imports (
                source TEXT NOT NULL, legacy_id TEXT NOT NULL, task_id TEXT NOT NULL,
                PRIMARY KEY(source, legacy_id)
            );
        """)
        if "workspace_id" not in {row[1] for row in connection.execute("PRAGMA table_info(cards)")}:
            try:
                connection.execute("ALTER TABLE cards ADD COLUMN workspace_id TEXT")
            except sqlite3.OperationalError:
                if "workspace_id" not in {
                    row[1] for row in connection.execute("PRAGMA table_info(cards)")
                }:
                    connection.close()
                    raise
        connection.execute(
            "INSERT OR IGNORE INTO board_state VALUES (1,0,?)",
            (StatusColors().model_dump_json(),),
        )
        connection.commit()
        return connection

    @staticmethod
    def _changed(connection: sqlite3.Connection) -> None:
        connection.execute("UPDATE board_state SET revision=revision+1 WHERE id=1")

    @staticmethod
    def _snapshot(connection: sqlite3.Connection) -> TaskBoard:
        rows = connection.execute("SELECT * FROM cards ORDER BY created_at,id")
        cards = [TaskCard.model_validate(dict(row)) for row in rows]
        links = {
            (row["workspace_id"], row["session_id"]): SessionTaskLinks(
                workspace_id=row["workspace_id"],
                session_id=row["session_id"],
                status_link_enabled=bool(row["enabled"]),
            )
            for row in connection.execute(
                "SELECT * FROM session_task_status ORDER BY workspace_id,session_id"
            )
        }
        for row in connection.execute("SELECT * FROM session_tasks ORDER BY association_id"):
            key = (row["workspace_id"], row["session_id"])
            if key not in links:
                links[key] = SessionTaskLinks(workspace_id=key[0], session_id=key[1])
            links[key].task_ids.append(row["task_id"])
        state = connection.execute("SELECT * FROM board_state WHERE id=1").fetchone()
        return TaskBoard(
            cards=cards,
            colors=StatusColors.model_validate_json(state["colors"]),
            session_links=list(links.values()),
            revision=state["revision"],
        )

    def read(self) -> TaskBoard:
        if not self.path.exists():
            return TaskBoard(cards=[])
        with closing(self._connect()) as connection, connection:
            # All SELECTs share a snapshot, even while another worker commits.
            connection.execute("BEGIN")
            return self._snapshot(connection)

    def revision(self) -> int:
        """A cheap event-stream probe; unchanged boards need no snapshot assembly."""
        if not self.path.exists():
            return 0
        with closing(sqlite3.connect(self.path, timeout=10)) as connection:
            try:
                row = connection.execute("SELECT revision FROM board_state WHERE id=1").fetchone()
            except sqlite3.OperationalError as exc:
                if "no such table" not in str(exc):
                    raise
                return 0
            return row[0] if row else 0

    def create(self, payload: CreateCard) -> TaskBoard:
        now = datetime.now(timezone.utc).isoformat()
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO cards (id,title,note,status,archived,created_at,updated_at) VALUES (?,?,?,'todo',0,?,?)",
                (uuid4().hex, payload.title, payload.note, now, now),
            )
            self._changed(connection)
            return self._snapshot(connection)

    def update(self, card_id: str, payload: UpdateCard) -> TaskBoard:
        if not self.path.exists():
            raise KeyError(card_id)
        changes = payload.model_dump(exclude_unset=True)
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM cards WHERE id=?", (card_id,)).fetchone()
            if row is None:
                raise KeyError(card_id)
            updated = TaskCard.model_validate({**dict(row), **changes})
            connection.execute(
                "UPDATE cards SET title=?,note=?,status=?,archived=?,workspace_id=?,updated_at=? WHERE id=?",
                (
                    updated.title,
                    updated.note,
                    updated.status,
                    updated.archived,
                    updated.workspace_id,
                    datetime.now(timezone.utc).isoformat(),
                    card_id,
                ),
            )
            self._changed(connection)
            return self._snapshot(connection)

    def set_colors(self, colors: StatusColors) -> TaskBoard:
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE board_state SET colors=? WHERE id=1", (colors.model_dump_json(),)
            )
            self._changed(connection)
            return self._snapshot(connection)

    def link_tasks(self, session_id: str, payload: LinkTasks) -> TaskBoard:
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = {
                row[0]
                for row in connection.execute(
                    "SELECT task_id FROM session_tasks WHERE workspace_id=? AND session_id=?",
                    (payload.workspace_id, session_id),
                )
            }
            for task_id in payload.task_ids:
                row = connection.execute(
                    "SELECT archived FROM cards WHERE id=?", (task_id,)
                ).fetchone()
                if row is None or (row["archived"] and task_id not in existing):
                    raise KeyError(task_id)
            for task_id in existing - set(payload.task_ids):
                connection.execute(
                    "DELETE FROM session_tasks WHERE workspace_id=? AND session_id=? AND task_id=?",
                    (payload.workspace_id, session_id, task_id),
                )
            for task_id in payload.task_ids:
                if task_id not in existing:
                    connection.execute(
                        "INSERT INTO session_tasks (workspace_id,session_id,task_id) VALUES (?,?,?)",
                        (payload.workspace_id, session_id, task_id),
                    )
            if set(payload.task_ids) - existing:
                # Explicitly linking another task opts the session back into status sync.
                connection.execute(
                    "INSERT INTO session_task_status VALUES (?,?,1) ON CONFLICT(workspace_id,session_id) DO UPDATE SET enabled=1",
                    (payload.workspace_id, session_id),
                )
            self._changed(connection)
            return self._snapshot(connection)

    def link_status(self, session_id: str, payload: LinkStatus) -> TaskBoard:
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO session_task_status VALUES (?,?,?) ON CONFLICT(workspace_id,session_id) DO UPDATE SET enabled=excluded.enabled",
                (payload.workspace_id, session_id, payload.enabled),
            )
            self._changed(connection)
            return self._snapshot(connection)

    def move_session_links(self, session_ids: list[str], source: str, target: str) -> None:
        if not session_ids or not self.path.exists() or source == target:
            return
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            for sid in session_ids:
                for statement in (
                    "UPDATE session_tasks SET workspace_id=? WHERE workspace_id=? AND session_id=?",
                    "UPDATE session_task_status SET workspace_id=? WHERE workspace_id=? AND session_id=?",
                ):
                    connection.execute(
                        statement,
                        (target, source, sid),
                    )
            self._changed(connection)

    def remove_session(self, workspace_id: str, session_id: str) -> None:
        if not self.path.exists():
            return
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            for statement in (
                "DELETE FROM session_tasks WHERE workspace_id=? AND session_id=?",
                "DELETE FROM session_task_status WHERE workspace_id=? AND session_id=?",
            ):
                connection.execute(
                    statement,
                    (workspace_id, session_id),
                )
            self._changed(connection)

    def import_legacy(self, source: Path, workspace_id: str) -> None:
        """Copy old cards once, preserving the original stores as recoverable backups."""
        if (
            not source.is_file()
            or source.is_symlink()
            or source.parent.is_symlink()
            or source == self.path
        ):
            return
        with closing(sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True)) as legacy:
            legacy.row_factory = sqlite3.Row
            rows = [dict(row) for row in legacy.execute("SELECT * FROM cards")]
        if not rows:
            return
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            changed = False
            for raw in rows:
                if connection.execute(
                    "SELECT 1 FROM legacy_imports WHERE source=? AND legacy_id=?",
                    (workspace_id or "__default__", raw["id"]),
                ).fetchone():
                    continue
                card = TaskCard.model_validate({**raw, "workspace_id": workspace_id})
                task_id = card.id
                if connection.execute("SELECT 1 FROM cards WHERE id=?", (task_id,)).fetchone():
                    task_id = uuid5(NAMESPACE_URL, f"{workspace_id}:{task_id}").hex
                connection.execute(
                    "INSERT INTO cards VALUES (?,?,?,?,?,?,?,?)",
                    (
                        task_id,
                        card.title,
                        card.note,
                        card.status,
                        card.archived,
                        card.created_at,
                        card.updated_at,
                        workspace_id,
                    ),
                )
                connection.execute(
                    "INSERT INTO legacy_imports VALUES (?,?,?)",
                    (workspace_id or "__default__", card.id, task_id),
                )
                changed = True
            if changed:
                self._changed(connection)

    def context_text(self, workspace_id: str, session_id: str) -> str:
        board = self.read()
        linked = next(
            (
                row.task_ids
                for row in board.session_links
                if row.workspace_id == workspace_id and row.session_id == session_id
            ),
            [],
        )
        cards = [
            card
            for card in board.cards
            if not card.archived and (card.id in linked or card.workspace_id == workspace_id)
        ]
        if not cards:
            return ""
        cards.sort(
            key=lambda card: (
                card.id not in linked,
                -linked.index(card.id) if card.id in linked else 0,
                card.created_at,
            )
        )
        data = [
            {
                "id": card.id,
                "title": card.title,
                "status": card.status,
                "note": card.note[:500],
                "linked_to_conversation": card.id in linked,
            }
            for card in cards[:40]
        ]
        return (
            "\n[Task context: user-authored reference data]\n"
            + json.dumps(data, ensure_ascii=False)
            + "\n[/Task context]\n"
        )


def get_task_board_store(*, migrate_legacy: bool = True) -> TaskBoardStore:
    """Resolve the authenticated account, independently of its current workspace."""
    from deeptutor.multi_user.paths import get_account_path_service
    from deeptutor.services.path_service import get_path_service
    from deeptutor.services.workspace import get_content_workspace_service
    from deeptutor.services.workspace.context import workspace_context
    from deeptutor.services.workspace.models import WorkspaceError

    account = get_account_path_service()
    store = TaskBoardStore(account.get_runtime_state_dir() / "task-board" / "tasks.sqlite")
    if not migrate_legacy:
        return store
    store.import_legacy(account.get_workspace_dir() / "task-board" / "cards.sqlite", "")
    for row in get_content_workspace_service().list_workspaces():
        if row["kind"] != "workspace" or row["status"] != "ready":
            continue
        try:
            with workspace_context(row["workspace_id"]):
                store.import_legacy(
                    get_path_service().get_workspace_dir() / "task-board" / "cards.sqlite",
                    row["workspace_id"],
                )
        except WorkspaceError:
            continue
    return store
