"""Low-latency wake-up channel for durable Mastery Topic events.

SQLite remains the replay authority.  This hub only tells connected clients
that a committed topic changed so they can read the durable event tail and
refresh the map immediately.  Publishing is synchronous and thread-safe,
which lets learning transactions running inside ``asyncio.to_thread`` wake an
uvicorn WebSocket loop without owning that loop.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import itertools
import threading


@dataclass(frozen=True)
class TopicSignal:
    path_id: str
    revision: int
    reason: str
    sequence: int


class TopicSubscription:
    def __init__(
        self,
        hub: "MasteryTopicEventHub",
        path_id: str,
        *,
        scope: str,
    ) -> None:
        self._hub = hub
        self.path_id = path_id
        self.scope = scope
        # A wake-up is only a hint to replay SQLite. Keeping the newest signal
        # is sufficient and prevents a slow/background tab from accumulating
        # an unbounded in-memory queue.
        self.queue: asyncio.Queue[TopicSignal] = asyncio.Queue(maxsize=1)
        self.loop = asyncio.get_running_loop()
        self._closed = False
        self._hub._add(self)

    async def get(self) -> TopicSignal:
        return await self.queue.get()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._hub._remove(self)


class MasteryTopicEventHub:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._subscriptions: dict[tuple[str, str], set[TopicSubscription]] = {}
        self._sequence = itertools.count(1)

    @staticmethod
    def _key(scope: str, path_id: str) -> tuple[str, str]:
        return str(scope or "default"), str(path_id)

    def subscribe(self, path_id: str, *, scope: str = "default") -> TopicSubscription:
        return TopicSubscription(self, str(path_id), scope=str(scope or "default"))

    def _add(self, subscription: TopicSubscription) -> None:
        with self._lock:
            key = self._key(subscription.scope, subscription.path_id)
            self._subscriptions.setdefault(key, set()).add(subscription)

    def _remove(self, subscription: TopicSubscription) -> None:
        with self._lock:
            key = self._key(subscription.scope, subscription.path_id)
            group = self._subscriptions.get(key)
            if not group:
                return
            group.discard(subscription)
            if not group:
                self._subscriptions.pop(key, None)

    def publish(
        self,
        path_id: str,
        revision: int,
        reason: str = "topic.changed",
        *,
        scope: str = "default",
    ) -> None:
        with self._lock:
            signal = TopicSignal(
                path_id=str(path_id),
                revision=max(0, int(revision)),
                reason=str(reason or "topic.changed"),
                sequence=next(self._sequence),
            )
            subscriptions = list(self._subscriptions.get(self._key(scope, signal.path_id), ()))
        for subscription in subscriptions:
            if subscription.loop.is_closed():
                subscription.close()
                continue
            try:
                subscription.loop.call_soon_threadsafe(
                    self._deliver_latest,
                    subscription,
                    signal,
                )
            except RuntimeError:
                subscription.close()

    @staticmethod
    def _deliver_latest(subscription: TopicSubscription, signal: TopicSignal) -> None:
        if subscription._closed:
            return
        if subscription.queue.full():
            subscription.queue.get_nowait()
        subscription.queue.put_nowait(signal)


mastery_topic_event_hub = MasteryTopicEventHub()


def publish_topic_signal(
    path_id: str,
    revision: int,
    reason: str = "topic.changed",
    *,
    scope: str = "default",
) -> None:
    mastery_topic_event_hub.publish(path_id, revision, reason, scope=scope)


__all__ = [
    "MasteryTopicEventHub",
    "TopicSignal",
    "TopicSubscription",
    "mastery_topic_event_hub",
    "publish_topic_signal",
]
