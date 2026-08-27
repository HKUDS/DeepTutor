"""Linking a chat-channel account to a DeepTutor account.

A partner reached over QQ or Telegram knows only a channel-local sender id.
Nothing connects that to the person's DeepTutor account, so without a link
every channel message is anonymous: it lands in the partner's shared thread
pool, which only admins can read, and the partner answers it out of the admin
workspace rather than the sender's own library and memory.

A link closes that gap. The person asks their partner for a code in the web
app, sends ``/link <code>`` to it from the chat account they want connected,
and from then on that sender id carries their identity: their conversations are
private to them and readable back in the web app, and the partner reads their
knowledge, notebooks and memory the same way it would in a browser turn.

State lives beside the partner it belongs to, in
``data/partners/<id>/channel_links.json``, and is rewritten whole under a
per-file lock so two channels redeeming at once cannot lose each other's work.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import secrets
import threading
from typing import Any

from deeptutor.partners.config.paths import get_partner_dir
from deeptutor.services.file_io import atomic_write_json

# Unambiguous when read aloud or retyped: no O/0, I/1, or similar look-alikes.
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_CODE_LENGTH = 6
_CODE_TTL = timedelta(minutes=15)

_locks: dict[Path, threading.Lock] = {}
_locks_mutex = threading.Lock()


@dataclass(frozen=True, slots=True)
class LinkCode:
    code: str
    expires_at: str


def link_key(channel: str, sender_id: str) -> str:
    """The stable identifier for one account on one channel."""
    return f"{channel}:{sender_id}"


def _path(partner_id: str) -> Path:
    return get_partner_dir(partner_id) / "channel_links.json"


def _lock(path: Path) -> threading.Lock:
    with _locks_mutex:
        lock = _locks.get(path)
        if lock is None:
            lock = threading.Lock()
            _locks[path] = lock
        return lock


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _read(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"links": {}, "codes": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"links": {}, "codes": {}}
    if not isinstance(data, dict):
        return {"links": {}, "codes": {}}
    links = data.get("links")
    codes = data.get("codes")
    return {
        "links": links if isinstance(links, dict) else {},
        "codes": codes if isinstance(codes, dict) else {},
    }


def _drop_expired(state: dict[str, Any]) -> dict[str, Any]:
    now = _now()
    state["codes"] = {
        code: record
        for code, record in state["codes"].items()
        if isinstance(record, dict) and _expiry(record) > now
    }
    return state


def _expiry(record: dict[str, Any]) -> datetime:
    try:
        return datetime.fromisoformat(str(record.get("expires_at") or ""))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


def _update(partner_id: str, mutate: Any) -> Any:
    """Read, mutate and rewrite the file as one indivisible step."""
    path = _path(partner_id)
    with _lock(path):
        state = _drop_expired(_read(path))
        result = mutate(state)
        atomic_write_json(path, state)
        return result


def issue_link_code(partner_id: str, user_id: str) -> LinkCode:
    """Mint a single-use code for *user_id*, replacing any code they still hold.

    One live code per person: a second request invalidates the first, so a code
    read off a stale screen cannot link an account the user has moved on from.
    """
    code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))
    expires_at = (_now() + _CODE_TTL).isoformat()

    def mutate(state: dict[str, Any]) -> None:
        state["codes"] = {
            existing: record
            for existing, record in state["codes"].items()
            if record.get("user_id") != user_id
        }
        state["codes"][code] = {"user_id": user_id, "expires_at": expires_at}

    _update(partner_id, mutate)
    return LinkCode(code=code, expires_at=expires_at)


def redeem_link_code(partner_id: str, code: str, *, channel: str, sender_id: str) -> str | None:
    """Bind *channel*/*sender_id* to whoever holds *code*; the account id, or None.

    The code is spent whether or not the sender was already linked, and a
    sender that was linked to someone else is re-pointed — the person holding
    the code is by definition the one at the keyboard.
    """
    wanted = (code or "").strip().upper()
    if not wanted:
        return None

    def mutate(state: dict[str, Any]) -> str | None:
        record = state["codes"].pop(wanted, None)
        if not isinstance(record, dict):
            return None
        user_id = str(record.get("user_id") or "")
        if not user_id:
            return None
        state["links"][link_key(channel, sender_id)] = {
            "user_id": user_id,
            "channel": channel,
            "sender_id": sender_id,
            "linked_at": _now().isoformat(),
        }
        return user_id

    return _update(partner_id, mutate)


def linked_user_id(partner_id: str, channel: str, sender_id: str) -> str | None:
    """The account behind a channel sender, or None when it is unlinked."""
    record = _read(_path(partner_id))["links"].get(link_key(channel, sender_id))
    if not isinstance(record, dict):
        return None
    return str(record.get("user_id") or "") or None


def list_links(partner_id: str, user_id: str) -> list[dict[str, Any]]:
    """Every channel account *user_id* has linked to this partner."""
    return [
        {"key": key, **record}
        for key, record in sorted(_read(_path(partner_id))["links"].items())
        if isinstance(record, dict) and record.get("user_id") == user_id
    ]


def remove_link(partner_id: str, user_id: str, key: str) -> bool:
    """Unlink one channel account. Only its own owner may."""

    def mutate(state: dict[str, Any]) -> bool:
        record = state["links"].get(key)
        if not isinstance(record, dict) or record.get("user_id") != user_id:
            return False
        del state["links"][key]
        return True

    return bool(_update(partner_id, mutate))


def forget_partner_links(partner_id: str) -> None:
    """Drop the cached lock for a deleted partner (its file goes with it)."""
    with _locks_mutex:
        _locks.pop(_path(partner_id), None)
