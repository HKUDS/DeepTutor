"""云端同步路由：手机端把本地变更推上云、把云端变更拉下来。

契约来源是 Android 端的同步引擎（``SyncTransport.kt`` / ``SyncEngine.kt`` /
``SyncPorts.kt``）。服务端逐字段对齐它的 JSON 形状，**不发明新字段**：

* ``GET  /api/sync/manifest`` → ``{"domains": {域: {"revision": int, "available": bool}}}``
* ``GET  /api/sync/changes``  → ``{"revision": int, "items": [...], "next_cursor": str | null}``
* ``POST /api/sync/push``     → ``{"results": [{"client_op_id", "status", "conflict_payload", "reason"}]}``
* ``GET  /api/sync/blob``     → ``{"offset", "total", "sha256", "data"}``
* ``POST /api/sync/blob``     → ``{"received", "completed"}``

端侧用 kotlinx.serialization 且 ``ignoreUnknownKeys = false``：响应里多一个字段
就会让端侧解码失败，所以每个响应模型都只声明契约里有的字段。

分权模型（硬设计，服务端不改动它）：

* ``knowledge_base`` —— 云权威。内容只有云端一个来源，端侧上行一律拒绝。
* ``sessions`` / ``learning`` —— 端权威。云端只做镜像，端→云为主。
* ``settings`` / ``persona`` / ``agent`` —— 双向。两边都改过就进冲突表等用户裁决，
  服务端不提供静默覆盖开关。

两道防线（客户端与服务端各做一次，缺一不可）：

1. 白名单：域不在 :data:`ALLOWED_DOMAINS` 里直接拒绝。
2. 敏感键：载荷里出现 ``api_key`` / ``secret`` / ``token`` 一类键名，整条拒绝，
   **不写库、不进日志、不回显**。被拒的条目只留一个固定文案的理由。

云端副本存在本地 SQLite（``<用户目录>/sync/sync.db``）：域版本号、实体副本、
变更日志、幂等回执、冲突留档、大文件分块，都在这里。
"""

from __future__ import annotations

import base64
import binascii
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import sqlite3
import threading
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from deeptutor.multi_user.paths import get_current_path_service

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# 常量：域、变更类型、结果状态
# ---------------------------------------------------------------------------

DOMAIN_KNOWLEDGE_BASE = "knowledge_base"
DOMAIN_LEARNING = "learning"
DOMAIN_SESSIONS = "sessions"
DOMAIN_SETTINGS = "settings"
DOMAIN_PERSONA = "persona"
DOMAIN_AGENT = "agent"

#: 可以进出同步通道的域（白名单）。与端侧 ``SyncDomains.ALL`` 一一对应。
ALLOWED_DOMAINS: tuple[str, ...] = (
    DOMAIN_KNOWLEDGE_BASE,
    DOMAIN_LEARNING,
    DOMAIN_SESSIONS,
    DOMAIN_SETTINGS,
    DOMAIN_PERSONA,
    DOMAIN_AGENT,
)

#: 云权威域：云→端。端侧上行不接受。
CLOUD_AUTHORITATIVE_DOMAINS = frozenset({DOMAIN_KNOWLEDGE_BASE})

#: 端权威域：端→云。云端只做镜像。
END_AUTHORITATIVE_DOMAINS = frozenset({DOMAIN_SESSIONS, DOMAIN_LEARNING})

#: 双向域：双方都改过就留冲突，不静默覆盖。
BIDIRECTIONAL_DOMAINS = frozenset({DOMAIN_SETTINGS, DOMAIN_PERSONA, DOMAIN_AGENT})

KIND_UPSERT = "upsert"
KIND_DELETE = "delete"

STATUS_APPLIED = "applied"
STATUS_CONFLICT = "conflict"
STATUS_REJECTED = "rejected"

#: 固定文案的理由。绝不回显载荷、实体内容或任何凭据。
REASON_DOMAIN_NOT_ALLOWED = "域不在同步白名单内。"
REASON_CLOUD_ONLY = "知识库由云端负责，端侧上行不接受。"
REASON_SENSITIVE = "载荷包含敏感字段，已拒绝。"
REASON_UNKNOWN_KIND = "未知的变更类型。"
REASON_STALE = "云端已有更新版本，未应用该变更。"
REASON_CONFLICT = "云端与端侧版本不一致，等待用户选择。"

#: 敏感键清单：与端侧 ``SyncDomains.FORBIDDEN_KEY_PARTS`` 同一份。
#: 键名小写后只要包含其中一段就算命中——宁可误伤一个设定项，也不能漏掉凭据。
FORBIDDEN_KEY_PARTS: tuple[str, ...] = (
    "api_key",
    "apikey",
    "secret",
    "token",
    "password",
    "passwd",
    "authorization",
    "credential",
    "private_key",
    "session_key",
)

MAX_PAGE_LIMIT = 500
DEFAULT_PAGE_LIMIT = 100
MAX_PUSH_BATCH = 200
MAX_BLOB_CHUNK = 4 * 1024 * 1024
DEFAULT_BLOB_CHUNK = 512 * 1024

#: 知识库发布时的上限：一个库最多下发这么多文档，单个文档最多这么多文本。
MAX_KB_DOCUMENTS = 200
MAX_KB_TEXT_BYTES = 256 * 1024
MAX_KB_BLOB_BYTES = 8 * 1024 * 1024

# ---------------------------------------------------------------------------
# 请求 / 响应模型：字段名与端侧数据类逐字对齐
# ---------------------------------------------------------------------------


class SyncPushItem(BaseModel):
    """上行的一条变更。"""

    client_op_id: str = Field(min_length=1, max_length=200)
    domain: str = Field(min_length=1, max_length=64)
    entity_id: str = Field(min_length=1, max_length=512)
    kind: str = Field(min_length=1, max_length=32)
    payload: dict[str, Any] = Field(default_factory=dict)
    revision: int = Field(default=0, ge=0)
    created_at: int = Field(default=0, ge=0)


class SyncPushRequest(BaseModel):
    """一次上行的批次。"""

    items: list[SyncPushItem] = Field(min_length=1, max_length=MAX_PUSH_BATCH)


class SyncPushResult(BaseModel):
    """一条上行的回执。"""

    client_op_id: str
    status: str
    conflict_payload: dict[str, Any] | None = None
    reason: str = ""


class SyncPushResponse(BaseModel):
    """一次上行的全部回执，顺序与请求一致。"""

    results: list[SyncPushResult] = Field(default_factory=list)


class SyncManifestEntry(BaseModel):
    """一个域的当前版本与可用性。"""

    revision: int = 0
    available: bool = True


class SyncManifestResponse(BaseModel):
    """各域当前版本与可用性。"""

    domains: dict[str, SyncManifestEntry] = Field(default_factory=dict)


class SyncChangeItem(BaseModel):
    """一条云端变更。"""

    entity_id: str
    kind: str
    payload: dict[str, Any] = Field(default_factory=dict)
    revision: int = 0


class SyncChangePage(BaseModel):
    """一页云端变更。"""

    revision: int = 0
    items: list[SyncChangeItem] = Field(default_factory=list)
    next_cursor: str | None = None


class SyncBlobChunk(BaseModel):
    """一块大文件数据。"""

    offset: int = 0
    total: int = 0
    sha256: str = ""
    data: str = ""


class SyncBlobUploadRequest(BaseModel):
    """上传一块大文件数据。"""

    domain: str = Field(min_length=1, max_length=64)
    id: str = Field(min_length=1, max_length=512)
    offset: int = Field(ge=0)
    total: int = Field(ge=1)
    sha256: str = Field(default="", max_length=128)
    data: str = ""
    final: bool = False


class SyncBlobUploadResponse(BaseModel):
    """一块大文件数据的接收结果。"""

    received: int = 0
    completed: bool = False


# ---------------------------------------------------------------------------
# 载荷闸门
# ---------------------------------------------------------------------------


def _forbidden_key_in(payload: Any) -> str | None:
    """返回命中的敏感键名；载荷干净时返回 ``None``。

    递归进入嵌套对象与数组：端侧 ``SyncPayloadGuard`` 也查列表里的映射
    （``forbiddenInsideLists``），这里保持同一口径。
    """
    if isinstance(payload, dict):
        for key, value in payload.items():
            lowered = str(key).lower()
            if any(part in lowered for part in FORBIDDEN_KEY_PARTS):
                return str(key)
            nested = _forbidden_key_in(value)
            if nested is not None:
                return nested
    elif isinstance(payload, list):
        for value in payload:
            nested = _forbidden_key_in(value)
            if nested is not None:
                return nested
    return None


# ---------------------------------------------------------------------------
# 云端同步存储
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sync_domain_state (
    domain   TEXT PRIMARY KEY,
    revision INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS sync_entities (
    domain          TEXT NOT NULL,
    entity_id       TEXT NOT NULL,
    kind            TEXT NOT NULL,
    payload         TEXT NOT NULL DEFAULT '{}',
    revision        INTEGER NOT NULL DEFAULT 0,
    client_revision INTEGER NOT NULL DEFAULT 0,
    updated_at      TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (domain, entity_id)
);

CREATE TABLE IF NOT EXISTS sync_changes (
    seq        INTEGER PRIMARY KEY AUTOINCREMENT,
    domain     TEXT NOT NULL,
    entity_id  TEXT NOT NULL,
    kind       TEXT NOT NULL,
    payload    TEXT NOT NULL DEFAULT '{}',
    revision   INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_sync_changes_domain ON sync_changes (domain, seq);

CREATE TABLE IF NOT EXISTS sync_ops (
    client_op_id     TEXT PRIMARY KEY,
    domain           TEXT NOT NULL DEFAULT '',
    status           TEXT NOT NULL,
    conflict_payload TEXT,
    reason           TEXT NOT NULL DEFAULT '',
    created_at       TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS sync_conflicts (
    id             TEXT PRIMARY KEY,
    domain         TEXT NOT NULL,
    entity_id      TEXT NOT NULL,
    local_payload  TEXT NOT NULL DEFAULT '{}',
    remote_payload TEXT NOT NULL DEFAULT '{}',
    created_at     TEXT NOT NULL DEFAULT '',
    resolved       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS sync_blobs (
    domain    TEXT NOT NULL,
    id        TEXT NOT NULL,
    total     INTEGER NOT NULL DEFAULT 0,
    sha256    TEXT NOT NULL DEFAULT '',
    received  INTEGER NOT NULL DEFAULT 0,
    completed INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (domain, id)
);

CREATE TABLE IF NOT EXISTS sync_blob_chunks (
    domain TEXT NOT NULL,
    id     TEXT NOT NULL,
    offset INTEGER NOT NULL,
    data   BLOB NOT NULL,
    PRIMARY KEY (domain, id, offset)
);
"""


def _now() -> str:
    """当前 UTC 时间戳（秒级精度，够用且不引入时区歧义）。"""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _dump(payload: dict[str, Any]) -> str:
    """载荷的稳定序列化：同一个载荷永远得到同一串文本。"""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _loads(text: str | None) -> dict[str, Any]:
    """载荷文本 → 对象。存坏了就当空对象，不让一次读取失败整个请求。"""
    if not text:
        return {}
    try:
        value = json.loads(text)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


class _SyncStore:
    """云端同步状态。

    一个库一份：域版本号、实体副本、变更日志、幂等回执、冲突留档、大文件分块。
    写入都在一把锁里串行执行——本机单用户部署，写入量是手机端的增量，
    串行足够，也不用再引一层并发控制。
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._lock = threading.RLock()
        self._schema_ready = False

    # -- 基础设施 ---------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        if self._schema_ready:
            return
        with self._lock:
            if self._schema_ready:
                return
            conn.executescript(_SCHEMA)
            conn.commit()
            self._schema_ready = True

    # -- 读取 -------------------------------------------------------------

    def _domain_revision(self, conn: sqlite3.Connection, domain: str) -> int:
        row = conn.execute(
            "SELECT revision FROM sync_domain_state WHERE domain = ?", (domain,)
        ).fetchone()
        return int(row["revision"]) if row else 0

    def _get_entity(
        self, conn: sqlite3.Connection, domain: str, entity_id: str
    ) -> sqlite3.Row | None:
        return conn.execute(
            "SELECT * FROM sync_entities WHERE domain = ? AND entity_id = ?",
            (domain, entity_id),
        ).fetchone()

    def _get_op(self, conn: sqlite3.Connection, client_op_id: str) -> SyncPushResult | None:
        row = conn.execute(
            "SELECT * FROM sync_ops WHERE client_op_id = ?", (client_op_id,)
        ).fetchone()
        if row is None:
            return None
        conflict_payload: dict[str, Any] | None = None
        if row["conflict_payload"]:
            conflict_payload = _loads(row["conflict_payload"])
        return SyncPushResult(
            client_op_id=row["client_op_id"],
            status=row["status"],
            conflict_payload=conflict_payload,
            reason=row["reason"],
        )

    def manifest(self) -> dict[str, SyncManifestEntry]:
        """各域的当前版本与可用性。"""
        conn = self._connect()
        try:
            self._ensure_schema(conn)
            return {
                domain: SyncManifestEntry(
                    revision=self._domain_revision(conn, domain),
                    available=True,
                )
                for domain in ALLOWED_DOMAINS
            }
        finally:
            conn.close()

    def changes(
        self, domain: str, since_seq: int, limit: int
    ) -> tuple[int, list[SyncChangeItem], str | None]:
        """一页变更。游标是变更日志的序号，重放同一个游标结果稳定。"""
        conn = self._connect()
        try:
            self._ensure_schema(conn)
            rows = conn.execute(
                "SELECT seq, entity_id, kind, payload, revision FROM sync_changes "
                "WHERE domain = ? AND seq > ? ORDER BY seq LIMIT ?",
                (domain, since_seq, limit + 1),
            ).fetchall()
            has_more = len(rows) > limit
            rows = rows[:limit]
            items: list[SyncChangeItem] = []
            for row in rows:
                items.append(
                    SyncChangeItem(
                        entity_id=row["entity_id"],
                        kind=row["kind"],
                        payload=_loads(row["payload"]),
                        revision=int(row["revision"]),
                    )
                )
            next_cursor = str(rows[-1]["seq"]) if has_more and rows else None
            return self._domain_revision(conn, domain), items, next_cursor
        finally:
            conn.close()

    def entity_payloads(self, domain: str) -> dict[str, tuple[str, str]]:
        """某个域当前的实体集合：``实体 id -> (变更类型, 载荷文本)``。"""
        conn = self._connect()
        try:
            self._ensure_schema(conn)
            rows = conn.execute(
                "SELECT entity_id, kind, payload FROM sync_entities WHERE domain = ?", (domain,)
            ).fetchall()
            return {row["entity_id"]: (row["kind"], row["payload"]) for row in rows}
        finally:
            conn.close()

    # -- 写入 -------------------------------------------------------------

    def _next_revision(self, conn: sqlite3.Connection, domain: str) -> int:
        revision = self._domain_revision(conn, domain) + 1
        conn.execute(
            "INSERT INTO sync_domain_state (domain, revision) VALUES (?, ?) "
            "ON CONFLICT(domain) DO UPDATE SET revision = excluded.revision",
            (domain, revision),
        )
        return revision

    def _write_change(
        self,
        conn: sqlite3.Connection,
        domain: str,
        entity_id: str,
        kind: str,
        payload: dict[str, Any],
        client_revision: int,
    ) -> int:
        """写一条变更：更新实体副本 + 追加变更日志，返回新的域版本号。"""
        revision = self._next_revision(conn, domain)
        payload_text = _dump(payload)
        now = _now()
        conn.execute(
            "INSERT INTO sync_entities "
            "(domain, entity_id, kind, payload, revision, client_revision, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(domain, entity_id) DO UPDATE SET "
            "kind = excluded.kind, payload = excluded.payload, revision = excluded.revision, "
            "client_revision = excluded.client_revision, updated_at = excluded.updated_at",
            (domain, entity_id, kind, payload_text, revision, client_revision, now),
        )
        conn.execute(
            "INSERT INTO sync_changes "
            "(domain, entity_id, kind, payload, revision, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (domain, entity_id, kind, payload_text, revision, now),
        )
        return revision

    def _record_conflict(
        self,
        conn: sqlite3.Connection,
        domain: str,
        entity_id: str,
        local_payload: dict[str, Any],
        remote_payload: dict[str, Any],
    ) -> None:
        conn.execute(
            "INSERT INTO sync_conflicts "
            "(id, domain, entity_id, local_payload, remote_payload, created_at, resolved) "
            "VALUES (?, ?, ?, ?, ?, ?, 0) "
            "ON CONFLICT(id) DO UPDATE SET "
            "local_payload = excluded.local_payload, remote_payload = excluded.remote_payload, "
            "created_at = excluded.created_at, resolved = 0",
            (
                f"{domain}/{entity_id}",
                domain,
                entity_id,
                _dump(local_payload),
                _dump(remote_payload),
                _now(),
            ),
        )

    def _record_op(
        self,
        conn: sqlite3.Connection,
        item: SyncPushItem,
        result: SyncPushResult,
    ) -> None:
        """记下这次上行的结果：同一个 ``client_op_id`` 再来一次就回放它。"""
        conn.execute(
            "INSERT OR REPLACE INTO sync_ops "
            "(client_op_id, domain, status, conflict_payload, reason, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                item.client_op_id,
                item.domain,
                result.status,
                _dump(result.conflict_payload) if result.conflict_payload is not None else None,
                result.reason,
                _now(),
            ),
        )

    def push(self, item: SyncPushItem) -> SyncPushResult:
        """处理一条上行变更。

        顺序是刻意的：幂等 → 白名单 → 方向 → 变更类型 → 敏感键 → 冲突 → 应用。
        敏感键检查在落库之前，被拒的载荷不会留在任何地方。
        """
        with self._lock:
            conn = self._connect()
            try:
                self._ensure_schema(conn)
                existing = self._get_op(conn, item.client_op_id)
                if existing is not None:
                    # 幂等：同一条操作重发，回放首次的结果，不再应用一次。
                    return existing
                result = self._apply_push(conn, item)
                self._record_op(conn, item, result)
                conn.commit()
                return result
            finally:
                conn.close()

    def _apply_push(self, conn: sqlite3.Connection, item: SyncPushItem) -> SyncPushResult:
        if item.domain not in ALLOWED_DOMAINS:
            return SyncPushResult(
                client_op_id=item.client_op_id,
                status=STATUS_REJECTED,
                reason=REASON_DOMAIN_NOT_ALLOWED,
            )
        if item.domain in CLOUD_AUTHORITATIVE_DOMAINS:
            # 云权威域：内容只有云端一个来源，端侧上行不接受。
            return SyncPushResult(
                client_op_id=item.client_op_id,
                status=STATUS_REJECTED,
                reason=REASON_CLOUD_ONLY,
            )
        kind = item.kind.strip().lower()
        if kind not in (KIND_UPSERT, KIND_DELETE):
            return SyncPushResult(
                client_op_id=item.client_op_id,
                status=STATUS_REJECTED,
                reason=REASON_UNKNOWN_KIND,
            )
        if _forbidden_key_in(item.payload) is not None:
            # 敏感键：整条拒绝。载荷不进库、不进日志、不回显。
            return SyncPushResult(
                client_op_id=item.client_op_id,
                status=STATUS_REJECTED,
                reason=REASON_SENSITIVE,
            )

        current = self._get_entity(conn, item.domain, item.entity_id)
        if (
            current is not None
            and current["kind"] == kind
            and current["payload"] == _dump(item.payload)
        ):
            # 内容一致：空操作也算应用成功，版本号不动。
            return SyncPushResult(client_op_id=item.client_op_id, status=STATUS_APPLIED)

        if current is not None:
            client_revision = int(current["client_revision"])
            cloud_payload = _loads(current["payload"])
            if item.domain in BIDIRECTIONAL_DOMAINS:
                if item.revision <= client_revision:
                    # 云端副本已经走到端侧这次修改之前：双方都改过，交给用户裁决，
                    # 不静默覆盖云端版本。
                    self._record_conflict(
                        conn,
                        item.domain,
                        item.entity_id,
                        item.payload,
                        cloud_payload,
                    )
                    return SyncPushResult(
                        client_op_id=item.client_op_id,
                        status=STATUS_CONFLICT,
                        conflict_payload=cloud_payload,
                        reason=REASON_CONFLICT,
                    )
            elif item.domain in END_AUTHORITATIVE_DOMAINS and item.revision < client_revision:
                # 端权威域的镜像：云端留着更新的那份，不被旧变更拉回去。
                return SyncPushResult(
                    client_op_id=item.client_op_id,
                    status=STATUS_REJECTED,
                    reason=REASON_STALE,
                )

        self._write_change(conn, item.domain, item.entity_id, kind, item.payload, item.revision)
        return SyncPushResult(client_op_id=item.client_op_id, status=STATUS_APPLIED)

    def publish(self, domain: str, entity_id: str, kind: str, payload: dict[str, Any]) -> None:
        """云端自己产生的一条变更（当前只有知识库域有这条路）。"""
        with self._lock:
            conn = self._connect()
            try:
                self._ensure_schema(conn)
                current = self._get_entity(conn, domain, entity_id)
                if (
                    current is not None
                    and current["kind"] == kind
                    and current["payload"] == _dump(payload)
                ):
                    return
                self._write_change(conn, domain, entity_id, kind, payload, 0)
                conn.commit()
            finally:
                conn.close()

    # -- 大文件 -----------------------------------------------------------

    def _read_range(
        self, conn: sqlite3.Connection, domain: str, blob_id: str, start: int, end: int
    ) -> bytes:
        rows = conn.execute(
            "SELECT offset, data FROM sync_blob_chunks "
            "WHERE domain = ? AND id = ? AND offset < ? ORDER BY offset",
            (domain, blob_id, end),
        ).fetchall()
        out = bytearray()
        for row in rows:
            chunk = bytes(row["data"])
            chunk_start = int(row["offset"])
            chunk_end = chunk_start + len(chunk)
            if chunk_end <= start:
                continue
            low = max(start, chunk_start)
            high = min(end, chunk_end)
            out += chunk[low - chunk_start : high - chunk_start]
        return bytes(out)

    def blob_chunk(self, domain: str, blob_id: str, offset: int, length: int) -> SyncBlobChunk:
        """取一块大文件数据。``sha256`` 是整个文件的校验值（端侧按整份核对）。"""
        conn = self._connect()
        try:
            self._ensure_schema(conn)
            row = conn.execute(
                "SELECT total, sha256 FROM sync_blobs WHERE domain = ? AND id = ?",
                (domain, blob_id),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="文件不存在。")
            total = int(row["total"])
            digest = str(row["sha256"] or "")
            if offset >= total:
                return SyncBlobChunk(offset=total, total=total, sha256=digest, data="")
            end = min(total, offset + length)
            data = self._read_range(conn, domain, blob_id, offset, end)
            return SyncBlobChunk(
                offset=offset,
                total=total,
                sha256=digest,
                data=base64.b64encode(data).decode("ascii"),
            )
        finally:
            conn.close()

    def blob_upload(
        self,
        domain: str,
        blob_id: str,
        offset: int,
        total: int,
        sha256: str,
        data: bytes,
        final: bool,
    ) -> SyncBlobUploadResponse:
        """写入一块大文件数据。"""
        with self._lock:
            conn = self._connect()
            try:
                self._ensure_schema(conn)
                row = conn.execute(
                    "SELECT total, sha256, received, completed FROM sync_blobs "
                    "WHERE domain = ? AND id = ?",
                    (domain, blob_id),
                ).fetchone()
                if (
                    row is not None
                    and int(row["completed"])
                    and sha256
                    and str(row["sha256"]).lower() == sha256.lower()
                ):
                    # 同样的内容已经完整上传过：直接回执，不重写。
                    return SyncBlobUploadResponse(received=int(row["received"]), completed=True)
                conn.execute(
                    "INSERT OR REPLACE INTO sync_blob_chunks (domain, id, offset, data) "
                    "VALUES (?, ?, ?, ?)",
                    (domain, blob_id, offset, data),
                )
                received = max(int(row["received"]) if row else 0, offset + len(data))
                completed = False
                digest = sha256
                if final:
                    content = self._read_range(conn, domain, blob_id, 0, total)
                    digest = hashlib.sha256(content).hexdigest()
                    if sha256 and digest.lower() != sha256.lower():
                        conn.rollback()
                        raise HTTPException(status_code=400, detail="上传校验失败。")
                    completed = True
                conn.execute(
                    "INSERT OR REPLACE INTO sync_blobs "
                    "(domain, id, total, sha256, received, completed) VALUES (?, ?, ?, ?, ?, ?)",
                    (domain, blob_id, total, digest, received, int(completed)),
                )
                conn.commit()
                return SyncBlobUploadResponse(received=received, completed=completed)
            finally:
                conn.close()


_STORES: dict[str, _SyncStore] = {}
_STORES_LOCK = threading.Lock()


def _store() -> _SyncStore:
    """当前用户的同步存储。"""
    path = get_current_path_service().get_user_root() / "sync" / "sync.db"
    key = str(path)
    with _STORES_LOCK:
        store = _STORES.get(key)
        if store is None:
            store = _SyncStore(path)
            _STORES[key] = store
        return store


# ---------------------------------------------------------------------------
# 云端发布源：知识库
# ---------------------------------------------------------------------------

_KB_PUBLISH_CACHE: dict[tuple[str, str], tuple[int, int]] = {}
_KB_PUBLISH_LOCK = threading.Lock()


def _publish_knowledge_base(store: _SyncStore) -> None:
    """把云端知识库发布到同步库。

    知识库是云权威域：内容只有这一个来源，端侧上行会被拒绝。这里读的是服务器
    自己的知识库目录；读不到就让该域停在旧版本，绝不让同步接口整体失败。
    """
    try:
        from deeptutor.multi_user.knowledge_access import current_kb_manager

        manager = current_kb_manager()
        names = [str(name) for name in manager.list_knowledge_bases()]
    except Exception:
        logger.debug("知识库发布跳过：读不到知识库清单。")
        return

    try:
        published: set[str] = set()
        for name in names:
            published |= _publish_kb_documents(store, manager, name)
        for entity_id in set(store.entity_payloads(DOMAIN_KNOWLEDGE_BASE)) - published:
            # 云端删掉的文件要下发删除，否则端侧会一直留着旧副本。
            store.publish(DOMAIN_KNOWLEDGE_BASE, entity_id, KIND_DELETE, {})
    except Exception:
        logger.debug("知识库发布跳过：写入同步库失败。")


def _publish_kb_documents(store: _SyncStore, manager: Any, name: str) -> set[str]:
    """发布一个知识库的文档。返回本次涉及的实体 id。"""
    try:
        from deeptutor.knowledge.manifest import document_root, iter_kb_documents

        kb_dir = Path(manager.base_dir) / name
        entry = dict((manager.config.get("knowledge_bases", {}) or {}).get(name, {}) or {})
        root = document_root(kb_dir, entry)
        if root is None or not root.is_dir():
            return set()

        documents: list[Path] = []
        for path in iter_kb_documents(root):
            documents.append(path)
            if len(documents) >= MAX_KB_DOCUMENTS:
                break

        entity_ids = {f"{name}:{path.relative_to(root).as_posix()}" for path in documents}
        signature = _kb_signature(documents)
        cache_key = (str(store.db_path), name)
        with _KB_PUBLISH_LOCK:
            unchanged = _KB_PUBLISH_CACHE.get(cache_key) == signature
        if unchanged:
            return entity_ids

        current = store.entity_payloads(DOMAIN_KNOWLEDGE_BASE)
        for path in documents:
            entity_id = f"{name}:{path.relative_to(root).as_posix()}"
            payload = {
                "kb_name": name,
                "title": path.stem,
                "source_type": "file",
                "content_text": _read_kb_text(path),
            }
            stored = current.get(entity_id)
            if stored is not None and stored[0] == KIND_UPSERT and stored[1] == _dump(payload):
                # 没变：不写变更日志，也不重发大文件。
                continue
            store.publish(DOMAIN_KNOWLEDGE_BASE, entity_id, KIND_UPSERT, payload)
            _publish_kb_blob(store, entity_id, path)
        with _KB_PUBLISH_LOCK:
            _KB_PUBLISH_CACHE[cache_key] = signature
        return entity_ids
    except Exception:
        logger.debug("知识库发布跳过：单个知识库读取失败。")
        return set()


def _kb_signature(documents: list[Path]) -> tuple[int, int]:
    """文档集合的廉价签名：条数 + 最新修改时间。用来跳过没变过的知识库。"""
    newest = 0
    for path in documents:
        try:
            newest = max(newest, path.stat().st_mtime_ns)
        except OSError:
            continue
    return len(documents), newest


def _read_kb_text(path: Path) -> str:
    """读文档正文（超长或读不了就当空）。"""
    try:
        if path.stat().st_size > MAX_KB_TEXT_BYTES:
            return ""
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _publish_kb_blob(store: _SyncStore, entity_id: str, path: Path) -> None:
    """把文档原文作为大文件发布出去。"""
    try:
        if path.stat().st_size > MAX_KB_BLOB_BYTES:
            return
        content = path.read_bytes()
    except OSError:
        return
    digest = hashlib.sha256(content).hexdigest()
    try:
        store.blob_upload(DOMAIN_KNOWLEDGE_BASE, entity_id, 0, len(content), digest, content, True)
    except HTTPException:
        logger.debug("知识库大文件发布跳过：校验未通过。")


# ---------------------------------------------------------------------------
# 端点
# ---------------------------------------------------------------------------


def _parse_cursor(since: str | None) -> int:
    """把客户端带来的游标解析成变更日志的序号。"""
    if since is None or not since.strip():
        return 0
    try:
        cursor = int(since)
    except ValueError:
        raise HTTPException(status_code=400, detail="同步游标无效。") from None
    if cursor < 0:
        raise HTTPException(status_code=400, detail="同步游标无效。")
    return cursor


@router.get("/manifest", response_model=SyncManifestResponse)
async def sync_manifest() -> SyncManifestResponse:
    """各域当前版本与可用性。

    ``available`` 表示这个域由本服务器提供；端侧拿到 ``false`` 就跳过该域。
    """
    store = _store()
    _publish_knowledge_base(store)
    return SyncManifestResponse(domains=store.manifest())


@router.get("/changes", response_model=SyncChangePage)
async def sync_changes(
    domain: str = Query(..., min_length=1, max_length=64),
    since: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
) -> SyncChangePage:
    """按域拉一页增量变更。

    ``since`` 是上一页的 ``next_cursor``；重放同一个游标拿到同一页。
    """
    if domain not in ALLOWED_DOMAINS:
        raise HTTPException(status_code=400, detail=REASON_DOMAIN_NOT_ALLOWED)
    cursor = _parse_cursor(since)
    store = _store()
    if domain in CLOUD_AUTHORITATIVE_DOMAINS:
        _publish_knowledge_base(store)
    revision, items, next_cursor = store.changes(domain, cursor, limit)
    return SyncChangePage(revision=revision, items=items, next_cursor=next_cursor)


@router.post("/push", response_model=SyncPushResponse)
async def sync_push(body: SyncPushRequest) -> SyncPushResponse:
    """批量上行变更。

    ``client_op_id`` 是幂等键：同一条操作重发，返回与首次一致的结果，不会重复应用。
    """
    store = _store()
    results = [store.push(item) for item in body.items]
    applied = sum(1 for result in results if result.status == STATUS_APPLIED)
    conflicts = sum(1 for result in results if result.status == STATUS_CONFLICT)
    rejected = sum(1 for result in results if result.status == STATUS_REJECTED)
    # 只记数量，不记载荷：日志里不出现任何实体内容，更不会出现凭据。
    logger.info(
        "同步上行：条目=%d 已应用=%d 冲突=%d 拒绝=%d",
        len(results),
        applied,
        conflicts,
        rejected,
    )
    return SyncPushResponse(results=results)


@router.get("/blob", response_model=SyncBlobChunk)
async def sync_blob_download(
    domain: str = Query(..., min_length=1, max_length=64),
    blob_id: str = Query(..., alias="id", min_length=1, max_length=512),
    offset: int = Query(default=0, ge=0),
    length: int = Query(default=DEFAULT_BLOB_CHUNK, ge=1, le=MAX_BLOB_CHUNK),
) -> SyncBlobChunk:
    """取一块大文件数据。"""
    if domain not in ALLOWED_DOMAINS:
        raise HTTPException(status_code=400, detail=REASON_DOMAIN_NOT_ALLOWED)
    return _store().blob_chunk(domain, blob_id, offset, length)


@router.post("/blob", response_model=SyncBlobUploadResponse)
async def sync_blob_upload(body: SyncBlobUploadRequest) -> SyncBlobUploadResponse:
    """上传一块大文件数据。"""
    if body.domain not in ALLOWED_DOMAINS:
        raise HTTPException(status_code=400, detail=REASON_DOMAIN_NOT_ALLOWED)
    try:
        data = base64.b64decode(body.data, validate=True) if body.data else b""
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail="分块数据无效。") from None
    if body.offset >= body.total:
        raise HTTPException(status_code=400, detail="分块位置无效。")
    if body.offset + len(data) > body.total:
        raise HTTPException(status_code=400, detail="分块数据超出声明长度。")
    return _store().blob_upload(
        body.domain,
        body.id,
        body.offset,
        body.total,
        body.sha256,
        data,
        body.final,
    )
