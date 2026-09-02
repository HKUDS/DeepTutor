"""Detached executor for a launcher-managed DeepTutor update."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess  # nosec B404 - commands are fixed and validated below
import sys
import time
from typing import Callable

from deeptutor.runtime.process import is_process_alive
from deeptutor.services.app_update import UpdateJob, UpdateJobStore


def build_update_command(target_version: str) -> list[str]:
    """Return the only package mutation the worker is allowed to execute."""

    # Round-trip through the job validator instead of accepting arbitrary text.
    validated = UpdateJob.from_dict(
        {
            "schema_version": 1,
            "id": "validation",
            "status": "pending",
            "current_version": target_version,
            "target_version": target_version,
            "created_at": "validation",
        }
    ).target_version
    return [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--no-input",
        "--disable-pip-version-check",
        "--upgrade",
        f"deeptutor=={validated}",
    ]


def build_restart_command(job: UpdateJob) -> tuple[list[str], Path]:
    if not job.restart_home or not job.restart_argv:
        raise ValueError("Update job is missing restart information")
    home = Path(job.restart_home).resolve()
    # UpdateJob.from_dict already restricts restart_argv to
    # `start --home <same-home> [--dev]`; preserve that exact trusted vector.
    return [sys.executable, "-m", "deeptutor_cli.main", *job.restart_argv], home


def _pid_is_alive(pid: int) -> bool:
    return is_process_alive(pid)


def wait_for_process_exit(pid: int, *, timeout: float = 60.0) -> None:
    if pid <= 0 or pid == os.getpid():
        raise ValueError("Invalid launcher process")
    deadline = time.monotonic() + timeout
    while _pid_is_alive(pid):
        if time.monotonic() >= deadline:
            raise TimeoutError("Launcher did not exit before the update timeout")
        time.sleep(0.05)


def _run_logged(command: list[str], *, cwd: Path, log_path: Path) -> int:
    with log_path.open("a", encoding="utf-8") as log:
        completed = subprocess.run(  # nosec B603
            command,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
            shell=False,
            env={**os.environ, "PIP_DISABLE_PIP_VERSION_CHECK": "1"},
        )
    return completed.returncode


def _launch_restart(job: UpdateJob, *, log_path: Path) -> None:
    command, home = build_restart_command(job)
    kwargs: dict[str, object] = {
        "cwd": str(home),
        "stdin": subprocess.DEVNULL,
        "stderr": subprocess.STDOUT,
        "close_fds": True,
        "shell": False,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
            | subprocess.DETACHED_PROCESS  # type: ignore[attr-defined]
        )
    else:
        kwargs["start_new_session"] = True
    with log_path.open("a", encoding="utf-8") as log:
        subprocess.Popen(  # type: ignore[arg-type,call-overload] # nosec B603
            command, stdout=log, **kwargs
        )


def run_update_worker(
    *,
    store_root: Path,
    parent_pid: int,
    wait_for_parent: Callable[[int], None] = wait_for_process_exit,
    command_runner: Callable[[list[str], Path, Path], int] | None = None,
    restart_launcher: Callable[[UpdateJob, Path], None] | None = None,
) -> int:
    """Install the target, then restore the application on either outcome."""

    store = UpdateJobStore(store_root)
    try:
        job = store.load()
        if job.status != "handoff":
            raise RuntimeError("Update job is not awaiting the worker")
        wait_for_parent(parent_pid)
        job = store.mark_running(job.id)
        runner = command_runner or (
            lambda command, cwd, log_path: _run_logged(command, cwd=cwd, log_path=log_path)
        )
        exit_code = runner(
            build_update_command(job.target_version), Path(job.restart_home or "."), store.log_path
        )
        if exit_code != 0:
            raise RuntimeError(f"pip exited with status {exit_code}")
        job = store.mark_restarting(job.id)
        (restart_launcher or (lambda value, path: _launch_restart(value, log_path=path)))(
            job,
            store.log_path,
        )
        return 0
    except Exception as exc:
        try:
            current = store.load()
            if current.status not in {"succeeded", "failed"}:
                current = store.mark_failed(current.id, str(exc) or type(exc).__name__)
            if current.restart_home and current.restart_argv:
                (restart_launcher or (lambda value, path: _launch_restart(value, log_path=path)))(
                    current,
                    store.log_path,
                )
        except Exception:
            pass
        return 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply a managed DeepTutor update")
    parser.add_argument("--store-root", type=Path, required=True)
    parser.add_argument("--parent-pid", type=int, required=True)
    args = parser.parse_args()
    raise SystemExit(run_update_worker(store_root=args.store_root, parent_pid=args.parent_pid))


if __name__ == "__main__":
    main()
