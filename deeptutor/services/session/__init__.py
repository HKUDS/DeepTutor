"""
Session Management Module
=========================

Provides unified session management for all agent modules.

Usage:
    from deeptutor.services.session import BaseSessionManager

    class MySessionManager(BaseSessionManager):
        def __init__(self):
            super().__init__("my_module")

        def _get_session_id_prefix(self) -> str:
            return "my_"

        def _get_default_title(self) -> str:
            return "New My Session"

        # ... implement other abstract methods
"""

from .base_session_manager import BaseSessionManager
from .protocol import SessionStoreProtocol
from .sqlite_store import SQLiteSessionStore, get_sqlite_session_store
from .store import (
    SessionStore,
    clear_session_store_cache,
    get_session_store,
    register_session_store_backend,
)
from .turn_runtime import TurnRuntimeManager, get_turn_runtime_manager

__all__ = [
    "BaseSessionManager",
    "SessionStoreProtocol",
    "SQLiteSessionStore",
    "SessionStore",
    "TurnRuntimeManager",
    "clear_session_store_cache",
    "get_session_store",
    "get_sqlite_session_store",
    "get_turn_runtime_manager",
    "register_session_store_backend",
]
