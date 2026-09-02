"""Explicit guardian-to-learner authorization records."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import threading
from typing import Any
from uuid import uuid4

from deeptutor.services.file_io import atomic_write_text

from .identity import get_user_by_id
from .paths import SYSTEM_ROOT

GUARDIANS_FILE = SYSTEM_ROOT / "guardians.json"
GUARDIAN_PERMISSIONS = frozenset(
    {"assign_materials", "manage_restrictions", "view_reports", "reset_credentials"}
)

_GUARDIANS_WRITE_LOCK = threading.Lock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_record(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    relationship_id = str(value.get("id") or f"ga_{uuid4().hex}")
    guardian_user_id = str(value.get("guardian_user_id") or "")
    learner_user_id = str(value.get("learner_user_id") or "")
    if not guardian_user_id or not learner_user_id:
        return None
    raw_permissions = value.get("permissions") if isinstance(value.get("permissions"), list) else []
    permissions = sorted(
        {
            str(item)
            for item in raw_permissions
            if isinstance(raw_permissions, list) and str(item) in GUARDIAN_PERMISSIONS
        }
    )
    revoked_at = value.get("revoked_at")
    return {
        "id": relationship_id,
        "guardian_user_id": guardian_user_id,
        "learner_user_id": learner_user_id,
        "permissions": permissions,
        "granted_at": str(value.get("granted_at") or _utc_now()),
        "revoked_at": str(revoked_at) if revoked_at else None,
        "revoked_by": str(value.get("revoked_by") or "") if revoked_at else "",
        "revocation_reason": (str(value.get("revocation_reason") or "") if revoked_at else ""),
    }


def _load_records() -> list[dict[str, Any]]:
    try:
        loaded = json.loads(GUARDIANS_FILE.read_text(encoding="utf-8"))
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
    GUARDIANS_FILE.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(GUARDIANS_FILE, json.dumps(records, indent=2, ensure_ascii=False))


def _require_ordinary_user(user_id: str, label: str) -> None:
    user_record = get_user_by_id(user_id)
    if user_record is None:
        raise ValueError(f"Unknown {label} user id: {user_id}")
    _username, record = user_record
    if str(record.get("role") or "user") == "admin":
        raise ValueError(f"Admin users cannot be {label}s.")
    preset = str(record.get("preset") or "standard")
    if label == "learner" and preset != "learner":
        raise ValueError("Guardian authorization requires a learner account.")
    if label == "guardian" and preset == "learner":
        raise ValueError("Learner accounts cannot be guardians.")


def authorize_guardian(
    guardian_user_id: str,
    learner_user_id: str,
    permissions: set[str] | frozenset[str] | list[str],
) -> dict[str, Any]:
    _require_ordinary_user(guardian_user_id, "guardian")
    _require_ordinary_user(learner_user_id, "learner")
    if guardian_user_id == learner_user_id:
        raise ValueError("A user cannot guard their own account.")
    allowed = sorted({item for item in permissions if item in GUARDIAN_PERMISSIONS})
    if not allowed:
        raise ValueError("At least one guardian permission is required.")

    with _GUARDIANS_WRITE_LOCK:
        records = _load_records()
        if any(
            record["guardian_user_id"] == guardian_user_id
            and record["learner_user_id"] == learner_user_id
            and record["revoked_at"] is None
            for record in records
        ):
            raise ValueError("This guardian is already authorized for the learner.")
        if any(
            record["guardian_user_id"] == learner_user_id
            and record["learner_user_id"] == guardian_user_id
            and record["revoked_at"] is None
            for record in records
        ):
            raise ValueError("A learner cannot guard their active guardian.")
        record = {
            "id": f"ga_{uuid4().hex}",
            "guardian_user_id": guardian_user_id,
            "learner_user_id": learner_user_id,
            "permissions": allowed,
            "granted_at": _utc_now(),
            "revoked_at": None,
            "revoked_by": "",
            "revocation_reason": "",
        }
        records.append(record)
        _write_records(records)
    return deepcopy(record)


def list_relationships(
    *,
    guardian_user_id: str | None = None,
    learner_user_id: str | None = None,
    include_revoked: bool = False,
) -> list[dict[str, Any]]:
    return [
        deepcopy(record)
        for record in _load_records()
        if (include_revoked or record["revoked_at"] is None)
        and (guardian_user_id is None or record["guardian_user_id"] == guardian_user_id)
        and (learner_user_id is None or record["learner_user_id"] == learner_user_id)
    ]


def relationship_by_id(relationship_id: str) -> dict[str, Any] | None:
    for record in _load_records():
        if record["id"] == relationship_id:
            return deepcopy(record)
    return None


def revoke_guardian(
    relationship_id: str,
    *,
    revoked_by: str,
    reason: str = "",
) -> dict[str, Any] | None:
    with _GUARDIANS_WRITE_LOCK:
        records = _load_records()
        for record in records:
            if record["id"] != relationship_id:
                continue
            if record["revoked_at"] is None:
                record["revoked_at"] = _utc_now()
                record["revoked_by"] = revoked_by
                record["revocation_reason"] = reason
                _write_records(records)
            return deepcopy(record)
    return None


def revoke_relationships_for_user(user_id: str, *, reason: str) -> int:
    with _GUARDIANS_WRITE_LOCK:
        records = _load_records()
        changed = 0
        now = _utc_now()
        for record in records:
            if user_id not in (
                record["guardian_user_id"],
                record["learner_user_id"],
            ):
                continue
            if record["revoked_at"] is not None:
                continue
            record["revoked_at"] = now
            record["revoked_by"] = "system"
            record["revocation_reason"] = reason
            changed += 1
        if changed:
            _write_records(records)
    return changed


def guardian_can_access(
    guardian_user_id: str,
    learner_user_id: str,
    permission: str,
) -> bool:
    try:
        # Account presets may change after authorization. Re-check the current
        # identities so an old relationship never turns a former learner (or a
        # learner promoted into the guardian role) into an authorization path.
        _require_ordinary_user(guardian_user_id, "guardian")
        _require_ordinary_user(learner_user_id, "learner")
    except ValueError:
        return False
    return any(
        record["guardian_user_id"] == guardian_user_id
        and record["learner_user_id"] == learner_user_id
        and record["revoked_at"] is None
        and permission in record["permissions"]
        for record in _load_records()
    )


__all__ = [
    "GUARDIANS_FILE",
    "GUARDIAN_PERMISSIONS",
    "authorize_guardian",
    "guardian_can_access",
    "list_relationships",
    "relationship_by_id",
    "revoke_guardian",
    "revoke_relationships_for_user",
]
