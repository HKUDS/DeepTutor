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


def test_worker_recovery_reports_and_skips_on_corrupt_state(tmp_path: Path) -> None:
    store, _job = _handoff_job(tmp_path)
    restarted: list[UpdateJob] = []
    corrupt_state = "{ not valid json"

    def run_and_corrupt(command: list[str], cwd: Path, log_path: Path) -> int:
        store.state_path.write_text(corrupt_state, encoding="utf-8")
        return 7

    result = run_update_worker(
        store_root=store.root,
        parent_pid=123,
        wait_for_parent=lambda _pid: None,
        command_runner=run_and_corrupt,
        restart_launcher=lambda value, _log: restarted.append(value),
    )

    assert result == 1
    assert restarted == []
    assert store.state_path.read_text(encoding="utf-8") == corrupt_state
    log = store.log_path.read_text(encoding="utf-8")
    assert "recovery aborted" in log
    assert "could not be loaded" in log
    assert "pip exited with status 7" in log


def test_worker_marks_failed_when_the_launcher_exits_early(tmp_path: Path) -> None:
    store, _job = _handoff_job(tmp_path)
    launches: list[UpdateJob] = []

    class ExitedProcess:
        def wait(self, timeout: float | None = None) -> int:
            return 23

    def restart(value: UpdateJob, _log_path: Path) -> ExitedProcess:
        launches.append(value)
        return ExitedProcess()

    result = run_update_worker(
        store_root=store.root,
        parent_pid=123,
        wait_for_parent=lambda _pid: None,
        command_runner=lambda _command, _cwd, _log: 0,
        restart_launcher=restart,
    )

    assert result == 1
    assert len(launches) == 1, "a launcher that just failed must not be spawned again"
    job = store.load()
    assert job.status == "failed"
    assert job.error is not None and "exited with status 23" in job.error


def test_worker_leaves_a_live_launcher_in_restarting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _job = _handoff_job(tmp_path)
    monkeypatch.setattr("deeptutor.runtime.update_worker.RESTART_STARTUP_GRACE_SECONDS", 0.0)

    class LiveProcess:
        def wait(self, timeout: float | None = None) -> int:
            import subprocess

            raise subprocess.TimeoutExpired("launcher", timeout or 0)

    result = run_update_worker(
        store_root=store.root,
        parent_pid=123,
        wait_for_parent=lambda _pid: None,
        command_runner=lambda _command, _cwd, _log: 0,
        restart_launcher=lambda _job, _log: LiveProcess(),
    )

    assert result == 0
    assert store.load().status == "restarting"


def test_update_command_upgrades_every_installed_module(monkeypatch: pytest.MonkeyPatch) -> None:
    from deeptutor.modules import catalog

    monkeypatch.setattr(
        catalog,
        "installed_distributions",
        lambda: ["deeptutor-server", "deeptutor-web", "deeptutor-parsing"],
    )

    command = build_update_command("1.7.2")

    assert command[-4:] == [
        "deeptutor==1.7.2",
        "deeptutor-server==1.7.2",
        "deeptutor-web==1.7.2",
        "deeptutor-parsing==1.7.2",
    ]


def test_update_command_keeps_core_only_installs_light(monkeypatch: pytest.MonkeyPatch) -> None:
    from deeptutor.modules import catalog

    monkeypatch.setattr(catalog, "installed_distributions", lambda: [])

    command = build_update_command("1.7.2")

    # Compare package arguments only: the interpreter path itself can contain
    # "deeptutor-" when the venv is named "deeptutor-dev-venv".
    specs = command[command.index("--upgrade") + 1 :]
    assert specs == ["deeptutor==1.7.2"]


def test_update_command_rejects_non_stable_or_injected_versions() -> None:
    with pytest.raises(ValueError):
        build_update_command("1.7.0rc1")
    with pytest.raises(ValueError):
        build_update_command("1.7.0; touch /tmp/nope")


def test_restart_ignores_stale_package_under_runtime_home(tmp_path, monkeypatch):
    import os
    import sys

    from deeptutor.runtime import update_worker

    _, job = _handoff_job(tmp_path)
    home = Path(job.restart_home)
    (home / "dt_probe.py").write_text("raise RuntimeError('stale source')", encoding="utf-8")
    installed = tmp_path / "installed"
    installed.mkdir()
    (installed / "dt_probe.py").write_text("print('installed package')", encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(installed))
    monkeypatch.delenv("PYTHONSAFEPATH", raising=False)
    monkeypatch.setattr(
        update_worker, "build_restart_command", lambda _: ([sys.executable, "-m", "dt_probe"], home)
    )
    log = tmp_path / "restart.log"
    process = update_worker._launch_restart(job, log_path=log)
    assert process.wait(timeout=15) == 0
    assert "installed package" in log.read_text()
