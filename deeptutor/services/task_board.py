"""Workspace-local task cards with transactional, multi-worker-safe persistence."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator

from deeptutor.services.path_service import get_path_service
from deeptutor.utils.secret_files import ensure_private_directory

TaskStatus = Literal["todo", "doing", "done"]
TaskTitle = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
TaskNote = Annotated[str, StringConstraints(max_length=2000)]


class CreateCard(BaseModel):
    """A learner-authored task; identifiers and timestamps are server-owned."""

    model_config = ConfigDict(extra="forbid")
    title: TaskTitle
    note: TaskNote = ""


class UpdateCard(BaseModel):
    """Only supplied fields change, preserving concurrent edits to other fields."""

    model_config = ConfigDict(extra="forbid")
    title: TaskTitle | None = None
    note: TaskNote | None = None
    status: TaskStatus | None = None
    archived: bool | None = None

    @field_validator("title", "note", "status", "archived", mode="before")
    @classmethod
    def reject_null(cls, value: object) -> object:
        """Omission is allowed; explicitly clearing a required field is not."""
        if value is None:
            raise ValueError("Card fields cannot be null.")
        return value


class TaskCard(CreateCard):
    """Persisted card returned to the board, including archived cards."""

    id: str
    status: TaskStatus
    archived: bool
    created_at: str
    updated_at: str


class TaskBoard(BaseModel):
    """A consistent snapshot of the current workspace's board."""

    cards: list[TaskCard]


class TaskBoardStore:
    """Open short-lived SQLite connections; never cache a user's active scope."""

    def __init__(self, path: Path):
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        ensure_private_directory(self.path.parent)
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute(
            """CREATE TABLE IF NOT EXISTS cards (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL CHECK(status IN ('todo', 'doing', 'done')),
                archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0, 1)),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        return connection

    @staticmethod
    def _snapshot(connection: sqlite3.Connection) -> TaskBoard:
        rows = connection.execute("SELECT * FROM cards ORDER BY created_at, id")
        return TaskBoard(cards=[TaskCard.model_validate(dict(row)) for row in rows])

    def read(self) -> TaskBoard:
        """Read cards without creating storage for an unused board."""
        if not self.path.exists():
            return TaskBoard(cards=[])
        with closing(self._connect()) as connection:
            return self._snapshot(connection)

    def create(self, payload: CreateCard) -> TaskBoard:
        """Add a task and return the snapshot committed by this transaction."""
        now = datetime.now(timezone.utc).isoformat()
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "INSERT INTO cards VALUES (?, ?, ?, 'todo', 0, ?, ?)",
                (uuid4().hex, payload.title, payload.note, now, now),
            )
            return self._snapshot(connection)

    def update(self, card_id: str, payload: UpdateCard) -> TaskBoard:
        """Edit, move, archive or restore a card atomically; fail if absent."""
        if not self.path.exists():
            raise KeyError(card_id)
        changes = payload.model_dump(exclude_unset=True)
        with closing(self._connect()) as connection, connection:
            # Serialize the read/modify/write across processes as well as threads.
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
            if row is None:
                raise KeyError(card_id)
            card = TaskCard.model_validate(dict(row))
            updated = TaskCard.model_validate({**card.model_dump(), **changes})
            connection.execute(
                """UPDATE cards SET title = ?, note = ?, status = ?, archived = ?,
                   updated_at = ? WHERE id = ?""",
                (
                    updated.title,
                    updated.note,
                    updated.status,
                    updated.archived,
                    datetime.now(timezone.utc).isoformat(),
                    card_id,
                ),
            )
            return self._snapshot(connection)


def get_task_board_store() -> TaskBoardStore:
    """Resolve storage after DeepTutor has installed the request's user/workspace."""
    return TaskBoardStore(get_path_service().get_workspace_dir() / "task-board" / "cards.sqlite")
