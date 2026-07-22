"""
Sandbox service facade.

The single entry point the rest of the app uses. It owns the chosen backend,
caches its liveness probe, enforces per-user quotas, and answers the
capability questions the skill/exec layers ask:

* :func:`exec_capability_available` — does a usable sandbox of this kind
  exist at all? (drives skill ``requires.sandbox`` gating)
* :meth:`SandboxService.isolation_level` — how strong is it? (drives the
  exec policy gate: SYSTEM for everyone, APPLICATION for admins only)
* :meth:`SandboxService.run` — execute, subject to quota.
"""

from __future__ import annotations

import asyncio
import logging

from deeptutor.core.i18n import t
from deeptutor.services.sandbox.backends import SandboxBackend
from deeptutor.services.sandbox.config import SandboxSettings, build_backend
from deeptutor.services.sandbox.quota import QuotaExceeded, UserExecQuota
from deeptutor.services.sandbox.spec import ExecRequest, ExecResult, IsolationLevel

logger = logging.getLogger(__name__)


class SandboxService:
    def __init__(self, settings: SandboxSettings | None = None) -> None:
        self._settings = settings or SandboxSettings.from_env()
        self._backend: SandboxBackend | None = build_backend(self._settings)
        self._healthy: bool | None = None
        self._health_detail = ""
        self._health_lock = asyncio.Lock()
        self._quota = UserExecQuota(
            max_concurrent=self._settings.max_concurrent_per_user,
            max_per_minute=self._settings.max_runs_per_minute_per_user,
        )

    @property
    def settings(self) -> SandboxSettings:
        return self._settings

    async def _ensure_healthy(self) -> bool:
        if self._backend is None:
            return False
        if self._healthy is not None:
            return self._healthy
        async with self._health_lock:
            if self._healthy is None:
                try:
                    self._healthy, self._health_detail = await self._backend.health()
                except Exception as exc:
                    self._healthy = False
                    self._health_detail = f"health check failed: {exc}"
                if not self._healthy:
                    logger.warning(
                        "sandbox backend %s unhealthy: %s",
                        type(self._backend).__name__,
                        self._health_detail,
                    )
        return bool(self._healthy)

    async def isolation_level(self) -> IsolationLevel:
        """Effective isolation level (OFF when no healthy backend)."""
        if not await self._ensure_healthy() or self._backend is None:
            return IsolationLevel.OFF
        return self._backend.level

    async def available(self) -> bool:
        return await self.isolation_level() is not IsolationLevel.OFF

    async def run(self, request: ExecRequest, *, user_id: str) -> ExecResult:
        """Run *request* for *user_id*, enforcing quota; never raises for
        command failure — only the sandbox/quota envelope is reported via
        :attr:`ExecResult.error`."""
        if not await self._ensure_healthy() or self._backend is None:
            return ExecResult(error=self._health_detail or t("sandbox.no_backend"))
        # Backstop for the per-user exec grant: pipelines hide the exec tool
        # when the grant denies it, but any path that reaches the sandbox
        # directly still answers to the same policy.
        try:
            from deeptutor.multi_user.tool_access import exec_override

            if exec_override() is False:
                return ExecResult(error=t("sandbox.disabled_for_account"))
        except Exception:
            logger.warning("per-user exec policy check failed; continuing", exc_info=True)
        try:
            lease = await self._quota.acquire(user_id)
        except QuotaExceeded as exc:
            return ExecResult(error=str(exc))
        async with lease:
            return await self._backend.exec(request)


_service: SandboxService | None = None


def get_sandbox_service() -> SandboxService:
    global _service
    if _service is None:
        _service = SandboxService()
    return _service


def reset_sandbox_service() -> None:
    """Drop the cached service (tests / config reloads)."""
    global _service
    _service = None


def exec_capability_available(kind: str = "shell") -> bool:
    """Whether a usable sandbox exists — used by skill ``requires.sandbox``.

    Synchronous (skill summary rendering is sync). Returns ``True`` when a
    backend is configured at all; the per-run health probe still gates
    actual execution, so a configured-but-down runner won't silently run
    unsandboxed.
    """
    if kind not in ("", "shell"):
        return False
    return get_sandbox_service()._backend is not None


__all__ = [
    "SandboxService",
    "exec_capability_available",
    "get_sandbox_service",
    "reset_sandbox_service",
]
