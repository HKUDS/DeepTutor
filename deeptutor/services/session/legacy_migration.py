"""Idempotent migration of the removed v1 JSON chat session store."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any
import uuid

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows development fallback
    fcntl = None  # type: ignore[assignment]

from deeptutor.services.file_io import atomic_write_json

from .protocol import SessionRepository


class LegacyMigrationError(RuntimeError):
    """Raised when v2 cannot safely archive every legacy chat."""


@dataclass(slots=True)
class LegacyMigrationReport:
    source: str
    source_hash: str = ""
    imported: int = 0
    skipped: int = 0
    failed: int = 0
    messages: int = 0
    archived_to: str = ""
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@contextmanager
def _migration_lock(archive_root: Path) -> Iterator[None]:
    archive_root.mkdir(parents=True, exist_ok=True)
    with (archive_root / ".migration.lock").open("a+b") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _load_ledger(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {"version": 1, "runs": []}
    if not isinstance(value, dict) or not isinstance(value.get("runs"), list):
        return {"version": 1, "runs": []}
    return value


def _normalize_session(raw: Any, index: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"sessions[{index}] is not an object")
    session_id = str(raw.get("session_id") or "").strip()
    if not session_id:
        raise ValueError(f"sessions[{index}] has no session_id")
    created_at = float(raw.get("created_at") or 0)
    updated_at = float(raw.get("updated_at") or created_at)
    settings = raw.get("settings") if isinstance(raw.get("settings"), dict) else {}
    knowledge_base = str(settings.get("kb_name") or "").strip()
    preferences = {
        "capability": "chat",
        "tools": ["web_search"] if bool(settings.get("enable_web_search")) else [],
        "knowledge_bases": (
            [knowledge_base] if knowledge_base and bool(settings.get("enable_rag")) else []
        ),
        "legacy_chat_settings": dict(settings),
        "legacy_migrated": True,
    }
    messages: list[dict[str, Any]] = []
    raw_messages = raw.get("messages") or []
    if not isinstance(raw_messages, list):
        raise ValueError(f"session {session_id!r} messages is not a list")
    for message_index, message in enumerate(raw_messages):
        if not isinstance(message, dict):
            raise ValueError(f"session {session_id!r} messages[{message_index}] is not an object")
        role = str(message.get("role") or "").strip()
        if role not in {"system", "user", "assistant", "tool"}:
            raise ValueError(f"session {session_id!r} messages[{message_index}] has invalid role")
        metadata: dict[str, Any] = {"legacy_chat": True}
        if isinstance(message.get("sources"), (dict, list)):
            metadata["sources"] = message["sources"]
        messages.append(
            {
                "role": role,
                "content": str(message.get("content") or ""),
                "created_at": float(message.get("timestamp") or created_at),
                "metadata": metadata,
            }
        )
    return {
        "session_id": session_id,
        "title": str(raw.get("title") or "New conversation")[:100],
        "created_at": created_at,
        "updated_at": updated_at,
        "preferences": preferences,
        "messages": messages,
    }


class LegacyChatSessionMigrator:
    def __init__(
        self,
        repository: SessionRepository,
        source: Path,
        archive_root: Path,
    ) -> None:
        self.repository = repository
        self.source = Path(source)
        self.archive_root = Path(archive_root)
        self.ledger_path = self.archive_root / "migration-ledger.json"

    async def migrate(self, *, dry_run: bool = False) -> LegacyMigrationReport:
        # Every Uvicorn worker runs lifespan. Serialize the whole migration so
        # followers see either the original source or the completed ledger,
        # never a half-moved file.
        with _migration_lock(self.archive_root):
            return await self._migrate_locked(dry_run=dry_run)

    async def _migrate_locked(self, *, dry_run: bool) -> LegacyMigrationReport:
        report = LegacyMigrationReport(source=str(self.source))
        if not self.source.exists():
            return report

        raw_bytes = await asyncio.to_thread(self.source.read_bytes)
        report.source_hash = hashlib.sha256(raw_bytes).hexdigest()
        self.archive_root.mkdir(parents=True, exist_ok=True)
        ledger = _load_ledger(self.ledger_path)
        previous = next(
            (
                run
                for run in ledger["runs"]
                if isinstance(run, dict)
                and run.get("source_hash") == report.source_hash
                and not run.get("failed")
            ),
            None,
        )
        if previous is not None:
            report.skipped = int(previous.get("imported") or 0) + int(previous.get("skipped") or 0)
            if not dry_run:
                report.archived_to = await asyncio.to_thread(
                    self._archive_source, report.source_hash
                )
            return report

        backup_path = self.archive_root / (
            f"pre-migration-{_timestamp()}-{report.source_hash[:12]}.json"
        )
        if not dry_run:
            await asyncio.to_thread(shutil.copy2, self.source, backup_path)

        try:
            document = json.loads(raw_bytes.decode("utf-8"))
            if not isinstance(document, dict) or not isinstance(document.get("sessions", []), list):
                raise ValueError("legacy chat root must contain a sessions list")
            sessions = [
                _normalize_session(value, index)
                for index, value in enumerate(document.get("sessions", []))
            ]
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            report.failed = 1
            report.errors.append(str(exc))
            raise LegacyMigrationError(
                f"Legacy chat migration preflight failed for {self.source}: {exc}"
            ) from exc

        if dry_run:
            report.imported = len(sessions)
            report.messages = sum(len(session["messages"]) for session in sessions)
            return report

        for session in sessions:
            try:
                result = await self.repository.import_legacy_session(**session)
                if result.get("imported"):
                    report.imported += 1
                    report.messages += int(result.get("message_count") or 0)
                else:
                    report.skipped += 1
            except Exception as exc:
                report.failed += 1
                report.errors.append(f"{session['session_id']}: {type(exc).__name__}: {exc}")

        if report.failed:
            raise LegacyMigrationError(
                f"Legacy chat migration partially failed ({report.failed} session(s)); "
                f"source retained at {self.source}"
            )

        report.archived_to = await asyncio.to_thread(self._archive_source, report.source_hash)
        ledger["runs"].append(
            {
                **report.to_dict(),
                "completed_at": datetime.now(UTC).isoformat(),
            }
        )
        atomic_write_json(self.ledger_path, ledger)
        return report

    def _archive_source(self, source_hash: str) -> str:
        target = self.archive_root / (
            f"sessions-{_timestamp()}-{source_hash[:12]}-{uuid.uuid4().hex[:8]}.json"
        )
        self.source.replace(target)
        return str(target)


async def migrate_all_legacy_chat_scopes(*, dry_run: bool = False) -> list[dict[str, Any]]:
    """Migrate the removed JSON store for admin and every local user scope."""

    from deeptutor.multi_user.identity import list_user_info
    from deeptutor.multi_user.models import CurrentUser
    from deeptutor.multi_user.paths import (
        local_admin_user,
        scope_for_user,
        user_context,
    )
    from deeptutor.services.path_service import get_path_service
    from deeptutor.services.session import get_session_store

    users = [local_admin_user()]
    for record in list_user_info():
        user_id = str(record.get("id") or "").strip()
        role = str(record.get("role") or "user")
        if user_id and role != "admin":
            users.append(
                CurrentUser(
                    id=user_id,
                    username=str(record.get("username") or user_id),
                    role="user",
                    scope=scope_for_user(user_id, is_admin=False),
                )
            )

    reports: list[dict[str, Any]] = []
    seen_scopes: set[str] = set()
    for user in users:
        if user.scope.cache_key in seen_scopes:
            continue
        seen_scopes.add(user.scope.cache_key)
        with user_context(user):
            paths = get_path_service()
            migrator = LegacyChatSessionMigrator(
                get_session_store(),
                paths.get_session_file("chat"),
                paths.get_user_root() / "archive" / "legacy-chat",
            )
            reports.append((await migrator.migrate(dry_run=dry_run)).to_dict())
    return reports


__all__ = [
    "LegacyChatSessionMigrator",
    "LegacyMigrationError",
    "LegacyMigrationReport",
    "migrate_all_legacy_chat_scopes",
]
