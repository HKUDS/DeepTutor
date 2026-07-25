from __future__ import annotations

from pathlib import Path
import sys

from deeptutor.runtime import launcher
from deeptutor.update.jobs import JobStatus, UpdateJobStore
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
