from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.multi_user.context import (
    get_current_user_or_none,
    reset_current_user,
    set_current_user,
)
from deeptutor.multi_user.models import CurrentUser, UserScope
from deeptutor.services.github_source.sync_service import GitHubSourceSyncService


@pytest.mark.asyncio
async def test_periodic_github_sync_installs_owner_and_restores_ambient(
    monkeypatch, tmp_path: Path
) -> None:
    owner = CurrentUser(
        id="owner",
        username="owner",
        role="user",
        scope=UserScope(kind="user", user_id="owner", root=tmp_path / "owner"),
    )
    ambient = CurrentUser(
        id="ambient",
        username="ambient",
        role="user",
        scope=UserScope(kind="user", user_id="ambient", root=tmp_path / "ambient"),
    )
    source = {"id": "source", "enabled": True}

    class _Manager:
        def __init__(self, *, base_dir: str) -> None:
            assert base_dir == str(tmp_path / "kbs")

        def get_all_github_sources(self):
            return [("kb", source)]

        def update_github_source_state(self, **_kwargs) -> None:
            raise AssertionError("sync should succeed")

    async def _sync_source(**_kwargs) -> None:
        assert get_current_user_or_none() == owner

    monkeypatch.setattr("deeptutor.knowledge.manager.KnowledgeBaseManager", _Manager)
    monkeypatch.setattr("deeptutor.services.github_source.sync.sync_source", _sync_source)
    service = GitHubSourceSyncService(base_dir=str(tmp_path / "kbs"), owner=owner)

    token = set_current_user(ambient)
    try:
        await service._sync_one_cycle()
        assert get_current_user_or_none() == ambient
    finally:
        reset_current_user(token)
