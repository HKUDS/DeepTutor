"""JSON sessions for solution sequences. The answer key never leaves this store."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import threading
from typing import Any

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{16,80}$")
_LOCKS_GUARD = threading.Lock()
_LOCKS: dict[str, threading.Lock] = {}


def _lock_for(root: Path) -> threading.Lock:
    key = str(root)
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _LOCKS[key] = lock
        return lock


def _atomic_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _outline_path(root: Path, kb_name: str) -> Path:
    # Hash the name so it cannot escape the outlines directory.
    token = hashlib.sha256(kb_name.strip().encode("utf-8")).hexdigest()[:24]
    return root / "outlines" / f"{token}.json"


class SequenceStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.sessions = root / "sessions"
        self.progress_path = root / "progress.json"

    def save(self, record: dict[str, Any]) -> None:
        problem_id = str(record.get("id") or "")
        if not _ID_RE.fullmatch(problem_id):
            raise ValueError("Invalid problem id.")
        with _lock_for(self.root):
            _atomic_write(self.sessions / f"{problem_id}.json", record)

    def load(self, problem_id: str) -> dict[str, Any] | None:
        if not _ID_RE.fullmatch(problem_id):
            return None
        path = self.sessions / f"{problem_id}.json"
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None

    def save_outline(self, kb_name: str, outline: dict[str, Any]) -> None:
        cleaned = kb_name.strip()
        if not cleaned:
            raise ValueError("Invalid knowledge base.")
        with _lock_for(self.root):
            _atomic_write(_outline_path(self.root, cleaned), outline)

    def load_outline(self, kb_name: str) -> dict[str, Any] | None:
        path = _outline_path(self.root, kb_name)
        with _lock_for(self.root):
            if not path.is_file():
                return None
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return None
        return data if isinstance(data, dict) else None

    def progress(self, kb_name: str, topic: str) -> int:
        key = _progress_key(kb_name, topic)
        with _lock_for(self.root):
            return int(_read_progress(self.progress_path).get(key, 0))

    def mark_solved(self, kb_name: str, topic: str, problem_id: str, *, goal: int) -> int:
        key = _progress_key(kb_name, topic)
        with _lock_for(self.root):
            payload = _read_progress_payload(self.progress_path)
            counts = payload["counts"]
            seen = payload["seen"]
            current = int(counts.get(key, 0))
            already = problem_id in seen.get(key, [])
            if not already and current < goal:
                current += 1
                counts[key] = current
                seen.setdefault(key, []).append(problem_id)
                _atomic_write(self.progress_path, payload)
            return current


def _progress_key(kb_name: str, topic: str) -> str:
    folded = " ".join(topic.casefold().split())
    return f"{kb_name.strip()}\n{folded}"[:300]


def _read_progress(path: Path) -> dict[str, int]:
    return _read_progress_payload(path)["counts"]


def _read_progress_payload(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"counts": {}, "seen": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"counts": {}, "seen": {}}
    if not isinstance(data, dict):
        return {"counts": {}, "seen": {}}
    counts = data.get("counts") if isinstance(data.get("counts"), dict) else {}
    seen = data.get("seen") if isinstance(data.get("seen"), dict) else {}
    return {"counts": counts, "seen": seen}
