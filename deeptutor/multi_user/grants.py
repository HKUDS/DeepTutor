"""Logical resource grants for non-admin users."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from .identity import get_user_by_id
from .paths import SYSTEM_ROOT, ensure_system_dirs

GRANTS_DIR = SYSTEM_ROOT / "grants"


def empty_grant(user_id: str) -> dict[str, Any]:
    return {
        "version": 1,
        "user_id": user_id,
        "models": {"llm": [], "embedding": [], "search": []},
        "knowledge_bases": [],
        "skills": [],
        "spaces": [],
    }


def grant_path(user_id: str) -> Path:
    ensure_system_dirs()
    return GRANTS_DIR / f"{user_id}.json"


def normalize_grant(user_id: str, payload: dict[str, Any] | None) -> dict[str, Any]:
    base = empty_grant(user_id)
    if not isinstance(payload, dict):
        return base
    base["version"] = int(payload.get("version") or 1)
    base["user_id"] = user_id
    models = payload.get("models") if isinstance(payload.get("models"), dict) else {}
    for service in ("llm", "embedding", "search"):
        items = models.get(service) if isinstance(models, dict) else []
        if not isinstance(items, list):
            items = []
        base["models"][service] = [dict(item) for item in items if isinstance(item, dict)]
    for key in ("knowledge_bases", "skills", "spaces"):
        values = payload.get(key) if isinstance(payload.get(key), list) else []
        base[key] = [dict(item) for item in values if isinstance(item, dict)]
    return base


def load_grant(user_id: str) -> dict[str, Any]:
    path = grant_path(user_id)
    if not path.exists():
        return empty_grant(user_id)
    try:
        return normalize_grant(user_id, json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return empty_grant(user_id)


def save_grant(user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    user_record = get_user_by_id(user_id)
    if user_record is None:
        raise ValueError(f"Unknown user id: {user_id}")
    _username, record = user_record
    if str(record.get("role") or "user") == "admin":
        raise ValueError("Admin users use the main workspace and cannot receive assignments.")
    grant = normalize_grant(user_id, payload)
    validate_grant(grant)
    path = grant_path(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(grant, indent=2, ensure_ascii=False), encoding="utf-8")
    return grant


def validate_grant(grant: dict[str, Any]) -> None:
    """Reject accidental secret/path material in grants.

    Grants carry logical ids only. Runtime resolution happens server-side.
    """
    forbidden = {"api_key", "secret", "password", "token", "path", "base_url"}

    def walk(value: Any, trail: str = "grant") -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                lowered = str(key).lower()
                if lowered in forbidden or lowered.endswith("_key"):
                    raise ValueError(f"Grants must not contain secret/path field: {trail}.{key}")
                walk(child, f"{trail}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{trail}[{index}]")

    walk(grant)


def public_grant(user_id: str) -> dict[str, Any]:
    return deepcopy(load_grant(user_id))
