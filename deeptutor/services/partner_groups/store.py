"""User-scoped atomic storage for Partner Groups and speaker-aware transcripts."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import re
import shutil
import threading

from deeptutor.multi_user.context import get_current_user
from deeptutor.multi_user.paths import get_current_path_service
from deeptutor.services.partner_groups.models import (
    GroupMessage,
    GroupSessionSummary,
    PartnerGroupConfig,
    PartnerInvocation,
)

_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,79}$")
_LOCKS: dict[Path, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()

PUBLIC_TRANSCRIPT_MAX_MESSAGES = 40
PUBLIC_TRANSCRIPT_MAX_CHARS = 16_000


def _lock_for(path: Path) -> threading.Lock:
    resolved = path.resolve()
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(resolved, threading.Lock())


def render_recent_lines(lines: list[str], *, max_chars: int, separator: str) -> str:
    """Keep the newest line and fill backwards without crossing a hard cap."""
    if max_chars <= 0 or not lines:
        return ""
    kept: list[str] = []
    total = 0
    for line in reversed(lines):
        join_cost = len(separator) if kept else 0
        available = max_chars - total - join_cost
        if available <= 0:
            break
        fragment = line[:available]
        kept.append(fragment)
        total += join_cost + len(fragment)
        if len(fragment) < len(line):
            break
    return separator.join(reversed(kept))


class PartnerGroupStore:
    @property
    def root(self) -> Path:
        root = get_current_path_service().get_user_root() / "partner_groups"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def list(self) -> list[PartnerGroupConfig]:
        owner_id = get_current_user().id
        groups: list[PartnerGroupConfig] = []
        for path in sorted(self.root.glob("*/config.json")):
            group = self._read_unchecked(path)
            # Listing is a cross-directory scan, so ownership must be visible at
            # this boundary rather than hidden inside a permissive file reader.
            if group is not None and group.owner_id == owner_id:
                groups.append(group)
        return sorted(groups, key=lambda item: item.updated_at, reverse=True)

    def get(self, group_id: str) -> PartnerGroupConfig | None:
        return self._read(self.group_dir(group_id) / "config.json")

    def save(self, group: PartnerGroupConfig) -> None:
        if group.owner_id != get_current_user().id:
            raise PermissionError("Partner Group belongs to another user.")
        directory = self.group_dir(group.group_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "config.json"
        tmp = path.with_suffix(".tmp")
        with _lock_for(path):
            tmp.write_text(
                json.dumps(group.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp.replace(path)

    def delete(self, group_id: str) -> bool:
        directory = self.group_dir(group_id)
        if not directory.exists():
            return False
        group = self.get(group_id)
        if group is None:
            return False
        shutil.rmtree(directory)
        return True

    def group_dir(self, group_id: str) -> Path:
        normalized = str(group_id or "").strip().lower()
        if not _SAFE_ID.fullmatch(normalized):
            raise ValueError("Invalid Partner Group id.")
        return self.root / normalized

    def _read(self, path: Path) -> PartnerGroupConfig | None:
        group = self._read_unchecked(path)
        if group is None or group.owner_id != get_current_user().id:
            return None
        return group

    @staticmethod
    def _read_unchecked(path: Path) -> PartnerGroupConfig | None:
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            group = PartnerGroupConfig(**data)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return None
        return group


class GroupTranscriptStore:
    def __init__(self, group_dir: Path) -> None:
        self.directory = group_dir / "sessions"

    def append(self, message: GroupMessage) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._path(message.session_key)
        with _lock_for(path):
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(message.to_dict(), ensure_ascii=False) + "\n")

    def create_session(self, session_key: str) -> GroupSessionSummary:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._path(session_key)
        with _lock_for(path):
            if path.exists():
                raise ValueError("Partner Group session already exists.")
            path.touch()
        summary = self._summary(path, empty_session_key=session_key)
        assert summary is not None
        return summary

    def list_sessions(self) -> list[GroupSessionSummary]:
        if not self.directory.exists():
            return []
        sessions = [
            summary
            for path in self.directory.glob("*.jsonl")
            if (summary := self._summary(path)) is not None
        ]
        return sorted(sessions, key=lambda item: item.updated_at, reverse=True)

    def delete_session(self, session_key: str) -> bool:
        path = self._path(session_key)
        with _lock_for(path):
            if not path.exists():
                return False
            path.unlink()
            return True

    def messages(self, session_key: str, *, limit: int = 200) -> list[GroupMessage]:
        path = self._path(session_key)
        rows = self._read_messages(path)
        return rows[-max(1, min(limit, 500)) :]

    def find_event(self, event_id: str) -> GroupMessage | None:
        event_id = str(event_id or "").strip()
        if not event_id:
            return None
        for path in self.directory.glob("*.jsonl"):
            for message in self._read_messages(path):
                if message.event_id == event_id:
                    return message
        return None

    def messages_for_turn(self, session_key: str, turn_id: str) -> list[GroupMessage]:
        return [
            row for row in self._read_messages(self._path(session_key)) if row.turn_id == turn_id
        ]

    def replace(self, message: GroupMessage) -> bool:
        """Replace one durable seat without changing its stable event id."""
        path = self._path(message.session_key)
        tmp = path.with_suffix(".tmp")
        with _lock_for(path):
            if not path.exists():
                return False
            replaced = False
            output: list[str] = []
            try:
                with path.open(encoding="utf-8") as handle:
                    for raw in handle:
                        try:
                            data = json.loads(raw)
                        except json.JSONDecodeError:
                            output.append(raw.rstrip("\n"))
                            continue
                        if isinstance(data, dict) and data.get("event_id") == message.event_id:
                            output.append(json.dumps(message.to_dict(), ensure_ascii=False))
                            replaced = True
                        else:
                            output.append(raw.rstrip("\n"))
            except OSError:
                return False
            if not replaced:
                return False
            tmp.write_text("\n".join(output) + "\n", encoding="utf-8")
            tmp.replace(path)
            return True

    def render_before_turn(
        self,
        session_key: str,
        turn_id: str,
        *,
        max_messages: int = PUBLIC_TRANSCRIPT_MAX_MESSAGES,
        max_chars: int = PUBLIC_TRANSCRIPT_MAX_CHARS,
    ) -> str:
        rows: list[GroupMessage] = []
        for row in self._read_messages(self._path(session_key)):
            if row.turn_id == turn_id:
                break
            if not row.error:
                rows.append(row)
        return self._render_rows(rows[-max_messages:], max_chars=max_chars)

    def render(
        self,
        session_key: str,
        *,
        max_messages: int = PUBLIC_TRANSCRIPT_MAX_MESSAGES,
        max_chars: int = PUBLIC_TRANSCRIPT_MAX_CHARS,
    ) -> str:
        """Render bounded history; the current user message is injected separately.

        The newest public message is mandatory (truncated if it alone exceeds the
        budget); older non-error messages are admitted in reverse chronological
        order. This makes the cap absolute while preserving the closest context.
        """
        rows = [row for row in self.messages(session_key, limit=max_messages) if not row.error]
        return self._render_rows(rows, max_chars=max_chars)

    def _summary(
        self,
        path: Path,
        *,
        empty_session_key: str | None = None,
    ) -> GroupSessionSummary | None:
        messages = self._read_messages(path)
        first_user = next((row for row in messages if row.role == "user"), None)
        title = ""
        if first_user is not None:
            title = " ".join(first_user.content.split())[:40].rstrip()
        if messages:
            session_key = messages[0].session_key
            created_at = messages[0].created_at
            updated_at = messages[-1].created_at
        else:
            # A normalized filename is not reversible. The only empty files we
            # can identify safely are those created in this process, where the
            # original key is still available to the caller.
            if empty_session_key is None:
                return None
            session_key = empty_session_key
            try:
                timestamp = path.stat().st_mtime
            except OSError:
                timestamp = 0.0
            created_at = datetime.fromtimestamp(timestamp, UTC).isoformat()
            updated_at = created_at
        return GroupSessionSummary(
            session_key=session_key,
            title=title,
            message_count=len(messages),
            updated_at=updated_at,
            created_at=created_at,
        )

    @staticmethod
    def _read_messages(path: Path) -> list[GroupMessage]:
        if not path.exists():
            return []
        rows: list[GroupMessage] = []
        try:
            with path.open(encoding="utf-8") as handle:
                for line in handle:
                    try:
                        data = json.loads(line)
                        rows.append(GroupMessage(**data))
                    except (TypeError, ValueError, json.JSONDecodeError):
                        continue
        except OSError:
            return []
        return rows

    @staticmethod
    def _render_rows(rows: list[GroupMessage], *, max_chars: int) -> str:
        rendered = [f"{row.author_name}: {row.content}" for row in rows]
        return render_recent_lines(rendered, max_chars=max_chars, separator="\n\n")

    def _path(self, session_key: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(session_key or "default"))
        safe = safe.strip(".")[:120] or "default"
        return self.directory / f"{safe}.jsonl"


class PartnerInvocationStore:
    """Atomic per-proposal state under a user-scoped Group directory."""

    def __init__(self, group_dir: Path) -> None:
        self.directory = group_dir / "invocations"
        self.directory.mkdir(parents=True, exist_ok=True)

    def save(self, invocation: PartnerInvocation) -> None:
        path = self._path(invocation.invocation_id)
        tmp = path.with_suffix(".tmp")
        with _lock_for(path):
            tmp.write_text(
                json.dumps(invocation.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp.replace(path)

    def get(self, invocation_id: str) -> PartnerInvocation | None:
        path = self._path(invocation_id)
        with _lock_for(path):
            return self._read(path)

    def list(self, session_key: str | None = None, *, limit: int = 200) -> list[PartnerInvocation]:
        rows: list[PartnerInvocation] = []
        for path in self.directory.glob("*.json"):
            invocation = self._read(path)
            if invocation is None:
                continue
            if session_key is not None and invocation.session_key != session_key:
                continue
            rows.append(invocation)
        rows.sort(key=lambda item: item.created_at)
        return rows[-max(1, min(limit, 500)) :]

    def delete_session(self, session_key: str) -> int:
        removed = 0
        for path in self.directory.glob("*.json"):
            invocation = self._read(path)
            if invocation is None or invocation.session_key != session_key:
                continue
            with _lock_for(path):
                if path.exists():
                    path.unlink()
                    removed += 1
        return removed

    def transition(
        self,
        invocation_id: str,
        *,
        allowed: set[str],
        status: str,
        **changes: str,
    ) -> PartnerInvocation:
        path = self._path(invocation_id)
        tmp = path.with_suffix(".tmp")
        with _lock_for(path):
            invocation = self._read(path)
            if invocation is None:
                raise LookupError("Partner invocation not found")
            if invocation.status not in allowed:
                raise ValueError(
                    f"Partner invocation is already {invocation.status}; expected "
                    + " or ".join(sorted(allowed))
                )
            invocation.status = status
            invocation.updated_at = changes.pop("updated_at", "") or invocation.updated_at
            for key, value in changes.items():
                if hasattr(invocation, key):
                    setattr(invocation, key, str(value or ""))
            tmp.write_text(
                json.dumps(invocation.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp.replace(path)
            return invocation

    def _path(self, invocation_id: str) -> Path:
        normalized = str(invocation_id or "").strip().lower()
        if not re.fullmatch(r"[a-f0-9]{32}", normalized):
            raise ValueError("Invalid Partner invocation id.")
        return self.directory / f"{normalized}.json"

    @staticmethod
    def _read(path: Path) -> PartnerInvocation | None:
        if not path.exists():
            return None
        try:
            return PartnerInvocation(**json.loads(path.read_text(encoding="utf-8")))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return None


__all__ = [
    "GroupTranscriptStore",
    "PUBLIC_TRANSCRIPT_MAX_CHARS",
    "PUBLIC_TRANSCRIPT_MAX_MESSAGES",
    "PartnerGroupStore",
    "PartnerInvocationStore",
    "render_recent_lines",
]
