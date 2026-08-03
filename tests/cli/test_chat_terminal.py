"""POSIX terminal behavior tests for the interactive chat CLI."""

from __future__ import annotations

import os
from pathlib import Path
import select
import subprocess
import sys
import time

import pytest

pty = pytest.importorskip("pty")
termios = pytest.importorskip("termios")


@pytest.mark.skipif(not hasattr(termios, "IUTF8"), reason="IUTF8 is not available")
def test_chat_repl_handles_utf8_backspace_and_restores_terminal_mode() -> None:
    master_fd, slave_fd = pty.openpty()
    original = termios.tcgetattr(slave_fd)
    original[0] &= ~termios.IUTF8
    termios.tcsetattr(slave_fd, termios.TCSANOW, original)

    project_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8:strict"
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "from deeptutor_cli.chat import _read_repl_input; "
                "print('RESULT=' + repr(_read_repl_input()))"
            ),
        ],
        cwd=project_root,
        env=env,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        close_fds=True,
    )

    output = bytearray()
    try:
        deadline = time.monotonic() + 10
        while b"You>" not in output and time.monotonic() < deadline:
            readable, _, _ = select.select([master_fd], [], [], 0.1)
            if readable:
                output.extend(os.read(master_fd, 4096))
        assert b"You>" in output

        os.write(master_fd, "能".encode() + b"\x7fok\n")
        process.wait(timeout=10)
        while True:
            readable, _, _ = select.select([master_fd], [], [], 0)
            if not readable:
                break
            try:
                output.extend(os.read(master_fd, 4096))
            except OSError:
                break

        assert process.returncode == 0, output.decode("utf-8", "replace")
        assert b"RESULT='ok'" in output
        assert not termios.tcgetattr(slave_fd)[0] & termios.IUTF8
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        os.close(master_fd)
        os.close(slave_fd)
