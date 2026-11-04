"""Explicit group records: an administrative container with a scoped lead.

A group is deliberately **not** a role. The lead stays an ordinary user; the
only authority a group grants is over the accounts listed in it, so a mistake
here widens one roster instead of promoting somebody. That is also why admins
are refused as leads or members: they already own the instance, and letting an
admin account sit inside a group would turn scoped oversight into a path back
to the admin surface.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import threading
from typing import Any, Iterable
import unicodedata
from uuid import uuid4

from deeptutor.services.file_io import atomic_write_text

from .identity import get_user_by_id
from .paths import SYSTEM_ROOT

GROUPS_FILE = SYSTEM_ROOT / "groups.json"
MAX_NAME_LENGTH = 64
MAX_MEMBERS = 200

_GROUPS_WRITE_LOCK = threading.Lock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_name(value: Any) -> str:
    name = str(value or "").strip()
    if not name or len(name) > MAX_NAME_LENGTH:
        raise ValueError(f"Group name must be 1-{MAX_NAME_LENGTH} characters")
    if any(unicodedata.category(character).startswith("C") for character in name):
        raise ValueError("Group name contains unsupported characters")
    return name


def _require_assignable_user(user_id: str, label: str) -> str:
    """Return the username for ``user_id``, refusing admins and unknown ids."""
    found = get_user_by_id(user_id)
    if found is None:
        raise ValueError(f"Unknown {label} user id: {user_id}")
    username, record = found
    if str(record.get("role") or "user") == "admin":
        raise ValueError(f"Admin users cannot be {label}s.")
    return str(username)


def _normalize_members(member_user_ids: Iterable[Any] | None, lead_user_id: str) -> list[str]:
    """Drop the lead and duplicates, then validate what is left.

    Order is preserved: the roster is a list the admin typed, and reordering it
    behind their back would make the API response surprising.
    """
    members: list[str] = []
    for raw_id in member_user_ids or []:
        user_id = str(raw_id or "").strip()
        if not user_id or user_id == lead_user_id or user_id in members:
            continue
        _require_assignable_user(user_id, "member")
        members.append(user_id)
    if len(members) > MAX_MEMBERS:
        raise ValueError(f"A group cannot hold more than {MAX_MEMBERS} members")
    return members


def _canonical_record(value: Any) -> dict[str, Any] | None:
    """Shape one stored record without consulting the user store.

    Reads must survive a roster that references a since-deleted account: the
    account stays in the record (it is evidence of what was granted) and the
    router decides how to present it.
    """
    if not isinstance(value, dict):
        return None
    lead_user_id = str(value.get("lead_user_id") or "").strip()
    if not lead_user_id:
        return None
    try:
        name = _clean_name(value.get("name"))
    except ValueError:
        return None
    raw_members = value.get("member_user_ids")
    members: list[str] = []
    if isinstance(raw_members, list):
        for item in raw_members:
            user_id = str(item or "").strip()
            if user_id and user_id != lead_user_id and user_id not in members:
                members.append(user_id)
    created_at = str(value.get("created_at") or _utc_now())
    return {
        "id": str(value.get("id") or f"g_{uuid4().hex}"),
        "name": name,
        "lead_user_id": lead_user_id,
        "member_user_ids": members,
        "created_at": created_at,
        "created_by": str(value.get("created_by") or ""),
        "updated_at": str(value.get("updated_at") or created_at),
    }


def _load_records() -> list[dict[str, Any]]:
    try:
        loaded = json.loads(GROUPS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(loaded, list):
        return []
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in loaded:
        record = _canonical_record(value)
        if record is None or record["id"] in seen:
            continue
        seen.add(record["id"])
        records.append(record)
    return records


def _write_records(records: list[dict[str, Any]]) -> None:
    GROUPS_FILE.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(GROUPS_FILE, json.dumps(records, indent=2, ensure_ascii=False))


def list_groups(
    *,
    lead_user_id: str | None = None,
    member_user_id: str | None = None,
) -> list[dict[str, Any]]:
    return [
        deepcopy(record)
        for record in _load_records()
        if (lead_user_id is None or record["lead_user_id"] == lead_user_id)
        and (member_user_id is None or member_user_id in record["member_user_ids"])
    ]


def get_group(group_id: str) -> dict[str, Any] | None:
    for record in _load_records():
        if record["id"] == group_id:
            return deepcopy(record)
    return None


def groups_led_by(user_id: str) -> list[dict[str, Any]]:
    return list_groups(lead_user_id=user_id)


def create_group(
    name: Any,
    *,
    lead_user_id: str,
    member_user_ids: Iterable[Any] | None = None,
    created_by: str = "",
) -> dict[str, Any]:
    cleaned_name = _clean_name(name)
    lead_user_id = str(lead_user_id or "").strip()
    _require_assignable_user(lead_user_id, "lead")
    members = _normalize_members(member_user_ids, lead_user_id)
    now = _utc_now()
    record = {
        "id": f"g_{uuid4().hex}",
        "name": cleaned_name,
        "lead_user_id": lead_user_id,
        "member_user_ids": members,
        "created_at": now,
        "created_by": str(created_by or ""),
        "updated_at": now,
    }
    with _GROUPS_WRITE_LOCK:
        records = _load_records()
        records.append(record)
        _write_records(records)
    return deepcopy(record)


def add_member(group_id: str, user_id: str) -> dict[str, Any] | None:
    """Append one existing account to the roster.

    Refuses admins for the same reason :func:`create_group` does: a roster that
    could contain an admin would be a route back to the admin surface.
    """
    user_id = str(user_id or "").strip()
    if not user_id:
        raise ValueError("A member user id is required")
    _require_assignable_user(user_id, "member")
    with _GROUPS_WRITE_LOCK:
        records = _load_records()
        for record in records:
            if record["id"] != group_id:
                continue
            if user_id == record["lead_user_id"]:
                raise ValueError("The group lead is already part of the group")
            if user_id in record["member_user_ids"]:
                raise ValueError("This account is already in the group")
            if len(record["member_user_ids"]) >= MAX_MEMBERS:
                raise ValueError(f"A group cannot hold more than {MAX_MEMBERS} members")
            record["member_user_ids"].append(user_id)
            record["updated_at"] = _utc_now()
            _write_records(records)
            return deepcopy(record)
    return None


def remove_member(group_id: str, user_id: str) -> dict[str, Any] | None:
    """Drop one account from the roster. The account itself is untouched."""
    with _GROUPS_WRITE_LOCK:
        records = _load_records()
        for record in records:
            if record["id"] != group_id:
                continue
            if user_id not in record["member_user_ids"]:
                return None
            record["member_user_ids"] = [
                member for member in record["member_user_ids"] if member != user_id
            ]
            record["updated_at"] = _utc_now()
            _write_records(records)
            return deepcopy(record)
    return None


def set_group_members(
    group_id: str, member_user_ids: Iterable[Any] | None
) -> dict[str, Any] | None:
    with _GROUPS_WRITE_LOCK:
        records = _load_records()
        for record in records:
            if record["id"] != group_id:
                continue
            record["member_user_ids"] = _normalize_members(member_user_ids, record["lead_user_id"])
            record["updated_at"] = _utc_now()
            _write_records(records)
            return deepcopy(record)
    return None


def delete_group(group_id: str) -> bool:
    with _GROUPS_WRITE_LOCK:
        records = _load_records()
        remaining = [record for record in records if record["id"] != group_id]
        if len(remaining) == len(records):
            return False
        _write_records(remaining)
    return True


def drop_member_everywhere(user_id: str) -> list[str]:
    """Remove an account from every roster; returns the group ids that changed.

    Promotion to admin is the case this exists for. Membership is a snapshot
    taken when the account joined, so a lead would otherwise keep authority over
    an account that is now an administrator. Refusing the action at the point of
    use (``_require_live_member``) stops the escalation; this stops the stale
    entry from existing at all.
    """
    if not user_id:
        return []
    with _GROUPS_WRITE_LOCK:
        records = _load_records()
        touched: list[str] = []
        for record in records:
            if user_id not in record["member_user_ids"]:
                continue
            record["member_user_ids"] = [
                member for member in record["member_user_ids"] if member != user_id
            ]
            record["updated_at"] = _utc_now()
            touched.append(str(record["id"]))
        if touched:
            _write_records(records)
        return touched


__all__ = [
    "GROUPS_FILE",
    "add_member",
    "drop_member_everywhere",
    "create_group",
    "delete_group",
    "get_group",
    "groups_led_by",
    "list_groups",
    "remove_member",
    "set_group_members",
]
