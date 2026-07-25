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
    wait_for_parent: Callable[[int], None] = wait_for_process_exit,
) -> int:
    """Apply one persisted PyPI job and persist its terminal status."""

    store = UpdateJobStore(store_root)
    try:
        job = store.load()
    except Exception:
        return 1
    try:
        if job.status is not JobStatus.PENDING:
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
