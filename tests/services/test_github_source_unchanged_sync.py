"""An unchanged GitHub source must still record that it was checked.

``sync_source`` returned ``skipped=True`` without touching the source's state
when the remote branch still pointed at the synced commit, so ``last_synced_at``
never moved: past the 24-hour freshness window the hourly service re-queried
GitHub every cycle and the source stayed stale forever, and an error string from
an earlier transient failure stayed on it after a later check had confirmed the
source current (#1489).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from deeptutor.services.github_source import sync as sync_module


class _Client:
    """Answers the SHA probe and fails loudly on any transfer."""

    def __init__(self, sha: str) -> None:
        self.sha = sha

    async def get_latest_commit_sha(self, repo: str, branch: str) -> str:
        return self.sha

    async def get_tree(self, *args: Any, **kwargs: Any):
        raise AssertionError("an unchanged source must not download anything")

    async def compare_commits(self, *args: Any, **kwargs: Any):
        raise AssertionError("an unchanged source must not compare commits")


@pytest.fixture
def recorded_state(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    writes: list[dict[str, Any]] = []

    class _Manager:
        def __init__(self, *, base_dir: str) -> None:
            self.base_dir = base_dir

        def update_github_source_state(self, **fields: Any) -> None:
            writes.append(fields)

    monkeypatch.setattr("deeptutor.knowledge.manager.KnowledgeBaseManager", _Manager)
    monkeypatch.setattr(
        "deeptutor.services.rag.provider_binding.resolve_bound_provider",
        lambda base_dir, kb_name: "llamaindex",
    )
    return writes


@pytest.mark.asyncio
async def test_unchanged_source_is_marked_fresh_and_its_old_error_cleared(
    tmp_path: Path, recorded_state: list[dict[str, Any]]
) -> None:
    source = {
        "id": "src",
        "repo": "owner/repo",
        "last_synced_sha": "deadbeef",
        "last_synced_at": "2020-01-01T00:00:00Z",
        "last_sync_status": "error",
        "last_sync_error": "rate limited",
        "files_synced": 7,
    }

    result = await sync_module.sync_source(
        "kb", source, base_dir=str(tmp_path), client=_Client("deadbeef")
    )

    assert (result.ok, result.skipped) == (True, True)
    assert len(recorded_state) == 1
    written = recorded_state[0]
    assert written["last_sync_status"] == "success"
    assert written["last_sync_error"] is None
    assert written["last_synced_sha"] == "deadbeef"
    assert written["last_synced_at"] > "2020-01-01T00:00:00Z"
    # Nothing was transferred, so the last real transfer's count must survive.
    assert "files_synced" not in written
