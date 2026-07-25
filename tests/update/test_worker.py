from __future__ import annotations

import json
from pathlib import Path
import sys

from deeptutor.update import InstallMode
from deeptutor.update.jobs import JobStatus, UpdateJobStore
from deeptutor.update.source import SourceUpdateError
from deeptutor.update.worker import run_update_worker


class RecordingExecutor:
    def __init__(self, exit_code: int) -> None:
        self.exit_code = exit_code
        self.commands: list[list[str]] = []

    def run(self, command: list[str], *, log_path: Path) -> int:
        self.commands.append(command)
        return self.exit_code


class RecordingRestartLauncher:
    def __init__(self) -> None:
        self.commands: list[tuple[list[str], Path]] = []

    def launch(self, command: list[str], *, cwd: Path, log_path: Path) -> None:
        self.commands.append((command, cwd))


def test_worker_waits_for_cli_exit_then_runs_fixed_pypi_upgrade(tmp_path: Path) -> None:
    store = UpdateJobStore(tmp_path)
    store.create_pypi(current_version="1.5.4", target_version="1.6.0")
    executor = RecordingExecutor(exit_code=0)
    events: list[str] = []

    exit_code = run_update_worker(
        store_root=tmp_path,
        parent_pid=123,
        executor=executor,
        wait_for_parent=lambda pid: events.append(f"wait:{pid}"),
    )

    assert exit_code == 0
    assert events == ["wait:123"]
    assert executor.commands == [
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--upgrade",
            "--no-input",
            "deeptutor==1.6.0",
        ]
    ]
    assert store.load().status is JobStatus.SUCCEEDED


def test_worker_persists_failed_command_status(tmp_path: Path) -> None:
    store = UpdateJobStore(tmp_path)
    store.create_pypi(current_version="1.5.4", target_version="1.6.0")
    executor = RecordingExecutor(exit_code=7)

    exit_code = run_update_worker(
        store_root=tmp_path,
        parent_pid=None,
        executor=executor,
        wait_for_parent=lambda pid: None,
    )

    job = store.load()
    assert exit_code == 1
    assert job.status is JobStatus.FAILED
    assert job.error == "pip exited with status 7"


def test_worker_rejects_a_tampered_target_without_running_a_command(tmp_path: Path) -> None:
    store = UpdateJobStore(tmp_path)
    store.create_pypi(current_version="1.5.4", target_version="1.6.0")
    payload = json.loads(store.state_path.read_text(encoding="utf-8"))
    payload["target_version"] = "1.6.0 --extra-index-url https://example.invalid"
    store.state_path.write_text(json.dumps(payload), encoding="utf-8")
    executor = RecordingExecutor(exit_code=0)

    exit_code = run_update_worker(
        store_root=tmp_path,
        parent_pid=None,
        executor=executor,
        wait_for_parent=lambda pid: None,
    )

    assert exit_code == 1
    assert executor.commands == []
    assert store.load().status is JobStatus.FAILED


def test_web_worker_restarts_the_same_home_exactly_once_after_upgrade(tmp_path: Path) -> None:
    home = tmp_path / "runtime home"
    restart_argv = ("start", "--home", str(home.resolve()), "--dev")
    store = UpdateJobStore(tmp_path / "jobs")
    job = store.create_pypi(
        current_version="1.5.4",
        target_version="1.6.0",
        restart_requested=True,
    )
    store.prepare_restart(job.id, home=home, restart_argv=restart_argv)
    restart_launcher = RecordingRestartLauncher()

    exit_code = run_update_worker(
        store_root=store.root,
        parent_pid=None,
        executor=RecordingExecutor(exit_code=0),
        restart_launcher=restart_launcher,
        wait_for_parent=lambda pid: None,
    )

    assert exit_code == 0
    assert restart_launcher.commands == [
        (
            [
                sys.executable,
                "-m",
                "deeptutor_cli.main",
                *restart_argv,
            ],
            home.resolve(),
        )
    ]
    restarted = store.load()
    assert restarted.status is JobStatus.RESTARTING
    assert restarted.restart_count == 1


def test_web_worker_applies_a_source_job_before_restarting(tmp_path: Path) -> None:
    home = tmp_path / "home"
    checkout = tmp_path / "checkout"
    store = UpdateJobStore(tmp_path / "jobs")
    job = store.create_source(
        current_version="1.5.4",
        target_version="1.6.0",
        source_root=checkout,
        restart_requested=True,
    )
    store.prepare_restart(job.id, home=home)
    seen: dict[str, object] = {}

    class SourceUpdater:
        def update(self, installation, target_version):
            seen["installation"] = installation
            seen["target_version"] = target_version

    restart_launcher = RecordingRestartLauncher()
    exit_code = run_update_worker(
        store_root=store.root,
        parent_pid=None,
        source_updater=SourceUpdater(),
        restart_launcher=restart_launcher,
    )

    assert exit_code == 0
    installation = seen["installation"]
    assert installation.mode is InstallMode.SOURCE_WEB
    assert installation.source_root == checkout.resolve()
    assert seen["target_version"] == "1.6.0"
    assert len(restart_launcher.commands) == 1
    assert store.load().status is JobStatus.RESTARTING


def test_failed_source_job_attempts_to_restore_the_app_once(tmp_path: Path) -> None:
    home = tmp_path / "home"
    store = UpdateJobStore(tmp_path / "jobs")
    job = store.create_source(
        current_version="1.5.4",
        target_version="1.6.0",
        source_root=tmp_path / "checkout",
        restart_requested=True,
    )
    store.prepare_restart(job.id, home=home)

    class BrokenSourceUpdater:
        def update(self, installation, target_version):
            raise SourceUpdateError("dependency refresh failed")

    restart_launcher = RecordingRestartLauncher()
    exit_code = run_update_worker(
        store_root=store.root,
        parent_pid=None,
        source_updater=BrokenSourceUpdater(),
        restart_launcher=restart_launcher,
    )

    failed = store.load()
    assert exit_code == 1
    assert failed.status is JobStatus.FAILED
    assert failed.error == "dependency refresh failed"
    assert len(restart_launcher.commands) == 1
