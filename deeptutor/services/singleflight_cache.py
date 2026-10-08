"""Small in-process TTL cache with one async producer per key."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import time
from typing import Generic, TypeVar

K = TypeVar("K")
V = TypeVar("V")


class AsyncSingleFlightTTLCache(Generic[K, V]):
    """Bounded insertion-ordered cache plus concurrent request coalescing."""

    def __init__(
        self,
        *,
        limit: int,
        ttl_seconds: float,
        value_timestamp: Callable[[V], float],
        now: Callable[[], float] = time.time,
    ) -> None:
        if limit < 1:
            raise ValueError("limit must be positive")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self.limit = limit
        self.ttl_seconds = ttl_seconds
        self.value_timestamp = value_timestamp
        self.now = now
        self.values: dict[K, V] = {}
        self.inflight: dict[K, asyncio.Task[V]] = {}

    def recall(self, key: K) -> V | None:
        value = self.values.get(key)
        if value is None:
            return None
        if self.now() - self.value_timestamp(value) > self.ttl_seconds:
            self.values.pop(key, None)
            return None
        return value

    def remember(self, key: K, value: V) -> None:
        self.values[key] = value
        overflow = len(self.values) - self.limit
        if overflow > 0:
            for stale in list(self.values)[:overflow]:
                self.values.pop(stale, None)

    async def get_or_create(
        self,
        key: K,
        factory: Callable[[], Awaitable[V]],
        *,
        cache_when: Callable[[V], bool] = lambda _value: True,
    ) -> V:
        cached = self.recall(key)
        if cached is not None:
            return cached

        pending = self.inflight.get(key)
        if pending is None or pending.done():

            async def produce() -> V:
                """Own cache insertion and cleanup even when every waiter leaves."""
                try:
                    value = await factory()
                    if cache_when(value):
                        self.remember(key, value)
                    return value
                finally:
                    if self.inflight.get(key) is asyncio.current_task():
                        self.inflight.pop(key, None)

            def consume_failure(task: asyncio.Task[V]) -> None:
                """Retrieve failures when no request remains to await the task."""
                if not task.cancelled():
                    task.exception()

            pending = asyncio.create_task(produce())
            self.inflight[key] = pending
            pending.add_done_callback(consume_failure)
        return await asyncio.shield(pending)


__all__ = ["AsyncSingleFlightTTLCache"]
