"""Persistent subagent session ids — continuity across DeepTutor turns.

The backend session/thread id from one consult is remembered (keyed by the chat
session + the connection) so the NEXT turn resumes the SAME local agent session:
the agent keeps the full context of everything DeepTutor — and the user, from
the sidebar — asked it earlier, instead of starting cold each turn. The consult
tool and the sidebar "message the agent directly" endpoint share this registry,
so both talk to one live session per (chat, connection).

Stored per-user under settings; entries for a connection are dropped when it is
disconnected.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from deeptutor.services.path_service import get_path_service

logger = logging.getLogger(__name__)

_FILE = "subagent_sessions.json"
_SEP = "::"


def session_key(chat_session_id: str, connection: str) -> str:
    """The registry key for one (chat session, connection) pair."""
    return f"{chat_session_id}{_SEP}{connection}"


def _path():
    return get_path_service().get_settings_file(_FILE)


def _load() -> dict[str, Any]:
    path = _path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        logger.warning("failed to read %s; ignoring", path, exc_info=True)
        return {}


def _save(data: dict[str, Any]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_session(key: str) -> str | None:
    """The remembered backend session id for *key*, or None."""
    entry = _load().get(key)
    if isinstance(entry, dict) and entry.get("session_id"):
        return str(entry["session_id"])
    return None


def remember_session(key: str, session_id: str, *, kind: str = "", cwd: str = "") -> None:
    """Persist the backend session id so the next turn resumes the same session."""
    if not session_id:
        return
    data = _load()
    data[key] = {"session_id": session_id, "kind": kind, "cwd": cwd}
    _save(data)


def forget_connection(connection: str) -> None:
    """Drop every remembered session for a connection (on disconnect)."""
    data = _load()
    suffix = f"{_SEP}{connection}"
    stale = [k for k in data if k.endswith(suffix)]
    for key in stale:
        data.pop(key, None)
    if stale:
        _save(data)


__all__ = ["session_key", "get_session", "remember_session", "forget_connection"]
