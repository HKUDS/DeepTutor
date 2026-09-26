"""Opt-in active web conversation shared by one account's browsers.

Conversation files retain their existing actor scope. This preference is kept
under the real account id even for admins, whose legacy Partner conversation
store is shared, so one admin's browser selection cannot move another's.
"""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import re
import sys
from threading import Lock
from typing import Callable, ContextManager, Iterator
from uuid import uuid4

from deeptutor.partners.config.paths import get_partner_user_dir
from deeptutor.partners.helpers import safe_filename

_KEY_RE = re.compile(r'^[^<>"/\\|?*\x00-\x1f\x7f]{1,128}$')
_lock = Lock()


@contextmanager
def _state_lock(path: Path) -> Iterator[None]:
    """Serialize read-modify-write across backend workers as well as threads."""
    with _lock:
        lock_path = path.with_name(f".{path.name}.lock")
        with lock_path.open("a+b") as handle:
            handle.seek(0, 2)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            if sys.platform == "win32":  # pragma: no cover - Windows only
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                handle.seek(0)
                if sys.platform == "win32":  # pragma: no cover - Windows only
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def validate_session_key(session_key: str) -> str:
    """Return the session-store stem used by history and the session list."""
    key = str(session_key or "").strip()
    if not _KEY_RE.fullmatch(key):
        raise ValueError("Invalid Partner session key")
    stem = safe_filename(key)
    # Existing channel sessions can have Unicode, spaces or punctuation in
    # their listed stems. Only colon's legacy filename substitution is allowed
    # when accepting a noncanonical caller key; all other lossy aliases fail.
    if not stem or stem != key.replace(":", "_"):
        raise ValueError("Invalid Partner session key")
    return stem


def _path(partner_id: str, account_id: str) -> Path:
    return get_partner_user_dir(partner_id, account_id) / "web_continuity.json"


def _read(path: Path) -> dict[str, str | bool | None]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"enabled": False, "session_key": None}
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Partner web continuity state could not be read") from exc
    if not isinstance(data, dict) or not isinstance(data.get("enabled"), bool):
        raise RuntimeError("Partner web continuity state is invalid")
    if data["enabled"] is not True:
        return {"enabled": False, "session_key": None}
    key = data.get("session_key")
    try:
        return {"enabled": True, "session_key": validate_session_key(key)}
    except ValueError as exc:
        raise RuntimeError("Partner web continuity state is invalid") from exc


def _write(path: Path, state: dict[str, str | bool | None]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(state), encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def get_web_continuity(partner_id: str, account_id: str) -> dict[str, str | bool | None]:
    path = _path(partner_id, account_id)
    with _state_lock(path):
        return _read(path)


def set_web_continuity(
    partner_id: str,
    account_id: str,
    *,
    enabled: bool,
    session_key: str | None = None,
    idle_lock: Callable[[str], ContextManager[None]] | None = None,
) -> dict[str, str | bool | None]:
    state: dict[str, str | bool | None] = {
        "enabled": enabled,
        "session_key": validate_session_key(session_key) if enabled else None,
    }
    path = _path(partner_id, account_id)
    with _state_lock(path):
        previous = _read(path)
        old_key = previous["session_key"] if previous["enabled"] else None
        # A turn on the selected key must finish before another browser can
        # switch away or disable continuity. The nonblocking per-session lock
        # also serializes this update with a just-started web turn.
        if old_key and old_key != state["session_key"] and idle_lock is not None:
            with idle_lock(str(old_key)):
                _write(path, state)
        else:
            _write(path, state)
    return state


def move_active_web_session(
    partner_id: str,
    account_id: str,
    *,
    session_key: str,
    new_session_key: str,
    only_if_current: bool = True,
    idle_lock: Callable[[str], ContextManager[None]] | None = None,
) -> str | None:
    """Update a selected key after archive/delete/branch/resume while enabled."""
    path = _path(partner_id, account_id)
    with _state_lock(path):
        state = _read(path)
        if not state["enabled"]:
            return None
        if only_if_current:
            try:
                source_key = validate_session_key(session_key)
            except ValueError:
                return None
            if state["session_key"] != source_key:
                return None
        next_key = validate_session_key(new_session_key)
        old_key = str(state["session_key"])
        if old_key != next_key and idle_lock is not None:
            with idle_lock(old_key):
                _write(path, {"enabled": True, "session_key": next_key})
        else:
            _write(path, {"enabled": True, "session_key": next_key})
        return next_key


def fresh_web_session_key() -> str:
    return f"web-{uuid4().hex}"


__all__ = [
    "fresh_web_session_key",
    "get_web_continuity",
    "move_active_web_session",
    "set_web_continuity",
    "validate_session_key",
]
