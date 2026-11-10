"""A first GitHub sync must not report success without usable source files."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from deeptutor.knowledge.manager import KnowledgeBaseManager
from deeptutor.services.github_source import sync as sync_module
from deeptutor.services.github_source.client import GitHubClient


@pytest.fixture
def sync_setup(tmp_path: Path, monkeypatch):
    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    (tmp_path / "kb").mkdir()
    manager.register_knowledge_base("kb")
    manager.add_github_source("kb", "owner/repo", branch="main", path="docs/", glob="*")
    monkeypatch.setattr(
        "deeptutor.services.rag.provider_binding.resolve_bound_provider",
        lambda base_dir, kb_name: "llamaindex",
    )
    indexed: list[str] = []

    async def record_index(kb_name, files, base_dir):
        indexed.extend(files)

    monkeypatch.setattr(sync_module, "_index_files", record_index)
    return manager, indexed


def _client(paths: list[str], downloads: list[str]) -> GitHubClient:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/commits/main"):
            return httpx.Response(200, json={"sha": "new-sha"})
        if "/git/trees/" in request.url.path:
            return httpx.Response(
                200,
                json={"tree": [{"path": path, "type": "blob", "sha": "blob"} for path in paths]},
            )
        if "/compare/" in request.url.path:
            return httpx.Response(
                200,
                json={"files": [{"filename": path, "status": "modified"} for path in paths]},
            )
        if request.url.host == "raw.githubusercontent.com":
            downloads.append(request.url.path)
            return httpx.Response(200, content=b"# Guide\n")
        raise AssertionError(f"Unexpected request: {request.url}")

    return GitHubClient(
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(respond))
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "paths, error_fragment",
    [
        (["other/guide.md"], "No files matched"),
        (["docs/logo.png", "docs/guide.rst", "other/guide.md"], "2 file(s) matched"),
    ],
)
async def test_first_sync_without_supported_files_records_actionable_error(
    tmp_path: Path, sync_setup, paths: list[str], error_fragment: str
) -> None:
    manager, indexed = sync_setup
    source = manager.get_github_sources("kb")[0]
    downloads: list[str] = []

    result = await sync_module.sync_source(
        "kb", source, base_dir=str(tmp_path), client=_client(paths, downloads)
    )

    assert result.ok is False
    assert error_fragment in result.error
    assert "path" in result.error and "glob" in result.error
    assert ".md" in result.error and ".markdown" in result.error
    saved = manager.get_github_sources("kb")[0]
    assert saved["last_sync_status"] == "error"
    assert saved["last_sync_error"] == result.error
    assert not saved.get("last_synced_sha")
    assert not saved.get("last_synced_at")
    assert not list((tmp_path / "kb" / "raw").iterdir())
    assert downloads == []
    assert indexed == []


@pytest.mark.asyncio
async def test_failed_empty_sync_can_retry_the_same_commit(tmp_path: Path, sync_setup) -> None:
    manager, indexed = sync_setup
    paths = ["docs/logo.png", "docs/guide.md"]
    downloads: list[str] = []
    client = _client(paths, downloads)
    source = manager.get_github_sources("kb")[0]
    manager.update_github_source_state("kb", source["id"], glob="*.png")
    source = manager.get_github_sources("kb")[0]
    failed = await sync_module.sync_source("kb", source, base_dir=str(tmp_path), client=client)
    assert failed.ok is False

    # Correcting the glob must retry the full sync at the same remote commit.
    manager.update_github_source_state("kb", source["id"], glob="*.md")
    source = manager.get_github_sources("kb")[0]
    result = await sync_module.sync_source("kb", source, base_dir=str(tmp_path), client=client)

    assert result.ok is True and result.skipped is False
    assert result.files_added == 1
    written = tmp_path / "kb" / "raw" / "guide.md"
    assert written.read_bytes() == b"# Guide\n"
    assert indexed == [str(written)]
    assert downloads == ["/owner/repo/new-sha/docs/guide.md"]
    saved = manager.get_github_sources("kb")[0]
    assert saved["last_sync_status"] == "success"
    assert saved["last_sync_error"] is None
    assert saved["last_synced_sha"] == "new-sha"
    assert saved["files_synced"] == 1


@pytest.mark.asyncio
async def test_incremental_sync_without_matching_changes_still_succeeds(
    tmp_path: Path, sync_setup
) -> None:
    manager, indexed = sync_setup
    source = manager.get_github_sources("kb")[0]
    manager.update_github_source_state(
        "kb", source["id"], last_synced_sha="old-sha", files_synced=1
    )
    raw_dir = tmp_path / "kb" / "raw"
    raw_dir.mkdir()
    guide = raw_dir / "guide.md"
    guide.write_bytes(b"# Existing guide\n")
    downloads: list[str] = []

    result = await sync_module.sync_source(
        "kb",
        manager.get_github_sources("kb")[0],
        base_dir=str(tmp_path),
        client=_client(["docs/logo.png", "other/guide.md"], downloads),
    )

    assert result.ok is True
    assert result.files_added == 0
    saved = manager.get_github_sources("kb")[0]
    assert saved["last_sync_status"] == "success"
    assert saved["last_synced_sha"] == "new-sha"
    assert guide.read_bytes() == b"# Existing guide\n"
    assert downloads == []
    assert indexed == []
