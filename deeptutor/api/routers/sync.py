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
* ``sessions`` / ``learning`` / ``memory`` —— 端权威。云端只做镜像，端→云为主。
* ``settings`` / ``persona`` / ``agent`` —— 双向。两边都改过就进冲突表等用户裁决，
  服务端不提供静默覆盖开关。

两道防线（客户端与服务端各做一次，缺一不可）：

1. 白名单：域不在 :data:`ALLOWED_DOMAINS` 里直接拒绝。
2. 敏感键：载荷里出现 ``api_key`` / ``secret`` / ``token`` 一类键名，整条拒绝，
   **不写库、不进日志、不回显**。被拒的条目只留一个固定文案的理由。

云端自己也会产生变更，并发布进同一个同步库：``knowledge_base``（知识库目录）、
``settings``（设定目录）、``persona``（画像目录）、``agent``（``agents.yaml``）。
发布方向与敏感键的处理和上行不同：**发布是剥，不是拒**——设定里混着真凭据，
发布前逐层把凭据键整条摘掉，其余键照发（见 :func:`_strip_publish_secrets`）。

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
import re
import sqlite3
import threading
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
import yaml

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
DOMAIN_MEMORY = "memory"

#: 可以进出同步通道的域（白名单）。与端侧 ``SyncDomains.ALL`` 一一对应。
ALLOWED_DOMAINS: tuple[str, ...] = (
    DOMAIN_KNOWLEDGE_BASE,
    DOMAIN_LEARNING,
    DOMAIN_SESSIONS,
    DOMAIN_SETTINGS,
    DOMAIN_PERSONA,
    DOMAIN_AGENT,
    DOMAIN_MEMORY,
)

#: 云权威域：云→端。端侧上行不接受。
CLOUD_AUTHORITATIVE_DOMAINS = frozenset({DOMAIN_KNOWLEDGE_BASE})

#: 端权威域：端→云。云端只做镜像。
END_AUTHORITATIVE_DOMAINS = frozenset({DOMAIN_SESSIONS, DOMAIN_LEARNING, DOMAIN_MEMORY})

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

#: 敏感键清单：与端侧 ``sync/ports/SensitiveKeys.kt`` 同一份。
#:
#: 判定按**词段**而不是子串。``max_tokens`` 含 "token" 但它不是凭据：按子串判
#: 会把整个 agent 载荷连同它的预算字段一起拒掉，而端侧用同一口径判，于是上行
#: 被整条拒绝，功能直接坏掉。``access_token``、``API_KEY`` 才是真的凭据。
#:
#: 词段切分覆盖下划线、连字符、点号、空格与驼峰，命中的是「词段序列整体出现」。
FORBIDDEN_KEY_PHRASES: tuple[tuple[str, ...], ...] = (
    ("api", "key"),
    ("apikey",),
    ("secret",),
    ("token",),
    ("password",),
    ("passwd",),
    ("authorization",),
    ("credential",),
    ("private", "key"),
    ("session", "key"),
)

#: 良性键名：整个键名命中这里就不算敏感。
#:
#: 只放「装的是个数、不是秘密」的键。``max_tokens`` 是模型输出预算，
#: ``max_completion_tokens`` 与 ``token_count`` 同理——把它们当凭据拒掉，
#: agent 配置的预算字段就同步不过去。
#:
#: 为什么需要白名单：``max_tokens`` 与 ``access_tokens`` 的结构完全一样，都是
#: 「修饰词 + token」，光看词段分不开。默认按禁用处理（宁可误伤），再把确定
#: 无害的那几个放出来。
BENIGN_KEYS: frozenset[str] = frozenset(
    {
        "max_tokens",
        "max_completion_tokens",
        "max_output_tokens",
        "token_count",
    }
)

#: 发布前剥离凭据用的额外词段：``extra_headers`` 里常常直接放令牌。
PUBLISH_EXTRA_SECRET_PHRASES: tuple[tuple[str, ...], ...] = (("extra", "headers"),)

MAX_PAGE_LIMIT = 500
DEFAULT_PAGE_LIMIT = 100
MAX_PUSH_BATCH = 200
MAX_BLOB_CHUNK = 4 * 1024 * 1024
DEFAULT_BLOB_CHUNK = 512 * 1024

#: 知识库发布时的上限：一个库最多下发这么多文档，单个文档最多这么多文本。
MAX_KB_DOCUMENTS = 200
MAX_KB_TEXT_BYTES = 256 * 1024
MAX_KB_BLOB_BYTES = 8 * 1024 * 1024

#: 云端自己会产生变更的域。``knowledge_base`` 是云权威域，内容只有云端一个来源；
#: 后三个是双向域——云端改了就下发，端侧改了也从云端镜像回去。
CLOUD_PUBLISHED_DOMAINS: frozenset[str] = frozenset(
    {DOMAIN_KNOWLEDGE_BASE, DOMAIN_SETTINGS, DOMAIN_PERSONA, DOMAIN_AGENT}
)

#: 发布前剥离凭据用的词段集合：以端侧的禁用词段为准，另加云端自己已知的凭据
#: 载体 ``extra_headers``：模型目录的请求头映射里常常直接放令牌。
PUBLISH_SECRET_KEY_PHRASES: tuple[tuple[str, ...], ...] = (
    FORBIDDEN_KEY_PHRASES + PUBLISH_EXTRA_SECRET_PHRASES
)

#: 设定文档与画像正文的大小上限：超过就不发，免得把一个巨大的 JSON 推进同步库。
MAX_SETTINGS_BYTES = 512 * 1024
MAX_PERSONA_CONTENT_BYTES = 256 * 1024

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
    """一条上行的回执。

    ``revision`` 是该实体在服务端的版本号：端侧拿它推进「云端那一半」的基线，
    下行时就不会把自己上行内容的镜像误判成「双方都改过」。
    """

    client_op_id: str
    status: str
    conflict_payload: dict[str, Any] | None = None
    reason: str = ""
    revision: int = 0


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


def _key_segments(key: str) -> list[str]:
    """键名 → 词段序列。

    先按分隔符切（``_ - . 空格`` 与任何非字母数字字符），再按驼峰切：
    ``apiKey`` → ``api`` + ``key``，``HTTPServer`` → ``http`` + ``server``。
    """
    segments: list[str] = []
    for word in re.split(r"[^A-Za-z0-9]+", key.strip()):
        if not word:
            continue
        segments.extend(part.lower() for part in _split_camel_case(word) if part)
    return segments


def _split_camel_case(word: str) -> list[str]:
    """驼峰切分：在一个大写字母前断开，前提是它后面跟着小写或数字。"""
    parts: list[str] = []
    start = 0
    for index in range(1, len(word)):
        current = word[index]
        previous = word[index - 1]
        if not current.isupper():
            continue
        following = word[index + 1] if index + 1 < len(word) else ""
        boundary = previous.islower() or previous.isdigit() or (
            previous.isupper() and following.islower()
        )
        if boundary:
            parts.append(word[start:index])
            start = index
    parts.append(word[start:])
    return parts


def _has_phrase(segments: list[str], phrase: tuple[str, ...]) -> bool:
    """词段序列里是否整体出现了某个词段序列。

    比较时容忍复数：``api_keys``、``credentials``、``access_tokens`` 都要命中，
    所以词段与禁用词相等的条件是「完全相同」或「禁用词加一个 s」。
    """
    if not phrase or len(phrase) > len(segments):
        return False
    for start in range(len(segments) - len(phrase) + 1):
        if all(
            segments[start + offset] == word or segments[start + offset] == f"{word}s"
            for offset, word in enumerate(phrase)
        ):
            return True
    return False


def _is_forbidden_key(key: str) -> bool:
    """键名是否命中凭据清单（上行方向：命中即整条拒绝）。"""
    segments = _key_segments(key)
    if not segments:
        return False
    if "_".join(segments) in BENIGN_KEYS:
        return False
    return any(_has_phrase(segments, phrase) for phrase in FORBIDDEN_KEY_PHRASES)


def _forbidden_key_in(payload: Any) -> str | None:
    """返回命中的敏感键名；载荷干净时返回 ``None``。

    递归进入嵌套对象与数组：端侧 ``SyncPayloadGuard`` 也查列表里的映射
    （``forbiddenInsideLists``），这里保持同一口径。
    """
    if isinstance(payload, dict):
        for key, value in payload.items():
            if _is_forbidden_key(str(key)):
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
    revision         INTEGER NOT NULL DEFAULT 0,
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

-- 记忆条目的镜像表：端权威域，手机端的记忆上行后落在这里。
-- 与 sync_entities 同为镜像，差别是这里按列存，云端不必解 JSON 就能读。
CREATE TABLE IF NOT EXISTS sync_memory_entries (
    entity_id  TEXT PRIMARY KEY,
    level      TEXT NOT NULL DEFAULT '',
    scope      TEXT NOT NULL DEFAULT '',
    slot       TEXT NOT NULL DEFAULT '',
    content    TEXT NOT NULL DEFAULT '',
    revision   INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT ''
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


def _payload_text(value: Any) -> str:
    """载荷里的一个字段 → 文本。字符串原样留，其它类型转成 JSON 文本。"""
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


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
            self._migrate_ops_revision(conn)
            conn.commit()
            self._schema_ready = True

    @staticmethod
    def _migrate_ops_revision(conn: sqlite3.Connection) -> None:
        """给旧库补上 ``sync_ops.revision``。

        ``CREATE TABLE IF NOT EXISTS`` 不会改动已存在的表，老用户的 sync.db 里
        没有这一列。回放旧的上行记录时要用它，缺列就直接补上。
        """
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(sync_ops)")}
        if "revision" not in columns:
            conn.execute("ALTER TABLE sync_ops ADD COLUMN revision INTEGER NOT NULL DEFAULT 0")

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
            revision=int(row["revision"] or 0),
        )

    def memory_entry(self, entity_id: str) -> dict[str, Any] | None:
        """记忆镜像里的一条：``level`` / ``scope`` / ``slot`` / ``content``。

        删除之前先读它：条目进了哪份文档，只有镜像表知道。
        """
        conn = self._connect()
        try:
            self._ensure_schema(conn)
            row = conn.execute(
                "SELECT level, scope, slot, content FROM sync_memory_entries WHERE entity_id = ?",
                (entity_id,),
            ).fetchone()
            if row is None:
                return None
            return {
                "level": str(row["level"]),
                "scope": str(row["scope"]),
                "slot": str(row["slot"]),
                "content": str(row["content"]),
            }
        finally:
            conn.close()

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
            "(client_op_id, domain, status, conflict_payload, reason, revision, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                item.client_op_id,
                item.domain,
                result.status,
                _dump(result.conflict_payload) if result.conflict_payload is not None else None,
                result.reason,
                result.revision,
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
            return SyncPushResult(
                client_op_id=item.client_op_id,
                status=STATUS_APPLIED,
                revision=int(current["revision"]),
            )

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
                        revision=int(current["revision"]),
                    )
            elif item.domain in END_AUTHORITATIVE_DOMAINS and item.revision < client_revision:
                # 端权威域的镜像：云端留着更新的那份，不被旧变更拉回去。
                return SyncPushResult(
                    client_op_id=item.client_op_id,
                    status=STATUS_REJECTED,
                    reason=REASON_STALE,
                    revision=int(current["revision"]),
                )

        revision = self._write_change(
            conn, item.domain, item.entity_id, kind, item.payload, item.revision
        )
        if item.domain == DOMAIN_MEMORY:
            self._write_memory_mirror(conn, item, revision)
        return SyncPushResult(
            client_op_id=item.client_op_id,
            status=STATUS_APPLIED,
            revision=revision,
        )

    def _write_memory_mirror(
        self, conn: sqlite3.Connection, item: SyncPushItem, revision: int
    ) -> None:
        """把记忆条目写进镜像表。

        端权威域：云端只做镜像，手机端的记忆是权威的那一份。
        """
        if item.kind == KIND_DELETE:
            conn.execute("DELETE FROM sync_memory_entries WHERE entity_id = ?", (item.entity_id,))
            return
        payload = item.payload
        conn.execute(
            "INSERT INTO sync_memory_entries "
            "(entity_id, level, scope, slot, content, revision, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(entity_id) DO UPDATE SET level = excluded.level, "
            "scope = excluded.scope, slot = excluded.slot, content = excluded.content, "
            "revision = excluded.revision, updated_at = excluded.updated_at",
            (
                item.entity_id,
                _payload_text(payload.get("level")),
                _payload_text(payload.get("scope")),
                _payload_text(payload.get("slot")),
                _payload_text(payload.get("content")),
                revision,
                _now(),
            ),
        )

    def publish(self, domain: str, entity_id: str, kind: str, payload: dict[str, Any]) -> None:
        """云端自己产生的一条变更。

        端侧已经上行过的实体，保留它记下的端侧版本号：双向域里端侧再把同一版
        推回来时，冲突判定才认得出「双方都改过」，不会静默覆盖云端版本。
        """
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
                client_revision = int(current["client_revision"]) if current is not None else 0
                self._write_change(conn, domain, entity_id, kind, payload, client_revision)
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
# 云端发布源：设定、画像、agent 配置
# ---------------------------------------------------------------------------

#: 云端发布源的去重签名：``(同步库路径, 域) -> 源签名``。
#: 源没变就不重发，端侧不会每轮都拉到一条「变更」。
_PUBLISH_CACHE: dict[tuple[str, str], tuple[Any, ...]] = {}
_PUBLISH_LOCK = threading.Lock()


def _is_publish_secret_key(key: str) -> bool:
    """键名是否命中凭据清单（发布方向：命中即整条摘掉）。

    按**词段**判定，与 :func:`_forbidden_key_in`、与端侧同一口径：
    ``api_key_backup`` 命中，``max_tokens`` 不命中——后者是 agent 配置的预算
    字段，不是凭据，摘掉就等于把预算功能丢了。
    """
    segments = _key_segments(key)
    if not segments:
        return False
    if "_".join(segments) in BENIGN_KEYS:
        return False
    return any(_has_phrase(segments, phrase) for phrase in PUBLISH_SECRET_KEY_PHRASES)


def _strip_publish_secrets(value: Any) -> Any:
    """逐层剥掉凭据键：命中的键整条丢弃，其余原样保留。

    与 :func:`_forbidden_key_in` 的分工：那条是「整条拒绝」，会把整个设定条目
    挡掉；这里要的是「只剥掉凭据，其余照发」。所以不能把值换成空串——空串会
    覆盖掉手机端自己填的键。
    """
    if isinstance(value, dict):
        return {
            key: _strip_publish_secrets(item)
            for key, item in value.items()
            if not _is_publish_secret_key(str(key))
        }
    if isinstance(value, list):
        return [_strip_publish_secrets(item) for item in value]
    return value


def _files_signature(paths: list[Path]) -> tuple[tuple[str, int, int], ...]:
    """文件集合的廉价签名：路径 + 修改时间 + 大小。用来跳过没变过的源。"""
    signature: list[tuple[str, int, int]] = []
    for path in paths:
        try:
            stat = path.stat()
        except OSError:
            continue
        signature.append((str(path), stat.st_mtime_ns, stat.st_size))
    return tuple(sorted(signature))


def _publish_settings(store: _SyncStore) -> None:
    """把云端设定发布到同步库。

    设定是双向域：云端改了就下发，端侧改了也从云端镜像回去。

    * 实体 id：设定键——设定文件名去掉扩展名（``model_catalog`` / ``interface``）。
    * 载荷：``{"value": <该份设定的 JSON 值>}``，与端侧 ``RoomSyncApplier``
      的设定映射逐字一致。

    设定目录里存着真凭据（模型目录的 ``api_key``、鉴权的 ``password_hash``……），
    发布前逐层剥掉：只剥凭据键，其余键照发。
    """
    settings_dir = get_current_path_service().get_settings_dir()
    try:
        files = sorted(path for path in settings_dir.glob("*.json") if path.is_file())
    except OSError:
        logger.debug("设定发布跳过：读不到设定目录。")
        return

    signature = _files_signature(files)
    cache_key = (str(store.db_path), DOMAIN_SETTINGS)
    with _PUBLISH_LOCK:
        if _PUBLISH_CACHE.get(cache_key) == signature:
            return

    payloads: list[tuple[str, dict[str, Any]]] = []
    incomplete = False
    for path in files:
        payload = _read_settings_payload(path)
        if payload is None:
            incomplete = True
            continue
        payloads.append((path.stem, payload))

    current = store.entity_payloads(DOMAIN_SETTINGS)
    for entity_id, payload in payloads:
        stored = current.get(entity_id)
        if stored is not None and stored[0] == KIND_UPSERT and stored[1] == _dump(payload):
            # 没变：不写变更日志，端侧不会多拉一轮。
            continue
        store.publish(DOMAIN_SETTINGS, entity_id, KIND_UPSERT, payload)

    if incomplete:
        # 这一轮有文件没读出来，结果不完整：不记签名，下一轮重来。
        return
    with _PUBLISH_LOCK:
        _PUBLISH_CACHE[cache_key] = signature


def _read_settings_payload(path: Path) -> dict[str, Any] | None:
    """读一份设定文档：剥掉凭据之后的 JSON 值。读不了或不是 JSON 就返回 None。"""
    try:
        if path.stat().st_size > MAX_SETTINGS_BYTES:
            logger.debug("设定发布跳过：文件超过体积上限。")
            return None
        raw = path.read_text(encoding="utf-8")
    except (OSError, ValueError):
        logger.debug("设定发布跳过：文件读不到。")
        return None
    try:
        parsed = json.loads(raw)
    except ValueError:
        logger.debug("设定发布跳过：文件不是合法 JSON。")
        return None
    return {"value": _strip_publish_secrets(parsed)}


def _publish_persona(store: _SyncStore) -> None:
    """把云端画像发布到同步库。

    * 实体 id：画像名（``peer`` / ``teacher`` / 用户自建画像）。
    * 载荷：``{"description": ..., "content": ...}``，与端侧 ``RoomSyncApplier``
      的画像映射逐字一致。

    ``content`` 是画像正文（``PERSONA.md`` 的全文），可能是长文本：超过上限就
    跳过这个画像，其余画像照发。
    """
    try:
        from deeptutor.services.persona.service import PERSONA_FILE, get_persona_service

        service = get_persona_service()
        personas = service.list_personas()
    except Exception:
        logger.debug("画像发布跳过：读不到画像清单。")
        return

    files = [service.root / info.name / PERSONA_FILE for info in personas]
    signature = _files_signature(files)
    cache_key = (str(store.db_path), DOMAIN_PERSONA)
    with _PUBLISH_LOCK:
        if _PUBLISH_CACHE.get(cache_key) == signature:
            return

    current = store.entity_payloads(DOMAIN_PERSONA)
    for info in personas:
        payload = _read_persona_payload(service, info.name)
        if payload is None:
            continue
        stored = current.get(info.name)
        if stored is not None and stored[0] == KIND_UPSERT and stored[1] == _dump(payload):
            continue
        store.publish(DOMAIN_PERSONA, info.name, KIND_UPSERT, payload)

    with _PUBLISH_LOCK:
        _PUBLISH_CACHE[cache_key] = signature


def _read_persona_payload(service: Any, name: str) -> dict[str, Any] | None:
    """读一个画像的详情：描述 + 正文。读不到或正文过大就返回 None。"""
    try:
        detail = service.get_detail(name)
    except Exception:
        logger.debug("画像发布跳过：单个画像读不到。")
        return None
    content = detail.content or ""
    if len(content.encode("utf-8")) > MAX_PERSONA_CONTENT_BYTES:
        logger.debug("画像发布跳过：正文超过体积上限。")
        return None
    return {"description": detail.description or "", "content": content}


def _publish_agents(store: _SyncStore) -> None:
    """把云端 agent 配置发布到同步库。

    源是 ``data/user/settings/agents.yaml``：那里才是用户自己的 agent 配置
    （每个 agent 的 temperature / max_tokens 与分步预算）。``AGENT_REGISTRY``
    只是界面的静态元数据（图标、颜色、文案），不发。

    * 实体 id：agent 名（``solve`` / ``research`` / ``brainstorm``……）。
    * 载荷：``{"name": <agent 名>, "config": <该 agent 的配置对象>}``，与端侧
      ``RoomSyncApplier`` 的 agent 映射逐字一致。
    """
    path = get_current_path_service().get_runtime_config_file("agents")
    try:
        if not path.is_file():
            return
        stat = path.stat()
    except OSError:
        logger.debug("agent 发布跳过：读不到 agents.yaml。")
        return

    signature = ((str(path), stat.st_mtime_ns, stat.st_size),)
    cache_key = (str(store.db_path), DOMAIN_AGENT)
    with _PUBLISH_LOCK:
        if _PUBLISH_CACHE.get(cache_key) == signature:
            return

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, yaml.YAMLError):
        logger.debug("agent 发布跳过：agents.yaml 读不了或不是合法 YAML。")
        return
    if not isinstance(raw, dict):
        logger.debug("agent 发布跳过：agents.yaml 顶层不是映射。")
        return

    current = store.entity_payloads(DOMAIN_AGENT)
    published: set[str] = set()
    for entries in raw.values():
        if not isinstance(entries, dict):
            continue
        for agent_name, config in entries.items():
            if not isinstance(config, dict):
                continue
            entity_id = str(agent_name)
            if entity_id in published:
                # 同名 agent 出现在两个分区：只发第一个，免得两条变更互相覆盖。
                logger.warning("agent 发布跳过：%s 在多个分区出现，只发第一个。", entity_id)
                continue
            published.add(entity_id)
            payload = {"name": entity_id, "config": _strip_publish_secrets(config)}
            stored = current.get(entity_id)
            if stored is not None and stored[0] == KIND_UPSERT and stored[1] == _dump(payload):
                continue
            store.publish(DOMAIN_AGENT, entity_id, KIND_UPSERT, payload)

    with _PUBLISH_LOCK:
        _PUBLISH_CACHE[cache_key] = signature


def _publish_cloud_domains(store: _SyncStore, domains: tuple[str, ...] | None = None) -> None:
    """把云端自己产生的内容发布进同步库。

    一个域失败只跳过那个域：设定文件读不到、画像服务起不来、agents.yaml 解析
    失败，都不该让整个同步端点 500——其它域照常发布。
    """
    publishers = (
        (DOMAIN_KNOWLEDGE_BASE, _publish_knowledge_base),
        (DOMAIN_SETTINGS, _publish_settings),
        (DOMAIN_PERSONA, _publish_persona),
        (DOMAIN_AGENT, _publish_agents),
    )
    for domain, publisher in publishers:
        if domains is not None and domain not in domains:
            continue
        try:
            publisher(store)
        except Exception as exc:
            # 只记域名和异常类型：不记载荷，日志里不会出现任何实体内容。
            logger.warning("云端发布跳过：%s 域本轮未发布（%s）。", domain, type(exc).__name__)


# ---------------------------------------------------------------------------
# 记忆镜像：端侧上行 → 云端 L2 / L3 文档
# ---------------------------------------------------------------------------

#: 端侧记忆条目在云端文档里的分区名。手机端的层级口径与云端不同，落进云端
#: 文档时用这个名字标出来，免得和云端自己 consolidate 出来的条目混在一起。
MEMORY_DEVICE_SECTION = "device"


def _mirror_memory_document(item: SyncPushItem, previous: dict[str, Any] | None) -> None:
    """把端侧的记忆条目写进云端对应的 L2 / L3 文档。

    记忆是端权威域：手机端那一份说了算，云端只镜像。对不上云端文档的条目
    （层不是 L2/L3、槽名不认识）就只留在镜像表里——宁可少一份，也不把条目
    塞进不对的文档。

    写文档是尽力而为：失败只记日志，不影响这次上行的结果。
    """
    try:
        from deeptutor.services.file_io import atomic_write_text
        from deeptutor.services.memory import paths
        from deeptutor.services.memory.document import Entry, serialize
        from deeptutor.services.memory.store import get_memory_store
    except Exception:
        logger.debug("记忆镜像跳过：记忆模块不可用。")
        return

    if item.kind.strip().lower() == KIND_DELETE:
        _remove_memory_document(item.entity_id, previous)
        return

    level = _payload_text(item.payload.get("level"))
    scope = _payload_text(item.payload.get("scope"))
    slot = _payload_text(item.payload.get("slot"))
    content = _payload_text(item.payload.get("content"))
    if not item.entity_id or not content:
        return

    if level == "L2" and scope in paths.SURFACES:
        layer, key = "L2", scope
        path = paths.l2_file(scope)
        section = slot or MEMORY_DEVICE_SECTION
    elif level == "L3" and slot in paths.L3_SLOTS:
        layer, key = "L3", slot
        path = paths.l3_file(slot)
        section = scope or MEMORY_DEVICE_SECTION
    else:
        logger.debug("记忆镜像跳过：条目对不上云端的 L2/L3 文档。")
        return

    try:
        doc = get_memory_store().read_doc(layer, key)
        entries = doc.section_entries(section)
        existing = doc.find(item.entity_id)
        if existing is not None:
            existing.text = content
        else:
            entries.append(Entry(id=item.entity_id, section=section, text=content, refs=[]))
        atomic_write_text(path, serialize(doc))
    except Exception as exc:
        # 文档写不进去只记日志：这次上行的结果已经定了，不该被记忆文档拖垮。
        logger.debug("记忆镜像跳过：文档写不进去（%s）。", type(exc).__name__)


def _remove_memory_document(entity_id: str, previous: dict[str, Any] | None) -> None:
    """把一条记忆从云端文档里拿掉。

    条目进了哪份文档，只有删除前的镜像知道（``previous``）；拿不到就只留在
    镜像表里，文档里的那一条交给 consolidate 清理。
    """
    if not entity_id or not previous:
        return
    try:
        from deeptutor.services.file_io import atomic_write_text
        from deeptutor.services.memory import paths
        from deeptutor.services.memory.document import serialize
        from deeptutor.services.memory.store import get_memory_store
    except Exception:
        logger.debug("记忆镜像跳过：记忆模块不可用。")
        return

    level = previous.get("level", "")
    scope = previous.get("scope", "")
    slot = previous.get("slot", "")
    if level == "L2" and scope in paths.SURFACES:
        layer, key = "L2", scope
        path = paths.l2_file(scope)
    elif level == "L3" and slot in paths.L3_SLOTS:
        layer, key = "L3", slot
        path = paths.l3_file(slot)
    else:
        return

    try:
        doc = get_memory_store().read_doc(layer, key)
        if not doc.remove(entity_id):
            return
        atomic_write_text(path, serialize(doc))
    except Exception as exc:
        logger.debug("记忆镜像跳过：文档删不掉（%s）。", type(exc).__name__)


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
    _publish_cloud_domains(store)
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
    if domain in CLOUD_PUBLISHED_DOMAINS:
        _publish_cloud_domains(store, (domain,))
    revision, items, next_cursor = store.changes(domain, cursor, limit)
    return SyncChangePage(revision=revision, items=items, next_cursor=next_cursor)


@router.post("/push", response_model=SyncPushResponse)
async def sync_push(body: SyncPushRequest) -> SyncPushResponse:
    """批量上行变更。

    ``client_op_id`` 是幂等键：同一条操作重发，返回与首次一致的结果，不会重复应用。
    """
    store = _store()
    results: list[SyncPushResult] = []
    for item in body.items:
        previous: dict[str, Any] | None = None
        if item.domain == DOMAIN_MEMORY and item.kind.strip().lower() == KIND_DELETE:
            # 删除之前先读镜像：条目进了哪份文档，只有镜像表知道。
            previous = store.memory_entry(item.entity_id)
        result = store.push(item)
        results.append(result)
        if item.domain == DOMAIN_MEMORY and result.status == STATUS_APPLIED:
            # 记忆是端权威域：云端只镜像，把条目写进云端自己的 L2/L3 文档。
            _mirror_memory_document(item, previous)
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
