from __future__ import annotations

import pytest

from deeptutor.app.container import ApplicationContainer


@pytest.mark.asyncio
async def test_startup_data_migrations_run_legacy_then_workspace_upgrade() -> None:
    container = object.__new__(ApplicationContainer)
    calls: list[str] = []

    async def migrate_legacy() -> list[dict[str, object]]:
        calls.append("legacy")
        return [{"imported": 2}]

    async def migrate_workspace() -> list[dict[str, object]]:
        calls.append("workspace")
        return [{"migrated": 3}]

    container.migrate_all_legacy_chats = migrate_legacy  # type: ignore[method-assign]
    container.migrate_all_workspace_preferences = migrate_workspace  # type: ignore[method-assign]

    reports = await container.run_startup_data_migrations()

    assert calls == ["legacy", "workspace"]
    assert reports == {
        "legacy_chat": [{"imported": 2}],
        "workspace_preferences": [{"migrated": 3}],
    }
