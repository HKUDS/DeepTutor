"""Backend-agnostic session store contract and factory.

The structural contract itself lives in :mod:`deeptutor.services.session.protocol`
as ``SessionStoreProtocol``; ``SessionStore`` is re-exported here as a stable
alias for backend implementations and tests. This module owns the pluggable
backend *registry* so additional stores (e.g. Postgres) can register themselves
and be selected via the ``DEEPTUTOR_SESSION_BACKEND`` environment variable.
"""

from __future__ import annotations

from collections.abc import Callable
import os
from typing import Any

from .protocol import SessionStoreProtocol

# Backward-compatible alias. The canonical, richer contract is
# ``SessionStoreProtocol``; both SQLite and PocketBase satisfy it.
SessionStore = SessionStoreProtocol

BackendFactory = Callable[..., SessionStoreProtocol]

_BACKEND_REGISTRY: dict[str, BackendFactory] = {}


def register_session_store_backend(name: str, factory: BackendFactory) -> None:
    """Register a named session-store backend factory."""
    resolved = str(name or "").strip().lower()
    if not resolved:
        raise ValueError("Backend name is required")
    _BACKEND_REGISTRY[resolved] = factory


def clear_session_store_cache() -> None:
    """Reset cached backend instances (mainly for tests)."""
    from .sqlite_store import clear_sqlite_session_store_cache

    clear_sqlite_session_store_cache()


def _load_builtin_backend(backend_name: str) -> None:
    """Import a built-in backend module so it self-registers on first use."""
    if backend_name in _BACKEND_REGISTRY:
        return
    if backend_name == "sqlite":
        from . import sqlite_store  # noqa: F401
    elif backend_name == "pocketbase":
        from . import pocketbase_store  # noqa: F401


def _resolve_backend_name(backend: str | None = None) -> str:
    """Resolve the backend: explicit arg > env var > PocketBase auto-detect > sqlite."""
    explicit = str(backend or os.getenv("DEEPTUTOR_SESSION_BACKEND") or "").strip().lower()
    if explicit:
        return explicit

    from deeptutor.services.pocketbase_client import is_pocketbase_enabled

    if is_pocketbase_enabled():
        return "pocketbase"
    return "sqlite"


def _create_session_store(backend_name: str, **kwargs: Any) -> SessionStoreProtocol:
    _load_builtin_backend(backend_name)
    factory = _BACKEND_REGISTRY.get(backend_name)
    if factory is None:
        available = ", ".join(sorted(_BACKEND_REGISTRY)) or "<none>"
        raise ValueError(f"Unsupported session backend: {backend_name!r} (available: {available})")
    return factory(**kwargs)


def get_session_store(backend: str | None = None, **kwargs: Any) -> SessionStoreProtocol:
    """Return the active session store backend.

    The backend is resolved from ``backend`` (or ``DEEPTUTOR_SESSION_BACKEND``),
    falling back to PocketBase when configured and SQLite otherwise. Per-backend
    instance caching is owned by each factory (e.g. SQLite caches per resolved
    database path to preserve multi-user isolation), so this function does not
    cache results itself.
    """
    return _create_session_store(_resolve_backend_name(backend), **kwargs)


__all__ = [
    "BackendFactory",
    "SessionStore",
    "clear_session_store_cache",
    "get_session_store",
    "register_session_store_backend",
]
