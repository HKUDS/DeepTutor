"""SQLite store for video-learning remote control and notes.

Owns pairing codes, device tokens, live player sessions, commands, and
timestamped notes. Device-token endpoints must never create a database from
unauthenticated input; use VideoLearningStore.open_existing.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import secrets
import sqlite3
import string
from pathlib import Path
from typing import Any

from deeptutor.video_learning.models import (
    Device,
    Pairing,
    PlayerCommand,
    PlayerSession,
    VideoNote,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pairings (
    pairing_id   TEXT PRIMARY KEY,
    code         TEXT NOT NULL UNIQUE,
    claim_secret TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    expires_at   TEXT NOT NULL,
    claimed      INTEGER NOT NULL DEFAULT 0,
    claimed_at   TEXT,
    owner_id     TEXT,
    device_id    TEXT
);

CREATE TABLE IF NOT EXISTS pairing_tokens (
    pairing_id  TEXT PRIMARY KEY,
    token_plain TEXT NOT NULL,
    delivered   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS devices (
    device_id    TEXT PRIMARY KEY,
    owner_id     TEXT NOT NULL,
    device_name  TEXT NOT NULL DEFAULT '',
    device_kind  TEXT NOT NULL DEFAULT 'ipad',
    token_hash   TEXT NOT NULL,
    paired_at    TEXT NOT NULL,
    last_seen    TEXT NOT NULL,
    active       INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_vl_devices_owner ON devices (owner_id);

CREATE TABLE IF NOT EXISTS sessions (
    session_id         TEXT PRIMARY KEY,
    owner_id           TEXT NOT NULL,
    device_id          TEXT NOT NULL,
    instance_origin    TEXT NOT NULL,
    video_id           TEXT NOT NULL,
    title              TEXT NOT NULL DEFAULT '',
    position_ms        INTEGER NOT NULL DEFAULT 0,
    duration_ms        INTEGER NOT NULL DEFAULT 0,
    playback_state     TEXT NOT NULL DEFAULT 'unknown',
    playback_rate      REAL NOT NULL DEFAULT 1.0,
    updated_at         TEXT NOT NULL,
    last_heartbeat_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_vl_sessions_owner ON sessions (owner_id);
CREATE INDEX IF NOT EXISTS idx_vl_sessions_device ON sessions (device_id);

CREATE TABLE IF NOT EXISTS commands (
    command_id   TEXT PRIMARY KEY,
    session_id   TEXT NOT NULL,
    owner_id     TEXT NOT NULL,
    device_id    TEXT NOT NULL,
    command_type TEXT NOT NULL,
    payload      TEXT NOT NULL DEFAULT '{}',
    status       TEXT NOT NULL DEFAULT 'pending',
    created_at   TEXT NOT NULL,
    acked_at     TEXT,
    error        TEXT
);

CREATE INDEX IF NOT EXISTS idx_vl_commands_session_status
    ON commands (session_id, status, created_at);

CREATE TABLE IF NOT EXISTS notes (
    note_id         TEXT PRIMARY KEY,
    owner_id        TEXT NOT NULL,
    source          TEXT NOT NULL DEFAULT 'invidious',
    instance_origin TEXT NOT NULL DEFAULT '',
    video_id        TEXT NOT NULL,
    title           TEXT NOT NULL DEFAULT '',
    position_ms     INTEGER NOT NULL,
    body            TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_vl_notes_owner_video
    ON notes (owner_id, video_id, position_ms);
"""

PAIRING_TTL = timedelta(minutes=5)
SESSION_OFFLINE_AFTER = timedelta(seconds=15)
COMMAND_TTL = timedelta(seconds=30)
CODE_ALPHABET = string.digits


class VideoLearningError(RuntimeError):
    """Base error for the video-learning store."""


class VideoLearningNotFound(VideoLearningError):
    """Requested record does not exist."""


class VideoLearningConflict(VideoLearningError):
    """Invalid state transition or duplicate claim."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _code(length: int = 6) -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(length))


def default_db_path(*, path_service: Any = None) -> Path:
    if path_service is None:
        from deeptutor.services.path_service import get_path_service

        path_service = get_path_service()
    return path_service.user_data_dir / "video_learning" / "remote.db"


class VideoLearningStore:
    """SQLite-backed remote-control + notes store."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @classmethod
    def open_existing(cls, db_path: str | Path) -> VideoLearningStore | None:
        path = Path(db_path)
        if not path.is_file():
            return None
        return cls(path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @staticmethod
    def _row_to_pairing(row: sqlite3.Row) -> Pairing:
        return Pairing(
            pairing_id=row["pairing_id"],
            code=row["code"],
            claim_secret=row["claim_secret"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            claimed=bool(row["claimed"]),
            claimed_at=row["claimed_at"],
            owner_id=row["owner_id"],
            device_id=row["device_id"],
        )

    @staticmethod
    def _row_to_device(row: sqlite3.Row) -> Device:
        return Device(
            device_id=row["device_id"],
            owner_id=row["owner_id"],
            device_name=row["device_name"],
            device_kind=row["device_kind"],
            paired_at=row["paired_at"],
            last_seen=row["last_seen"],
            active=bool(row["active"]),
        )

    @staticmethod
    def _row_to_session(row: sqlite3.Row) -> PlayerSession:
        return PlayerSession(
            session_id=row["session_id"],
            owner_id=row["owner_id"],
            device_id=row["device_id"],
            instance_origin=row["instance_origin"],
            video_id=row["video_id"],
            title=row["title"],
            position_ms=int(row["position_ms"]),
            duration_ms=int(row["duration_ms"]),
            playback_state=row["playback_state"],
            playback_rate=float(row["playback_rate"]),
            updated_at=row["updated_at"],
            last_heartbeat_at=row["last_heartbeat_at"],
        )

    @staticmethod
    def _row_to_command(row: sqlite3.Row) -> PlayerCommand:
        return PlayerCommand(
            command_id=row["command_id"],
            session_id=row["session_id"],
            owner_id=row["owner_id"],
            device_id=row["device_id"],
            command_type=row["command_type"],
            payload=json.loads(row["payload"] or "{}"),
            status=row["status"],
            created_at=row["created_at"],
            acked_at=row["acked_at"],
            error=row["error"],
        )

    @staticmethod
    def _row_to_note(row: sqlite3.Row) -> VideoNote:
        return VideoNote(
            note_id=row["note_id"],
            owner_id=row["owner_id"],
            source=row["source"],
            instance_origin=row["instance_origin"],
            video_id=row["video_id"],
            title=row["title"],
            position_ms=int(row["position_ms"]),
            body=row["body"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def create_pairing(self) -> Pairing:
        now = _now()
        pairing = Pairing(
            pairing_id=secrets.token_urlsafe(12),
            code=_code(),
            claim_secret=secrets.token_urlsafe(24),
            created_at=now.isoformat(),
            expires_at=(now + PAIRING_TTL).isoformat(),
        )
        for _ in range(8):
            try:
                with self._connect() as conn:
                    conn.execute(
                        """INSERT INTO pairings
                           (pairing_id, code, claim_secret, created_at, expires_at)
                           VALUES (?, ?, ?, ?, ?)""",
                        (
                            pairing.pairing_id,
                            pairing.code,
                            pairing.claim_secret,
                            pairing.created_at,
                            pairing.expires_at,
                        ),
                    )
                return pairing
            except sqlite3.IntegrityError:
                pairing.code = _code()
        raise VideoLearningError("Could not allocate a unique pairing code.")

    def get_pairing(self, pairing_id: str) -> Pairing | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM pairings WHERE pairing_id = ?",
                (pairing_id,),
            ).fetchone()
        return self._row_to_pairing(row) if row else None

    def get_pairing_by_code(self, code: str) -> Pairing | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM pairings WHERE code = ?",
                (code.strip(),),
            ).fetchone()
        return self._row_to_pairing(row) if row else None

    def claim_pairing(
        self,
        *,
        code: str,
        owner_id: str,
        device_name: str = "iPad",
        device_kind: str = "ipad",
    ) -> tuple[Pairing, Device, str]:
        pairing = self.get_pairing_by_code(code)
        if pairing is None:
            raise VideoLearningNotFound("Pairing code not found.")
        if pairing.claimed:
            raise VideoLearningConflict("Pairing code already claimed.")
        if _parse_iso(pairing.expires_at) <= _now():
            raise VideoLearningConflict("Pairing code expired.")

        device_id = secrets.token_urlsafe(12)
        token = secrets.token_urlsafe(32)
        now = _now_iso()
        device = Device(
            device_id=device_id,
            owner_id=owner_id,
            device_name=device_name or "iPad",
            device_kind=device_kind or "ipad",
            paired_at=now,
            last_seen=now,
            active=True,
        )
        with self._connect() as conn:
            cur = conn.execute(
                """UPDATE pairings
                   SET claimed = 1, claimed_at = ?, owner_id = ?, device_id = ?
                   WHERE pairing_id = ? AND claimed = 0""",
                (now, owner_id, device_id, pairing.pairing_id),
            )
            if cur.rowcount != 1:
                raise VideoLearningConflict("Pairing code already claimed.")
            conn.execute(
                """INSERT INTO devices
                   (device_id, owner_id, device_name, device_kind, token_hash,
                    paired_at, last_seen, active)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 1)""",
                (
                    device.device_id,
                    device.owner_id,
                    device.device_name,
                    device.device_kind,
                    _hash_token(token),
                    device.paired_at,
                    device.last_seen,
                ),
            )
            conn.execute(
                """INSERT INTO pairing_tokens (pairing_id, token_plain, delivered)
                   VALUES (?, ?, 0)""",
                (pairing.pairing_id, token),
            )
        pairing.claimed = True
        pairing.claimed_at = now
        pairing.owner_id = owner_id
        pairing.device_id = device_id
        return pairing, device, token

    def pairing_status(self, pairing_id: str, claim_secret: str) -> dict[str, Any]:
        pairing = self.get_pairing(pairing_id)
        if pairing is None or not secrets.compare_digest(pairing.claim_secret, claim_secret):
            raise VideoLearningNotFound("Pairing not found.")
        expired = _parse_iso(pairing.expires_at) <= _now()
        if not pairing.claimed:
            return {
                "pairing_id": pairing.pairing_id,
                "status": "expired" if expired else "pending",
                "expires_at": pairing.expires_at,
            }

        token: str | None = None
        with self._connect() as conn:
            row = conn.execute(
                """SELECT token_plain FROM pairing_tokens
                   WHERE pairing_id = ? AND delivered = 0""",
                (pairing_id,),
            ).fetchone()
            if row is not None:
                token = row["token_plain"]
                conn.execute(
                    "UPDATE pairing_tokens SET delivered = 1 WHERE pairing_id = ?",
                    (pairing_id,),
                )
        result: dict[str, Any] = {
            "pairing_id": pairing.pairing_id,
            "status": "claimed",
            "expires_at": pairing.expires_at,
            "device_id": pairing.device_id,
            "owner_id": pairing.owner_id,
        }
        if token is not None:
            result["token"] = token
        return result

    def list_devices(self, owner_id: str) -> list[Device]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM devices
                   WHERE owner_id = ?
                   ORDER BY paired_at DESC""",
                (owner_id,),
            ).fetchall()
        return [self._row_to_device(row) for row in rows]

    def revoke_device(self, owner_id: str, device_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                """UPDATE devices SET active = 0
                   WHERE device_id = ? AND owner_id = ? AND active = 1""",
                (device_id, owner_id),
            )
            return cur.rowcount > 0

    def verify_token(self, device_id: str, token: str) -> Device | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM devices WHERE device_id = ?",
                (device_id,),
            ).fetchone()
        if row is None or not row["active"]:
            return None
        if not secrets.compare_digest(row["token_hash"], _hash_token(token)):
            return None
        return self._row_to_device(row)

    def touch_device(self, device_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE devices SET last_seen = ? WHERE device_id = ?",
                (_now_iso(), device_id),
            )

    def upsert_session(
        self,
        *,
        device: Device,
        instance_origin: str,
        video_id: str,
        title: str,
        position_ms: int,
        duration_ms: int,
        playback_state: str,
        playback_rate: float,
        session_id: str | None = None,
    ) -> PlayerSession:
        now = _now_iso()
        sid = session_id or secrets.token_urlsafe(12)
        with self._connect() as conn:
            existing = None
            if session_id:
                existing = conn.execute(
                    "SELECT session_id FROM sessions WHERE session_id = ? AND device_id = ?",
                    (session_id, device.device_id),
                ).fetchone()
            if existing is None:
                active = conn.execute(
                    """SELECT session_id FROM sessions
                       WHERE device_id = ? AND video_id = ? AND instance_origin = ?
                       ORDER BY last_heartbeat_at DESC LIMIT 1""",
                    (device.device_id, video_id, instance_origin),
                ).fetchone()
                if active is not None:
                    sid = active["session_id"]
                    existing = active
            if existing is None:
                conn.execute(
                    """INSERT INTO sessions
                       (session_id, owner_id, device_id, instance_origin, video_id,
                        title, position_ms, duration_ms, playback_state, playback_rate,
                        updated_at, last_heartbeat_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        sid,
                        device.owner_id,
                        device.device_id,
                        instance_origin,
                        video_id,
                        title,
                        max(0, int(position_ms)),
                        max(0, int(duration_ms)),
                        playback_state or "unknown",
                        float(playback_rate or 1.0),
                        now,
                        now,
                    ),
                )
            else:
                conn.execute(
                    """UPDATE sessions SET
                        title = ?, position_ms = ?, duration_ms = ?,
                        playback_state = ?, playback_rate = ?,
                        updated_at = ?, last_heartbeat_at = ?
                       WHERE session_id = ?""",
                    (
                        title,
                        max(0, int(position_ms)),
                        max(0, int(duration_ms)),
                        playback_state or "unknown",
                        float(playback_rate or 1.0),
                        now,
                        now,
                        sid,
                    ),
                )
            conn.execute(
                "UPDATE devices SET last_seen = ? WHERE device_id = ?",
                (now, device.device_id),
            )
            row = conn.execute(
                "SELECT * FROM sessions WHERE session_id = ?",
                (sid,),
            ).fetchone()
        return self._row_to_session(row)

    def list_sessions(self, owner_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM sessions
                   WHERE owner_id = ?
                   ORDER BY last_heartbeat_at DESC""",
                (owner_id,),
            ).fetchall()
        result = []
        for row in rows:
            session = self._row_to_session(row)
            online = (_now() - _parse_iso(session.last_heartbeat_at)) <= SESSION_OFFLINE_AFTER
            result.append(
                {
                    "session_id": session.session_id,
                    "owner_id": session.owner_id,
                    "device_id": session.device_id,
                    "instance_origin": session.instance_origin,
                    "video_id": session.video_id,
                    "title": session.title,
                    "position_ms": session.position_ms,
                    "duration_ms": session.duration_ms,
                    "playback_state": session.playback_state,
                    "playback_rate": session.playback_rate,
                    "updated_at": session.updated_at,
                    "last_heartbeat_at": session.last_heartbeat_at,
                    "online": online,
                }
            )
        return result

    def get_session(self, session_id: str, owner_id: str | None = None) -> PlayerSession | None:
        with self._connect() as conn:
            if owner_id is None:
                row = conn.execute(
                    "SELECT * FROM sessions WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM sessions WHERE session_id = ? AND owner_id = ?",
                    (session_id, owner_id),
                ).fetchone()
        return self._row_to_session(row) if row else None

    def session_is_online(self, session: PlayerSession) -> bool:
        return (_now() - _parse_iso(session.last_heartbeat_at)) <= SESSION_OFFLINE_AFTER

    def enqueue_command(
        self,
        *,
        session: PlayerSession,
        command_type: str,
        payload: dict[str, Any] | None = None,
        command_id: str | None = None,
    ) -> PlayerCommand:
        if command_type not in {"pause", "play", "seek"}:
            raise VideoLearningConflict(f"Unsupported command type: {command_type}")
        if not self.session_is_online(session):
            raise VideoLearningConflict("Player session is offline.")
        cid = command_id or secrets.token_urlsafe(12)
        now = _now_iso()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT * FROM commands WHERE command_id = ?",
                (cid,),
            ).fetchone()
            if existing is not None:
                return self._row_to_command(existing)
            conn.execute(
                """INSERT INTO commands
                   (command_id, session_id, owner_id, device_id, command_type,
                    payload, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)""",
                (
                    cid,
                    session.session_id,
                    session.owner_id,
                    session.device_id,
                    command_type,
                    json.dumps(payload or {}),
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM commands WHERE command_id = ?",
                (cid,),
            ).fetchone()
        return self._row_to_command(row)

    def pending_commands(self, device_id: str, session_id: str | None = None) -> list[PlayerCommand]:
        cutoff = (_now() - COMMAND_TTL).isoformat()
        with self._connect() as conn:
            conn.execute(
                """UPDATE commands SET status = 'expired'
                   WHERE device_id = ? AND status = 'pending' AND created_at < ?""",
                (device_id, cutoff),
            )
            if session_id:
                rows = conn.execute(
                    """SELECT * FROM commands
                       WHERE device_id = ? AND session_id = ? AND status = 'pending'
                       ORDER BY created_at ASC""",
                    (device_id, session_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM commands
                       WHERE device_id = ? AND status = 'pending'
                       ORDER BY created_at ASC""",
                    (device_id,),
                ).fetchall()
        return [self._row_to_command(row) for row in rows]

    def ack_command(
        self,
        *,
        device_id: str,
        command_id: str,
        ok: bool,
        error: str | None = None,
    ) -> PlayerCommand:
        now = _now_iso()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM commands WHERE command_id = ? AND device_id = ?",
                (command_id, device_id),
            ).fetchone()
            if row is None:
                raise VideoLearningNotFound("Command not found.")
            if row["status"] in {"acked", "failed"}:
                return self._row_to_command(row)
            status = "acked" if ok else "failed"
            conn.execute(
                """UPDATE commands
                   SET status = ?, acked_at = ?, error = ?
                   WHERE command_id = ?""",
                (status, now, error, command_id),
            )
            row = conn.execute(
                "SELECT * FROM commands WHERE command_id = ?",
                (command_id,),
            ).fetchone()
        return self._row_to_command(row)

    def get_command(self, command_id: str, owner_id: str) -> PlayerCommand | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM commands WHERE command_id = ? AND owner_id = ?",
                (command_id, owner_id),
            ).fetchone()
        return self._row_to_command(row) if row else None

    def create_note(
        self,
        *,
        owner_id: str,
        video_id: str,
        position_ms: int,
        body: str,
        title: str = "",
        source: str = "invidious",
        instance_origin: str = "",
    ) -> VideoNote:
        body = (body or "").strip()
        if not body:
            raise VideoLearningConflict("Note body is required.")
        if not video_id.strip():
            raise VideoLearningConflict("video_id is required.")
        now = _now_iso()
        note = VideoNote(
            note_id=secrets.token_urlsafe(12),
            owner_id=owner_id,
            source=source or "invidious",
            instance_origin=instance_origin or "",
            video_id=video_id.strip(),
            title=title or "",
            position_ms=max(0, int(position_ms)),
            body=body,
            created_at=now,
            updated_at=now,
        )
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO notes
                   (note_id, owner_id, source, instance_origin, video_id, title,
                    position_ms, body, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    note.note_id,
                    note.owner_id,
                    note.source,
                    note.instance_origin,
                    note.video_id,
                    note.title,
                    note.position_ms,
                    note.body,
                    note.created_at,
                    note.updated_at,
                ),
            )
        return note

    def list_notes(self, owner_id: str, video_id: str) -> list[VideoNote]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM notes
                   WHERE owner_id = ? AND video_id = ?
                   ORDER BY position_ms ASC, created_at ASC""",
                (owner_id, video_id),
            ).fetchall()
        return [self._row_to_note(row) for row in rows]

    def update_note(self, owner_id: str, note_id: str, body: str) -> VideoNote:
        body = (body or "").strip()
        if not body:
            raise VideoLearningConflict("Note body is required.")
        now = _now_iso()
        with self._connect() as conn:
            cur = conn.execute(
                """UPDATE notes SET body = ?, updated_at = ?
                   WHERE note_id = ? AND owner_id = ?""",
                (body, now, note_id, owner_id),
            )
            if cur.rowcount != 1:
                raise VideoLearningNotFound("Note not found.")
            row = conn.execute(
                "SELECT * FROM notes WHERE note_id = ?",
                (note_id,),
            ).fetchone()
        return self._row_to_note(row)

    def delete_note(self, owner_id: str, note_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM notes WHERE note_id = ? AND owner_id = ?",
                (note_id, owner_id),
            )
            return cur.rowcount > 0
