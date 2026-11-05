"""Multiplex turn-scoped host calls over one private Node child per event loop.

The reader only routes frames. Host operations inherit the originating turn's
context, so user/workspace/model ContextVars cannot leak between concurrent turns.
There is deliberately no mid-turn fallback or retry after a worker failure.
"""

from __future__ import annotations

import asyncio
import atexit
from contextlib import suppress
import json
import os
from pathlib import Path
import shutil
from typing import Any, Protocol
import uuid

_MAX_FRAME = 48 * 1024 * 1024
_MAX_RUNS = 128
_IDLE_WORKER_SECONDS = 30.0
_clients: dict[asyncio.AbstractEventLoop, EngineClient] = {}


class Host(Protocol):
    async def invoke(self, operation: str, args: dict[str, Any], state: dict[str, Any]) -> Any: ...


class EngineUnavailableError(RuntimeError):
    """A scheduler failure must fail the turn without replaying side effects."""


class EngineClient:
    def __init__(self) -> None:
        self._process: asyncio.subprocess.Process | None = None
        self._reader: asyncio.Task[None] | None = None
        self._startup = asyncio.Lock()
        self._write_lock = asyncio.Lock()
        self._runs: dict[str, asyncio.Queue[dict[str, Any] | Exception]] = {}
        self._idle_handle: asyncio.TimerHandle | None = None
        self._closed = False

    async def _ensure_started(self) -> None:
        async with self._startup:
            if self._closed:
                raise EngineUnavailableError("TypeScript scheduler client is closed")
            self._cancel_idle_close()
            if self._process is not None and self._process.returncode is None:
                return
            if self._reader is not None:
                await self._reader
            entry = (
                Path(__file__).resolve().parents[3]
                / "packages/chat-engine/dist/src/transport/stdio.js"
            )
            node = shutil.which(os.getenv("DEEPTUTOR_NODE_EXECUTABLE", "node"))
            if node is None or not entry.is_file():
                raise EngineUnavailableError(
                    "TypeScript chat engine needs Node >=22 and a build: "
                    "cd packages/chat-engine && npm ci && npm run build. "
                    "Set DEEPTUTOR_CHAT_ENGINE=python to select the Python scheduler."
                )
            self._process = await asyncio.create_subprocess_exec(
                node,
                str(entry),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                # stdout is private protocol; do not expose child diagnostics.
                stderr=asyncio.subprocess.DEVNULL,
                limit=_MAX_FRAME,
                # The worker receives per-turn credentials through its pipe,
                # never through NODE_OPTIONS or arbitrary startup hooks.
                env={
                    key: os.environ[key]
                    for key in ("PATH", "SYSTEMROOT", "SystemRoot", "WINDIR")
                    if key in os.environ
                },
            )
            self._reader = asyncio.create_task(
                self._read(self._process), name="ts-chat-engine-reader"
            )

    async def _read(self, process: asyncio.subprocess.Process) -> None:
        assert process.stdout is not None
        try:
            while line := await process.stdout.readline():
                frame = json.loads(line)
                if not isinstance(frame, dict) or frame.get("v") != 1:
                    raise EngineUnavailableError("Invalid TypeScript scheduler protocol")
                queue = self._runs.get(str(frame.get("runId", "")))
                if queue is not None:
                    queue.put_nowait(frame)
        except (Exception, asyncio.CancelledError):
            pass
        finally:
            if process.returncode is None:
                with suppress(ProcessLookupError):
                    process.terminate()
            # A caller may start another turn as soon as it receives failure.
            # Reap first so _ensure_started cannot reuse the exiting worker.
            await process.wait()
            for queue in tuple(self._runs.values()):
                with suppress(asyncio.QueueFull):
                    queue.put_nowait(
                        EngineUnavailableError("TypeScript scheduler stopped during turn")
                    )

    async def _send(self, frame: dict[str, Any]) -> None:
        payload = (json.dumps({"v": 1, **frame}, ensure_ascii=False) + "\n").encode()
        if len(payload) > _MAX_FRAME:
            raise EngineUnavailableError("TypeScript scheduler frame exceeds limit")
        async with self._write_lock:
            process = self._process
            if process is None or process.stdin is None or process.returncode is not None:
                raise EngineUnavailableError("TypeScript scheduler is unavailable")
            try:
                process.stdin.write(payload)
                await process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError) as exc:
                raise EngineUnavailableError("TypeScript scheduler connection closed") from exc

    async def run(self, host: Host, config: dict[str, int]) -> dict[str, Any]:
        await self._ensure_started()
        if len(self._runs) >= _MAX_RUNS:
            raise EngineUnavailableError("TypeScript scheduler is at capacity")
        run_id = uuid.uuid4().hex
        queue: asyncio.Queue[dict[str, Any] | Exception] = asyncio.Queue(maxsize=4)
        self._runs[run_id] = queue
        failures: dict[str, Exception] = {}
        try:
            await self._send({"kind": "run", "runId": run_id, "config": config})
            while True:
                # Scheduler decisions are local and bounded. Provider/tool/user
                # waits happen in host.invoke below and have their own policy.
                frame = await asyncio.wait_for(queue.get(), timeout=15)
                if isinstance(frame, Exception):
                    raise frame
                kind = frame.get("kind")
                if kind == "complete":
                    return frame["state"]
                if kind == "failed":
                    original = failures.get(str(frame.get("callId", "")))
                    if original is not None:
                        raise original
                    raise EngineUnavailableError(str(frame.get("message", "Scheduler failed")))
                if kind != "call":
                    raise EngineUnavailableError("Unknown scheduler operation")
                call_id = str(frame["callId"])
                reply: dict[str, Any] = {"kind": "reply", "runId": run_id, "callId": call_id}
                try:
                    result = await self._invoke_host(host, frame)
                    reply.update(ok=True, result=result)
                except Exception as exc:
                    # Keep the original typed exception in-process. Node only
                    # needs to know whether salvage is safe after visible output.
                    from deeptutor.core.capability_protocol import CapabilityPrerequisiteError

                    failures[call_id] = exc
                    reply.update(
                        ok=False,
                        error={
                            "message": str(exc)[:4096],
                            "partialResponse": bool(getattr(exc, "partial_response", False)),
                            "fatal": isinstance(exc, CapabilityPrerequisiteError),
                        },
                    )
                await self._send(reply)
        finally:
            self._runs.pop(run_id, None)
            with suppress(Exception, asyncio.CancelledError):
                await self._send({"kind": "cancel", "runId": run_id})
            if not self._runs and not self._closed:
                self._cancel_idle_close()
                self._idle_handle = asyncio.get_running_loop().call_later(
                    _IDLE_WORKER_SECONDS, self._schedule_idle_close
                )

    async def run_native(
        self, host: Host, payload: dict[str, Any], *, kind: str = "native"
    ) -> dict[str, Any]:
        """Run model/context/tools in Node; service only explicit remaining ports.

        Per-tool calls run concurrently from this turn's ContextVars. Stream
        event calls are acknowledged after publication, providing backpressure.
        Credentials travel only in this private pipe, never process arguments.
        """
        if kind not in {"native", "history", "completion", "service"}:
            raise ValueError("Unknown native engine request")
        await self._ensure_started()
        if len(self._runs) >= _MAX_RUNS:
            raise EngineUnavailableError("TypeScript scheduler is at capacity")
        run_id = uuid.uuid4().hex
        queue: asyncio.Queue[dict[str, Any] | Exception] = asyncio.Queue(maxsize=64)
        self._runs[run_id] = queue
        operations: set[asyncio.Task[None]] = set()

        async def respond(frame: dict[str, Any]) -> None:
            reply = {"kind": "reply", "runId": run_id, "callId": frame["callId"]}
            try:
                reply.update(ok=True, result=await self._invoke_host(host, frame))
            except Exception as exc:
                reply.update(ok=False, error={"message": str(exc)[:4096], "partialResponse": True})
            try:
                await self._send(reply)
            except Exception as exc:
                with suppress(asyncio.QueueFull):
                    queue.put_nowait(exc)

        try:
            await self._send({"kind": kind, "runId": run_id, "input": payload})
            while True:
                # Node owns provider idle deadlines; a user/tool wait may be
                # intentionally long. Reader EOF always wakes this queue.
                incoming = asyncio.create_task(queue.get())
                assert self._reader is not None
                try:
                    completed, _ = await asyncio.wait(
                        (incoming, self._reader), return_when=asyncio.FIRST_COMPLETED
                    )
                    if incoming not in completed:
                        raise EngineUnavailableError("TypeScript engine stopped during turn")
                    frame = incoming.result()
                finally:
                    if not incoming.done():
                        incoming.cancel()
                        with suppress(asyncio.CancelledError):
                            await incoming
                if isinstance(frame, Exception):
                    raise frame
                if frame.get("kind") == "complete":
                    return frame["state"]
                if frame.get("kind") == "failed":
                    raise EngineUnavailableError(str(frame.get("message") or "Native turn failed"))
                if frame.get("kind") != "call":
                    raise EngineUnavailableError("Unknown native engine frame")
                task = asyncio.create_task(respond(frame))
                operations.add(task)
                task.add_done_callback(operations.discard)
        except Exception as exc:
            # A failed native turn may already have visible text or committed
            # tool effects. Never let a partner backup model replay that turn.
            from deeptutor.services.llm.exceptions import LLMProviderTransportError

            raise LLMProviderTransportError(str(exc), partial_response=True) from exc
        finally:
            self._runs.pop(run_id, None)
            for task in operations:
                task.cancel()
            if operations:
                await asyncio.gather(*operations, return_exceptions=True)
            with suppress(Exception, asyncio.CancelledError):
                await self._send({"kind": "cancel", "runId": run_id})
            if not self._runs and not self._closed:
                self._cancel_idle_close()
                self._idle_handle = asyncio.get_running_loop().call_later(
                    _IDLE_WORKER_SECONDS, self._schedule_idle_close
                )

    def _cancel_idle_close(self) -> None:
        if self._idle_handle is not None:
            self._idle_handle.cancel()
            self._idle_handle = None

    def _schedule_idle_close(self) -> None:
        self._idle_handle = None
        task = asyncio.create_task(self._close_if_idle())
        task.add_done_callback(
            lambda completed: completed.exception() if not completed.cancelled() else None
        )

    async def _close_if_idle(self) -> None:
        async with self._startup:
            if not self._runs:
                await self._stop_process()

    async def _invoke_host(self, host: Host, frame: dict[str, Any]) -> Any:
        # Spawn from the turn task, never from the shared reader: create_task
        # copies the authenticated/model/workspace context here. Racing the
        # reader also cancels an ask_user/provider wait if the worker dies.
        operation = asyncio.create_task(
            host.invoke(frame["operation"], frame["input"], frame["state"])
        )
        assert self._reader is not None
        try:
            completed, _ = await asyncio.wait(
                (operation, self._reader), return_when=asyncio.FIRST_COMPLETED
            )
            if self._reader in completed:
                raise EngineUnavailableError("TypeScript scheduler stopped during host operation")
            return await operation
        finally:
            if not operation.done():
                operation.cancel()
                with suppress(asyncio.CancelledError):
                    await operation

    async def close(self) -> None:
        self._closed = True
        self._cancel_idle_close()
        async with self._startup:
            await self._stop_process()

    async def _stop_process(self) -> None:
        process = self._process
        if process is None:
            return
        if process.returncode is None:
            with suppress(ProcessLookupError):
                process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=3)
        except TimeoutError:
            with suppress(ProcessLookupError):
                process.kill()
            await process.wait()
        if self._reader is not None:
            await self._reader
        self._process = None


def get_engine_client() -> EngineClient:
    loop = asyncio.get_running_loop()
    # Short-lived Python SDK event loops must not leave Node children behind.
    for old, client in list(_clients.items()):
        if old.is_closed():
            process = client._process
            if process is not None and process.returncode is None:
                with suppress(ProcessLookupError):
                    process.terminate()
            _clients.pop(old, None)
    if loop not in _clients:
        _clients[loop] = EngineClient()
    return _clients[loop]


async def close_engine_clients() -> None:
    client = _clients.pop(asyncio.get_running_loop(), None)
    if client is not None:
        await client.close()


@atexit.register
def _terminate_children() -> None:
    for client in _clients.values():
        process = client._process
        if process is not None and process.returncode is None:
            with suppress(ProcessLookupError):
                process.terminate()
