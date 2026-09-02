"""Process-level dependency container and scoped runtime registry."""

from __future__ import annotations

import asyncio
import contextlib
import os
import socket
from typing import Any
import uuid

from deeptutor.runtime.capability_catalog import get_capability_catalog
from deeptutor.runtime.coordination import (
    CoordinationSettings,
    MemoryCoordinator,
    RedisCoordinator,
    RuntimeConfigurationError,
    RuntimeCoordinator,
    TurnRecoveryService,
)
from deeptutor.runtime.registry.capability_registry import CapabilityRegistry
from deeptutor.runtime.turn_engine import TurnEngine
from deeptutor.services.config import load_integrations_settings, load_system_settings
from deeptutor.services.session import get_session_store
from deeptutor.services.session.protocol import SessionStoreProtocol
from deeptutor.services.session.scope import store_scope
from deeptutor.services.session.turn_runtime import TurnRuntimeManager

from .service import TurnApplicationService


class StoreProvider:
    def get(self) -> SessionStoreProtocol:
        return get_session_store()


class RuntimeRegistry:
    def __init__(
        self,
        coordinator: RuntimeCoordinator,
        worker_id: str,
        turn_engine: TurnEngine | None = None,
    ) -> None:
        self.coordinator = coordinator
        self.worker_id = worker_id
        self.turn_engine = turn_engine
        self._runtimes: dict[str, TurnRuntimeManager] = {}

    def get(self, store: SessionStoreProtocol) -> TurnRuntimeManager:
        key = store_scope(store).cache_key
        runtime = self._runtimes.get(key)
        if runtime is None:
            runtime = TurnRuntimeManager(
                store,
                coordinator=self.coordinator,
                owner_id=self.worker_id,
                turn_engine=self.turn_engine,
            )
            self._runtimes[key] = runtime
        return runtime

    async def close(self, *, drain_timeout_seconds: float = 60.0) -> None:
        runtimes = list(self._runtimes.values())
        self._runtimes.clear()
        if runtimes:
            await asyncio.gather(
                *(
                    runtime.close(drain_timeout_seconds=drain_timeout_seconds)
                    for runtime in runtimes
                ),
                return_exceptions=True,
            )

    def owner_turn_count(self) -> int:
        return sum(len(runtime._executions) for runtime in self._runtimes.values())


class ApplicationContainer:
    def __init__(
        self,
        *,
        settings: CoordinationSettings,
        coordinator: RuntimeCoordinator,
        worker_id: str,
    ) -> None:
        self.settings = settings
        self.coordinator = coordinator
        self.worker_id = worker_id
        self.capability_catalog = get_capability_catalog()
        self.capability_registry = CapabilityRegistry(self.capability_catalog)
        self.capability_registry.load_builtins()
        self.capability_registry.load_plugins()
        self.turn_engine = TurnEngine(self.capability_registry)
        self.store_provider = StoreProvider()
        self.runtime_registry = RuntimeRegistry(coordinator, worker_id, self.turn_engine)
        self.turns = TurnApplicationService(
            self.store_provider,
            self.runtime_registry,
            coordinator,
        )
        self._recovery_services: dict[str, TurnRecoveryService] = {}
        self._started = False

    @classmethod
    def build(cls) -> "ApplicationContainer":
        settings = CoordinationSettings.from_runtime_settings(
            load_system_settings(), load_integrations_settings()
        )
        coordinator: RuntimeCoordinator
        if settings.backend == "redis":
            coordinator = RedisCoordinator(
                settings.redis_url,
                key_prefix=settings.key_prefix,
                lease_ttl_seconds=settings.lease_ttl_seconds,
                stream_retention_seconds=settings.stream_retention_seconds,
            )
        else:
            coordinator = MemoryCoordinator(lease_ttl_seconds=settings.lease_ttl_seconds)
        worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        return cls(settings=settings, coordinator=coordinator, worker_id=worker_id)

    async def start(self) -> None:
        if self._started:
            return
        if not await self.coordinator.health():
            raise RuntimeConfigurationError(
                "Turn coordination backend is unavailable; refusing to start"
            )
        self._started = True

    async def close(self) -> None:
        if not self._started:
            return
        await self.runtime_registry.close(drain_timeout_seconds=60.0)
        with contextlib.suppress(Exception):
            await self.coordinator.close()
        self._started = False

    async def recover_once(self) -> None:
        """Recover expired turns across every registered user repository.

        Missing turns are deliberately not acknowledged by a repository's
        recovery service; the next user scope therefore still gets a chance
        to claim and recover them.
        """

        from deeptutor.multi_user.paths import user_context

        seen: set[str] = set()
        for user in self._local_users():
            with user_context(user):
                store = self.store_provider.get()
                scope_key = store_scope(store).cache_key
                if scope_key in seen:
                    continue
                seen.add(scope_key)
                recovery = self._recovery_services.get(scope_key)
                if recovery is None:
                    recovery = TurnRecoveryService(self.coordinator, store)
                    self._recovery_services[scope_key] = recovery
                await recovery.recover_once()

    @staticmethod
    def _local_users() -> list[Any]:
        """Return the admin plus every registered local user scope."""

        from deeptutor.multi_user.identity import list_user_info
        from deeptutor.multi_user.models import CurrentUser
        from deeptutor.multi_user.paths import local_admin_user, scope_for_user

        users = [local_admin_user()]
        for record in list_user_info():
            user_id = str(record.get("id") or "").strip()
            role = str(record.get("role") or "user")
            if not user_id or role == "admin":
                continue
            users.append(
                CurrentUser(
                    id=user_id,
                    username=str(record.get("username") or user_id),
                    role="user",
                    scope=scope_for_user(user_id, is_admin=False),
                )
            )
        return users

    async def migrate_legacy_chat(self, *, dry_run: bool = False) -> dict[str, Any]:
        """Migrate the current scope's removed v1 JSON chat store."""

        from deeptutor.services.path_service import get_path_service
        from deeptutor.services.session.legacy_migration import (
            LegacyChatSessionMigrator,
        )

        paths = get_path_service()
        migrator = LegacyChatSessionMigrator(
            self.store_provider.get(),
            paths.get_session_file("chat"),
            paths.get_user_root() / "archive" / "legacy-chat",
        )
        return (await migrator.migrate(dry_run=dry_run)).to_dict()

    async def migrate_all_legacy_chats(self, *, dry_run: bool = False) -> list[dict[str, Any]]:
        """Migrate admin and every registered local user scope."""

        from deeptutor.services.session.legacy_migration import (
            migrate_all_legacy_chat_scopes,
        )

        return await migrate_all_legacy_chat_scopes(dry_run=dry_run)

    async def migrate_all_workspace_preferences(self) -> list[dict[str, Any]]:
        """Upgrade legacy Reading/Mastery metadata in every account scope."""

        from deeptutor.multi_user.identity import list_user_info
        from deeptutor.multi_user.models import CurrentUser
        from deeptutor.multi_user.paths import local_admin_user, scope_for_user, user_context

        users = [local_admin_user()]
        users.extend(
            CurrentUser(
                id=str(record.get("id") or ""),
                username=str(record.get("username") or record.get("id") or ""),
                role="admin" if str(record.get("role") or "user") == "admin" else "user",
                scope=scope_for_user(
                    str(record.get("id") or ""),
                    is_admin=str(record.get("role") or "user") == "admin",
                ),
            )
            for record in list_user_info()
            if str(record.get("id") or "").strip()
        )

        reports: list[dict[str, Any]] = []
        seen_users: set[str] = set()
        for user in users:
            if user.id in seen_users:
                continue
            seen_users.add(user.id)
            with user_context(user):
                migrated = await self.store_provider.get().migrate_workspace_preferences()
            reports.append(
                {
                    "user_id": user.id,
                    "scope": user.scope.cache_key,
                    "migrated": migrated,
                }
            )
        return reports

    async def run_startup_data_migrations(self) -> dict[str, list[dict[str, Any]]]:
        """Run every idempotent migration shared by all server launch modes."""

        return {
            "legacy_chat": await self.migrate_all_legacy_chats(),
            "workspace_preferences": await self.migrate_all_workspace_preferences(),
        }

    async def runtime_report(self) -> dict[str, Any]:
        report = self.settings.runtime_report()
        coordinator_healthy = await self.coordinator.health()
        report.update(
            {
                "worker_id": self.worker_id,
                "redis_status": (
                    "ok"
                    if self.settings.backend == "redis" and coordinator_healthy
                    else ("unavailable" if self.settings.backend == "redis" else "not_configured")
                ),
                "leader_id": await self.coordinator.leader_id(),
                "owner_turn_count": self.runtime_registry.owner_turn_count(),
                "recovery_backlog": sum(
                    recovery.backlog for recovery in self._recovery_services.values()
                ),
            }
        )
        return report


_default_container: ApplicationContainer | None = None


def get_application_container() -> ApplicationContainer:
    global _default_container
    if _default_container is None:
        _default_container = ApplicationContainer.build()
    return _default_container


def set_application_container(container: ApplicationContainer | None) -> None:
    global _default_container
    _default_container = container


__all__ = [
    "ApplicationContainer",
    "RuntimeRegistry",
    "StoreProvider",
    "get_application_container",
    "set_application_container",
]
