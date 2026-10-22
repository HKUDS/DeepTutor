"""Own a MinerU CLI tree; settle it before publishing parser output."""

from contextlib import contextmanager
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Any


def _process_group_exists(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # An inaccessible group is still indistinguishable from a live group.
        return True
    return True


@contextmanager
def cli_process(cmd: list[str], log_path: Path, env: dict[str, str]):
    """Run a CLI with attempt-owned descendants and settle them on every exit."""
    process = None
    job = None
    assigned = False
    with log_path.open("wb") as output:
        try:
            kwargs: dict[str, Any] = {
                "stdout": output,
                "stderr": subprocess.STDOUT,
                "shell": False,
                "env": env,
            }
            if sys.platform == "win32":
                import psutil
                import win32api
                import win32con
                import win32job
                import win32process

                job = win32job.CreateJobObject(None, "")
                limits = win32job.QueryInformationJobObject(
                    job, win32job.JobObjectExtendedLimitInformation
                )
                limits["BasicLimitInformation"]["LimitFlags"] |= (
                    win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                )
                win32job.SetInformationJobObject(
                    job, win32job.JobObjectExtendedLimitInformation, limits
                )
                # Attach before execution: no child can escape an assignment race.
                kwargs["creationflags"] = win32con.CREATE_SUSPENDED | subprocess.CREATE_NO_WINDOW
                process = subprocess.Popen(cmd, **kwargs)  # nosec B603: fixed argv, shell=False
                win32job.AssignProcessToJobObject(job, int(process._handle))
                assigned = True
                threads = psutil.Process(process.pid).threads()
                if len(threads) != 1:
                    raise RuntimeError("Cannot identify the suspended MinerU main thread")
                thread = win32api.OpenThread(win32con.THREAD_SUSPEND_RESUME, False, threads[0].id)
                try:
                    win32process.ResumeThread(thread)
                finally:
                    thread.Close()
            else:
                process = subprocess.Popen(cmd, start_new_session=True, **kwargs)  # nosec B603
            yield process
        finally:
            if sys.platform == "win32" and job is not None:
                try:
                    if process is not None and not assigned:
                        process.kill()  # Still suspended; cannot have spawned a child.
                    win32job.TerminateJobObject(job, 1)
                    deadline = time.monotonic() + 5
                    while win32job.QueryInformationJobObject(
                        job, win32job.JobObjectBasicAccountingInformation
                    )["ActiveProcesses"]:
                        if time.monotonic() >= deadline:
                            raise RuntimeError("MinerU process-tree cleanup did not settle")
                        time.sleep(0.05)
                finally:
                    job.Close()
            elif process is not None:
                cleanup_deadline = time.monotonic() + 5
                for sig, grace in ((signal.SIGTERM, 0.5), (signal.SIGKILL, 4.5)):
                    try:
                        os.killpg(process.pid, sig)
                    except ProcessLookupError:
                        break
                    except PermissionError:
                        pass
                    if process.poll() is None:
                        try:
                            process.wait(timeout=grace)
                        except subprocess.TimeoutExpired:
                            pass
                    group_exists = True
                    while group_exists and time.monotonic() < cleanup_deadline:
                        group_exists = _process_group_exists(process.pid)
                        if group_exists:
                            time.sleep(0.05)
                    if not group_exists:
                        break
                if process.poll() is None:
                    try:
                        process.kill()
                    except OSError:
                        pass
                    process.wait(timeout=5)
