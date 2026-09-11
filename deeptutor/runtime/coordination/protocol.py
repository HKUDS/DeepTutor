"""Port used by the application layer for process-independent turn control."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .types import BackgroundCommand, LeaderLease, TurnCommand, TurnLease


@runtime_checkable
class RuntimeCoordinator(Protocol):
    mode: str

    async def acquire_turn(
        self, turn_id: str, session_id: str, owner_id: str
    ) -> TurnLease | None: ...

    async def renew_turn(self, lease: TurnLease) -> TurnLease | None: ...

    async def release_turn(self, lease: TurnLease) -> bool: ...

    async def get_lease(self, turn_id: str) -> TurnLease | None: ...

    async def list_expired_turn_ids(self) -> list[str]: ...

    async def acknowledge_expired_turn(self, turn_id: str) -> None: ...

    async def publish_event(self, turn_id: str, event: dict[str, Any]) -> dict[str, Any]: ...

    async def read_events(self, turn_id: str, after_seq: int = 0) -> list[dict[str, Any]]: ...

    async def submit_command(
        self,
        turn_id: str,
        kind: str,
        payload: dict[str, Any] | None = None,
        *,
        command_id: str | None = None,
    ) -> TurnCommand | None: ...

    async def read_commands(
        self, turn_id: str, after_id: str = "0-0"
    ) -> list[tuple[str, TurnCommand]]: ...

    async def submit_background_command(
        self,
        kind: str,
        payload: dict[str, Any] | None = None,
        *,
        command_id: str | None = None,
    ) -> BackgroundCommand | None: ...

    async def read_background_commands(
        self, after_id: str = "0-0"
    ) -> list[tuple[str, BackgroundCommand]]: ...

    async def acknowledge_background_command(
        self, stream_id: str, lease: LeaderLease | None = None
    ) -> bool: ...

    async def acquire_leader(self, owner_id: str) -> LeaderLease | None: ...

    async def renew_leader(self, lease: LeaderLease) -> LeaderLease | None: ...

    async def release_leader(self, lease: LeaderLease) -> bool: ...

    async def leader_id(self) -> str | None: ...

    async def health(self) -> bool: ...

    async def close(self) -> None: ...


__all__ = ["RuntimeCoordinator"]
