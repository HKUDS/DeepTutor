"""Lossless SQLite conversation transfer; all numeric references are preserved.

Transfers refuse primary-key conflicts instead of silently renumbering messages
that books or mastery sources may refer to. Source/target updates share one
SQLite transaction. A verified backup is retained by the migration caller.
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Iterable

from deeptutor.services.workspace.models import WorkspaceError
from deeptutor.services.workspace.references import rebind_local_urls


def transfer_sessions(
    source: Path, destination: Path, session_ids: Iterable[str], workspace_id: str
) -> int:
    ids = sorted(set(session_ids))
    if not ids or source.resolve() == destination.resolve():
        return 0
    from deeptutor.services.session.sqlite_store import SQLiteSessionStore

    SQLiteSessionStore(source)
    SQLiteSessionStore(destination)
    conn = sqlite3.connect(source, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("ATTACH DATABASE ? AS target", (str(destination),))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("CREATE TEMP TABLE selected_sessions (id TEXT PRIMARY KEY)")
        conn.executemany("INSERT INTO selected_sessions VALUES (?)", [(sid,) for sid in ids])
        selected = "SELECT id FROM selected_sessions"
        live = conn.execute(
            f"SELECT id FROM turns WHERE session_id IN ({selected}) AND status IN ('queued','running','waiting_input') LIMIT 1"  # nosec B608 - fixed tables and local schema; values bound
        ).fetchone()
        if live:
            raise WorkspaceError("Wait for active conversations before migrating data.")
        tables = [
            ("sessions", f"id IN ({selected})"),
            ("messages", f"session_id IN ({selected})"),
            ("turns", f"session_id IN ({selected})"),
            (
                "turn_events",
                f"turn_id IN (SELECT id FROM main.turns WHERE session_id IN ({selected}))",  # nosec B608 - fixed tables and local schema; values bound
            ),
            (
                "notebook_categories",
                f"id IN (SELECT category_id FROM main.notebook_entry_categories WHERE entry_id IN (SELECT id FROM main.notebook_entries WHERE session_id IN ({selected})))",  # nosec B608 - fixed tables and local schema; values bound
            ),
            ("notebook_entries", f"session_id IN ({selected})"),
            (
                "notebook_entry_categories",
                f"entry_id IN (SELECT id FROM main.notebook_entries WHERE session_id IN ({selected}))",  # nosec B608 - fixed tables and local schema; values bound
            ),
            ("assessment_attempts", f"session_id IN ({selected})"),
        ]
        for table, where in tables:
            rows = conn.execute(f'SELECT * FROM main."{table}" WHERE {where}').fetchall()  # nosec B608 - fixed tables and local schema; values bound
            if not rows:
                continue
            columns = rows[0].keys()
            # Preserve extension/legacy fields instead of silently discarding
            # them when the target was created by a newer schema version.
            target_columns = {
                row[1] for row in conn.execute(f'PRAGMA target.table_info("{table}")')
            }
            for info in conn.execute(f'PRAGMA main.table_info("{table}")').fetchall():
                if info[1] not in target_columns:
                    name = info[1].replace('"', '""')
                    kind = (
                        info[2]
                        if info[2] in {"TEXT", "INTEGER", "REAL", "BLOB", "NUMERIC"}
                        else "TEXT"
                    )
                    conn.execute(f'ALTER TABLE target."{table}" ADD COLUMN "{name}" {kind}')
            column_sql = ",".join(f'"{name}"' for name in columns)
            placeholders = ",".join("?" for _ in columns)
            for row in rows:
                values = dict(row)
                values = {
                    key: rebind_local_urls(value, workspace_id) if isinstance(value, str) else value
                    for key, value in values.items()
                }
                if table == "sessions":
                    prefs = json.loads(values.get("preferences_json") or "{}")
                    values["preferences_json"] = json.dumps(
                        {**prefs, "workspace_id": workspace_id}, ensure_ascii=False
                    )
                if table == "notebook_categories":
                    existing = conn.execute(
                        "SELECT * FROM target.notebook_categories WHERE id = ?", (row["id"],)
                    ).fetchone()
                    if existing and dict(existing) == dict(row):
                        continue
                conn.execute(
                    f'INSERT INTO target."{table}" ({column_sql}) VALUES ({placeholders})',  # nosec B608 - fixed tables and local schema; values bound
                    tuple(values[name] for name in columns),
                )
                info = conn.execute(f'PRAGMA main.table_info("{table}")').fetchall()
                keys = [column[1] for column in info if column[5]]
                predicate = " AND ".join(f'"{name}"=?' for name in keys)
                saved = conn.execute(
                    f'SELECT {column_sql} FROM target."{table}" WHERE {predicate}',  # nosec B608 - fixed tables and local schema; values bound
                    tuple(values[key] for key in keys),
                ).fetchone()
                if saved is None or dict(saved) != values:
                    raise WorkspaceError("The conversation copy could not be verified.")
        copied = conn.execute(
            f"SELECT count(*) FROM target.sessions WHERE id IN ({selected})"  # nosec B608 - fixed tables and local schema; values bound
        ).fetchone()[0]
        if copied != len(ids):
            raise WorkspaceError("The conversation copy could not be verified.")
        # Notebook and assessment evidence normally survives a conversation
        # deletion by detaching from it. A workspace transfer is different:
        # verified copies now belong to the destination, so remove the source
        # copies explicitly before deleting their conversations.
        conn.execute(
            f"DELETE FROM main.notebook_entries WHERE session_id IN ({selected})"  # nosec B608 - fixed tables and local schema; values bound
        )
        conn.execute(
            f"DELETE FROM main.assessment_attempts WHERE session_id IN ({selected})"  # nosec B608 - fixed tables and local schema; values bound
        )
        conn.execute(f"DELETE FROM main.sessions WHERE id IN ({selected})")  # nosec B608 - fixed tables and local schema; values bound
        conn.commit()
        return copied
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise WorkspaceError(
            "The destination contains conflicting conversation or question IDs. Choose an empty workspace."
        ) from exc
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
