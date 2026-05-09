"""
Structural protocol for session stores.

Both SQLiteSessionStore and PocketBaseSessionStore satisfy this protocol,
allowing the rest of the codebase to be store-agnostic.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SessionStoreProtocol(Protocol):
    async def create_session(
        self,
        title: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]: ...

    async def get_session(self, session_id: str) -> dict[str, Any] | None: ...

    async def ensure_session(self, session_id: str | None = None) -> dict[str, Any]: ...

    async def create_turn(self, session_id: str, capability: str = "") -> dict[str, Any]: ...

    async def get_turn(self, turn_id: str) -> dict[str, Any] | None: ...

    async def get_active_turn(self, session_id: str) -> dict[str, Any] | None: ...

    async def list_active_turns(self, session_id: str) -> list[dict[str, Any]]: ...

    async def update_turn_status(self, turn_id: str, status: str, error: str = "") -> bool: ...

    async def append_turn_event(self, turn_id: str, event: dict[str, Any]) -> dict[str, Any]: ...

    async def get_turn_events(self, turn_id: str, after_seq: int = 0) -> list[dict[str, Any]]: ...

    async def update_session_title(self, session_id: str, title: str) -> bool: ...

    async def delete_session(self, session_id: str) -> bool: ...

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        capability: str = "",
        events: list[dict[str, Any]] | None = None,
        attachments: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int: ...

    async def delete_message(self, message_id: int | str) -> bool: ...

    async def get_last_message(
        self, session_id: str, role: str | None = None
    ) -> dict[str, Any] | None: ...

    async def get_messages(self, session_id: str) -> list[dict[str, Any]]: ...

    async def get_messages_for_context(self, session_id: str) -> list[dict[str, Any]]: ...

    async def list_sessions(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]: ...

    async def update_summary(self, session_id: str, summary: str, up_to_msg_id: int) -> bool: ...

    async def update_session_preferences(
        self, session_id: str, preferences: dict[str, Any]
    ) -> bool: ...

    async def get_session_with_messages(self, session_id: str) -> dict[str, Any] | None: ...
