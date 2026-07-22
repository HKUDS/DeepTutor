"""
Local store for skill-hub publish credentials
==============================================

Per-hub bearer tokens minted by ``skill login`` (browser OAuth) and consumed by
``skill publish`` / ``skill update``. Kept in the settings dir as
``skill_hub_auth.json`` with ``0600`` perms — separate from ``skill_hubs.json``
(hub endpoints, shareable) because tokens are secrets.

Resolution order at publish time stays: explicit ``--token`` → env
(``DEEPTUTOR_HUB_TOKEN`` / ``EDUHUB_TOKEN``) → this store.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from deeptutor.services.path_service import get_path_service

logger = logging.getLogger(__name__)

_AUTH_SETTINGS_FILE = "skill_hub_auth"


def _auth_path() -> Path | None:
    try:
        path = get_path_service().get_settings_file(_AUTH_SETTINGS_FILE)
    except Exception:
        return None
    return path if isinstance(path, Path) else None


def _load() -> dict[str, Any]:
    path = _auth_path()
    if path is None or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("skill_hub_auth settings file is unreadable; ignoring it")
        return {}
    return data if isinstance(data, dict) else {}


def get_stored_token(hub: str) -> str | None:
    """The saved bearer token for ``hub``, or None."""
    entry = (_load().get("tokens") or {}).get(hub)
    if isinstance(entry, dict):
        token = str(entry.get("token") or "").strip()
        return token or None
    return None


def get_stored_identity(hub: str) -> dict[str, Any] | None:
    """The saved login/name snapshot for ``hub`` (for ``whoami``-style display)."""
    entry = (_load().get("tokens") or {}).get(hub)
    return entry if isinstance(entry, dict) else None


def store_token(
    hub: str,
    token: str,
    *,
    login: str | None = None,
    name: str | None = None,
) -> None:
    """Persist (and overwrite) the token for ``hub`` with ``0600`` perms."""
    path = _auth_path()
    if path is None:
        raise RuntimeError("No settings directory available to store the token.")
    data = _load()
    tokens = data.get("tokens")
    if not isinstance(tokens, dict):
        tokens = {}
        data["tokens"] = tokens
    tokens[hub] = {"token": token, "login": login, "name": name}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def clear_token(hub: str) -> bool:
    """Remove the saved token for ``hub``; returns whether one was present."""
    path = _auth_path()
    if path is None or not path.exists():
        return False
    data = _load()
    tokens = data.get("tokens")
    if not isinstance(tokens, dict) or hub not in tokens:
        return False
    del tokens[hub]
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return True


__all__ = ["clear_token", "get_stored_identity", "get_stored_token", "store_token"]
