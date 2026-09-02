"""Validated construction of the process-level runtime coordinator."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .memory import MemoryCoordinator
from .protocol import RuntimeCoordinator
from .redis import RedisCoordinator


class RuntimeConfigurationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CoordinationSettings:
    backend_workers: int = 1
    backend: str = "memory"
    redis_url: str = ""
    key_prefix: str = "deeptutor"
    lease_ttl_seconds: int = 30
    renew_interval_seconds: int = 10
    recovery_interval_seconds: int = 10
    stream_retention_seconds: int = 86_400

    @classmethod
    def from_runtime_settings(
        cls,
        system: dict[str, Any],
        integrations: dict[str, Any],
    ) -> "CoordinationSettings":
        raw = integrations.get("turn_coordination")
        coordination = raw if isinstance(raw, dict) else {}
        settings = cls(
            backend_workers=max(1, int(system.get("backend_workers") or 1)),
            backend=str(coordination.get("backend") or "memory").lower(),
            redis_url=str(coordination.get("redis_url") or ""),
            key_prefix=str(coordination.get("key_prefix") or "deeptutor").strip(":") or "deeptutor",
            lease_ttl_seconds=int(coordination.get("lease_ttl_seconds") or 30),
            renew_interval_seconds=int(coordination.get("renew_interval_seconds") or 10),
            recovery_interval_seconds=int(coordination.get("recovery_interval_seconds") or 10),
            stream_retention_seconds=int(coordination.get("stream_retention_seconds") or 86_400),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.backend not in {"memory", "redis"}:
            raise RuntimeConfigurationError(
                f"Unsupported turn coordination backend: {self.backend}"
            )
        if self.backend_workers > 1 and self.backend != "redis":
            raise RuntimeConfigurationError(
                "backend_workers > 1 requires turn_coordination.backend=redis"
            )
        if self.backend == "redis" and not self.redis_url:
            raise RuntimeConfigurationError(
                "turn_coordination.redis_url is required for Redis coordination"
            )
        if self.lease_ttl_seconds < 10:
            raise RuntimeConfigurationError("lease_ttl_seconds must be at least 10")
        if not 0 < self.renew_interval_seconds < self.lease_ttl_seconds:
            raise RuntimeConfigurationError(
                "renew_interval_seconds must be positive and less than lease_ttl_seconds"
            )

    def runtime_report(self) -> dict[str, Any]:
        """Return diagnostics without exposing the Redis URL or credentials."""
        return {
            "worker_count": self.backend_workers,
            "coordination_mode": self.backend,
            "redis_configured": bool(self.redis_url) if self.backend == "redis" else False,
            "lease_ttl_seconds": self.lease_ttl_seconds,
            "renew_interval_seconds": self.renew_interval_seconds,
            "recovery_interval_seconds": self.recovery_interval_seconds,
        }


async def create_runtime_coordinator(
    settings: CoordinationSettings,
) -> RuntimeCoordinator:
    settings.validate()
    if settings.backend == "memory":
        return MemoryCoordinator(lease_ttl_seconds=settings.lease_ttl_seconds)
    coordinator = RedisCoordinator(
        settings.redis_url,
        key_prefix=settings.key_prefix,
        lease_ttl_seconds=settings.lease_ttl_seconds,
        stream_retention_seconds=settings.stream_retention_seconds,
    )
    if not await coordinator.health():
        await coordinator.close()
        raise RuntimeConfigurationError("Redis coordination is configured but Redis is unavailable")
    return coordinator


__all__ = [
    "CoordinationSettings",
    "RuntimeConfigurationError",
    "create_runtime_coordinator",
]
