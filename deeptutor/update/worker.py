"""Out-of-process executor for persisted update jobs."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Callable, Protocol

from packaging.version import Version

from .jobs import JobStatus, UpdateJobStore


class CommandExecutor(Protocol):
    """Boundary for executing the fixed update command."""

    def run(self, command: list[str], *, log_path: Path) -> int:
        """Run *command* without a shell and return its exit status."""


class SubprocessCommandExecutor:
    """Execute an update while appending output to the worker log."""

    def run(self, command: list[str], *, log_path: Path) -> int:
        """Run the fixed PyPI command and append its combined output."""

        with log_path.open("a", encoding="utf-8") as log:
            completed = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
                shell=False,
            )
        return completed.returncode


class RestartLauncher(Protocol):
    """Boundary for starting the updated application."""

    def launch(self, command: list[str], *, cwd: Path, log_path: Path) -> None:
        """Start the fixed restart command without waiting for it to exit."""


class SubprocessRestartLauncher:
    """Start the updated application as a detached process."""

    def launch(self, command: list[str], *, cwd: Path, log_path: Path) -> None:
        """Launch the fixed application command as a detached process."""

        kwargs: dict[str, object] = {
            "stdin": subprocess.DEVNULL,
            "stderr": subprocess.STDOUT,
            "close_fds": True,
            "shell": False,
            "cwd": str(cwd),
        }
        if os.name == "nt":
            kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
                | subprocess.DETACHED_PROCESS  # type: ignore[attr-defined]
            )
        else:
            kwargs["start_new_session"] = True
        with log_path.open("a", encoding="utf-8") as log:
            subprocess.Popen(command, stdout=log, **kwargs)  # type: ignore[arg-type,call-overload]


def build_pypi_update_command(target_version: str) -> list[str]:
    """Build the only command a PyPI update job may execute."""

    version = Version(target_version)
    if version.is_prerelease or version.is_devrelease:
        raise ValueError("Update target must be a stable version")
    return [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--upgrade",
        "--no-input",
        f"deeptutor=={version}",
    ]


def build_restart_command(restart_argv: tuple[str, ...]) -> list[str]:
    """Build the only application restart command the worker may launch."""

    if len(restart_argv) < 3 or restart_argv[:2] != ("start", "--home"):
        raise ValueError("Invalid restart arguments")
    return [
        sys.executable,
        "-m",
        "deeptutor_cli.main",
        *restart_argv,
    ]


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def wait_for_process_exit(pid: int, *, timeout: float = 60.0) -> None:
    """Wait for the scheduling CLI process to release imported files."""

    if pid <= 0 or pid == os.getpid():
        raise ValueError("Invalid parent process")
    deadline = time.monotonic() + timeout
    while _pid_is_alive(pid):
        if time.monotonic() >= deadline:
            raise TimeoutError("CLI process did not exit before update timeout")
        time.sleep(0.05)


def run_update_worker(
    *,
    store_root: Path,
    parent_pid: int | None,
    executor: CommandExecutor | None = None,
    restart_launcher: RestartLauncher | None = None,
    wait_for_parent: Callable[[int], None] = wait_for_process_exit,
) -> int:
    """Apply one persisted PyPI job and persist its terminal status."""

    store = UpdateJobStore(store_root)
    try:
        job = store.load()
    except Exception:
        return 1
    try:
        if job.status not in {JobStatus.PENDING, JobStatus.HANDOFF}:
            raise RuntimeError("Update job is not pending")
        if parent_pid is not None:
            wait_for_parent(parent_pid)
        store.mark_running(job.id)
        command = build_pypi_update_command(job.target_version)
        exit_code = (executor or SubprocessCommandExecutor()).run(
            command,
            log_path=store.log_path,
        )
        if exit_code != 0:
            store.mark_failed(job.id, f"pip exited with status {exit_code}")
            return 1
        if job.restart_requested:
            if not job.restart_home:
                raise RuntimeError("Update job is missing its restart home")
            if not job.restart_argv:
                raise RuntimeError("Update job is missing its restart arguments")
            home = Path(job.restart_home).resolve()
            store.mark_restarting(job.id)
            (restart_launcher or SubprocessRestartLauncher()).launch(
                build_restart_command(job.restart_argv),
                cwd=home,
                log_path=store.log_path,
            )
        else:
            store.mark_succeeded(job.id)
        return 0
    except Exception as exc:
        try:
            store.mark_failed(job.id, str(exc) or type(exc).__name__)
        except Exception:
            pass
        return 1


def main() -> None:
    """Run one update worker from trusted persisted arguments."""

    parser = argparse.ArgumentParser(description="DeepTutor update worker")
    parser.add_argument("--store-root", type=Path, required=True)
    parser.add_argument("--parent-pid", type=int, required=True)
    args = parser.parse_args()
    raise SystemExit(
        run_update_worker(
            store_root=args.store_root,
            parent_pid=args.parent_pid,
        )
    )


if __name__ == "__main__":
    main()
