from __future__ import annotations

from pathlib import Path
import subprocess
import sys

from deeptutor.runtime import launcher
from deeptutor.update.jobs import JobStatus, UpdateJobStore
from deeptutor.update.source import CommandResult, SourceUpdater
from deeptutor.update.worker import run_update_worker


class _WorkerLauncher:
    def __init__(self) -> None:
        self.calls: list[tuple[Path, int]] = []

    def launch(self, store_root: Path, *, parent_pid: int) -> None:
        self.calls.append((store_root, parent_pid))


class _SuccessfulUpgrade:
    def run(self, command: list[str], *, log_path: Path) -> int:
        return 0


class _RestartLauncher:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], Path]] = []

    def launch(self, command: list[str], *, cwd: Path, log_path: Path) -> None:
        self.calls.append((command, cwd))


def _git(cwd: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        check=True,
        text=True,
    )
    return completed.stdout.strip()


class _SourceRunner:
    def __init__(self) -> None:
        self.commands: list[tuple[list[str], Path]] = []

    def run(self, command: list[str], *, cwd: Path) -> CommandResult:
        self.commands.append((command, cwd))
        if command[0] != "git":
            return CommandResult(0)
        completed = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            check=False,
            text=True,
        )
        return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def test_web_update_handoff_preserves_runtime_data_and_completes_once(
    tmp_path: Path,
) -> None:
    home = tmp_path / "runtime home"
    restart_argv = ("start", "--home", str(home.resolve()), "--dev")
    preserved = {
        home / "data" / "user" / "settings" / "system.json": (
            '{"backend_port": 8019, "frontend_port": 3799}'
        ),
        home / "data" / "knowledge_bases" / "algebra" / "meta.json": ('{"name": "Algebra"}'),
        home / "data" / "user" / "workspace" / "memory" / "profile.md": ("prefers worked examples"),
    }
    for path, content in preserved.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    store = UpdateJobStore(home / "data" / "user" / "update")
    job = store.create_pypi(
        current_version="1.5.4",
        target_version="1.6.0",
        restart_requested=True,
    )
    worker_launcher = _WorkerLauncher()

    assert launcher._handoff_pending_update(
        home,
        restart_argv=restart_argv,
        worker_launcher=worker_launcher,
        parent_pid=123,
    )
    assert worker_launcher.calls == [(store.root, 123)]

    restart_launcher = _RestartLauncher()
    assert (
        run_update_worker(
            store_root=store.root,
            parent_pid=None,
            executor=_SuccessfulUpgrade(),
            restart_launcher=restart_launcher,
        )
        == 0
    )
    assert len(restart_launcher.calls) == 1
    restart_command, restart_cwd = restart_launcher.calls[0]
    assert restart_command == [
        sys.executable,
        "-m",
        "deeptutor_cli.main",
        *restart_argv,
    ]
    assert restart_cwd == home.resolve()

    assert launcher._complete_restarted_update(home)
    assert launcher._complete_restarted_update(home) is False
    assert store.load().status is JobStatus.SUCCEEDED
    assert store.load().restart_count == 1
    for path, content in preserved.items():
        assert path.read_text(encoding="utf-8") == content


def test_source_web_job_updates_dependencies_and_restarts(tmp_path: Path) -> None:
    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    checkout = tmp_path / "checkout"
    _git(tmp_path, "init", "--bare", str(remote))
    _git(tmp_path, "init", "--initial-branch=main", str(seed))
    _git(seed, "config", "user.email", "tests@example.com")
    _git(seed, "config", "user.name", "DeepTutor Tests")
    (seed / "deeptutor").mkdir()
    (seed / "deeptutor" / "__init__.py").write_text("", encoding="utf-8")
    (seed / "pyproject.toml").write_text(
        "[project]\nname='deeptutor'\n",
        encoding="utf-8",
    )
    (seed / "web").mkdir()
    (seed / "web" / "package-lock.json").write_text("base\n", encoding="utf-8")
    (seed / "release.txt").write_text("base\n", encoding="utf-8")
    _git(seed, "add", ".")
    _git(seed, "commit", "-m", "base")
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "-u", "origin", "main")
    _git(tmp_path, "clone", str(remote), str(checkout))
    (seed / "release.txt").write_text("stable\n", encoding="utf-8")
    (seed / "web" / "package-lock.json").write_text("stable\n", encoding="utf-8")
    _git(seed, "add", ".")
    _git(seed, "commit", "-m", "stable release")
    target = _git(seed, "rev-parse", "HEAD")
    _git(seed, "tag", "v1.6.0")
    _git(seed, "push", "origin", "main", "v1.6.0")

    home = tmp_path / "home"
    restart_argv = ("start", "--home", str(home.resolve()))
    store = UpdateJobStore(home / "data" / "user" / "update")
    job = store.create_source(
        current_version="1.5.4",
        target_version="1.6.0",
        source_root=checkout,
        restart_requested=True,
    )
    worker_launcher = _WorkerLauncher()
    assert launcher._handoff_pending_update(
        home,
        restart_argv=restart_argv,
        worker_launcher=worker_launcher,
        parent_pid=123,
    )

    source_runner = _SourceRunner()
    restart_launcher = _RestartLauncher()
    assert (
        run_update_worker(
            store_root=store.root,
            parent_pid=None,
            source_updater=SourceUpdater(
                runner=source_runner,
                python_executable="python-under-test",
                bun_executable="bun",
            ),
            restart_launcher=restart_launcher,
        )
        == 0
    )

    assert _git(checkout, "rev-parse", "HEAD") == target
    assert any(
        command[:5] == ["python-under-test", "-m", "pip", "install", "--no-deps"]
        for command, _cwd in source_runner.commands
    )
    assert (["bun", "install", "--no-save"], checkout / "web") in source_runner.commands
    assert restart_launcher.calls == [
        (
            [sys.executable, "-m", "deeptutor_cli.main", *restart_argv],
            home.resolve(),
        )
    ]
    assert store.load().status is JobStatus.RESTARTING
    assert launcher._complete_restarted_update(home)
    assert store.load().status is JobStatus.SUCCEEDED
