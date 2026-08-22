"""SQLite-backed storage for synced MarginNote 4 objects.

This is the *only* module that knows the on-disk schema. Every other layer --
tools, capability, HTTP bridge -- goes through the public methods here.

Schema overview
---------------
* ``mn4_objects`` -- one row per synced MN4 entity, JSON payload in ``raw``.
* ``mn4_devices`` -- paired devices with hashed tokens.
* ``mn4_cursors`` -- per-device sync position.
* ``mn4_tombstones`` -- deleted object IDs (soft-delete for conflict resolution).

The database file lives under ``data/marginnote4/<kb_name>.db`` by default.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import secrets
import sqlite3
from typing import Any

from deeptutor.capabilities.marginnote4.models import (
    ALL_TYPES,
    MarginNoteObject,
    PairedDevice,
    SyncBatch,
    SyncResult,
)

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS mn4_objects (
    object_id     TEXT NOT NULL,
    device_id     TEXT NOT NULL,
    object_type   TEXT NOT NULL,
    title         TEXT NOT NULL DEFAULT '',
    content       TEXT NOT NULL DEFAULT '',
    excerpt       TEXT,
    document_id   TEXT,
    document_title TEXT,
    page          INTEGER,
    tags          TEXT NOT NULL DEFAULT '[]',
    links         TEXT NOT NULL DEFAULT '[]',
    color         TEXT,
    created_at    TEXT NOT NULL DEFAULT '',
    updated_at    TEXT NOT NULL DEFAULT '',
    synced_at     TEXT NOT NULL DEFAULT '',
    raw           TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (object_id, device_id)
);

CREATE INDEX IF NOT EXISTS idx_mn4_type   ON mn4_objects (object_type);
CREATE INDEX IF NOT EXISTS idx_mn4_doc    ON mn4_objects (document_id);
CREATE INDEX IF NOT EXISTS idx_mn4_search ON mn4_objects (title);

CREATE TABLE IF NOT EXISTS mn4_devices (
    device_id    TEXT PRIMARY KEY,
    device_name  TEXT NOT NULL DEFAULT '',
    device_kind  TEXT NOT NULL DEFAULT 'macos',
    token_hash   TEXT NOT NULL,
    paired_at    TEXT NOT NULL DEFAULT '',
    last_seen    TEXT NOT NULL DEFAULT '',
    active       INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS mn4_cursors (
    device_id  TEXT PRIMARY KEY,
    cursor     TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS mn4_tombstones (
    object_id  TEXT NOT NULL,
    device_id  TEXT NOT NULL,
    deleted_at TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (object_id, device_id)
);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def default_db_path(kb_name: str, *, path_service: Any = None) -> Path:
    """Default database location under DeepTutor's data directory.

    ``path_service`` overrides whose workspace is used. The device-token
    endpoints carry no session, so they must name the workspace they mean
    rather than inherit whatever the ambient request context happens to be —
    see ``api/routers/marginnote4.py``.
    """
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in kb_name)
    if path_service is None:
        from deeptutor.services.path_service import get_path_service

        path_service = get_path_service()
    return path_service.user_data_dir / "marginnote4" / f"{safe}.db"


def resolve_db_path(
    kb_name: str,
    *,
    metadata: dict[str, Any] | None = None,
    path_service: Any = None,
) -> Path:
    """The store a connected MN4 library actually uses.

    A KB entry may pin ``db_path``; otherwise the path is derived from the name.
    That rule has three readers — the capability binding, the session endpoints
    that pair and list devices, and the device endpoints that sync — and a token
    issued against one store is invisible to a sync resolved against another, so
    it lives here rather than at each of them.

    Pass ``metadata`` when the caller already resolved the KB entry. Otherwise
    it is looked up, and a failure (no such KB, no request context) falls
    through to the derived path.
    """
    if metadata is None:
        metadata = _kb_metadata(kb_name)
    pinned = str((metadata or {}).get("db_path") or "").strip()
    if pinned:
        return Path(pinned)
    return default_db_path(kb_name, path_service=path_service)


def _kb_metadata(kb_name: str) -> dict[str, Any] | None:
    try:
        from deeptutor.multi_user.knowledge_access import resolve_kb_metadata

        return resolve_kb_metadata(kb_name)
    except Exception:  # noqa: BLE001 - unresolvable KB → derive from the name
        return None


class MarginNoteStore:
    """CRUD + search over synced MN4 objects backed by SQLite.

    A single store instance serves one connected MarginNote 4 KB. The store
    owns its SQLite connection and is safe for sequential use from async code
    (each public method opens a short-lived connection).
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @classmethod
    def open_existing(cls, db_path: str | Path) -> "MarginNoteStore | None":
        """Open an already-paired store, or ``None`` when there is none.

        Constructing a store creates its directory and schema, so the
        device-token endpoints — which are reached *before* any credential has
        been checked — must not construct one from caller-supplied input. Use
        this instead: no file, no store, and nothing written to disk by an
        unauthenticated request.
        """
        path = Path(db_path)
        if not path.is_file():
            return None
        return cls(path)

    # -- internal helpers ---------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @staticmethod
    def _row_to_object(row: sqlite3.Row) -> MarginNoteObject:
        return MarginNoteObject(
            object_id=row["object_id"],
            object_type=row["object_type"],
            title=row["title"],
            content=row["content"],
            excerpt=row["excerpt"],
            document_id=row["document_id"],
            document_title=row["document_title"],
            page=row["page"],
            tags=json.loads(row["tags"]),
            links=json.loads(row["links"]),
            color=row["color"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            synced_at=row["synced_at"],
            device_id=row["device_id"],
            raw=json.loads(row["raw"]),
        )

    # -- device pairing -----------------------------------------------------

    def pair_device(
        self,
        *,
        device_name: str = "",
        device_kind: str = "macos",
    ) -> tuple[PairedDevice, str]:
        """Register a new device. Returns ``(device, plaintext_token)``.

        The token is returned once; only its SHA-256 hash is stored. The
        caller must deliver it to the device over a trusted channel.
        """
        device_id = secrets.token_urlsafe(12)
        token = secrets.token_urlsafe(32)
        token_hash = _hash_token(token)
        now = _now_iso()
        device = PairedDevice(
            device_id=device_id,
            device_name=device_name,
            device_kind=device_kind,
            paired_at=now,
            last_seen=now,
        )
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO mn4_devices
                   (device_id, device_name, device_kind, token_hash,
                    paired_at, last_seen, active)
                   VALUES (?, ?, ?, ?, ?, ?, 1)""",
                (device_id, device_name, device_kind, token_hash, now, now),
            )
            conn.execute(
                "INSERT OR REPLACE INTO mn4_cursors (device_id, cursor) VALUES (?, '')",
                (device_id,),
            )
        return device, token

    def revoke_device(self, device_id: str) -> bool:
        """Mark a device inactive. Returns True if a row was affected."""
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE mn4_devices SET active = 0 WHERE device_id = ? AND active = 1",
                (device_id,),
            )
            return cur.rowcount > 0

    def verify_token(self, device_id: str, token: str) -> bool:
        """Check a device token against the stored hash."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT token_hash, active FROM mn4_devices WHERE device_id = ?",
                (device_id,),
            ).fetchone()
        if row is None or not row["active"]:
            return False
        return secrets.compare_digest(row["token_hash"], _hash_token(token))

    def list_devices(self) -> list[PairedDevice]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM mn4_devices ORDER BY paired_at").fetchall()
        return [_row_to_device(r) for r in rows]

    def touch_device(self, device_id: str) -> None:
        """Update last_seen timestamp for a device."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE mn4_devices SET last_seen = ? WHERE device_id = ?",
                (_now_iso(), device_id),
            )

    # -- sync ingest --------------------------------------------------------

    def ingest(self, batch: SyncBatch) -> SyncResult:
        """Upsert a batch of objects and advance the device cursor."""
        stored = updated = deleted = 0
        now = _now_iso()
        with self._connect() as conn:
            for obj in batch.objects:
                if obj.object_type not in ALL_TYPES:
                    logger.warning("Skipping unknown MN4 type: %s", obj.object_type)
                    continue
                prev = conn.execute(
                    "SELECT synced_at FROM mn4_objects WHERE object_id = ? AND device_id = ?",
                    (obj.object_id, batch.device_id),
                ).fetchone()
                synced_at = obj.synced_at or now
                conn.execute(
                    """INSERT INTO mn4_objects
                       (object_id, device_id, object_type, title, content,
                        excerpt, document_id, document_title, page, tags,
                        links, color, created_at, updated_at, synced_at, raw)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(object_id, device_id) DO UPDATE SET
                         object_type=excluded.object_type,
                         title=excluded.title, content=excluded.content,
                         excerpt=excluded.excerpt,
                         document_id=excluded.document_id,
                         document_title=excluded.document_title,
                         page=excluded.page, tags=excluded.tags,
                         links=excluded.links, color=excluded.color,
                         created_at=excluded.created_at,
                         updated_at=excluded.updated_at,
                         synced_at=excluded.synced_at, raw=excluded.raw""",
                    (
                        obj.object_id,
                        batch.device_id,
                        obj.object_type,
                        obj.title,
                        obj.content,
                        obj.excerpt,
                        obj.document_id,
                        obj.document_title,
                        obj.page,
                        json.dumps(obj.tags, ensure_ascii=False),
                        json.dumps(obj.links, ensure_ascii=False),
                        obj.color,
                        obj.created_at,
                        obj.updated_at,
                        synced_at,
                        json.dumps(obj.raw, ensure_ascii=False),
                    ),
                )
                if prev:
                    updated += 1
                else:
                    stored += 1

            for oid in batch.deleted_ids:
                conn.execute(
                    "INSERT OR REPLACE INTO mn4_tombstones "
                    "(object_id, device_id, deleted_at) VALUES (?, ?, ?)",
                    (oid, batch.device_id, now),
                )
                conn.execute(
                    "DELETE FROM mn4_objects WHERE object_id = ? AND device_id = ?",
                    (oid, batch.device_id),
                )
                deleted += 1

            new_cursor = _now_iso()
            conn.execute(
                "INSERT OR REPLACE INTO mn4_cursors (device_id, cursor) VALUES (?, ?)",
                (batch.device_id, new_cursor),
            )

        return SyncResult(stored=stored, updated=updated, deleted=deleted, new_cursor=new_cursor)

    def get_cursor(self, device_id: str) -> str:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT cursor FROM mn4_cursors WHERE device_id = ?",
                (device_id,),
            ).fetchone()
        return row["cursor"] if row else ""

    # -- read operations ----------------------------------------------------

    def get(self, object_id: str, *, device_id: str = "") -> MarginNoteObject | None:
        """Fetch a single object by ID."""
        with self._connect() as conn:
            if device_id:
                row = conn.execute(
                    "SELECT * FROM mn4_objects WHERE object_id = ? AND device_id = ?",
                    (object_id, device_id),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM mn4_objects WHERE object_id = ? LIMIT 1",
                    (object_id,),
                ).fetchone()
        return self._row_to_object(row) if row else None

    def search(
        self,
        query: str,
        *,
        object_type: str = "",
        device_id: str = "",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Case-insensitive substring search over titles and content."""
        query = (query or "").strip()
        if not query:
            return []
        needle = f"%{query.lower()}%"
        sql = (
            "SELECT * FROM mn4_objects "
            "WHERE (LOWER(title) LIKE ? OR LOWER(content) LIKE ? "
            "OR LOWER(COALESCE(excerpt, '')) LIKE ? "
            "OR LOWER(COALESCE(document_title, '')) LIKE ?)"
        )
        params: list[Any] = [needle, needle, needle, needle]
        if object_type:
            sql += " AND object_type = ?"
            params.append(object_type)
        if device_id:
            sql += " AND device_id = ?"
            params.append(device_id)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_to_summary(self._row_to_object(r), query) for r in rows]

    def list_objects(
        self,
        *,
        object_type: str = "",
        document_id: str = "",
        device_id: str = "",
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """List objects with optional type/document filter."""
        sql = "SELECT * FROM mn4_objects WHERE 1=1"
        params: list[Any] = []
        if object_type:
            sql += " AND object_type = ?"
            params.append(object_type)
        if document_id:
            sql += " AND document_id = ?"
            params.append(document_id)
        if device_id:
            sql += " AND device_id = ?"
            params.append(device_id)
        sql += " ORDER BY COALESCE(document_title, title), updated_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_to_summary(self._row_to_object(r), "") for r in rows]

    def list_documents(self, *, device_id: str = "") -> list[dict[str, Any]]:
        """Distinct source documents with object counts."""
        sql = (
            "SELECT document_id, document_title, COUNT(*) AS n "
            "FROM mn4_objects WHERE document_id IS NOT NULL"
        )
        params: list[Any] = []
        if device_id:
            sql += " AND device_id = ?"
            params.append(device_id)
        sql += " GROUP BY document_id, document_title ORDER BY document_title"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            {
                "document_id": r["document_id"],
                "title": r["document_title"] or "(untitled)",
                "count": int(r["n"]),
            }
            for r in rows
        ]

    def linked_objects(self, object_id: str, *, device_id: str = "") -> list[dict[str, Any]]:
        """Return objects linked TO or FROM the given object."""
        obj = self.get(object_id, device_id=device_id)
        if obj is None:
            return []
        linked_ids = set(obj.links)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT object_id FROM mn4_objects WHERE links LIKE ?",
                (f'%"{object_id}"%',),
            ).fetchall()
        for r in rows:
            linked_ids.add(r["object_id"])
        results: list[dict[str, Any]] = []
        for lid in linked_ids:
            linked = self.get(lid, device_id=device_id)
            if linked:
                results.append(_to_summary(linked, ""))
        return results

    def collect_tags(self, *, device_id: str = "", limit: int = 200) -> list[dict[str, Any]]:
        """All tags across objects, ranked by frequency."""
        with self._connect() as conn:
            sql = "SELECT tags FROM mn4_objects"
            params: list[Any] = []
            if device_id:
                sql += " WHERE device_id = ?"
                params.append(device_id)
            rows = conn.execute(sql, params).fetchall()
        counts: dict[str, int] = {}
        for r in rows:
            for tag in json.loads(r["tags"]):
                tag = tag.strip()
                if tag:
                    counts[tag] = counts.get(tag, 0) + 1
        ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        return [{"tag": t, "count": c} for t, c in ranked[:limit]]

    def count(self, *, device_id: str = "") -> int:
        """Total object count, optionally filtered by device."""
        with self._connect() as conn:
            if device_id:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM mn4_objects WHERE device_id = ?",
                    (device_id,),
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) AS n FROM mn4_objects").fetchone()
        return row["n"]


def _row_to_device(row: sqlite3.Row) -> PairedDevice:
    return PairedDevice(
        device_id=row["device_id"],
        device_name=row["device_name"],
        device_kind=row["device_kind"],
        paired_at=row["paired_at"],
        last_seen=row["last_seen"],
        active=bool(row["active"]),
    )


def _to_summary(obj: MarginNoteObject, query: str) -> dict[str, Any]:
    """Compact dict for search/list results (omits raw payload)."""
    body = obj.content or obj.excerpt or ""
    return {
        "object_id": obj.object_id,
        "object_type": obj.object_type,
        "title": obj.title,
        "document_title": obj.document_title,
        "page": obj.page,
        "tags": obj.tags,
        "snippet": _snippet(body, query),
        "updated_at": obj.updated_at,
    }


def _snippet(body: str, query: str, width: int = 160) -> str:
    if not body:
        return ""
    if not query:
        return body[:width].strip().replace("\n", " ")
    lowered = body.lower()
    idx = lowered.find(query.lower())
    if idx < 0:
        return body[:width].strip().replace("\n", " ")
    start = max(0, idx - width // 3)
    tail = "..." if start + width < len(body) else ""
    return ("..." if start else "") + body[start : start + width].strip().replace("\n", " ") + tail


__all__ = ["MarginNoteStore"]
