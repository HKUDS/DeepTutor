"""Extensible shared-memory registry; the first implementation is a whiteboard."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import threading
from typing import Protocol

from deeptutor.services.partner_groups.models import GroupMessage
from deeptutor.services.partner_groups.store import render_recent_lines

_WHITEBOARD_LOCKS: dict[Path, threading.Lock] = {}
_WHITEBOARD_LOCKS_GUARD = threading.Lock()


def _whiteboard_lock(path: Path) -> threading.Lock:
    resolved = path.resolve()
    with _WHITEBOARD_LOCKS_GUARD:
        return _WHITEBOARD_LOCKS.setdefault(resolved, threading.Lock())


class GroupSharedMemory(Protocol):
    name: str
    label: str
    description: str

    def pin(self, message: GroupMessage, *, pinned_at: str) -> tuple[dict, bool]: ...

    def unpin(self, event_id: str, *, unpinned_at: str) -> bool: ...

    def unpin_session(self, session_key: str, *, unpinned_at: str) -> int: ...

    def entries(self, *, limit: int = 200) -> list[dict]: ...

    def render(self, *, max_entries: int = 80, max_chars: int = 16_000) -> str: ...


class SharedMemoryRegistry:
    def __init__(self) -> None:
        self._types: dict[str, type[WhiteboardMemory]] = {}

    def register(self, memory_type: type[WhiteboardMemory]) -> None:
        if memory_type.name in self._types:
            raise ValueError(f"Shared memory type already registered: {memory_type.name}")
        self._types[memory_type.name] = memory_type

    def validate(self, name: str) -> None:
        """Validate a configured type without constructing storage."""
        if name not in self._types:
            raise ValueError(f"Unknown shared memory type: {name}")

    def create(self, name: str, group_dir: Path) -> GroupSharedMemory:
        self.validate(name)
        memory_type = self._types.get(name)
        assert memory_type is not None
        return memory_type(group_dir)

    def describe(self) -> list[dict[str, str]]:
        return [
            {
                "name": item.name,
                "label": item.label,
                "description": item.description,
            }
            for item in self._types.values()
        ]


@dataclass(slots=True)
class WhiteboardMemory:
    """Append-only register of explicitly curated public transcript messages."""

    group_dir: Path
    name = "whiteboard"
    label = "Shared whiteboard"
    description = "Shared Group notes stored separately from the public transcript."

    @property
    def path(self) -> Path:
        return self.group_dir / "shared" / "whiteboard.jsonl"

    def pin(self, message: GroupMessage, *, pinned_at: str) -> tuple[dict, bool]:
        entry = {
            "schema_version": 2,
            "kind": "pin",
            "event_id": message.event_id,
            "turn_id": message.turn_id,
            "session_key": message.session_key,
            "author_id": message.author_id,
            "author_name": message.author_name,
            "content": message.content,
            "created_at": message.created_at,
            "pinned_at": pinned_at,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _whiteboard_lock(self.path):
            active = self._entries_unlocked()
            existing = next(
                (row for row in active if row.get("event_id") == message.event_id),
                None,
            )
            if existing is not None:
                return existing, False
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry, True

    def unpin(self, event_id: str, *, unpinned_at: str) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _whiteboard_lock(self.path):
            active = self._entries_unlocked()
            if not any(row.get("event_id") == event_id for row in active):
                return False
            self._append_tombstones_unlocked([event_id], unpinned_at=unpinned_at)
            return True

    def unpin_session(self, session_key: str, *, unpinned_at: str) -> int:
        with _whiteboard_lock(self.path):
            event_ids = [
                str(row.get("event_id") or "")
                for row in self._entries_unlocked()
                if row.get("session_key") == session_key and row.get("event_id")
            ]
            self._append_tombstones_unlocked(event_ids, unpinned_at=unpinned_at)
            return len(event_ids)

    def entries(self, *, limit: int = 200) -> list[dict]:
        with _whiteboard_lock(self.path):
            rows = self._entries_unlocked()
        return rows[-max(1, min(limit, 500)) :]

    def render(self, *, max_entries: int = 80, max_chars: int = 16_000) -> str:
        rendered = [
            f"{entry.get('author_name') or 'User'}: {entry.get('content') or ''}"
            for entry in self.entries(limit=max_entries)
        ]
        # A future memory implementation may re-enter model context. Keep its
        # newest entry, then admit older entries newest-first under a hard cap.
        return render_recent_lines(rendered, max_chars=max_chars, separator="\n")

    def _entries_unlocked(self) -> list[dict]:
        if not self.path.exists():
            return []
        active: dict[str, dict] = {}
        order: list[str] = []
        try:
            with self.path.open(encoding="utf-8") as handle:
                for line in handle:
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    # Version-1 rows were automatic copies of user messages.
                    # Leaving them on disk but excluding them keeps migration
                    # lossless while preventing old noise from entering the UI.
                    if not isinstance(row, dict) or row.get("schema_version") != 2:
                        continue
                    event_id = str(row.get("event_id") or "")
                    if not event_id:
                        continue
                    if row.get("kind") == "unpin":
                        active.pop(event_id, None)
                        if event_id in order:
                            order.remove(event_id)
                    elif row.get("kind") == "pin" and row.get("content"):
                        active[event_id] = row
                        if event_id in order:
                            order.remove(event_id)
                        order.append(event_id)
        except OSError:
            return []
        return [active[event_id] for event_id in order if event_id in active]

    def _append_tombstones_unlocked(self, event_ids: list[str], *, unpinned_at: str) -> None:
        if not event_ids:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            for event_id in event_ids:
                handle.write(
                    json.dumps(
                        {
                            "schema_version": 2,
                            "kind": "unpin",
                            "event_id": event_id,
                            "unpinned_at": unpinned_at,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )


shared_memory_registry = SharedMemoryRegistry()
shared_memory_registry.register(WhiteboardMemory)

__all__ = [
    "GroupSharedMemory",
    "SharedMemoryRegistry",
    "WhiteboardMemory",
    "shared_memory_registry",
]
