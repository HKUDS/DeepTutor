"""Process-local coordinator for CodeBuddy SDK authentication."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import time
from typing import Any

#: Hard ceilings for awaiting a CodeBuddy SDK auth flow. The SDK can report
#: ``result=success`` while handing back a flow that never resolves, so an
#: unbounded ``await flow`` would hang the caller forever. ``_LOGIN_TIMEOUT``
#: matches the 300 s the SDK passes to ``authenticate``.
_PROBE_TIMEOUT = 45.0
_LOGIN_TIMEOUT = 300.0
#: Status poll probe timeout and backoff to prevent repeated SDK spawns
_STATUS_PROBE_WAIT_S = 20.0
_STATUS_PROBE_BACKOFF_S = 120.0


class CodeBuddyAuthService:
    """Probe existing SDK auth and keep one browser login flow alive."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._flow: Any | None = None
        self._task: asyncio.Task[Any] | None = None
        self._connection = "disconnected"
        self._operation_state: str | None = None
        self._authorize_url: str | None = None
        self._user_label: str | None = None
        self._error_code: str | None = None
        self._generation = 0
        self._probe_task: asyncio.Task[Any] | None = None
        self._probe_generation = 0
        self._probe_retry_at = 0.0
        self._starting_generation: int | None = None
        self._tasks: set[asyncio.Task[Any]] = set()

    def public_status(self) -> dict[str, Any]:
        return {
            "connection": self._connection,
            "operation_state": self._operation_state,
            "authorize_url": self._authorize_url,
            "user_label": self._user_label,
            "error_code": self._error_code,
        }

    async def status(self) -> dict[str, Any]:
        """Share a bounded probe; polling never owns or cancels that probe."""
        async with self._lock:
            if self._starting_generation is not None or (self._task and not self._task.done()):
                return self.public_status()
            if self._probe_task and not self._probe_task.done():
                probe_task = self._probe_task
            elif time.monotonic() < self._probe_retry_at:
                return self.public_status()
            else:
                self._probe_generation += 1
                probe_task = asyncio.create_task(
                    self._probe_and_apply(self._generation, self._probe_generation)
                )
                self._probe_task = probe_task
                self._track_task(probe_task)
        try:
            await asyncio.wait_for(asyncio.shield(probe_task), timeout=_STATUS_PROBE_WAIT_S)
        except TimeoutError:
            # A short HTTP poll deadline is not an authentication failure.
            # The independently bounded probe will publish its result later.
            pass
        async with self._lock:
            return self.public_status()

    async def _probe_and_apply(self, generation: int, probe_generation: int) -> None:
        try:
            probe = await _await_flow(self._run_probe(), _PROBE_TIMEOUT, self._track_task)
        except Exception as exc:  # noqa: BLE001 - stable public status
            probe = ("error", exc)
        async with self._lock:
            if self._generation != generation or self._probe_generation != probe_generation:
                return
            self._apply_probe(probe)
            if probe[0] in {"available", "error"}:
                self._probe_retry_at = time.monotonic() + _STATUS_PROBE_BACKOFF_S

    async def start_login(self) -> dict[str, Any]:
        """Reuse local auth or start one browser login without locking SDK I/O."""
        async with self._lock:
            if self._starting_generation is not None or (self._task and not self._task.done()):
                return self.public_status()
            self._generation += 1
            generation = self._generation
            self._starting_generation = generation
            self._probe_generation += 1
            self._probe_retry_at = 0.0
            self._connection = "authorizing"
            self._operation_state = "waiting"
            self._authorize_url = None
            self._user_label = None
            self._error_code = None
        try:
            label = await _await_flow(self._probe_local_login(), _PROBE_TIMEOUT, self._track_task)
            if label is not None:
                async with self._lock:
                    if self._generation == generation:
                        self._apply_probe(("local", label))
                    return self.public_status()
            flow = await _await_flow(_start_sdk_authenticate(), _PROBE_TIMEOUT, self._track_task)
            async with self._lock:
                stale = self._generation != generation
                if not stale:
                    self._flow = flow
                    task: asyncio.Task[Any]
                    if getattr(flow, "auth_url", ""):
                        self._authorize_url = str(flow.auth_url)
                        task = asyncio.create_task(self._wait_for_login(flow, generation))
                    else:
                        task = asyncio.create_task(
                            _await_flow(flow, _PROBE_TIMEOUT, self._track_task)
                        )
                    self._task = task
                    self._track_task(task)
            if stale:
                await _cancel_flow(flow)
                return self.public_status()
            if getattr(flow, "auth_url", ""):
                return self.public_status()
            result = await task
            async with self._lock:
                if self._generation == generation:
                    self._flow = None
                    self._task = None
                    self._mark_connected(result)
                return self.public_status()
        except asyncio.CancelledError:
            async with self._lock:
                if self._generation == generation:
                    self._flow = None
                    self._task = None
                    self._connection = "disconnected"
                    self._operation_state = "cancelled"
            raise
        except Exception as exc:  # noqa: BLE001 - converted to stable public state
            async with self._lock:
                if self._generation == generation:
                    self._flow = None
                    self._task = None
                    self._mark_error(exc)
                return self.public_status()
        finally:
            async with self._lock:
                if self._starting_generation == generation:
                    self._starting_generation = None

    async def cancel_login(self) -> dict[str, Any]:
        async with self._lock:
            self._generation += 1
            self._probe_generation += 1
            self._starting_generation = None
            self._probe_retry_at = time.monotonic() + _STATUS_PROBE_BACKOFF_S
            flow = self._flow
            task = self._task
            self._flow = None
            self._task = None
            self._connection = "disconnected"
            self._operation_state = "cancelled"
            self._authorize_url = None
            self._error_code = None
        if task and not task.done():
            task.cancel()
        if flow is not None:
            await _cancel_flow(flow)
        async with self._lock:
            return self.public_status()

    async def logout(self) -> dict[str, Any]:
        """Disconnect DeepTutor from the CodeBuddy session on this host.

        Not a sign-out: the session belongs to the IDE plugin / CLI that
        created it, and only they can end it.
        """
        async with self._lock:
            self._generation += 1
            generation = self._generation
            self._probe_generation += 1
            self._starting_generation = None
            self._probe_retry_at = time.monotonic() + _STATUS_PROBE_BACKOFF_S
            flow = self._flow
            task = self._task
            self._flow = None
            self._task = None
        if task and not task.done():
            task.cancel()
        if flow is not None:
            await _cancel_flow(flow)

        # DeepTutor does not own this credential: it is the session the IDE
        # plugin and the `codebuddy` CLI share on this host. Ending it from a
        # web endpoint would sign the operator out of their editor too — and on
        # a shared host, out of whoever else is on that login. Drop our cached
        # clients and report where the session actually lives.
        from deeptutor.runtime.agentic.client import reset_agentic_client_pool
        from deeptutor.services.codebuddy_credentials import load_credentials

        reset_agentic_client_pool()
        async with self._lock:
            if self._generation != generation:
                return self.public_status()
            if load_credentials() is not None:
                self._connection = "connected"
                self._operation_state = "failed"
                self._authorize_url = None
                self._error_code = "logout_external"
                return self.public_status()
            self._connection = "disconnected"
            self._operation_state = None
            self._authorize_url = None
            self._user_label = None
            self._error_code = None
            return self.public_status()

    async def _run_probe(self) -> tuple[str, Any]:
        """Probe for an existing login without holding the lock.

        Returns ``(state, payload)`` for ``_apply_probe``: ``("local", label)``,
        ``("connected", result)``, ``("available", None)``, or ``("error", exc)``.
        """
        label = await self._probe_local_login()
        if label is not None:
            return "local", label
        try:
            flow = await _start_sdk_authenticate()
            if getattr(flow, "auth_url", ""):
                await _cancel_flow(flow)
                return "available", None
            result = await _await_flow(flow, _PROBE_TIMEOUT, self._track_task)
            return "connected", result
        except Exception as exc:  # noqa: BLE001 - converted to stable public state
            return "error", exc

    def _apply_probe(self, probe: tuple[str, Any]) -> None:
        state, payload = probe
        if state == "local":
            self._mark_connected(None)
            self._user_label = str(payload)
        elif state == "connected":
            self._mark_connected(payload)
        elif state == "available":
            self._connection = "disconnected"
            self._operation_state = None
            self._authorize_url = None
            self._user_label = None
            self._error_code = None
        else:
            self._mark_error(payload)

    async def _probe_local_login(self) -> str | None:
        """Return the stored session's label, or ``None`` when not signed in.

        This path needs no Agent SDK, so it is tried before the SDK probe.
        """
        from deeptutor.services.codebuddy_credentials import load_credentials, probe_account

        credentials = load_credentials()
        if credentials is None:
            return None
        try:
            return await probe_account(credentials)
        except Exception:  # noqa: BLE001 - fall through to the SDK probe
            return None

    async def _wait_for_login(self, flow: Any, generation: int) -> None:
        flow_task = asyncio.create_task(_await_flow(flow, _LOGIN_TIMEOUT, self._track_task))
        async with self._lock:
            self._track_task(flow_task)

        try:
            result = await flow_task
        except asyncio.CancelledError:
            return
        except Exception as exc:  # noqa: BLE001 - converted to stable public state
            async with self._lock:
                if self._generation == generation and self._flow is flow:
                    self._flow = None
                    self._task = None
                    self._mark_error(exc)
            return

        async with self._lock:
            if self._generation == generation and self._flow is flow:
                self._flow = None
                self._task = None
                self._mark_connected(result)

    def _track_task(self, task: asyncio.Task[Any]) -> None:
        """Track a task so it stays owned until it finishes."""
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _mark_connected(self, result: Any) -> None:
        userinfo = getattr(result, "userinfo", None)
        self._connection = "connected"
        self._operation_state = "completed"
        self._authorize_url = None
        self._user_label = _userinfo_label(userinfo)
        self._error_code = None

    def _mark_error(self, exc: Exception) -> None:
        message = str(exc).lower()
        if isinstance(exc, ImportError):
            code = "sdk_missing"
        elif "not found" in message or "no such file" in message:
            code = "cli_missing"
        elif "timed out" in message or "timeout" in message:
            code = "login_timeout"
        else:
            code = "auth_failed"
        self._connection = "error"
        self._operation_state = "failed"
        self._authorize_url = None
        self._user_label = None
        self._error_code = code


async def _start_sdk_authenticate() -> Any:
    try:
        from codebuddy_agent_sdk import authenticate
    except ImportError as exc:
        raise ImportError("codebuddy-agent-sdk is not installed") from exc
    return await authenticate(timeout=_LOGIN_TIMEOUT)


async def _await_flow(
    awaitable: Any,
    timeout: float,
    track: Callable[[asyncio.Task[Any]], None] | None = None,
) -> Any:
    """Bound SDK work without waiting forever for cancellation acknowledgement."""
    task = asyncio.ensure_future(awaitable)
    if track is not None:
        track(task)
    try:
        done, _ = await asyncio.wait({task}, timeout=timeout)
        if not done:
            raise TimeoutError(f"codebuddy auth flow timed out after {timeout:.0f}s")
        return task.result()
    finally:
        if not task.done():
            task.cancel()
        # A cancellation-resistant SDK task stays owned by the service until
        # completion; retrieve late exceptions even after the caller has left.
        task.add_done_callback(lambda done: None if done.cancelled() else done.exception())


async def _cancel_flow(flow: Any) -> None:
    try:
        await _await_flow(flow.cancel(), 5.0)
    except Exception:  # noqa: BLE001 - advisory, bounded cancellation
        pass


def _userinfo_label(userinfo: Any) -> str | None:
    if userinfo is None:
        return None
    for field in ("user_nickname", "user_name", "user_id"):
        value = getattr(userinfo, field, None)
        if value:
            return str(value)
    return None


_service: CodeBuddyAuthService | None = None


def get_codebuddy_auth_service() -> CodeBuddyAuthService:
    global _service
    if _service is None:
        _service = CodeBuddyAuthService()
    return _service


__all__ = ["CodeBuddyAuthService", "get_codebuddy_auth_service"]
