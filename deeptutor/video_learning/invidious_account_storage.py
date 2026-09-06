"""Owner-private persistence for Invidious account authorization.

This module owns filesystem layout, permissions, atomic publication, and the
one-time pending-flow claim.  It deliberately knows nothing about HTTP or the
authorization workflow that consumes the records.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
import time
from typing import Any

from deeptutor.multi_user.paths import owner_secrets_dir

_SECRETS_SUBDIR = ("private", "video-learning-invidious")


@dataclass(frozen=True, slots=True)
class PendingFlow:
    owner_id: str
    api_base_url: str
    callback_url: str
    expires_at: float


def asset_dir(owner_id: str) -> Path:
    path = owner_secrets_dir(owner_id)
    for part in _SECRETS_SUBDIR:
        path = path / part
        path.mkdir(parents=True, exist_ok=True)
        os.chmod(path, stat.S_IRWXU)
    return path


def account_path(owner_id: str) -> Path:
    return asset_dir(owner_id) / "account.json"


def pending_dir(owner_id: str) -> Path:
    path = asset_dir(owner_id) / "pending"
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, stat.S_IRWXU)
    return path


def flow_path(owner_id: str, state: str) -> Path:
    # State never becomes a path segment. Besides avoiding traversal hazards,
    # hashing keeps a filesystem backup from disclosing a still-live callback
    # state to someone who can list filenames but not read owner-private files.
    digest = hashlib.sha256(state.encode("utf-8")).hexdigest()
    return pending_dir(owner_id) / f"{digest}.json"


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def write_private_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            stat.S_IRUSR | stat.S_IWUSR,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def pending_flow(path: Path) -> PendingFlow | None:
    payload = read_json(path)
    owner_id = payload.get("owner_id")
    api_base_url = payload.get("api_base_url")
    callback_url = payload.get("callback_url")
    expires_at = payload.get("expires_at")
    if (
        not isinstance(owner_id, str)
        or not owner_id
        or not isinstance(api_base_url, str)
        or not api_base_url
        or not isinstance(callback_url, str)
        or not callback_url
        or not isinstance(expires_at, (int, float))
    ):
        return None
    return PendingFlow(
        owner_id=owner_id,
        api_base_url=api_base_url,
        callback_url=callback_url,
        expires_at=float(expires_at),
    )


def purge_expired(owner_id: str, now: float | None = None) -> None:
    current = time.time() if now is None else now
    for path in pending_dir(owner_id).glob("*.json"):
        flow = pending_flow(path)
        if flow is None or flow.owner_id != owner_id or flow.expires_at <= current:
            path.unlink(missing_ok=True)


def replace_pending_flow(*, state: str, flow: PendingFlow) -> None:
    """Publish one flow after invalidating older flows for the same instance."""
    for path in pending_dir(flow.owner_id).glob("*.json"):
        existing = pending_flow(path)
        if (
            existing is None
            or existing.owner_id != flow.owner_id
            or existing.api_base_url == flow.api_base_url
        ):
            path.unlink(missing_ok=True)
    write_private_json(
        flow_path(flow.owner_id, state),
        {"version": 1, **asdict(flow)},
    )


def consume_pending_flow(owner_id: str, state: str) -> PendingFlow | None:
    if not state:
        return None
    source = flow_path(owner_id, state)
    claim = source.with_name(f".{source.name}.{secrets.token_hex(8)}.claim")
    try:
        # Same-filesystem rename is the one-time claim. It works across Uvicorn
        # workers and across restarts, unlike a process-local dictionary.
        source.rename(claim)
    except FileNotFoundError:
        return None
    try:
        flow = pending_flow(claim)
    finally:
        claim.unlink(missing_ok=True)
    if flow is None or flow.owner_id != owner_id or flow.expires_at <= time.time():
        return None
    return flow


def read_account(owner_id: str) -> dict[str, Any]:
    return read_json(account_path(owner_id))


def write_account(owner_id: str, payload: dict[str, Any]) -> None:
    write_private_json(account_path(owner_id), payload)


def forget_account(owner_id: str) -> None:
    account_path(owner_id).unlink(missing_ok=True)


__all__ = [
    "PendingFlow",
    "consume_pending_flow",
    "flow_path",
    "forget_account",
    "purge_expired",
    "read_account",
    "read_json",
    "replace_pending_flow",
    "write_account",
    "write_private_json",
]
