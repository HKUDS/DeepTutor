"""Unchanged-SHA GitHub syncs must refresh persisted sync state.

When the remote branch still points at the same SHA that was synced before,
the sync is skipped, but the source's ``last_synced_at`` should still advance
and any previous transient ``last_sync_error`` should be cleared. Otherwise
the source stays marked stale past its freshness window even though GitHub
already confirmed it is current, and the next hourly cycle queries the
remote again for no reason.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from deeptutor.services.github_source import sync as sync_module


@dataclass
class _Entry:
    path: str


class _Client:
    """Stub client: reports a single fixed SHA, never downloads anything."""

    def __init__(self, latest_sha: str) -> None:
        self.latest_sha = latest_sha

    async def get_latest_commit_sha(self, _repo: str, _branch: str) -> str:
        return self.latest_sha

    async def get_tree(self, _repo, _branch, *, path_prefix="", glob="*"):
        return []

    async def compare_commits(self, _repo, _old_sha, _new_sha):
        return []

    async def download_file(self, _repo, _path, _sha):
        raise AssertionError("download should not be called on unchanged SHA")


def test_unchanged_sha_refreshes_last_synced_at(tmp_path: Path, monkeypatch) -> None:
    class Manager:
        calls: list[dict] = []

        def __init__(self, *, base_dir: str) -> None:
            self.base_dir = base_dir

        def update_github_source_state(self, **kwargs) -> None:
            self.calls.append(kwargs)

    monkeypatch.setattr("deeptutor.knowledge.manager.KnowledgeBaseManager", Manager)

    client = _Client(latest_sha="abc123")
    source = {
        "id": "source-1",
        "repo": "owner/repo",
        "branch": "main",
        "last_synced_sha": "abc123",
        "last_synced_at": "2026-08-01T00:00:00+00:00",
        "last_sync_status": "error",
        "last_sync_error": "transient upstream timeout",
    }

    result = asyncio.run(
        sync_module.sync_source(
            "kb",
            source,
            base_dir=str(tmp_path),
            client=client,
        )
    )

    assert result.ok is True
    assert result.skipped is True
    assert len(Manager.calls) == 1
    call = Manager.calls[0]
    assert call["kb_name"] == "kb"
    assert call["source_id"] == "source-1"
    assert call["last_sync_status"] == "success"
    assert call["last_sync_error"] is None
    assert call["last_synced_at"] != "2026-08-01T00:00:00+00:00"
    # last_synced_sha must NOT be cleared: the remote still matches it.
    assert "last_synced_sha" not in call


def test_unchanged_sha_makes_no_remote_downloads(tmp_path: Path, monkeypatch) -> None:
    class Manager:
        def __init__(self, *, base_dir: str) -> None:
            self.base_dir = base_dir

        def update_github_source_state(self, **_kwargs) -> None:
            return None

    monkeypatch.setattr("deeptutor.knowledge.manager.KnowledgeBaseManager", Manager)

    client = _Client(latest_sha="abc123")
    source = {
        "id": "source-1",
        "repo": "owner/repo",
        "branch": "main",
        "last_synced_sha": "abc123",
    }

    result = asyncio.run(
        sync_module.sync_source(
            "kb",
            source,
            base_dir=str(tmp_path),
            client=client,
        )
    )

    assert result.ok is True
    assert result.skipped is True
    assert result.files_added == 0
    assert result.files_updated == 0
