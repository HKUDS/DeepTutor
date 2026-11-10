"""Process-local coordinator for CodeBuddy SDK authentication."""

from __future__ import annotations

import asyncio
from typing import Any

#: Hard ceilings for awaiting a CodeBuddy SDK auth flow. The SDK can report
#: ``result=success`` while handing back a flow that never resolves, so an
#: unbounded ``await flow`` would hang the caller forever. ``_LOGIN_TIMEOUT``
#: matches the 300 s the SDK passes to ``authenticate``.
_PROBE_TIMEOUT = 45.0
_LOGIN_TIMEOUT = 300.0


class CodeBuddyAuthService:
    """Probe existing SDK auth and keep one browser login flow alive."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._flow: Any | None = None
        self._task: asyncio.Task[None] | None = None
        self._connection = "disconnected"
        self._operation_state: str | None = None
        self._authorize_url: str | None = None
        self._user_label: str | None = None
        self._error_code: str | None = None

    def public_status(self) -> dict[str, Any]:
        return {
            "connection": self._connection,
            "operation_state": self._operation_state,
            "authorize_url": self._authorize_url,
            "user_label": self._user_label,
            "error_code": self._error_code,
        }

    async def status(self) -> dict[str, Any]:
        """Return current status, probing the SDK when no login is active."""
        async with self._lock:
            if self._task and not self._task.done():
                return self.public_status()

        # Probing spawns a process and may await a flow, so it must not run
        # under the lock: a wedged probe would then block every other caller,
        # including the status polls the frontend issues every few seconds.
        probe = await self._probe()
        async with self._lock:
            if self._task and not self._task.done():
                return self.public_status()
            self._apply_probe(probe)
            return self.public_status()

    async def start_login(self) -> dict[str, Any]:
        """Reuse local auth or start a browser-based SDK login flow."""
        async with self._lock:
            if self._task and not self._task.done():
                return self.public_status()
        label = await self._probe_local_login()
        if label is not None:
            async with self._lock:
                self._apply_probe(("local", label))
                return self.public_status()
        try:
            flow = await _start_sdk_authenticate()
            if getattr(flow, "auth_url", ""):
                async with self._lock:
                    if self._task and not self._task.done():
                        try:
                            await flow.cancel()
                        except Exception:  # noqa: BLE001 - cancellation is advisory
                            pass
                        return self.public_status()
                    self._flow = flow
                    self._connection = "authorizing"
                    self._operation_state = "waiting"
                    self._authorize_url = str(flow.auth_url)
                    self._user_label = None
                    self._error_code = None
                    self._task = asyncio.create_task(self._wait_for_login(flow))
                    return self.public_status()
            # The SDK can report success while handing back a flow with no
            # auth_url that never resolves. Bound the await so a wedged flow
            # surfaces as a timeout instead of freezing the settings API.
            result = await _await_flow(flow, _PROBE_TIMEOUT)
            async with self._lock:
                self._mark_connected(result)
                return self.public_status()
        except Exception as exc:  # noqa: BLE001 - converted to stable public state
            async with self._lock:
                self._mark_error(exc)
                return self.public_status()

    async def cancel_login(self) -> dict[str, Any]:
        async with self._lock:
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
            try:
                await flow.cancel()
            except Exception:
                pass
        return self.public_status()

    async def logout(self) -> dict[str, Any]:
        """Disconnect DeepTutor from the CodeBuddy session on this host.

        Not a sign-out: the session belongs to the IDE plugin / CLI that
        created it, and only they can end it.
        """
        async with self._lock:
            flow = self._flow
            task = self._task
            self._flow = None
            self._task = None
        if task and not task.done():
            task.cancel()
        if flow is not None:
            try:
                await flow.cancel()
            except Exception:
                pass

        # DeepTutor does not own this credential: it is the session the IDE
        # plugin and the `codebuddy` CLI share on this host. Ending it from a
        # web endpoint would sign the operator out of their editor too — and on
        # a shared host, out of whoever else is on that login. Drop our cached
        # clients and report where the session actually lives.
        from deeptutor.runtime.agentic.client import reset_agentic_client_pool
        from deeptutor.services.codebuddy_credentials import load_credentials

        reset_agentic_client_pool()
        async with self._lock:
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

    async def _probe(self) -> tuple[str, Any]:
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
                try:
                    await flow.cancel()
                except Exception:  # noqa: BLE001 - cancellation is advisory
                    pass
                return "available", None
            result = await _await_flow(flow, _PROBE_TIMEOUT)
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

    async def _wait_for_login(self, flow: Any) -> None:
        try:
            result = await _await_flow(flow, _LOGIN_TIMEOUT)
        except asyncio.CancelledError:
            return
        except Exception as exc:  # noqa: BLE001 - converted to stable public state
            async with self._lock:
                if self._flow is flow:
                    self._flow = None
                    self._task = None
                    self._mark_error(exc)
            return

        async with self._lock:
            if self._flow is flow:
                self._flow = None
                self._task = None
                self._mark_connected(result)

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


async def _await_flow(awaitable: Any, timeout: float) -> Any:
    """Await a CodeBuddy auth flow under a hard timeout.

    Uses ``asyncio.wait`` rather than ``wait_for``: the flow only implements
    ``__await__`` and may ignore cancellation, so waiting on an explicit task
    lets us cancel it and return regardless of the deadline being hit.
    """
    task = asyncio.ensure_future(awaitable)
    done, _ = await asyncio.wait({task}, timeout=timeout)
    if not done:
        task.cancel()
        raise TimeoutError(f"codebuddy auth flow timed out after {timeout:.0f}s")
    return task.result()


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
