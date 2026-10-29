"""Real process regressions for bounded, tree-wide launcher shutdown."""

from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

import psutil
import pytest

from deeptutor.runtime import launcher

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX sessions and signals")


def _wait_file(path: Path) -> str:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if path.exists() and (text := path.read_text()):
            return text
        time.sleep(0.01)
    pytest.fail(f"test process did not become ready: {path}")


def _alive(pid: int) -> bool:
    try:
        proc = psutil.Process(pid)
        return proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def _spawn(code: str) -> launcher.ManagedProcess:
    proc = subprocess.Popen([sys.executable, "-c", code], start_new_session=True)
    return launcher.ManagedProcess("test-worker", proc, proc.pid)


def _cleanup(proc: launcher.ManagedProcess, child_pids: list[int] = ()) -> None:
    for pid in child_pids:
        try:
            psutil.Process(pid).kill()
        except psutil.NoSuchProcess:
            pass
    try:
        os.killpg(proc.pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    proc.process.wait(timeout=3)


def test_terminates_services_together_and_reaps_stubborn_children(tmp_path, monkeypatch):
    """Both services receive TERM before either service gets its grace period."""
    monkeypatch.setattr(launcher, "SHUTDOWN_GRACE_SECONDS", 0.3)
    workers = []
    try:
        for index in range(2):
            ready, stopped = tmp_path / f"ready{index}", tmp_path / f"term{index}"
            workers.append(
                _spawn(f"""
import signal, time
from pathlib import Path
signal.signal(signal.SIGTERM, lambda *_: Path({str(stopped)!r}).write_text(str(time.monotonic())))
Path({str(ready)!r}).write_text('ready')
while True: time.sleep(1)
""")
            )
            _wait_file(ready)
        started = time.monotonic()
        launcher._terminate_all(workers)
        elapsed = time.monotonic() - started
        times = [float((tmp_path / f"term{i}").read_text()) for i in range(2)]
        assert max(times) - started < 0.25
        assert elapsed < 1.5
        assert all(w.process.returncode == -signal.SIGKILL for w in workers)
    finally:
        for worker in workers:
            _cleanup(worker)


def test_kills_separate_session_child_after_parent_exits(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "SHUTDOWN_GRACE_SECONDS", 0.2)
    ready = tmp_path / "child"
    child_code = f"""
import os, signal, time
from pathlib import Path
signal.signal(signal.SIGTERM, signal.SIG_IGN)
Path({str(ready)!r}).write_text(str(os.getpid()))
while True: time.sleep(1)
"""
    worker = _spawn(f"""
import subprocess, sys, time
subprocess.Popen([sys.executable, '-c', {child_code!r}], start_new_session=True)
while True: time.sleep(1)
""")
    children = []
    try:
        children.append(int(_wait_file(ready)))
        assert os.getpgid(children[0]) != worker.pgid
        launcher._terminate_all([worker])
        assert worker.process.returncode is not None
        assert not _alive(children[0])
    finally:
        _cleanup(worker, children)


def test_cleans_group_even_when_its_leader_already_exited(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "SHUTDOWN_GRACE_SECONDS", 0.2)
    ready = tmp_path / "child"
    child_code = f"""
import os, signal, time
from pathlib import Path
signal.signal(signal.SIGTERM, signal.SIG_IGN)
Path({str(ready)!r}).write_text(str(os.getpid()))
while True: time.sleep(1)
"""
    worker = _spawn(f"""
import subprocess, sys
subprocess.Popen([sys.executable, '-c', {child_code!r}])
""")
    children = []
    try:
        children.append(int(_wait_file(ready)))
        worker.process.wait(timeout=3)
        launcher._terminate_all([worker])
        deadline = time.monotonic() + 1
        while _alive(children[0]) and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not _alive(children[0])
    finally:
        _cleanup(worker, children)


def test_second_interrupt_skips_remaining_grace_period(tmp_path):
    ready = tmp_path / "ready"
    worker = _spawn(f"""
import signal, time
from pathlib import Path
signal.signal(signal.SIGTERM, signal.SIG_IGN)
Path({str(ready)!r}).write_text('ready')
while True: time.sleep(1)
""")
    force = threading.Event()
    timer = threading.Timer(0.1, force.set)
    try:
        _wait_file(ready)
        started = time.monotonic()
        timer.start()
        launcher._terminate_all([worker], force=force)
        assert time.monotonic() - started < 1.5
        assert worker.process.returncode == -signal.SIGKILL
    finally:
        timer.cancel()
        timer.join()
        _cleanup(worker)
