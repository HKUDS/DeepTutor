"""Workspace-scoped notebook manager initialization."""

from concurrent.futures import ThreadPoolExecutor
import threading

import pytest

from deeptutor.services.notebook import service
from deeptutor.services.path_service import PathService


def test_concurrent_first_access_shares_one_manager(tmp_path, monkeypatch) -> None:
    paths = PathService(workspace_root=tmp_path)
    monkeypatch.setattr(service, "get_path_service", lambda: paths)
    monkeypatch.setattr(service, "_instances", {})
    constructing = threading.Event()
    second_started = threading.Event()
    second_constructing = threading.Event()
    release = threading.Event()
    calls = []

    class SlowManager(service.NotebookManager):
        def __init__(self, base_dir=None):
            calls.append(self)
            if len(calls) == 1:
                constructing.set()
                assert release.wait(5), "first constructor was not released"
            else:
                second_constructing.set()
            super().__init__(base_dir=base_dir)

    monkeypatch.setattr(service, "NotebookManager", SlowManager)

    def get_second_manager():
        second_started.set()
        return service.get_notebook_manager()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(service.get_notebook_manager)
        try:
            assert constructing.wait(5), "first constructor did not start"
            second = pool.submit(get_second_manager)
            assert second_started.wait(5), "second caller did not start"
            # On the old factory the second caller constructs another manager
            # while the first is paused. With serialized initialization it waits.
            second_constructing.wait(0.5)
        finally:
            release.set()
        first_manager = first.result(timeout=5)
        second_manager = second.result(timeout=5)

    assert first_manager is second_manager
    assert len(calls) == 1
    assert service.get_notebook_manager() is first_manager


def test_concurrent_proxy_saves_keep_every_record(tmp_path, monkeypatch) -> None:
    paths = PathService(workspace_root=tmp_path)
    monkeypatch.setattr(service, "get_path_service", lambda: paths)
    monkeypatch.setattr(service, "_instances", {})
    notebook_id = service.NotebookManager(str(paths.get_notebook_dir())).create_notebook("Race")[
        "id"
    ]

    def save(index):
        return service.notebook_manager.add_record(
            [notebook_id], "chat", f"record-{index}", "query", f"body-{index}"
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(save, range(24)))

    assert all(result["added_to_notebooks"] == [notebook_id] for result in results)
    reloaded = service.NotebookManager(str(paths.get_notebook_dir())).get_notebook(notebook_id)
    assert {record["title"] for record in reloaded["records"]} == {
        f"record-{index}" for index in range(24)
    }
    assert service.notebook_manager.list_notebooks()[0]["record_count"] == 24


def test_manager_registry_keeps_workspaces_separate(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(service, "_instances", {})
    paths = PathService(workspace_root=tmp_path / "first")
    monkeypatch.setattr(service, "get_path_service", lambda: paths)
    first = service.get_notebook_manager()
    notebook = first.create_notebook("First workspace")

    paths = PathService(workspace_root=tmp_path / "second")
    second = service.get_notebook_manager()
    assert second is not first
    assert second.list_notebooks() == []

    paths = PathService(workspace_root=tmp_path / "first")
    assert service.get_notebook_manager() is first
    assert first.get_notebook(notebook["id"])["name"] == "First workspace"


def test_failed_initialization_can_be_retried(tmp_path, monkeypatch) -> None:
    paths = PathService(workspace_root=tmp_path)
    monkeypatch.setattr(service, "get_path_service", lambda: paths)
    monkeypatch.setattr(service, "_instances", {})
    manager_type = service.NotebookManager

    def unavailable(base_dir=None):
        raise OSError("notebook directory unavailable")

    monkeypatch.setattr(service, "NotebookManager", unavailable)
    with pytest.raises(OSError, match="notebook directory unavailable"):
        service.get_notebook_manager()

    monkeypatch.setattr(service, "NotebookManager", manager_type)
    with ThreadPoolExecutor(max_workers=1) as pool:
        manager = pool.submit(service.get_notebook_manager).result(timeout=5)
    assert manager.create_notebook("Retry")["name"] == "Retry"
