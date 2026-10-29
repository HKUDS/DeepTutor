"""Cross-platform liveness checks and cleanup of owned subprocess trees."""

from __future__ import annotations

import os
import signal
import subprocess
import time


def kill_process_tree(pid: int) -> None:
    """Kill an owned child (started in a new POSIX session) and its helpers.

    Callers still reap their process/streams before releasing runtime leases.
    Windows Process.kill() alone leaves build and renderer children running.
    """
    if os.name != "nt":
        for attempt in range(5):
            try:
                os.killpg(pid, signal.SIGKILL)
                return
            except ProcessLookupError:
                return
            except PermissionError:
                # macOS can briefly report EPERM (even for signal 0) while
                # reaping a group. Retry only briefly; persistent permission
                # failures must still reach the caller, never imply cleanup.
                if attempt == 4:
                    raise
                time.sleep(0.01)
        return
    # Fixed Windows utility and argument list; no shell or caller-supplied executable.
    result = subprocess.run(  # nosec B607
        ["taskkill", "/PID", str(pid), "/T", "/F"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=10,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode not in (0, 128):
        raise RuntimeError(f"Could not terminate process tree {pid}: {result.returncode}")


def _is_windows_process_alive(pid: int) -> bool:
    try:
        import ctypes
        from ctypes import wintypes

        process_query_limited_information = 0x1000
        still_active = 259
        win_dll = getattr(ctypes, "WinDLL", None)
        if win_dll is None:
            return False
        kernel32 = win_dll("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return False
        try:
            exit_code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
    except (AttributeError, OSError):
        return False


def is_process_alive(pid: int | None) -> bool:
    """Return whether ``pid`` is alive without signalling or terminating it."""

    if pid is None or pid <= 0:
        return False
    if os.name == "nt":
        # CPython implements ordinary os.kill signals with TerminateProcess on
        # Windows, so os.kill(pid, 0) is destructive rather than a POSIX probe.
        return _is_windows_process_alive(pid)
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


__all__ = ["is_process_alive", "kill_process_tree"]
