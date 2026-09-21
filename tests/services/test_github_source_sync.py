"""Regression tests for GitHub knowledge-source synchronization."""

from datetime import datetime

import pytest

from deeptutor.services.base_sync import is_stale
from deeptutor.services.github_source import sync as sync_module
from deeptutor.services.github_source.sync import sync_source


@pytest.mark.asyncio
async def test_unchanged_source_refreshes_success_state(monkeypatch, tmp_path) -> None:
    latest_sha = "unchanged-sha"
    state_updates: list[dict] = []

    class FakeClient:
        async def get_latest_commit_sha(self, repo: str, branch: str) -> str:
            assert repo == "owner/repo"
            assert branch == "main"
            return latest_sha

        async def get_tree(self, *_args, **_kwargs):
            raise AssertionError("an unchanged source must not fetch the repository tree")

        async def compare_commits(self, *_args, **_kwargs):
            raise AssertionError("an unchanged source must not compare commits")

        async def download_file(self, *_args, **_kwargs):
            raise AssertionError("an unchanged source must not download files")

    class FakeManager:
        def __init__(self, *, base_dir: str) -> None:
            assert base_dir == str(tmp_path)

        def update_github_source_state(self, **fields) -> None:
            state_updates.append(fields)

    monkeypatch.setattr("deeptutor.knowledge.manager.KnowledgeBaseManager", FakeManager)

    async def fail_index(*_args, **_kwargs):
        raise AssertionError("an unchanged source must not update the index")

    monkeypatch.setattr(sync_module, "_index_files", fail_index)

    source = {
        "id": "source-1",
        "repo": "owner/repo",
        "branch": "main",
        "last_synced_sha": latest_sha,
        "last_synced_at": "2026-01-01T00:00:00+00:00",
        "last_sync_status": "error",
        "last_sync_error": "temporary failure",
    }
    result = await sync_source(
        "test-kb",
        source,
        base_dir=str(tmp_path),
        client=FakeClient(),
    )

    assert result.ok is True
    assert result.skipped is True
    assert len(state_updates) == 1
    update = state_updates[0]
    assert update["kb_name"] == "test-kb"
    assert update["source_id"] == "source-1"
    assert update["last_synced_sha"] == latest_sha
    assert update["last_sync_status"] == "success"
    assert update["last_sync_error"] is None
    assert datetime.fromisoformat(update["last_synced_at"]).tzinfo is not None

    refreshed_source = source | {
        key: value for key, value in update.items() if key not in {"kb_name", "source_id"}
    }
    assert is_stale(refreshed_source, stale_hours=24) is False
