"""Own a MinerU CLI tree; settle it before publishing parser output."""

from contextlib import contextmanager
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Any

#: How long the process tree gets to disappear after the kill signals. Shared
#: with the Windows job-object loop below so both platforms give up at the same
#: point; a test can shorten it instead of waiting the real deadline.
_PROCESS_SETTLE_SECONDS = 5.0


class ProcessTreeNotSettled(RuntimeError):
    """The CLI tree did not go away within the settle deadline.

    Distinct from a generic failure so the caller can report "cleanup failed"
    rather than "the parser crashed": the parse may well have produced usable
    artifacts, and only the teardown is in doubt (#2426).
    """


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
                    deadline = time.monotonic() + _PROCESS_SETTLE_SECONDS
                    while win32job.QueryInformationJobObject(
                        job, win32job.JobObjectBasicAccountingInformation
                    )["ActiveProcesses"]:
                        if time.monotonic() >= deadline:
                            raise ProcessTreeNotSettled("MinerU process-tree cleanup did not settle")
                        time.sleep(0.05)
                finally:
                    job.Close()
            elif process is not None:
                for sig in (signal.SIGTERM, signal.SIGKILL):
                    try:
                        os.killpg(process.pid, sig)
                    except ProcessLookupError:
                        break
            if process is not None:
                process.wait(timeout=5)
            # Reaping the direct child says nothing about the group: ``killpg``
            # only queues the signal, and a CLI that exits on its own is reaped
            # before the signal even lands on what it spawned. Publishing the
            # parse at that point leaves those descendants running (#2426), so
            # the group is polled until it is empty — the same "settle or fail
            # loudly" contract the Windows branch above enforces on its job
            # object, with the same deadline.
            if sys.platform != "win32" and process is not None:
                deadline = time.monotonic() + _PROCESS_SETTLE_SECONDS
                while _process_group_alive(process.pid):
                    if time.monotonic() >= deadline:
                        raise ProcessTreeNotSettled("MinerU process-tree cleanup did not settle")
                    time.sleep(0.05)


def _process_group_alive(pgid: int) -> bool:
    """Whether the process group still has a signalable member.

    Signal 0 performs the permission and existence checks without delivering
    anything. The group disappears once its last member is gone, so
    ``ProcessLookupError`` is the settled state. A member that was reparented
    and left unreaped does not keep the group alive, verified on Linux, so this
    cannot spin forever on a zombie.
    """
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return False
    return True
