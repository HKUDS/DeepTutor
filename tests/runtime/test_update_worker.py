from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.runtime.update_worker import build_update_command, run_update_worker
from deeptutor.services.app_update import UpdateJob, UpdateJobStore


def _handoff_job(tmp_path: Path) -> tuple[UpdateJobStore, UpdateJob]:
    store = UpdateJobStore(tmp_path / "update")
    pending = store.create(current_version="1.6.1", target_version="1.7.0")
    home = tmp_path / "home"
    home.mkdir()
    job = store.prepare_handoff(
        pending.id,
        home=home,
        restart_argv=["start", "--home", str(home.resolve())],
    )
    return store, job


def test_worker_updates_then_restarts(tmp_path: Path) -> None:
    store, job = _handoff_job(tmp_path)
    captured: dict[str, object] = {}

    def run(command: list[str], cwd: Path, log_path: Path) -> int:
        captured.update(command=command, cwd=cwd, log_path=log_path)
        return 0

    def restart(value: UpdateJob, log_path: Path) -> None:
        captured.update(restart=value, restart_log=log_path)

    result = run_update_worker(
        store_root=store.root,
        parent_pid=123,
        wait_for_parent=lambda pid: captured.update(parent_pid=pid),
        command_runner=run,
        restart_launcher=restart,
    )

    assert result == 0
    assert captured["parent_pid"] == 123
    assert captured["command"] == build_update_command("1.7.0")
    assert isinstance(captured["restart"], UpdateJob)
    assert store.load().status == "restarting"
    assert store.load().restart_count == 1


def test_worker_failure_is_durable_and_restores_app(tmp_path: Path) -> None:
    store, _job = _handoff_job(tmp_path)
    restarted: list[UpdateJob] = []

    result = run_update_worker(
        store_root=store.root,
        parent_pid=123,
        wait_for_parent=lambda _pid: None,
        command_runner=lambda _command, _cwd, _log: 7,
        restart_launcher=lambda value, _log: restarted.append(value),
    )

    assert result == 1
    assert store.load().status == "failed"
    assert store.load().error == "pip exited with status 7"
    assert restarted and restarted[0].status == "failed"


def test_update_command_rejects_non_stable_or_injected_versions() -> None:
    with pytest.raises(ValueError):
        build_update_command("1.7.0rc1")
    with pytest.raises(ValueError):
        build_update_command("1.7.0; touch /tmp/nope")
