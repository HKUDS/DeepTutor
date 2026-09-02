"""Stable process-local identity for session stores and turn runtimes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class StoreScope:
    """A storage backend as seen by one authenticated workspace owner."""

    backend: str
    resource: str
    owner_id: str

    @property
    def cache_key(self) -> str:
        return f"{self.backend}:{self.resource}:{self.owner_id}"


def current_owner_id() -> str:
    from deeptutor.multi_user.context import get_current_user

    return str(get_current_user().id or "local-admin")


def pocketbase_scope(url: str) -> StoreScope:
    return StoreScope(
        backend="pocketbase",
        resource=str(url or "").rstrip("/"),
        owner_id=current_owner_id(),
    )


def store_scope(store: Any) -> StoreScope:
    explicit = getattr(store, "store_scope", None)
    if isinstance(explicit, StoreScope):
        return explicit

    db_path = getattr(store, "db_path", None)
    if db_path is not None:
        return StoreScope(
            backend="sqlite",
            resource=str(Path(db_path).resolve()),
            owner_id=current_owner_id(),
        )

    return StoreScope(
        backend=f"custom:{type(store).__module__}.{type(store).__qualname__}",
        resource=str(getattr(store, "scope_key", "default")),
        owner_id=current_owner_id(),
    )


__all__ = ["StoreScope", "current_owner_id", "pocketbase_scope", "store_scope"]
