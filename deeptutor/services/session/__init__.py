"""Unified repository-backed session management."""

from .protocol import SessionStoreProtocol
from .sqlite_store import (
    SQLiteSessionStore,
    get_sqlite_session_store,
    make_imported_session_id,
)
from .turn_runtime import TurnRuntimeManager, get_turn_runtime_manager

_pocketbase_store_instances: dict[str, SessionStoreProtocol] = {}


def get_session_store() -> SessionStoreProtocol:
    """
    Return the active session store backend.

    When integrations.pocketbase_url is configured, returns a
    PocketBaseSessionStore. Otherwise falls back to the local
    SQLiteSessionStore (default, zero-config behaviour).
    """
    from deeptutor.services.pocketbase_client import is_pocketbase_enabled

    if is_pocketbase_enabled():
        from deeptutor.services.config import load_integrations_settings

        from .pocketbase_store import PocketBaseSessionStore
        from .scope import pocketbase_scope

        url = str(load_integrations_settings().get("pocketbase_url") or "").rstrip("/")
        scope = pocketbase_scope(url)
        if scope.cache_key not in _pocketbase_store_instances:
            store = PocketBaseSessionStore()
            store.store_scope = scope
            _pocketbase_store_instances[scope.cache_key] = store
        return _pocketbase_store_instances[scope.cache_key]
    return get_sqlite_session_store()


__all__ = [
    "SessionStoreProtocol",
    "SQLiteSessionStore",
    "TurnRuntimeManager",
    "get_session_store",
    "get_sqlite_session_store",
    "get_turn_runtime_manager",
    "make_imported_session_id",
]
