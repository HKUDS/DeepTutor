"""Cancellation must stop a tool process and the descendants holding its pipes."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import signal
import sys

import pytest

from deeptutor.services.sandbox.backends import RestrictedSubprocessBackend
from deeptutor.services.sandbox.spec import ExecRequest


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process-group regression")
@pytest.mark.parametrize("leader_exits", [False, True])
async def test_cancel_kills_tool_and_child(tmp_path: Path, leader_exits: bool) -> None:
    heartbeat = tmp_path / "heartbeat"
    pidfile = tmp_path / "child.pid"
    child = (
        "import time; from pathlib import Path; "
        f"p=Path({str(heartbeat)!r}); "
        "exec('while True:\\n p.write_text(str(time.monotonic_ns()))\\n time.sleep(.02)')"
    )
    parent = (
        "import subprocess,sys,time; from pathlib import Path; "
        f"p=subprocess.Popen([sys.executable,'-c',{child!r}]); "
        f"Path({str(pidfile)!r}).write_text(str(p.pid)); time.sleep(60)"
    )
    if leader_exits:
        parent = parent.replace("time.sleep(60)", "sys.exit(0)")
    task = asyncio.create_task(
        RestrictedSubprocessBackend().exec(ExecRequest.of_argv([sys.executable, "-c", parent]))
    )
    try:
        for _ in range(100):
            if heartbeat.exists():
                break
            await asyncio.sleep(0.02)
        assert heartbeat.exists(), "child did not start"
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 5)
        stopped = heartbeat.read_text()
        await asyncio.sleep(0.15)
        assert heartbeat.read_text() == stopped, "child survived tool cancellation"
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        if pidfile.exists():
            try:
                os.kill(int(pidfile.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass
