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
from deeptutor.services.app_update import (
    UpdateJob,
    UpdateJobStore,
    installed_update_packages,
    legacy_cli_migration_required,
    validate_update_packages,
)


def build_update_command(target_version: str, packages: tuple[str, ...] = ()) -> list[str]:
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
        *(f"{name}=={validated}" for name in validate_update_packages(packages) or ()),
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


def _launch_restart(job: UpdateJob, *, log_path: Path) -> subprocess.Popen:
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
        return subprocess.Popen(  # type: ignore[arg-type,call-overload] # nosec B603
            command, stdout=log, **kwargs
        )


def wait_for_restart(
    store: UpdateJobStore,
    job: UpdateJob,
    process: subprocess.Popen,
    *,
    timeout: float = 300.0,
) -> None:
    """Wait for the existing launcher's readiness receipt or bounded failure."""
    deadline = time.monotonic() + timeout
    while True:
        current = store.load()
        if current.id != job.id:
            raise RuntimeError("Update job ownership changed during restart")
        if current.status == "succeeded":
            return
        if current.status == "failed":
            raise RuntimeError(current.error or "Restart failed")
        code = process.poll()
        if code is not None:
            try:
                with store.log_path.open("rb") as log:
                    log.seek(0, os.SEEK_END)
                    log.seek(max(0, log.tell() - 2048))
                    tail = log.read().decode("utf-8", errors="replace")[-700:].strip()
            except OSError:
                tail = ""
            raise RuntimeError(
                f"Restart launcher exited with status {code}" + (f": {tail}" if tail else "")
            )
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"Restart launcher did not report readiness within {timeout:g} seconds"
            )
        time.sleep(0.1)


def _log_aborted_recovery(
    store: UpdateJobStore, *, original: Exception, load_error: Exception
) -> None:
    """Leave a durable record when recovery cannot even read the job state."""

    message = (
        "update worker: recovery aborted; update state could not be loaded "
        f"({type(load_error).__name__}: {load_error}). "
        f"Original failure: {type(original).__name__}: {original}. "
        "The job state was left untouched; inspect it before restarting DeepTutor.\n"
    )
    try:
        with store.log_path.open("a", encoding="utf-8") as log:
            log.write(message)
    except OSError:
        # The launcher redirects worker stderr into this same log file; if the
        # file itself is unreachable there is nowhere durable left to report.
        print(message, file=sys.stderr)


def run_update_worker(
    *,
    store_root: Path,
    parent_pid: int,
    wait_for_parent: Callable[[int], None] = wait_for_process_exit,
    command_runner: Callable[[list[str], Path, Path], int] | None = None,
    restart_launcher: Callable[[UpdateJob, Path], subprocess.Popen | None] | None = None,
    restart_timeout: float = 300.0,
) -> int:
    """Install the target, then restore the application on either outcome."""

    store = UpdateJobStore(store_root)
    installed = False
    job: UpdateJob | None = None
    try:
        job = store.load()
        if job.status != "handoff":
            raise RuntimeError("Update job is not awaiting the worker")
        if legacy_cli_migration_required():
            raise RuntimeError(
                "Uninstall legacy deeptutor-cli before upgrading and keep the same runtime home."
            )
        wait_for_parent(parent_pid)
        job = store.mark_running(job.id)
        packages = job.packages
        if packages is None:
            # Older queued jobs have no snapshot; this still runs before pip.
            packages = installed_update_packages(job.current_version)
        runner = command_runner or (
            lambda command, cwd, log_path: _run_logged(command, cwd=cwd, log_path=log_path)
        )
        exit_code = runner(
            build_update_command(job.target_version, packages),
            Path(job.restart_home or "."),
            store.log_path,
        )
        if exit_code != 0:
            raise RuntimeError(f"pip exited with status {exit_code}")
        installed = True
        job = store.mark_restarting(job.id)
        process = (restart_launcher or (lambda value, path: _launch_restart(value, log_path=path)))(
            job,
            store.log_path,
        )
        if process is not None:
            wait_for_restart(store, job, process, timeout=restart_timeout)
        return 0
    except Exception as exc:
        try:
            current = store.load()
        except Exception as load_error:
            # Corrupt or unreadable state: both mark_failed and the trusted
            # restart vector come from it, so record why and skip this round
            # instead of exiting silently.
            _log_aborted_recovery(store, original=exc, load_error=load_error)
            return 1
        if job is not None and current.id != job.id:
            print(
                f"Update {job.id} lost ownership; preserving job {current.id}. Original failure: {exc}",
                file=sys.stderr,
            )
            return 1
        try:
            if current.status not in {"succeeded", "failed"}:
                current = store.mark_failed(current.id, str(exc) or type(exc).__name__)
            if not installed and current.restart_home and current.restart_argv:
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
