"""Generated behavior slice of the unified turn runtime."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
import contextlib
import hashlib
import inspect
import json
import logging
import time
from typing import TYPE_CHECKING, Any

from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.services.session.protocol import SessionStoreProtocol
from deeptutor.services.session.scope import store_scope

from .._turn_runtime_shared import (
    _LiveSubscriber,
    _TurnExecution,
)

if TYPE_CHECKING:
    from deeptutor.runtime.coordination import RuntimeCoordinator
    from deeptutor.services.app_update import UpdateJob

logger = logging.getLogger(__name__)


class TurnLifecycle:
    def __init__(
        self,
        store: SessionStoreProtocol | None = None,
        *,
        coordinator: RuntimeCoordinator | None = None,
        owner_id: str = "",
        turn_engine: Any | None = None,
    ) -> None:
        from deeptutor.services.session import get_session_store

        self.store = store or get_session_store()
        self.coordinator = coordinator
        self.owner_id = owner_id
        if turn_engine is None:
            from deeptutor.runtime.turn_engine import get_turn_engine

            turn_engine = get_turn_engine()
        self.turn_engine = turn_engine
        scope_digest = hashlib.sha256(
            store_scope(self.store).cache_key.encode("utf-8")
        ).hexdigest()[:16]
        self._coordination_scope = scope_digest
        self._lock = asyncio.Lock()
        self._executions: dict[str, _TurnExecution] = {}
        self._accepting_turns = True
        # Per-turn reply queues used by tools that pause the agentic
        # loop (e.g. ``ask_user``). Queue is created in ``_run_turn``
        # before the orchestrator is invoked and cleaned up in the
        # ``finally`` block, so callers of ``submit_user_reply`` see
        # ``False`` for any turn that is no longer awaiting input.
        # Each entry is a dict of shape:
        #   {"text": str, "answers": list[{"questionId": str, "text": str}] | None}
        # ``text`` is always present (flat fallback for legacy callers);
        # ``answers`` carries the structured per-question replies when the
        # frontend sends the v2 ``ask_user`` shape.
        self._reply_queues: dict[str, asyncio.Queue[dict[str, Any] | None]] = {}

    async def close(self, *, drain_timeout_seconds: float = 0.0) -> None:
        """Stop accepting work and deterministically release runtime resources."""
        async with self._lock:
            self._accepting_turns = False
            executions = list(self._executions.values())
            reply_queues = list(self._reply_queues.values())
            self._reply_queues.clear()

        tasks: list[asyncio.Task[Any]] = []
        for execution in executions:
            for subscriber in list(execution.subscribers):
                with contextlib.suppress(asyncio.QueueFull):
                    subscriber.queue.put_nowait(None)
            execution.subscribers.clear()
            if execution.task is not None and not execution.task.done():
                execution.shutdown_requested = True
                tasks.append(execution.task)
        for queue in reply_queues:
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(None)
        if tasks:
            if drain_timeout_seconds > 0:
                _done, pending = await asyncio.wait(tasks, timeout=float(drain_timeout_seconds))
            else:
                pending = set(tasks)
            for task in pending:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        async with self._lock:
            self._executions.clear()

        close_store = getattr(self.store, "close", None)
        if callable(close_store):
            result = close_store()
            if inspect.isawaitable(result):
                await result

    async def has_live_execution(self, turn_id: str) -> bool:
        """Public check for whether this process still owns the turn's runner.

        Lets transport callers (e.g. the unified WS router) avoid reaching into
        ``_lock`` / ``_executions`` directly.
        """
        return await self._has_live_execution(turn_id)

    async def has_live_executions(self) -> bool:
        """Return whether any turn is still owned by this process.

        Managed application updates use this coarse process-level signal before
        stopping the server. Placeholders without a task still count as live:
        they represent turns paused between setup and execution or awaiting a
        resume path, and interrupting either would lose learner-visible work.
        """
        async with self._lock:
            return any(
                execution.task is None or not execution.task.done()
                for execution in self._executions.values()
            )

    async def reserve_managed_update(
        self,
        reserve: Callable[[], UpdateJob],
    ) -> UpdateJob | None:
        """Atomically reserve an update only while this process is idle.

        The same lock publishes new turn ownership. Once ``reserve`` creates
        the durable update marker, later turns are rejected until the launcher
        replaces this process. A failed handoff removes that marker, allowing
        the next turn request to thaw the runtime automatically.
        """
        async with self._lock:
            if any(
                execution.task is None or not execution.task.done()
                for execution in self._executions.values()
            ):
                return None
            job = reserve()
            self._accepting_turns = False
            return job

    @staticmethod
    def _managed_update_is_active() -> bool:
        from deeptutor.services.app_update import UpdateJobStore, update_store_root

        store = UpdateJobStore(update_store_root())
        try:
            job = store.load()
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            return False
        return store.active_path.exists() and job.status in {
            "pending",
            "handoff",
            "running",
            "restarting",
        }

    def _turns_blocked_for_update_locked(self) -> bool:
        if self._accepting_turns:
            return False
        if not self._managed_update_is_active():
            self._accepting_turns = True
            return False
        return True

    async def _ensure_accepting_turns(self) -> None:
        async with self._lock:
            if self._turns_blocked_for_update_locked():
                raise RuntimeError(
                    "DeepTutor is preparing an update; try again after it reconnects"
                )

    async def _has_live_execution(self, turn_id: str) -> bool:
        """Whether this process still owns the turn's in-memory runner."""
        async with self._lock:
            execution = self._executions.get(turn_id)
            if execution is None:
                return False
            # Some tests and pause/resubscribe paths create an execution
            # placeholder without a task. Treat its presence as live so we do
            # not falsely fail a turn that is still owned by this process.
            return execution.task is None or not execution.task.done()

    async def _transition_execution(
        self,
        execution: _TurnExecution,
        status: str,
        error: str = "",
        *,
        failure_code: str = "",
        retryable: bool = False,
    ) -> bool:
        return await self.store.transition_turn(
            execution.turn_id,
            status,
            expected_status="running",
            fencing_token=(execution.lease.fencing_token if execution.lease is not None else None),
            error=error,
            failure_code=failure_code,
            retryable=retryable,
        )

    async def _coordinate_execution(self, execution: _TurnExecution) -> None:
        """Renew ownership and consume commands addressed to this worker."""
        if self.coordinator is None or execution.lease is None:
            return
        lease = execution.lease
        renew_interval = max(
            0.25,
            min(10.0, float(getattr(self.coordinator, "lease_ttl_seconds", 30.0)) / 3),
        )
        renew_at = time.monotonic() + renew_interval
        command_cursor = "0-0"
        try:
            while execution.task is None or not execution.task.done():
                commands = await self.coordinator.read_commands(
                    execution.turn_id, after_id=command_cursor
                )
                for command_cursor, command in commands:
                    if command.kind == "cancel":
                        if execution.task is not None:
                            execution.task.cancel()
                        return
                    if command.kind == "submit_user_reply":
                        await self.submit_user_reply(
                            execution.turn_id,
                            text=command.payload.get("text"),
                            answers=command.payload.get("answers"),
                        )
                    elif command.kind == "user_input":
                        from deeptutor.runtime.stream_bus import get_bus

                        bus = get_bus(execution.turn_id)
                        if bus is not None:
                            bus.submit_input(str(command.payload.get("content") or ""))
                if time.monotonic() >= renew_at:
                    renewed = await self.coordinator.renew_turn(lease)
                    if renewed is None:
                        execution.lease_lost = True
                        if execution.task is not None:
                            execution.task.cancel()
                        return
                    lease = renewed
                    execution.lease = renewed
                    renew_at = time.monotonic() + renew_interval
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Continuing without a provable lease risks split-brain. Stop the
            # Python coroutine; the leader recovery service writes the durable
            # retryable failure after Redis becomes available again.
            execution.lease_lost = True
            if execution.task is not None:
                execution.task.cancel()

    async def cancel_turn(self, turn_id: str) -> bool:
        async with self._lock:
            execution = self._executions.get(turn_id)
        if execution is None or execution.task is None or execution.task.done():
            if self.coordinator is not None:
                return False
            turn = await self.store.get_turn(turn_id)
            if turn is None or turn.get("status") != "running":
                return False
            await self.store.update_turn_status(turn_id, "cancelled", "Turn cancelled")
            return True
        execution.task.cancel()
        # Wait for the task to finish so its finally block (including save)
        # completes before the caller proceeds.
        try:
            await execution.task
        except asyncio.CancelledError:
            pass
        return True

    async def submit_user_reply(
        self,
        turn_id: str,
        text: str | None = None,
        *,
        answers: list[dict[str, Any]] | None = None,
    ) -> bool:
        """Deliver a user reply to a turn that's paused on ``ask_user``.

        Returns ``True`` if the turn was waiting and the reply was
        accepted; ``False`` if no waiter is registered (turn finished,
        was cancelled, or the model never asked).

        Accepts either ``text`` (single free-form reply, legacy single-
        question shape) or ``answers`` (list of ``{questionId, text}``
        pairs, v2 multi-question shape). Both may be passed; the
        consumer prefers structured ``answers`` when present and falls
        back to ``text`` for the legacy case. The payload is enqueued —
        the pipeline's ``await waiter()`` call unblocks on the next
        event-loop tick and substitutes the reply into the matching
        ``role=tool`` message.
        """
        queue = self._reply_queues.get(turn_id)
        if queue is None:
            return False
        payload: dict[str, Any] = {"text": text or "", "answers": answers}
        await queue.put(payload)
        return True

    async def subscribe_turn(
        self,
        turn_id: str,
        after_seq: int = 0,
    ) -> AsyncIterator[dict[str, Any]]:
        backlog = await self.store.get_turn_events(turn_id, after_seq=after_seq)
        last_seq = after_seq
        # Track whether we ever yielded a terminal event (DONE) — if the live
        # queue ends WITHOUT one (e.g. a transient send-side stall on
        # ``safe_send`` swallowed it), we synthesise one before returning so
        # the frontend's ``isStreaming`` state clears immediately rather than
        # waiting on the 45s heartbeat-timeout + reconnect catchup path.
        done_yielded = False

        def _track(item: dict[str, Any]) -> dict[str, Any]:
            nonlocal done_yielded
            if str(item.get("type") or "") == "done":
                done_yielded = True
            return item

        for item in backlog:
            last_seq = max(last_seq, int(item.get("seq") or 0))
            yield _track(item)

        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        subscriber = _LiveSubscriber(queue=queue)
        execution: _TurnExecution | None = None
        live_backlog: list[dict[str, Any]] = []
        async with self._lock:
            execution = self._executions.get(turn_id)
            if execution is not None:
                execution.subscribers.append(subscriber)
                live_backlog = [
                    item for item in execution.events if int(item.get("seq") or 0) > last_seq
                ]

        for item in live_backlog:
            seq = int(item.get("seq") or 0)
            if seq <= last_seq:
                continue
            last_seq = seq
            yield _track(item)

        catchup = []
        if execution is None:
            catchup = await self.store.get_turn_events(turn_id, after_seq=last_seq)
        for item in catchup:
            seq = int(item.get("seq") or 0)
            if seq <= last_seq:
                continue
            last_seq = seq
            yield _track(item)

        turn = await self.store.get_turn(turn_id)
        if execution is None:
            if turn is None or turn.get("status") != "running":
                # Turn already finished and we didn't see a DONE in any of the
                # persisted history above — synthesise one so the caller can
                # still close out its streaming state cleanly.
                if not done_yielded:
                    if turn is not None and str(turn.get("status") or "") == "failed":
                        error_event = self._synthesize_error_event(
                            turn_id,
                            turn,
                            seq=last_seq + 1,
                        )
                        if error_event is not None:
                            yield error_event
                            last_seq += 1
                    yield self._synthesize_done_event(
                        turn_id,
                        turn,
                        seq=last_seq + 1,
                    )
                return
            # A running turn may be owned by another worker. Subscription is a
            # read-only operation; distributed coordinators attach a live event
            # source above this local-runtime fallback.
            return
        queue_drained = False
        try:
            while True:
                item = await queue.get()
                if item is None:
                    queue_drained = True
                    break
                seq = int(item.get("seq") or 0)
                if seq <= last_seq:
                    continue
                last_seq = seq
                yield _track(item)
        finally:
            async with self._lock:
                execution = self._executions.get(turn_id)
                if execution is not None:
                    execution.subscribers = [
                        sub for sub in execution.subscribers if sub is not subscriber
                    ]
            # Safety net: if we drained the live queue (None sentinel arrived)
            # without ever yielding a DONE, the turn is over server-side but
            # the frontend wouldn't know. Read the persisted turn status one
            # more time and synthesise a terminal DONE only for genuinely
            # terminal turns so ``isStreaming`` clears without waiting on
            # the heartbeat-reconnect fallback. A running turn may be paused
            # on ``ask_user`` or may have had this subscription replaced; in
            # that case a synthetic DONE would falsely mark the turn
            # completed while the backend is still awaiting input.
            # Only a producer sentinel proves that this live stream drained.
            # Cancelling this generator is how the WS router replaces a
            # subscription during resume; synthesising from that cancellation
            # races the replacement and emits a second terminal event.
            if queue_drained and not done_yielded:
                final_turn = await self.store.get_turn(turn_id)
                final_status = str((final_turn or {}).get("status") or "").strip()
                if final_turn is None or final_status in {"failed", "cancelled", "completed"}:
                    yield self._synthesize_done_event(
                        turn_id,
                        final_turn,
                        seq=last_seq + 1,
                    )

    @staticmethod
    def _synthesize_done_event(
        turn_id: str,
        turn: dict[str, Any] | None,
        *,
        seq: int,
    ) -> dict[str, Any]:
        """Build a DONE event payload from the persisted turn status.

        Used as a recovery path when ``subscribe_turn`` finishes without
        ever observing a live or persisted DONE event for a turn that has
        nonetheless terminated server-side. Mirrors the shape of the
        events the runtime would normally publish so the frontend doesn't
        need a special code path to consume it.
        """
        status = "completed"
        error: str | None = None
        if turn is not None:
            raw_status = str(turn.get("status") or "").strip()
            if raw_status in {"failed", "cancelled", "completed"}:
                status = raw_status
            error_text = str(turn.get("error") or "").strip()
            if error_text:
                error = error_text
        metadata: dict[str, Any] = {"status": status, "synthesized": True}
        if error:
            metadata["error"] = error
        return {
            "type": "done",
            "source": "turn_runtime",
            "stage": "",
            "content": "",
            "metadata": metadata,
            "session_id": str((turn or {}).get("session_id") or ""),
            "turn_id": turn_id,
            "seq": max(1, int(seq)),
            "timestamp": time.time(),
        }

    @staticmethod
    def _synthesize_error_event(
        turn_id: str,
        turn: dict[str, Any] | None,
        *,
        seq: int,
    ) -> dict[str, Any] | None:
        """Build a terminal ERROR event from a failed persisted turn."""
        error = str((turn or {}).get("error") or "").strip()
        if not error:
            return None
        return {
            "type": "error",
            "source": "turn_runtime",
            "stage": "",
            "content": error,
            "metadata": {
                "status": "failed",
                "synthesized": True,
                "turn_terminal": True,
            },
            "session_id": str((turn or {}).get("session_id") or ""),
            "turn_id": turn_id,
            "seq": max(1, int(seq)),
            "timestamp": time.time(),
        }

    async def subscribe_session(
        self,
        session_id: str,
        after_seq: int = 0,
    ) -> AsyncIterator[dict[str, Any]]:
        active_turn = await self.store.get_active_turn(session_id)
        if active_turn is None:
            return
        async for item in self.subscribe_turn(active_turn["id"], after_seq=after_seq):
            yield item

    async def _publish_mastery_path_change(
        self,
        execution: _TurnExecution,
        *,
        capability_name: str,
        started_on: str,
        ended_on: str,
        mastery_mode: bool = False,
    ) -> None:
        """Announce a path the turn moved onto, so the client stops lying."""
        if (
            not (capability_name == "mastery_path" or mastery_mode)
            or not ended_on
            or ended_on == started_on
        ):
            return
        await self._publish_live_event(
            execution,
            StreamEvent(
                type=StreamEventType.SESSION_META,
                source="turn_runtime",
                metadata={"mastery_path_id": ended_on},
            ),
        )

    async def _publish_mastery_mode_change(
        self,
        execution: _TurnExecution,
        *,
        started_in: str,
        ended_in: str,
    ) -> None:
        """Announce a mode the tutor switched into, so the client stops lying.

        The three mode buttons above the transcript are the learner's only sign
        of which tools the tutor may reach for. A switch the tutor made itself
        already reached the conversation's stored preference, but an open
        client would keep the old one highlighted until a reload — so the tutor
        would say "I have switched to outline mode" over a header still reading
        "Study", which is the product contradicting itself out loud.
        """
        if not ended_in or ended_in == started_in:
            return
        await self._publish_live_event(
            execution,
            StreamEvent(
                type=StreamEventType.SESSION_META,
                source="turn_runtime",
                metadata={"mastery_session_mode": ended_in},
            ),
        )

    async def _publish_live_event(
        self,
        execution: _TurnExecution,
        event: StreamEvent,
    ) -> dict[str, Any]:
        if event.type == StreamEventType.DONE and not event.metadata.get("status"):
            event.metadata = {**event.metadata, "status": "completed"}
        event.session_id = execution.session_id
        event.turn_id = execution.turn_id
        payload = event.to_dict()
        if self.coordinator is not None and execution.lease is not None:
            payload = await self.coordinator.publish_event(execution.turn_id, payload)
        async with self._lock:
            current = self._executions.get(execution.turn_id, execution)
            seq = int(payload.get("seq") or 0)
            if seq <= 0:
                seq = current.next_seq
                current.next_seq += 1
                if current is not execution:
                    execution.next_seq = max(execution.next_seq, current.next_seq)
            else:
                current.next_seq = max(current.next_seq, seq + 1)
                execution.next_seq = max(execution.next_seq, seq + 1)
            payload["seq"] = seq
            current.events.append(payload)
            if current is not execution:
                execution.events.append(payload)
            subscribers = list(current.subscribers)
        if event.type == StreamEventType.DONE:
            # Never expose DONE to a process-local subscriber before the
            # complete event prefix is durable. Redis subscribers already
            # read the same canonical payload from the shared journal.
            await self._flush_buffered_events(execution)
        for subscriber in subscribers:
            with contextlib.suppress(asyncio.QueueFull):
                subscriber.queue.put_nowait(payload)
        return payload

    async def _flush_buffered_events(self, execution: _TurnExecution) -> None:
        """Persist buffered turn events after the live stream has already drained."""
        async with execution.flush_lock:
            await self._flush_buffered_events_once(execution)

    async def _flush_buffered_events_once(self, execution: _TurnExecution) -> None:
        """One serialized persistence attempt for :meth:`_flush_buffered_events`."""
        async with self._lock:
            events = list(execution.events)
        persisted_events = list(execution.persisted_events)
        pending = events[len(persisted_events) :]
        if not pending:
            execution.events_persisted = len(persisted_events) == len(events)
            execution.events_flushed = True
            return

        append_batch = getattr(self.store, "append_events", None)
        if callable(append_batch):
            try:
                persisted_batch = await append_batch(
                    execution.turn_id,
                    pending,
                    fencing_token=(
                        execution.lease.fencing_token if execution.lease is not None else None
                    ),
                )
            except ValueError as exc:
                # A turn can disappear when the session is deleted while the
                # turn task is draining post-stream persistence.
                if "Turn not found:" not in str(exc):
                    raise
                logger.warning(
                    "Skip persisting %d buffered event(s) for missing turn %s",
                    len(pending),
                    execution.turn_id,
                )
                execution.persisted_events = persisted_events
                execution.events_persisted = True
                execution.events_flushed = True
                return
            execution.persisted_events = persisted_events + list(persisted_batch)
            execution.events_persisted = len(execution.persisted_events) == len(events)
            execution.events_flushed = True
            return

        try:
            for index, payload in enumerate(pending):
                try:
                    persisted = await self.store.append_turn_event(execution.turn_id, payload)
                except ValueError as exc:
                    # A turn can disappear when the session is deleted while the turn
                    # task is draining post-stream persistence. Avoid cascading
                    # failures. The turn will not come back, so drop the whole
                    # remaining batch with one summary line instead of logging once
                    # per buffered event.
                    if "Turn not found:" not in str(exc):
                        raise
                    logger.warning(
                        "Skip persisting %d buffered event(s) for missing turn %s (first: %s)",
                        len(pending) - index,
                        execution.turn_id,
                        payload.get("type", ""),
                    )
                    break
                persisted_events.append(persisted)
        except Exception:
            # Cache a committed prefix so retries continue after it instead of
            # duplicating already persisted events on non-batching backends.
            execution.persisted_events = persisted_events
            raise
        execution.persisted_events = persisted_events
        execution.events_persisted = len(persisted_events) == len(events)
        execution.events_flushed = True
