"""Lease-controlled singleton ownership of process-level background services."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
import contextlib
import logging

from deeptutor.runtime.coordination import BackgroundCommand, LeaderLease, RuntimeCoordinator

logger = logging.getLogger(__name__)

AsyncCallback = Callable[[], Awaitable[None]]
ControlCallback = Callable[[BackgroundCommand], Awaitable[None]]


class _LeadershipLost(RuntimeError):
    """Internal control-flow signal raised when the leader lease is lost."""


class BackgroundLeaderSupervisor:
    def __init__(
        self,
        coordinator: RuntimeCoordinator,
        worker_id: str,
        *,
        start_callbacks: Sequence[AsyncCallback] = (),
        stop_callbacks: Sequence[AsyncCallback] = (),
        recovery_callback: AsyncCallback | None = None,
        control_callback: ControlCallback | None = None,
        renew_interval_seconds: float = 10.0,
        recovery_interval_seconds: float = 10.0,
        election_interval_seconds: float = 1.0,
    ) -> None:
        self.coordinator = coordinator
        self.worker_id = worker_id
        self.start_callbacks = tuple(start_callbacks)
        self.stop_callbacks = tuple(stop_callbacks)
        self.recovery_callback = recovery_callback
        self.control_callback = control_callback
        self.renew_interval_seconds = max(0.01, float(renew_interval_seconds))
        self.recovery_interval_seconds = max(0.01, float(recovery_interval_seconds))
        self.election_interval_seconds = max(0.01, float(election_interval_seconds))
        self.lease: LeaderLease | None = None
        self._task: asyncio.Task[None] | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._leadership_lost = asyncio.Event()
        self._services_running = False
        self._started_service_count = 0
        self._background_cursor = "0-0"

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="background-leader")

    async def close(self) -> None:
        task = self._task
        self._task = None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await self._stop_services()
        await self._stop_heartbeat()
        if self.lease is not None:
            with contextlib.suppress(Exception):
                await self.coordinator.release_leader(self.lease)
            self.lease = None

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        next_recovery = 0.0
        while True:
            try:
                if self.lease is None:
                    self.lease = await self.coordinator.acquire_leader(self.worker_id)
                    if self.lease is None:
                        await asyncio.sleep(self.election_interval_seconds)
                        continue
                    self._start_heartbeat()
                    await self._while_leader(self._start_services())
                    next_recovery = loop.time()

                if self._leadership_lost.is_set():
                    raise _LeadershipLost
                await self._while_leader(self._drain_background_commands())

                now = loop.time()
                if self.recovery_callback is not None and now >= next_recovery:
                    await self._while_leader(self.recovery_callback())
                    next_recovery = now + self.recovery_interval_seconds
                try:
                    await asyncio.wait_for(
                        self._leadership_lost.wait(),
                        timeout=min(
                            self.election_interval_seconds,
                            self.renew_interval_seconds / 2,
                        ),
                    )
                    raise _LeadershipLost
                except TimeoutError:
                    pass
            except asyncio.CancelledError:
                raise
            except _LeadershipLost:
                await self._lose_leadership()
            except Exception:
                logger.exception("Background leader loop failed on worker %s", self.worker_id)
                await self._lose_leadership()
                await asyncio.sleep(self.election_interval_seconds)

    async def _lose_leadership(self) -> None:
        # Stop the singleton services before another worker can take over.
        lease = self.lease
        await self._stop_services()
        await self._stop_heartbeat()
        if lease is not None:
            with contextlib.suppress(Exception):
                await self.coordinator.release_leader(lease)
        self.lease = None
        self._leadership_lost.clear()
        self._background_cursor = "0-0"

    def _start_heartbeat(self) -> None:
        self._leadership_lost.clear()
        self._heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(), name=f"background-leader-heartbeat:{self.worker_id}"
        )

    async def _stop_heartbeat(self) -> None:
        task = self._heartbeat_task
        self._heartbeat_task = None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(self.renew_interval_seconds)
            lease = self.lease
            if lease is None:
                return
            try:
                renewed = await self.coordinator.renew_leader(lease)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Background leader heartbeat failed on worker %s", self.worker_id)
                renewed = None
            if renewed is None:
                self._leadership_lost.set()
                return
            self.lease = renewed

    async def _while_leader(self, operation: Awaitable[None]) -> None:
        if self._leadership_lost.is_set():
            if asyncio.iscoroutine(operation):
                operation.close()
            raise _LeadershipLost
        operation_task = asyncio.ensure_future(operation)
        lost_task = asyncio.create_task(self._leadership_lost.wait())
        try:
            done, _ = await asyncio.wait(
                {operation_task, lost_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if lost_task in done and self._leadership_lost.is_set():
                operation_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await operation_task
                raise _LeadershipLost
            await operation_task
        finally:
            if not operation_task.done():
                operation_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await operation_task
            lost_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await lost_task

    async def _drain_background_commands(self) -> None:
        if self.control_callback is None:
            return
        rows = await self.coordinator.read_background_commands(self._background_cursor)
        for stream_id, command in rows:
            await self.control_callback(command)
            lease = self.lease
            if lease is None or not await self.coordinator.acknowledge_background_command(
                stream_id, lease
            ):
                raise _LeadershipLost
            self._background_cursor = stream_id

    async def _start_services(self) -> None:
        if self._services_running:
            return
        try:
            for callback in self.start_callbacks:
                # Count before awaiting so cancellation during a partial start still
                # invokes the matching cleanup callback.
                self._started_service_count += 1
                await callback()
        except asyncio.CancelledError:
            await self._stop_started_services()
            raise
        except Exception:
            await self._stop_started_services()
            raise
        self._services_running = True

    async def _stop_services(self) -> None:
        if not self._services_running and not self._started_service_count:
            return
        await self._stop_started_services()
        self._services_running = False

    async def _stop_started_services(self) -> None:
        stop_count = min(self._started_service_count, len(self.stop_callbacks))
        for callback in reversed(self.stop_callbacks[:stop_count]):
            with contextlib.suppress(Exception):
                await callback()
        self._started_service_count = 0


__all__ = ["BackgroundLeaderSupervisor"]
