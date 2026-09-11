"""SQLite catalog for private Immersive Reading workspaces.

The database lives below the current owner's existing ``workspace/reading``
directory. The path service supplies the same per-user security boundary used
by notebooks and the content-addressed :class:`ReadingStore`.
"""

from __future__ import annotations

from contextlib import contextmanager
from enum import Enum
from pathlib import Path
import re
import sqlite3
import threading
import time
from typing import Iterator, Sequence
import uuid

from deeptutor.reading.catalog_models import (
    IngestionStatus,
    MaterialRecord,
    ReadingSessionRecord,
    SourceKind,
    WorkspaceRecord,
    WorkspaceTab,
)
from deeptutor.reading.models import ReadingError
from deeptutor.services.path_service import get_path_service

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def _value(value: str | Enum) -> str:
    return str(value.value if isinstance(value, Enum) else value)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class ReadingCatalogStore:
    """Durable workspace metadata for one already-scoped owner."""

    def __init__(self, root: Path | str | None = None) -> None:
        if root is None:
            root = get_path_service().get_workspace_feature_dir("reading")
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "_catalog.sqlite3"
        self._lock = threading.RLock()
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _initialize(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS reading_schema (version INTEGER NOT NULL);
                INSERT INTO reading_schema(version)
                    SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM reading_schema);

                CREATE TABLE IF NOT EXISTS reading_materials (
                    material_id TEXT PRIMARY KEY,
                    content_id TEXT NOT NULL,
                    filename TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL,
                    source_kind TEXT NOT NULL,
                    source_url TEXT NOT NULL DEFAULT '',
                    mime TEXT NOT NULL DEFAULT '',
                    render_mode TEXT NOT NULL DEFAULT 'text',
                    cover_url TEXT NOT NULL DEFAULT '',
                    duration_seconds REAL NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'queued',
                    progress INTEGER NOT NULL DEFAULT 0,
                    error_code TEXT NOT NULL DEFAULT '',
                    error_detail TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    last_opened_at REAL NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_reading_materials_updated
                    ON reading_materials(updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_reading_materials_content
                    ON reading_materials(content_id);

                CREATE TABLE IF NOT EXISTS reading_workspaces (
                    workspace_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    active_material_id TEXT REFERENCES reading_materials(material_id)
                        ON DELETE SET NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_reading_workspaces_updated
                    ON reading_workspaces(updated_at DESC);

                CREATE TABLE IF NOT EXISTS reading_workspace_materials (
                    workspace_id TEXT NOT NULL REFERENCES reading_workspaces(workspace_id)
                        ON DELETE CASCADE,
                    material_id TEXT NOT NULL REFERENCES reading_materials(material_id)
                        ON DELETE CASCADE,
                    tab_order INTEGER NOT NULL,
                    pinned INTEGER NOT NULL DEFAULT 0,
                    opened INTEGER NOT NULL DEFAULT 1,
                    added_at REAL NOT NULL,
                    PRIMARY KEY (workspace_id, material_id),
                    UNIQUE (workspace_id, tab_order)
                );

                CREATE TABLE IF NOT EXISTS reading_workspace_sessions (
                    workspace_id TEXT NOT NULL REFERENCES reading_workspaces(workspace_id)
                        ON DELETE CASCADE,
                    session_id TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL DEFAULT 'New reading conversation',
                    active_material_id TEXT REFERENCES reading_materials(material_id)
                        ON DELETE SET NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (workspace_id, session_id)
                );
                CREATE INDEX IF NOT EXISTS idx_reading_sessions_workspace_updated
                    ON reading_workspace_sessions(workspace_id, updated_at DESC);

                CREATE TABLE IF NOT EXISTS reading_session_links (
                    workspace_id TEXT NOT NULL,
                    source_session_id TEXT NOT NULL,
                    target_session_id TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY (workspace_id, source_session_id, target_session_id),
                    FOREIGN KEY (workspace_id, source_session_id)
                        REFERENCES reading_workspace_sessions(workspace_id, session_id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (workspace_id, target_session_id)
                        REFERENCES reading_workspace_sessions(workspace_id, session_id)
                        ON DELETE CASCADE,
                    CHECK (source_session_id <> target_session_id)
                );
                """
            )
            columns = {
                str(row["name"])
                for row in conn.execute("PRAGMA table_info(reading_materials)").fetchall()
            }
            if "duration_seconds" not in columns:
                conn.execute(
                    "ALTER TABLE reading_materials "
                    "ADD COLUMN duration_seconds REAL NOT NULL DEFAULT 0"
                )
            if self._content_id_is_unique(conn):
                self._remove_content_id_unique_constraint(conn)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_reading_materials_updated "
                "ON reading_materials(updated_at DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_reading_materials_content "
                "ON reading_materials(content_id)"
            )
            conn.execute("UPDATE reading_schema SET version = 3")

    @staticmethod
    def _content_id_is_unique(conn: sqlite3.Connection) -> bool:
        for index in conn.execute("PRAGMA index_list(reading_materials)").fetchall():
            if not bool(index["unique"]):
                continue
            columns = [
                row["name"]
                for row in conn.execute(f"PRAGMA index_info('{index['name']}')").fetchall()
            ]
            if columns == ["content_id"]:
                return True
        return False

    @staticmethod
    def _remove_content_id_unique_constraint(conn: sqlite3.Connection) -> None:
        """Rebuild the legacy table without changing existing material ids."""
        conn.commit()
        conn.execute("PRAGMA foreign_keys = OFF")
        try:
            conn.executescript(
                """
                BEGIN IMMEDIATE;
                CREATE TABLE reading_materials_new (
                    material_id TEXT PRIMARY KEY,
                    content_id TEXT NOT NULL,
                    filename TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL,
                    source_kind TEXT NOT NULL,
                    source_url TEXT NOT NULL DEFAULT '',
                    mime TEXT NOT NULL DEFAULT '',
                    render_mode TEXT NOT NULL DEFAULT 'text',
                    cover_url TEXT NOT NULL DEFAULT '',
                    duration_seconds REAL NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'queued',
                    progress INTEGER NOT NULL DEFAULT 0,
                    error_code TEXT NOT NULL DEFAULT '',
                    error_detail TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    last_opened_at REAL NOT NULL DEFAULT 0
                );
                INSERT INTO reading_materials_new (
                    material_id, content_id, filename, title, source_kind, source_url,
                    mime, render_mode, cover_url, duration_seconds, status, progress,
                    error_code, error_detail, created_at, updated_at, last_opened_at
                )
                SELECT material_id, content_id, filename, title, source_kind, source_url,
                       mime, render_mode, cover_url, duration_seconds, status, progress,
                       error_code, error_detail, created_at, updated_at, last_opened_at
                FROM reading_materials;
                DROP TABLE reading_materials;
                ALTER TABLE reading_materials_new RENAME TO reading_materials;
                COMMIT;
                """
            )
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.execute("PRAGMA foreign_keys = ON")
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:  # pragma: no cover - signals a corrupt legacy catalog
            raise ReadingError("reading catalog migration found invalid material references")

    # -- materials -------------------------------------------------------

    def upsert_material(
        self,
        *,
        content_id: str,
        filename: str,
        title: str,
        source_kind: SourceKind | str,
        source_url: str = "",
        mime: str = "",
        render_mode: str = "text",
        cover_url: str = "",
        duration_seconds: float = 0.0,
        status: IngestionStatus | str = IngestionStatus.QUEUED,
        progress: int | None = None,
        material_id: str | None = None,
        error_code: str = "",
        error_detail: str = "",
    ) -> MaterialRecord:
        content_id = str(content_id or "").strip()
        resolved_id = material_id or (
            content_id if _SAFE_ID.fullmatch(content_id) else _new_id("mat")
        )
        self._validate_id(resolved_id, "material")
        content_id = content_id or resolved_id
        try:
            status_value = IngestionStatus(_value(status)).value
            source_value = SourceKind(_value(source_kind)).value
        except ValueError as exc:
            raise ReadingError(str(exc)) from exc
        resolved_progress = 100 if status_value == "ready" else max(0, min(progress or 0, 99))
        now = time.time()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO reading_materials (
                    material_id, content_id, filename, title, source_kind, source_url,
                    mime, render_mode, cover_url, status, progress, error_code,
                    error_detail, duration_seconds, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(material_id) DO UPDATE SET
                    content_id = excluded.content_id,
                    filename = excluded.filename, title = excluded.title,
                    source_kind = excluded.source_kind, source_url = excluded.source_url,
                    mime = excluded.mime, render_mode = excluded.render_mode,
                    cover_url = CASE WHEN excluded.cover_url <> '' THEN excluded.cover_url
                                     ELSE reading_materials.cover_url END,
                    duration_seconds = CASE WHEN excluded.duration_seconds > 0
                                            THEN excluded.duration_seconds
                                            ELSE reading_materials.duration_seconds END,
                    status = excluded.status, progress = excluded.progress,
                    error_code = excluded.error_code, error_detail = excluded.error_detail,
                    updated_at = excluded.updated_at
                """,
                (
                    resolved_id,
                    content_id,
                    filename.strip()[:500],
                    (title or filename or "Untitled material").strip()[:500],
                    source_value,
                    source_url.strip()[:4096],
                    mime.strip()[:255],
                    render_mode.strip()[:32] or "text",
                    cover_url.strip()[:4096],
                    status_value,
                    resolved_progress,
                    error_code.strip()[:128],
                    error_detail.strip()[:4000],
                    max(0.0, float(duration_seconds or 0)),
                    now,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM reading_materials WHERE material_id = ?", (resolved_id,)
            ).fetchone()
        if row is None:  # pragma: no cover
            raise ReadingError("material could not be stored")
        return self._material(row)

    def register_manifest(self, manifest) -> MaterialRecord:
        """Register an existing ReadingStore manifest without re-extracting it."""
        return self.upsert_material(
            content_id=manifest.material_id,
            material_id=manifest.material_id,
            filename=manifest.filename,
            title=manifest.title,
            source_kind=SourceKind.FILE,
            mime=manifest.mime,
            render_mode=manifest.render_mode,
            status=IngestionStatus.READY,
        )

    def get_material(self, material_id: str) -> MaterialRecord | None:
        self._validate_id(material_id, "material")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM reading_materials WHERE material_id = ?", (material_id,)
            ).fetchone()
        return self._material(row) if row else None

    def find_material_by_content(self, content_id: str) -> MaterialRecord | None:
        """Return the stable default material for shared extracted content."""
        resolved = str(content_id or "").strip()
        if not resolved:
            return None
        with self._connect() as conn:
            row = conn.execute(
                """SELECT * FROM reading_materials WHERE content_id = ?
                   ORDER BY created_at, material_id LIMIT 1""",
                (resolved,),
            ).fetchone()
        return self._material(row) if row else None

    def find_ready_material_by_filename(
        self, filename: str, *, mime: str = ""
    ) -> MaterialRecord | None:
        """Find one ready exact-name match with a compatible media type."""
        resolved_name = Path(str(filename or "")).name.strip()
        if not resolved_name:
            return None
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM reading_materials
                   WHERE filename = ? COLLATE NOCASE AND status = 'ready'
                   ORDER BY updated_at DESC, material_id""",
                (resolved_name,),
            ).fetchall()
        wanted_mime = str(mime or "").strip().lower()
        suffix = Path(resolved_name).suffix.lower()
        for row in rows:
            row_mime = str(row["mime"] or "").lower()
            row_suffix = Path(str(row["filename"] or "")).suffix.lower()
            if not wanted_mime or wanted_mime == row_mime or (suffix and suffix == row_suffix):
                return self._material(row)
        return None

    def list_materials(
        self,
        *,
        search: str = "",
        status: IngestionStatus | str | None = None,
        library_filter: str = "all",
        limit: int = 200,
        offset: int = 0,
    ) -> list[MaterialRecord]:
        clauses: list[str] = []
        params: list[object] = []
        if search.strip():
            escaped = self._escape_like(search.strip())
            clauses.append("(title LIKE ? ESCAPE '\\' OR filename LIKE ? ESCAPE '\\')")
            params.extend((f"%{escaped}%", f"%{escaped}%"))
        if status is not None:
            clauses.append("status = ?")
            params.append(_value(status))
        if library_filter == "unassigned":
            clauses.append(
                "NOT EXISTS (SELECT 1 FROM reading_workspace_materials wm "
                "WHERE wm.material_id = reading_materials.material_id)"
            )
        elif library_filter == "processing":
            clauses.append("status IN ('queued', 'processing')")
        elif library_filter == "failed":
            clauses.append("status = 'failed'")
        elif library_filter != "all":
            raise ReadingError(f"unsupported material library filter: {library_filter}")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend((max(1, min(int(limit), 500)), max(0, int(offset))))
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM reading_materials {where} "  # noqa: S608  # nosec B608 - where is built from internal clauses; every value stays bound
                "ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                params,
            ).fetchall()
        return [self._material(row) for row in rows]

    def collections_for_materials(
        self, material_ids: Sequence[str]
    ) -> dict[str, list[dict[str, str]]]:
        """Load collection membership for many materials with one grouped query."""
        unique_ids = list(dict.fromkeys(material_ids))
        grouped: dict[str, list[dict[str, str]]] = {material_id: [] for material_id in unique_ids}
        if not unique_ids:
            return grouped
        placeholders = ",".join("?" for _ in unique_ids)
        with self._connect() as conn:
            rows = conn.execute(
                f"""SELECT wm.material_id, w.workspace_id, w.title
                    FROM reading_workspace_materials wm
                    JOIN reading_workspaces w USING (workspace_id)
                    WHERE wm.material_id IN ({placeholders})
                    ORDER BY w.title COLLATE NOCASE, w.workspace_id""",  # noqa: S608  # nosec B608 - placeholders is a generated "?,?" list; every value is bound
                unique_ids,
            ).fetchall()
        for row in rows:
            grouped[row["material_id"]].append(
                {"workspace_id": row["workspace_id"], "title": row["title"]}
            )
        return grouped

    def collections_for_material(self, material_id: str) -> list[dict[str, str]]:
        self._validate_id(material_id, "material")
        return self.collections_for_materials([material_id])[material_id]

    def library_counts(
        self,
        material_ids: Sequence[str] | None = None,
    ) -> dict[str, object]:
        """Counts for the visible material library, independent of page filters."""
        params: list[str] = []
        where = ""
        if material_ids is not None:
            ids = tuple(dict.fromkeys(str(item) for item in material_ids if str(item)))
            if ids:
                placeholders = ",".join("?" for _ in ids)
                where = f"WHERE material_id IN ({placeholders})"
                params.extend(ids)
            else:
                where = "WHERE 0"
        with self._connect() as conn:
            row = conn.execute(
                f"""SELECT
                       COUNT(*) AS all_count,
                       COALESCE(SUM(NOT EXISTS (
                           SELECT 1 FROM reading_workspace_materials wm
                           WHERE wm.material_id = reading_materials.material_id
                       )), 0) AS unassigned_count,
                       COALESCE(SUM(status IN ('queued', 'processing')), 0) AS processing_count,
                       COALESCE(SUM(status = 'failed'), 0) AS failed_count,
                       COALESCE(SUM(CASE
                           WHEN render_mode = 'video' OR source_kind = 'video' THEN 1 ELSE 0
                       END), 0) AS video_count,
                       COALESCE(SUM(CASE
                           WHEN render_mode = 'audio' OR source_kind = 'audio' THEN 1 ELSE 0
                       END), 0) AS audio_count,
                       COALESCE(SUM(CASE
                           WHEN render_mode NOT IN ('video', 'audio') AND source_kind = 'web'
                           THEN 1 ELSE 0
                       END), 0) AS web_count,
                       COALESCE(SUM(CASE
                           WHEN render_mode NOT IN ('video', 'audio') AND source_kind = 'file'
                           THEN 1 ELSE 0
                       END), 0) AS document_count
                   FROM reading_materials
                   {where}""",  # nosec B608 - only placeholder shape is interpolated
                params,
            ).fetchone()
        assert row is not None
        return {
            "all": int(row["all_count"]),
            "unassigned": int(row["unassigned_count"]),
            "processing": int(row["processing_count"]),
            "failed": int(row["failed_count"]),
            "by_kind": {
                "document": int(row["document_count"]),
                "web": int(row["web_count"]),
                "video": int(row["video_count"]),
                "audio": int(row["audio_count"]),
            },
        }

    def count_materials_for_content(self, content_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM reading_materials WHERE content_id = ?",
                (str(content_id or "").strip(),),
            ).fetchone()
        return int(row["count"]) if row else 0

    def update_material_status(
        self,
        material_id: str,
        status: IngestionStatus | str,
        *,
        progress: int | None = None,
        error_code: str = "",
        error_detail: str = "",
    ) -> MaterialRecord:
        self._validate_id(material_id, "material")
        value = IngestionStatus(_value(status)).value
        resolved_progress = 100 if value == "ready" else max(0, min(progress or 0, 99))
        with self._lock, self._connect() as conn:
            changed = conn.execute(
                """
                UPDATE reading_materials
                SET status = ?, progress = ?, error_code = ?, error_detail = ?, updated_at = ?
                WHERE material_id = ?
                """,
                (
                    value,
                    resolved_progress,
                    error_code[:128],
                    error_detail[:4000],
                    time.time(),
                    material_id,
                ),
            ).rowcount
        if not changed:
            raise ReadingError(f"material {material_id!r} not found")
        record = self.get_material(material_id)
        assert record is not None
        return record

    def delete_material(self, material_id: str) -> bool:
        self._validate_id(material_id, "material")
        with self._lock, self._connect() as conn:
            return bool(
                conn.execute(
                    "DELETE FROM reading_materials WHERE material_id = ?", (material_id,)
                ).rowcount
            )

    # -- workspaces and tabs --------------------------------------------

    def create_workspace(
        self,
        title: str,
        material_ids: Sequence[str] = (),
        *,
        description: str = "",
        workspace_id: str | None = None,
    ) -> WorkspaceRecord:
        resolved_id = workspace_id or _new_id("rw")
        self._validate_id(resolved_id, "workspace")
        unique_materials = list(dict.fromkeys(material_ids))
        now = time.time()
        with self._lock, self._connect() as conn:
            self._require_materials(conn, unique_materials)
            conn.execute(
                """
                INSERT INTO reading_workspaces (
                    workspace_id, title, description, active_material_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    resolved_id,
                    (title or "Untitled reading workspace").strip()[:300],
                    description.strip()[:2000],
                    unique_materials[0] if unique_materials else None,
                    now,
                    now,
                ),
            )
            conn.executemany(
                """
                INSERT INTO reading_workspace_materials (
                    workspace_id, material_id, tab_order, added_at
                ) VALUES (?, ?, ?, ?)
                """,
                [
                    (resolved_id, material_id, index, now)
                    for index, material_id in enumerate(unique_materials)
                ],
            )
        detail = self.get_workspace(resolved_id)
        assert detail is not None
        return detail

    def get_workspace(self, workspace_id: str) -> WorkspaceRecord | None:
        self._validate_id(workspace_id, "workspace")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM reading_workspaces WHERE workspace_id = ?", (workspace_id,)
            ).fetchone()
            if row is None:
                return None
            return self._workspace(
                row,
                tabs=self._workspace_tabs(conn, workspace_id),
            )

    def list_workspaces(
        self,
        *,
        search: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> list[WorkspaceRecord]:
        clauses: list[str] = []
        params: list[object] = []
        if search.strip():
            clauses.append("w.title LIKE ? ESCAPE '\\'")
            params.append(f"%{self._escape_like(search.strip())}%")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend((max(1, min(int(limit), 500)), max(0, int(offset))))
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT w.workspace_id FROM reading_workspaces w {where} "  # noqa: S608  # nosec B608 - where is built from internal clauses; every value stays bound
                "ORDER BY w.updated_at DESC LIMIT ? OFFSET ?",
                params,
            ).fetchall()
        results: list[WorkspaceRecord] = []
        for row in rows:
            workspace = self.get_workspace(row["workspace_id"])
            if workspace is not None:
                results.append(workspace)
        return results

    def update_workspace(
        self, workspace_id: str, *, title: str | None = None, description: str | None = None
    ) -> WorkspaceRecord:
        self._validate_id(workspace_id, "workspace")
        assignments = ["updated_at = ?"]
        params: list[object] = [time.time()]
        if title is not None:
            assignments.append("title = ?")
            params.append((title or "Untitled reading workspace").strip()[:300])
        if description is not None:
            assignments.append("description = ?")
            params.append(description.strip()[:2000])
        params.append(workspace_id)
        with self._lock, self._connect() as conn:
            changed = conn.execute(
                f"UPDATE reading_workspaces SET {', '.join(assignments)} WHERE workspace_id = ?",  # noqa: S608  # nosec B608 - assignments are internal column names; every value stays bound
                params,
            ).rowcount
        if not changed:
            raise ReadingError(f"workspace {workspace_id!r} not found")
        detail = self.get_workspace(workspace_id)
        assert detail is not None
        return detail

    def delete_workspace(self, workspace_id: str) -> bool:
        self._validate_id(workspace_id, "workspace")
        with self._lock, self._connect() as conn:
            return bool(
                conn.execute(
                    "DELETE FROM reading_workspaces WHERE workspace_id = ?", (workspace_id,)
                ).rowcount
            )

    def add_material(
        self, workspace_id: str, material_id: str, *, make_active: bool = False
    ) -> WorkspaceRecord:
        self._validate_id(workspace_id, "workspace")
        self._validate_id(material_id, "material")
        now = time.time()
        with self._lock, self._connect() as conn:
            self._require_workspace(conn, workspace_id)
            self._require_materials(conn, [material_id])
            existing = conn.execute(
                """SELECT 1 FROM reading_workspace_materials
                   WHERE workspace_id = ? AND material_id = ?""",
                (workspace_id, material_id),
            ).fetchone()
            if existing is None:
                next_order = conn.execute(
                    """SELECT COALESCE(MAX(tab_order), -1) + 1
                       FROM reading_workspace_materials WHERE workspace_id = ?""",
                    (workspace_id,),
                ).fetchone()[0]
                conn.execute(
                    """INSERT INTO reading_workspace_materials
                       (workspace_id, material_id, tab_order, added_at) VALUES (?, ?, ?, ?)""",
                    (workspace_id, material_id, next_order, now),
                )
            current = conn.execute(
                "SELECT active_material_id FROM reading_workspaces WHERE workspace_id = ?",
                (workspace_id,),
            ).fetchone()[0]
            active = material_id if make_active or current is None else current
            conn.execute(
                """UPDATE reading_workspaces SET active_material_id = ?, updated_at = ?
                   WHERE workspace_id = ?""",
                (active, now, workspace_id),
            )
        return self._existing_workspace(workspace_id)

    def remove_material(self, workspace_id: str, material_id: str) -> WorkspaceRecord:
        with self._lock, self._connect() as conn:
            self._require_workspace(conn, workspace_id)
            removed = conn.execute(
                """DELETE FROM reading_workspace_materials
                   WHERE workspace_id = ? AND material_id = ?""",
                (workspace_id, material_id),
            ).rowcount
            if not removed:
                raise ReadingError("material does not belong to this reading workspace")
            rows = conn.execute(
                """SELECT material_id FROM reading_workspace_materials
                   WHERE workspace_id = ? ORDER BY tab_order""",
                (workspace_id,),
            ).fetchall()
            # Move through negative values to avoid the unique order constraint.
            conn.execute(
                "UPDATE reading_workspace_materials SET tab_order = -tab_order - 1 WHERE workspace_id = ?",
                (workspace_id,),
            )
            for index, row in enumerate(rows):
                conn.execute(
                    """UPDATE reading_workspace_materials SET tab_order = ?
                       WHERE workspace_id = ? AND material_id = ?""",
                    (index, workspace_id, row["material_id"]),
                )
            current = conn.execute(
                "SELECT active_material_id FROM reading_workspaces WHERE workspace_id = ?",
                (workspace_id,),
            ).fetchone()[0]
            active = rows[0]["material_id"] if current == material_id and rows else current
            if not rows:
                active = None
            conn.execute(
                """UPDATE reading_workspaces SET active_material_id = ?, updated_at = ?
                   WHERE workspace_id = ?""",
                (active, time.time(), workspace_id),
            )
        return self._existing_workspace(workspace_id)

    def reorder_materials(self, workspace_id: str, material_ids: Sequence[str]) -> WorkspaceRecord:
        ordered = list(material_ids)
        if len(ordered) != len(set(ordered)):
            raise ReadingError("tab order contains duplicate materials")
        with self._lock, self._connect() as conn:
            current = [
                row["material_id"]
                for row in conn.execute(
                    """SELECT material_id FROM reading_workspace_materials
                   WHERE workspace_id = ? ORDER BY tab_order""",
                    (workspace_id,),
                ).fetchall()
            ]
            if set(current) != set(ordered):
                raise ReadingError("tab order must include every workspace material exactly once")
            conn.execute(
                "UPDATE reading_workspace_materials SET tab_order = -tab_order - 1 WHERE workspace_id = ?",
                (workspace_id,),
            )
            for index, material_id in enumerate(ordered):
                conn.execute(
                    """UPDATE reading_workspace_materials SET tab_order = ?
                       WHERE workspace_id = ? AND material_id = ?""",
                    (index, workspace_id, material_id),
                )
            conn.execute(
                "UPDATE reading_workspaces SET updated_at = ? WHERE workspace_id = ?",
                (time.time(), workspace_id),
            )
        return self._existing_workspace(workspace_id)

    def set_active_material(self, workspace_id: str, material_id: str) -> WorkspaceRecord:
        now = time.time()
        with self._lock, self._connect() as conn:
            member = conn.execute(
                """SELECT 1 FROM reading_workspace_materials
                   WHERE workspace_id = ? AND material_id = ?""",
                (workspace_id, material_id),
            ).fetchone()
            if member is None:
                raise ReadingError("material does not belong to this reading workspace")
            conn.execute(
                """UPDATE reading_workspaces SET active_material_id = ?, updated_at = ?
                   WHERE workspace_id = ?""",
                (material_id, now, workspace_id),
            )
            conn.execute(
                "UPDATE reading_materials SET last_opened_at = ? WHERE material_id = ?",
                (now, material_id),
            )
        return self._existing_workspace(workspace_id)

    # -- reading sessions ------------------------------------------------

    def attach_session(
        self,
        workspace_id: str,
        session_id: str,
        *,
        title: str = "New reading conversation",
        active_material_id: str | None = None,
    ) -> ReadingSessionRecord:
        self._validate_id(session_id, "session")
        now = time.time()
        with self._lock, self._connect() as conn:
            self._require_workspace(conn, workspace_id)
            if (
                active_material_id
                and conn.execute(
                    """SELECT 1 FROM reading_workspace_materials
                   WHERE workspace_id = ? AND material_id = ?""",
                    (workspace_id, active_material_id),
                ).fetchone()
                is None
            ):
                raise ReadingError("active material does not belong to this reading workspace")
            existing = conn.execute(
                "SELECT workspace_id FROM reading_workspace_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if existing and existing["workspace_id"] != workspace_id:
                raise ReadingError("session already belongs to another reading workspace")
            conn.execute(
                """INSERT INTO reading_workspace_sessions
                   (workspace_id, session_id, title, active_material_id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(session_id) DO UPDATE SET title = excluded.title,
                       active_material_id = excluded.active_material_id,
                       updated_at = excluded.updated_at""",
                (
                    workspace_id,
                    session_id,
                    (title or "New reading conversation").strip()[:300],
                    active_material_id,
                    now,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM reading_workspace_sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        assert row is not None
        return self._session(row)

    def list_sessions(self, workspace_id: str) -> list[ReadingSessionRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM reading_workspace_sessions
                   WHERE workspace_id = ? ORDER BY updated_at DESC""",
                (workspace_id,),
            ).fetchall()
        return [self._session(row) for row in rows]

    def rename_session(
        self, workspace_id: str, session_id: str, title: str
    ) -> ReadingSessionRecord:
        with self._lock, self._connect() as conn:
            changed = conn.execute(
                """UPDATE reading_workspace_sessions SET title = ?, updated_at = ?
                   WHERE workspace_id = ? AND session_id = ?""",
                (
                    (title or "New reading conversation").strip()[:300],
                    time.time(),
                    workspace_id,
                    session_id,
                ),
            ).rowcount
            row = conn.execute(
                """SELECT * FROM reading_workspace_sessions
                   WHERE workspace_id = ? AND session_id = ?""",
                (workspace_id, session_id),
            ).fetchone()
        if not changed or row is None:
            raise ReadingError("reading session not found in this workspace")
        return self._session(row)

    def detach_session(self, workspace_id: str, session_id: str) -> bool:
        with self._lock, self._connect() as conn:
            return bool(
                conn.execute(
                    """DELETE FROM reading_workspace_sessions
                       WHERE workspace_id = ? AND session_id = ?""",
                    (workspace_id, session_id),
                ).rowcount
            )

    def link_session(
        self, workspace_id: str, source_session_id: str, target_session_id: str
    ) -> None:
        if source_session_id == target_session_id:
            raise ReadingError("a reading session cannot reference itself")
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """SELECT session_id FROM reading_workspace_sessions
                   WHERE workspace_id = ? AND session_id IN (?, ?)""",
                (workspace_id, source_session_id, target_session_id),
            ).fetchall()
            if {row["session_id"] for row in rows} != {source_session_id, target_session_id}:
                raise ReadingError("linked sessions must belong to the same reading workspace")
            conn.execute(
                """INSERT OR IGNORE INTO reading_session_links
                   (workspace_id, source_session_id, target_session_id, created_at)
                   VALUES (?, ?, ?, ?)""",
                (workspace_id, source_session_id, target_session_id, time.time()),
            )

    def list_session_links(self, workspace_id: str, source_session_id: str) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT target_session_id FROM reading_session_links
                   WHERE workspace_id = ? AND source_session_id = ? ORDER BY created_at""",
                (workspace_id, source_session_id),
            ).fetchall()
        return [row["target_session_id"] for row in rows]

    def unlink_session(
        self, workspace_id: str, source_session_id: str, target_session_id: str
    ) -> bool:
        with self._lock, self._connect() as conn:
            return bool(
                conn.execute(
                    """DELETE FROM reading_session_links
                       WHERE workspace_id = ? AND source_session_id = ?
                         AND target_session_id = ?""",
                    (workspace_id, source_session_id, target_session_id),
                ).rowcount
            )

    # -- row and validation helpers -------------------------------------

    @staticmethod
    def _material(row: sqlite3.Row) -> MaterialRecord:
        return MaterialRecord(
            material_id=row["material_id"],
            content_id=row["content_id"],
            filename=row["filename"],
            title=row["title"],
            source_kind=SourceKind(row["source_kind"]),
            source_url=row["source_url"],
            mime=row["mime"],
            render_mode=row["render_mode"],
            cover_url=row["cover_url"],
            duration_seconds=float(row["duration_seconds"]),
            status=IngestionStatus(row["status"]),
            progress=int(row["progress"]),
            error_code=row["error_code"],
            error_detail=row["error_detail"],
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
            last_opened_at=float(row["last_opened_at"]),
        )

    @classmethod
    def _workspace(cls, row: sqlite3.Row, *, tabs=()) -> WorkspaceRecord:
        return WorkspaceRecord(
            workspace_id=row["workspace_id"],
            title=row["title"],
            description=row["description"],
            active_material_id=row["active_material_id"],
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
            tabs=tuple(tabs),
        )

    @classmethod
    def _workspace_tabs(cls, conn: sqlite3.Connection, workspace_id: str) -> list[WorkspaceTab]:
        rows = conn.execute(
            """SELECT m.*, wm.tab_order, wm.pinned, wm.opened, wm.added_at
               FROM reading_workspace_materials wm JOIN reading_materials m USING (material_id)
               WHERE wm.workspace_id = ? ORDER BY wm.tab_order""",
            (workspace_id,),
        ).fetchall()
        return [
            WorkspaceTab(
                material=cls._material(row),
                tab_order=int(row["tab_order"]),
                pinned=bool(row["pinned"]),
                opened=bool(row["opened"]),
                added_at=float(row["added_at"]),
            )
            for row in rows
        ]

    @staticmethod
    def _session(row: sqlite3.Row) -> ReadingSessionRecord:
        return ReadingSessionRecord(
            workspace_id=row["workspace_id"],
            session_id=row["session_id"],
            title=row["title"],
            active_material_id=row["active_material_id"],
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )

    def _existing_workspace(self, workspace_id: str) -> WorkspaceRecord:
        workspace = self.get_workspace(workspace_id)
        if workspace is None:
            raise ReadingError(f"workspace {workspace_id!r} not found")
        return workspace

    @staticmethod
    def _validate_id(value: str, label: str) -> None:
        if not _SAFE_ID.fullmatch(str(value or "")):
            raise ReadingError(f"invalid {label} id: {value!r}")

    @staticmethod
    def _escape_like(value: str) -> str:
        return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    @staticmethod
    def _require_workspace(conn: sqlite3.Connection, workspace_id: str) -> None:
        if (
            conn.execute(
                "SELECT 1 FROM reading_workspaces WHERE workspace_id = ?", (workspace_id,)
            ).fetchone()
            is None
        ):
            raise ReadingError(f"workspace {workspace_id!r} not found")

    @staticmethod
    def _require_materials(conn: sqlite3.Connection, material_ids: Sequence[str]) -> None:
        if not material_ids:
            return
        placeholders = ",".join("?" for _ in material_ids)
        found = {
            row["material_id"]
            for row in conn.execute(
                f"SELECT material_id FROM reading_materials WHERE material_id IN ({placeholders})",  # noqa: S608  # nosec B608 - placeholders is a generated "?,?" list; every value is bound
                list(material_ids),
            ).fetchall()
        }
        missing = [material_id for material_id in material_ids if material_id not in found]
        if missing:
            raise ReadingError(f"unknown reading materials: {', '.join(missing)}")


__all__ = ["ReadingCatalogStore"]
