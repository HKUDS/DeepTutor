"""Own a MinerU CLI tree; settle it before publishing parser output."""

from contextlib import contextmanager
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Any


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
                for sig in (signal.SIGTERM, signal.SIGKILL):
                    try:
                        os.killpg(process.pid, sig)
                    except ProcessLookupError:
                        break
                    except PermissionError:
                        if _process_group_alive(process.pid):
                            raise
                        break
            if process is not None:
                process.wait(timeout=5)
            if sys.platform != "win32" and process is not None:
                deadline = time.monotonic() + 5
                while _process_group_alive(process.pid):
                    if time.monotonic() >= deadline:
                        raise RuntimeError("MinerU process-tree cleanup did not settle")
                    time.sleep(0.05)


def _process_group_alive(pgid: int) -> bool:
    """A killed group may remain visible while init reaps its zombies."""
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Darwin also reports EPERM on a group containing only zombies.
        pass

    if sys.platform != "darwin":
        import psutil

        saw_member = False
        for proc in psutil.process_iter():
            try:
                if os.getpgid(proc.pid) != pgid:
                    continue
                saw_member = True
                if proc.status() not in {psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD}:
                    return True
            except (ProcessLookupError, psutil.NoSuchProcess):
                continue
            except psutil.AccessDenied:
                return True
        return not saw_member

    # On Darwin getpgid(pid) can no longer resolve an unreaped zombie;
    # ps exposes the kernel group and state together on both POSIX targets.
    rows = subprocess.check_output(  # nosec B603 B607 -- fixed POSIX utility, no shell
        ["/bin/ps", "-Ao", "pgid=,stat="], text=True, timeout=2
    )
    states = [
        state
        for group, state in (line.split() for line in rows.splitlines() if line.strip())
        if group == str(pgid)
    ]
    # An existing group hidden from inspection must not be declared settled.
    return not states or any(not state.startswith("Z") for state in states)
