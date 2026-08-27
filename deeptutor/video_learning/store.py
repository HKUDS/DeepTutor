"""SQLite store for video-learning remote control and notes.

Owns pairing codes, device tokens, live player sessions, commands, and
timestamped notes. Device-token endpoints must never create a database from
unauthenticated input; use VideoLearningStore.open_existing.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
import string
from typing import Any

from deeptutor.video_learning.models import (
    Device,
    DeviceCommand,
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

CREATE TABLE IF NOT EXISTS renderer_bootstraps (
    bootstrap_id TEXT PRIMARY KEY, ticket_hash TEXT NOT NULL UNIQUE, owner_id TEXT NOT NULL,
    device_name TEXT NOT NULL DEFAULT 'iPad', device_kind TEXT NOT NULL DEFAULT 'ipad',
    invidious_origin TEXT NOT NULL DEFAULT '', material_id TEXT NOT NULL DEFAULT '',
    expires_at TEXT NOT NULL, redeemed_at TEXT
);
CREATE TABLE IF NOT EXISTS renderer_material_bindings (
    device_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, material_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS renderer_invidious_sessions (
    device_id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    invidious_origin TEXT NOT NULL,
    session_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS device_commands (
    command_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, device_id TEXT NOT NULL,
    command_type TEXT NOT NULL, payload TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL, acked_at TEXT, error TEXT
);
CREATE INDEX IF NOT EXISTS idx_vl_device_commands_status ON device_commands (device_id, status, created_at);

CREATE TABLE IF NOT EXISTS sessions (
    session_id         TEXT PRIMARY KEY,
    owner_id           TEXT NOT NULL,
    device_id          TEXT NOT NULL,
    instance_origin    TEXT NOT NULL,
    video_id           TEXT NOT NULL,
    material_id        TEXT NOT NULL DEFAULT '',
    title              TEXT NOT NULL DEFAULT '',
    position_ms        INTEGER NOT NULL DEFAULT 0,
    duration_ms        INTEGER NOT NULL DEFAULT 0,
    playback_state     TEXT NOT NULL DEFAULT 'unknown',
    playback_rate      REAL NOT NULL DEFAULT 1.0,
    controller_token_hash TEXT NOT NULL DEFAULT '',
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
            session_columns = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
            if "controller_token_hash" not in session_columns:
                conn.execute("ALTER TABLE sessions ADD COLUMN controller_token_hash TEXT NOT NULL DEFAULT ''")
            if "material_id" not in session_columns:
                conn.execute("ALTER TABLE sessions ADD COLUMN material_id TEXT NOT NULL DEFAULT ''")
            bootstrap_columns = {row[1] for row in conn.execute("PRAGMA table_info(renderer_bootstraps)")}
            if "invidious_origin" not in bootstrap_columns:
                conn.execute("ALTER TABLE renderer_bootstraps ADD COLUMN invidious_origin TEXT NOT NULL DEFAULT ''")
            if "material_id" not in bootstrap_columns:
                conn.execute("ALTER TABLE renderer_bootstraps ADD COLUMN material_id TEXT NOT NULL DEFAULT ''")

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
            material_id=str(row["material_id"] or ""),
            title=row["title"],
            position_ms=int(row["position_ms"]),
            duration_ms=int(row["duration_ms"]),
            playback_state=row["playback_state"],
            playback_rate=float(row["playback_rate"]),
            updated_at=row["updated_at"],
            last_heartbeat_at=row["last_heartbeat_at"],
            controller_token_hash=str(row["controller_token_hash"] or ""),
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
    def _row_to_device_command(row: sqlite3.Row) -> DeviceCommand:
        return DeviceCommand(command_id=row["command_id"], owner_id=row["owner_id"], device_id=row["device_id"],
            command_type=row["command_type"], payload=json.loads(row["payload"] or "{}"), status=row["status"],
            created_at=row["created_at"], acked_at=row["acked_at"], error=row["error"])

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

    def device_is_online(self, device: Device) -> bool:
        return device.active and (_now() - _parse_iso(device.last_seen)) <= SESSION_OFFLINE_AFTER

    def create_renderer_bootstrap(
        self,
        *,
        owner_id: str,
        device_name: str = "iPad",
        device_kind: str = "ipad",
        invidious_origin: str = "",
        material_id: str = "",
    ) -> tuple[str, str, str]:
        ticket, bootstrap_id = secrets.token_urlsafe(32), secrets.token_urlsafe(12)
        expires_at = (_now() + PAIRING_TTL).isoformat()
        with self._connect() as conn:
            conn.execute("INSERT INTO renderer_bootstraps (bootstrap_id,ticket_hash,owner_id,device_name,device_kind,invidious_origin,material_id,expires_at) VALUES (?,?,?,?,?,?,?,?)",
                         (bootstrap_id, _hash_token(ticket), owner_id, device_name or "iPad", device_kind or "ipad", invidious_origin, material_id, expires_at))
        return bootstrap_id, ticket, expires_at

    def redeem_renderer_bootstrap(self, *, ticket: str) -> tuple[Device, str, str]:
        now, device_id, token = _now_iso(), secrets.token_urlsafe(12), secrets.token_urlsafe(32)
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM renderer_bootstraps WHERE ticket_hash=? AND redeemed_at IS NULL", (_hash_token(ticket),)).fetchone()
            if row is None:
                raise VideoLearningNotFound("Bootstrap ticket not found.")
            if _parse_iso(row["expires_at"]) <= _now():
                raise VideoLearningConflict("Bootstrap ticket expired.")
            redeemed = conn.execute(
                "UPDATE renderer_bootstraps SET redeemed_at=? WHERE bootstrap_id=? AND redeemed_at IS NULL",
                (now, row["bootstrap_id"]),
            )
            if redeemed.rowcount != 1:
                raise VideoLearningConflict("Bootstrap ticket already redeemed.")
            conn.execute("INSERT INTO devices (device_id,owner_id,device_name,device_kind,token_hash,paired_at,last_seen,active) VALUES (?,?,?,?,?,?,?,1)",
                         (device_id,row["owner_id"],row["device_name"],row["device_kind"],_hash_token(token),now,now))
            if row["material_id"]:
                conn.execute(
                    """INSERT INTO renderer_material_bindings
                       (device_id, owner_id, material_id, created_at)
                       VALUES (?, ?, ?, ?)
                       ON CONFLICT(device_id) DO UPDATE SET
                         owner_id=excluded.owner_id,
                         material_id=excluded.material_id,
                         created_at=excluded.created_at""",
                    (device_id, row["owner_id"], row["material_id"], now),
                )
        return Device(device_id,row["owner_id"],row["device_name"],row["device_kind"],now,now), token, str(row["invidious_origin"] or "")

    def get_renderer_material_binding(self, *, owner_id: str, device_id: str) -> str:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT material_id FROM renderer_material_bindings WHERE owner_id=? AND device_id=?",
                (owner_id, device_id),
            ).fetchone()
        return str(row["material_id"] or "") if row is not None else ""

    def save_renderer_invidious_session(self, *, device_id: str, owner_id: str, invidious_origin: str, session_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO renderer_invidious_sessions
                   (device_id,owner_id,invidious_origin,session_id,created_at)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(device_id) DO UPDATE SET
                     owner_id=excluded.owner_id,
                     invidious_origin=excluded.invidious_origin,
                     session_id=excluded.session_id,
                     created_at=excluded.created_at""",
                (device_id, owner_id, invidious_origin, session_id, _now_iso()),
            )

    def get_renderer_invidious_session(self, *, owner_id: str, device_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM renderer_invidious_sessions WHERE device_id=? AND owner_id=?",
                (device_id, owner_id),
            ).fetchone()
        return dict(row) if row is not None else None

    def delete_renderer_invidious_session(self, *, owner_id: str, device_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM renderer_invidious_sessions WHERE device_id=? AND owner_id=?",
                (device_id, owner_id),
            ).fetchone()
            if row is not None:
                conn.execute(
                    "DELETE FROM renderer_invidious_sessions WHERE device_id=? AND owner_id=?",
                    (device_id, owner_id),
                )
        return dict(row) if row is not None else None

    def enqueue_device_command(self, *, owner_id: str, device_id: str, payload: dict[str, Any]) -> DeviceCommand:
        device = next((d for d in self.list_devices(owner_id) if d.device_id == device_id and d.active), None)
        if device is None:
            raise VideoLearningNotFound("Device not found.")
        if not self.device_is_online(device):
            raise VideoLearningConflict("Renderer is offline.")
        cid, now = secrets.token_urlsafe(12), _now_iso()
        with self._connect() as conn:
            conn.execute("INSERT INTO device_commands (command_id,owner_id,device_id,command_type,payload,status,created_at) VALUES (?,?,?,'open_video',?,'pending',?)", (cid,owner_id,device_id,json.dumps(payload),now))
            row = conn.execute("SELECT * FROM device_commands WHERE command_id=?", (cid,)).fetchone()
        return self._row_to_device_command(row)

    def pending_device_commands(self, device_id: str) -> list[DeviceCommand]:
        cutoff = (_now() - COMMAND_TTL).isoformat()
        with self._connect() as conn:
            conn.execute("UPDATE device_commands SET status='expired' WHERE device_id=? AND status='pending' AND created_at<?",(device_id,cutoff))
            rows=conn.execute("SELECT * FROM device_commands WHERE device_id=? AND status='pending' ORDER BY created_at",(device_id,)).fetchall()
        return [self._row_to_device_command(row) for row in rows]

    def get_device_command(self, owner_id: str, device_id: str, command_id: str) -> DeviceCommand | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM device_commands WHERE command_id=? AND owner_id=? AND device_id=?",
                (command_id, owner_id, device_id),
            ).fetchone()
        return self._row_to_device_command(row) if row else None

    def ack_device_command(self, *, device_id: str, command_id: str, ok: bool, error: str | None = None) -> DeviceCommand:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM device_commands WHERE command_id=? AND device_id=?",
                (command_id, device_id),
            ).fetchone()
            if row is None:
                raise VideoLearningNotFound("Device command not found.")
            conn.execute("UPDATE device_commands SET status=?, acked_at=?, error=? WHERE command_id=?",("acked" if ok else "failed",_now_iso(),error,command_id))
            row=conn.execute("SELECT * FROM device_commands WHERE command_id=?",(command_id,)).fetchone()
        return self._row_to_device_command(row)

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
        material_id: str = "",
    ) -> PlayerSession:
        now = _now_iso()
        sid = session_id or secrets.token_urlsafe(12)
        with self._connect() as conn:
            existing = None
            if session_id:
                existing = conn.execute(
                    "SELECT session_id, video_id FROM sessions WHERE session_id = ? AND device_id = ?",
                    (session_id, device.device_id),
                ).fetchone()
            if existing is None:
                active = conn.execute(
                    """SELECT session_id, video_id FROM sessions
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
                        material_id, updated_at, last_heartbeat_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                        material_id,
                        now,
                        now,
                    ),
                )
            else:
                conn.execute(
                    """UPDATE sessions SET
                        video_id = ?, title = ?, position_ms = ?, duration_ms = ?,
                        playback_state = ?, playback_rate = ?,
                        material_id = ?,
                        updated_at = ?, last_heartbeat_at = ?
                       WHERE session_id = ?""",
                    (
                        video_id,
                        title,
                        max(0, int(position_ms)),
                        max(0, int(duration_ms)),
                        playback_state or "unknown",
                        float(playback_rate or 1.0),
                        material_id if str(existing["video_id"] or "") == video_id else "",
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

    def bind_session_material(self, *, session_id: str, owner_id: str, material_id: str) -> PlayerSession | None:
        if not material_id:
            return None
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE sessions SET material_id=? WHERE session_id=? AND owner_id=?",
                (material_id, session_id, owner_id),
            )
            if cur.rowcount != 1:
                return None
            row = conn.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone()
        return self._row_to_session(row) if row else None

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
                    "material_id": session.material_id,
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

    def latest_session_for_device(self, device_id: str) -> PlayerSession | None:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT * FROM sessions
                   WHERE device_id = ?
                   ORDER BY last_heartbeat_at DESC LIMIT 1""",
                (device_id,),
            ).fetchone()
        return self._row_to_session(row) if row else None

    def issue_session_controller(
        self,
        *,
        owner_id: str,
        session_id: str,
        controller_secret: str,
    ) -> PlayerSession | None:
        if not controller_secret:
            return None
        with self._connect() as conn:
            cur = conn.execute(
                """UPDATE sessions SET controller_token_hash = ?
                   WHERE session_id = ? AND owner_id = ?""",
                (_hash_token(controller_secret), session_id, owner_id),
            )
            if cur.rowcount != 1:
                return None
            row = conn.execute(
                "SELECT * FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return self._row_to_session(row) if row else None

    def verify_session_controller(
        self,
        *,
        owner_id: str,
        session_id: str,
        controller_cookie: str | None,
    ) -> bool:
        if not controller_cookie or ":" not in controller_cookie:
            return False
        cookie_session_id, secret = controller_cookie.split(":", 1)
        if cookie_session_id != session_id or not secret:
            return False
        with self._connect() as conn:
            row = conn.execute(
                """SELECT controller_token_hash FROM sessions
                   WHERE session_id = ? AND owner_id = ?""",
                (session_id, owner_id),
            ).fetchone()
        expected = str(row["controller_token_hash"] or "") if row is not None else ""
        return bool(expected) and secrets.compare_digest(expected, _hash_token(secret))

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
        if command_type not in {"pause", "play", "seek", "volume", "mute", "playback_rate", "fullscreen"}:
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
