"""Canonical live-event publication, batching, persistence, and replay."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from deeptutor.services.session.protocol import TurnRepository

from .protocol import RuntimeCoordinator
from .types import TurnLease


class TurnEventJournal:
    def __init__(
        self,
        coordinator: RuntimeCoordinator,
        repository: TurnRepository,
        lease: TurnLease,
        *,
        batch_size: int = 25,
        flush_interval_seconds: float = 0.25,
    ) -> None:
        self.coordinator = coordinator
        self.repository = repository
        self.lease = lease
        self.batch_size = max(1, int(batch_size))
        self.flush_interval_seconds = max(0.01, float(flush_interval_seconds))
        self._pending: list[dict[str, Any]] = []
        self._last_flush = time.monotonic()
        self._lock = asyncio.Lock()

    async def publish(self, event: dict[str, Any]) -> dict[str, Any]:
        """Publish to the shared stream before buffering for durable storage."""
        persisted = await self.coordinator.publish_event(self.lease.turn_id, event)
        async with self._lock:
            self._pending.append(persisted)
            should_flush = len(self._pending) >= self.batch_size or (
                time.monotonic() - self._last_flush >= self.flush_interval_seconds
            )
        if should_flush:
            await self.flush()
        return persisted

    async def flush(self) -> int:
        async with self._lock:
            if not self._pending:
                return 0
            pending = self._pending
            self._pending = []
        try:
            await self.repository.append_events(
                self.lease.turn_id,
                pending,
                fencing_token=self.lease.fencing_token,
            )
        except Exception:
            async with self._lock:
                self._pending = pending + self._pending
            raise
        self._last_flush = time.monotonic()
        return len(pending)

    async def flush_terminal(self) -> int:
        """Persist every shared event before a terminal transition is allowed."""
        await self.flush()
        durable = await self.repository.get_events(self.lease.turn_id)
        after_seq = max((int(event["seq"]) for event in durable), default=0)
        missing = await self.coordinator.read_events(self.lease.turn_id, after_seq)
        if missing:
            await self.repository.append_events(
                self.lease.turn_id,
                missing,
                fencing_token=self.lease.fencing_token,
            )
        return len(missing)

    async def replay(self, after_seq: int = 0) -> list[dict[str, Any]]:
        durable = await self.repository.get_events(self.lease.turn_id, after_seq)
        seen = {int(event["seq"]): event for event in durable}
        live = await self.coordinator.read_events(self.lease.turn_id, after_seq)
        for event in live:
            seq = int(event["seq"])
            existing = seen.get(seq)
            if existing is not None and not _same_event(existing, event):
                raise ValueError(f"Turn event conflict: {self.lease.turn_id} seq={seq}")
            seen[seq] = event
        return [seen[seq] for seq in sorted(seen)]


def _same_event(left: dict[str, Any], right: dict[str, Any]) -> bool:
    fields = ("type", "source", "stage", "content", "metadata", "turn_id", "seq")
    return all(left.get(field) == right.get(field) for field in fields)


__all__ = ["TurnEventJournal"]
