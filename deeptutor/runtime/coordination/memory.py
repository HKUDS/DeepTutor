"""Single-process coordinator with the same semantics as the Redis adapter."""

from __future__ import annotations

import asyncio
from bisect import bisect_left, bisect_right
from collections import OrderedDict
from dataclasses import replace
import time
from typing import Any

from .types import BackgroundCommand, LeaderLease, TurnCommand, TurnLease


def _seq(row: dict[str, Any]) -> int:
    return int(row["seq"])


class MemoryCoordinator:
    """Leases, live event tails and command queues for one process.

    The live tail is only the bridge between a running turn and its
    subscribers: every replay starts from the durable journal, and once a
    turn's lease is released its tail is complete there. So a released turn's
    events and commands are dropped after ``retention_seconds`` — enough for a
    subscriber still mid-poll — instead of living until the process exits,
    which in a long-running server is every streamed delta of every turn.
    Background commands are dropped once acknowledged, and the ids kept for
    de-duplication are bounded.
    """

    mode = "memory"
    retention_seconds = 120.0
    _command_id_limit = 4096

    def __init__(self, *, lease_ttl_seconds: float = 30.0) -> None:
        self.lease_ttl_seconds = float(lease_ttl_seconds)
        self._lock = asyncio.Lock()
        self._fencing_token = 0
        self._turn_leases: dict[str, TurnLease] = {}
        self._session_turns: dict[str, str] = {}
        self._known_turns: set[str] = set()
        self._events: dict[str, list[dict[str, Any]]] = {}
        self._event_waiters: dict[str, set[asyncio.Future[None]]] = {}
        self._commands: dict[str, list[tuple[str, TurnCommand]]] = {}
        self._command_ids: dict[str, str] = {}
        self._background_commands: list[tuple[str, BackgroundCommand]] = []
        self._background_command_ids: OrderedDict[str, None] = OrderedDict()
        self._background_seq = 0
        self._background_cursor = "0-0"
        # Released turns, oldest first, with when their tail may be dropped.
        self._retired: OrderedDict[str, float] = OrderedDict()
        self._leader: LeaderLease | None = None
        self._closed = False

    def _expires_at(self) -> float:
        return time.time() + self.lease_ttl_seconds

    def _retire(self, turn_id: str) -> None:
        """Mark a turn's live tail for removal (caller holds the lock)."""
        self._retired.pop(turn_id, None)
        self._retired[turn_id] = time.monotonic() + self.retention_seconds
        self._sweep()

    def _retire_if_unleased(self, turn_id: str) -> None:
        """A write for a turn nobody holds (a late tail) must still expire."""
        if turn_id not in self._turn_leases and turn_id not in self._retired:
            self._retire(turn_id)

    def _sweep(self) -> None:
        now = time.monotonic()
        while self._retired:
            turn_id, due = next(iter(self._retired.items()))
            if due > now:
                break
            self._retired.popitem(last=False)
            if turn_id in self._turn_leases:
                continue  # taken again since — still live
            self._events.pop(turn_id, None)
            for _, command in self._commands.pop(turn_id, []):
                self._command_ids.pop(command.command_id, None)

    @staticmethod
    def _active(lease: TurnLease | LeaderLease | None) -> bool:
        return lease is not None and lease.expires_at > time.time()

    async def acquire_turn(self, turn_id: str, session_id: str, owner_id: str) -> TurnLease | None:
        async with self._lock:
            current_turn_id = self._session_turns.get(session_id)
            current = self._turn_leases.get(current_turn_id or "")
            if self._active(current):
                return None
            self._fencing_token += 1
            lease = TurnLease(
                turn_id=turn_id,
                session_id=session_id,
                owner_id=owner_id,
                fencing_token=self._fencing_token,
                expires_at=self._expires_at(),
            )
            self._turn_leases[turn_id] = lease
            self._session_turns[session_id] = turn_id
            self._known_turns.add(turn_id)
            self._retired.pop(turn_id, None)
            return lease

    async def renew_turn(self, lease: TurnLease) -> TurnLease | None:
        async with self._lock:
            current = self._turn_leases.get(lease.turn_id)
            if not self._active(current) or current is None:
                return None
            if (
                current.owner_id != lease.owner_id
                or current.fencing_token != lease.fencing_token
                or current.session_id != lease.session_id
            ):
                return None
            renewed = replace(current, expires_at=self._expires_at())
            self._turn_leases[lease.turn_id] = renewed
            return renewed

    async def release_turn(self, lease: TurnLease) -> bool:
        async with self._lock:
            current = self._turn_leases.get(lease.turn_id)
            if current is None or (
                current.owner_id != lease.owner_id or current.fencing_token != lease.fencing_token
            ):
                return False
            self._turn_leases.pop(lease.turn_id, None)
            if self._session_turns.get(lease.session_id) == lease.turn_id:
                self._session_turns.pop(lease.session_id, None)
            self._retire(lease.turn_id)
            self._wake_event_waiters(lease.turn_id)
            return True

    async def get_lease(self, turn_id: str) -> TurnLease | None:
        async with self._lock:
            lease = self._turn_leases.get(turn_id)
            return lease if self._active(lease) else None

    async def list_expired_turn_ids(self) -> list[str]:
        async with self._lock:
            return sorted(
                turn_id
                for turn_id in self._known_turns
                if not self._active(self._turn_leases.get(turn_id))
            )

    async def acknowledge_expired_turn(self, turn_id: str) -> None:
        async with self._lock:
            lease = self._turn_leases.get(turn_id)
            if self._active(lease):
                return
            self._known_turns.discard(turn_id)
            # Recovery has verified the durable terminal row. Keeping these
            # payloads forever leaks every completed conversation (#1971).
            self._events.pop(turn_id, None)
            for _, command in self._commands.pop(turn_id, []):
                self._command_ids.pop(command.command_id, None)
            if lease is not None and not self._active(lease):
                self._turn_leases.pop(turn_id, None)
                if self._session_turns.get(lease.session_id) == turn_id:
                    self._session_turns.pop(lease.session_id, None)
            if turn_id not in self._turn_leases:
                self._retire(turn_id)

    async def publish_event(self, turn_id: str, event: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            rows = self._events.setdefault(turn_id, [])
            payload = dict(event)
            seq = int(payload.get("seq") or 0)
            if seq <= 0:
                seq = (int(rows[-1]["seq"]) if rows else 0) + 1
            payload["turn_id"] = payload.get("turn_id") or turn_id
            payload["seq"] = seq
            if rows and seq <= _seq(rows[-1]):
                # A re-publish: rows are in seq order, so find it directly
                # rather than scanning a long turn's whole tail every time.
                index = bisect_left(rows, seq, key=_seq)
                existing = rows[index] if index < len(rows) else None
                if existing is not None and _seq(existing) == seq and existing == payload:
                    return dict(existing)
                raise ValueError(f"Turn event conflict: {turn_id} seq={seq}")
            rows.append(payload)
            self._retire_if_unleased(turn_id)
            self._wake_event_waiters(turn_id)
            return dict(payload)

    def _wake_event_waiters(self, turn_id: str) -> None:
        # Called under _lock. Futures carry notifications, never event bodies;
        # the journal/ordered tail remains the source of truth for replay.
        for waiter in self._event_waiters.pop(turn_id, ()):
            if not waiter.done():
                waiter.set_result(None)

    async def wait_for_events(self, turn_id: str, after_seq: int, *, timeout: float = 1.0) -> None:
        """Wait without polling, including publication between read and wait."""
        async with self._lock:
            rows = self._events.get(turn_id, [])
            if self._closed or (rows and _seq(rows[-1]) > after_seq):
                return
            waiter = asyncio.get_running_loop().create_future()
            self._event_waiters.setdefault(turn_id, set()).add(waiter)
        try:
            await asyncio.wait_for(waiter, timeout=timeout)
        except TimeoutError:
            pass  # Periodic durable-state/lease checks still detect recovery.
        finally:
            async with self._lock:
                waiters = self._event_waiters.get(turn_id)
                if waiters is not None:
                    waiters.discard(waiter)
                    if not waiters:
                        self._event_waiters.pop(turn_id, None)

    async def read_events(self, turn_id: str, after_seq: int = 0) -> list[dict[str, Any]]:
        async with self._lock:
            self._sweep()
            rows = self._events.get(turn_id, [])
            start = bisect_right(rows, max(0, int(after_seq)), key=_seq)
            return [dict(event) for event in rows[start:]]

    async def submit_command(
        self,
        turn_id: str,
        kind: str,
        payload: dict[str, Any] | None = None,
        *,
        command_id: str | None = None,
    ) -> TurnCommand | None:
        command = TurnCommand.create(turn_id, kind, payload, command_id=command_id)
        async with self._lock:
            if command.command_id in self._command_ids:
                return None
            self._command_ids[command.command_id] = turn_id
            rows = self._commands.setdefault(turn_id, [])
            stream_id = f"{len(rows) + 1}-0"
            rows.append((stream_id, command))
            self._retire_if_unleased(turn_id)
            return command

    async def read_commands(
        self, turn_id: str, after_id: str = "0-0"
    ) -> list[tuple[str, TurnCommand]]:
        try:
            after = int(after_id.split("-", 1)[0])
        except (TypeError, ValueError):
            after = 0
        async with self._lock:
            return [
                (stream_id, command)
                for stream_id, command in self._commands.get(turn_id, [])
                if int(stream_id.split("-", 1)[0]) > after
            ]

    async def submit_background_command(
        self,
        kind: str,
        payload: dict[str, Any] | None = None,
        *,
        command_id: str | None = None,
    ) -> BackgroundCommand | None:
        command = BackgroundCommand.create(kind, payload, command_id=command_id)
        async with self._lock:
            if command.command_id in self._background_command_ids:
                return None
            self._background_command_ids[command.command_id] = None
            while len(self._background_command_ids) > self._command_id_limit:
                self._background_command_ids.popitem(last=False)
            self._background_seq += 1
            stream_id = f"{self._background_seq}-0"
            self._background_commands.append((stream_id, command))
            return command

    async def read_background_commands(
        self, after_id: str = "0-0"
    ) -> list[tuple[str, BackgroundCommand]]:
        def sequence(stream_id: str) -> int:
            try:
                return int(stream_id.split("-", 1)[0])
            except (TypeError, ValueError):
                return 0

        async with self._lock:
            after = max(sequence(after_id), sequence(self._background_cursor))
            return [
                (stream_id, command)
                for stream_id, command in self._background_commands
                if sequence(stream_id) > after
            ]

    async def acknowledge_background_command(
        self, stream_id: str, lease: LeaderLease | None = None
    ) -> bool:
        async with self._lock:
            if lease is not None:
                current = self._leader
                if (
                    current is None
                    or not self._active(current)
                    or current.owner_id != lease.owner_id
                    or current.fencing_token != lease.fencing_token
                ):
                    return False
            self._background_cursor = stream_id
            # Nothing at or before the cursor is ever read again.
            try:
                done = int(stream_id.split("-", 1)[0])
            except (TypeError, ValueError):
                done = 0
            self._background_commands = [
                row for row in self._background_commands if int(row[0].split("-", 1)[0]) > done
            ]
            return True

    async def acquire_leader(self, owner_id: str) -> LeaderLease | None:
        async with self._lock:
            if self._active(self._leader):
                return None
            self._fencing_token += 1
            self._leader = LeaderLease(owner_id, self._fencing_token, self._expires_at())
            return self._leader

    async def renew_leader(self, lease: LeaderLease) -> LeaderLease | None:
        async with self._lock:
            current = self._leader
            if not self._active(current) or current is None:
                return None
            if current.owner_id != lease.owner_id or current.fencing_token != lease.fencing_token:
                return None
            self._leader = replace(current, expires_at=self._expires_at())
            return self._leader

    async def release_leader(self, lease: LeaderLease) -> bool:
        async with self._lock:
            current = self._leader
            if current is None or (
                current.owner_id != lease.owner_id or current.fencing_token != lease.fencing_token
            ):
                return False
            self._leader = None
            return True

    async def leader_id(self) -> str | None:
        async with self._lock:
            return self._leader.owner_id if self._active(self._leader) and self._leader else None

    async def health(self) -> bool:
        return not self._closed

    async def close(self) -> None:
        async with self._lock:
            self._closed = True
            for turn_id in list(self._event_waiters):
                self._wake_event_waiters(turn_id)


__all__ = ["MemoryCoordinator"]
