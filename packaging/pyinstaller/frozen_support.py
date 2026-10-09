"""Packaging-only frozen-process patches (not part of the DeepTutor library).

Applied from ``entry.py`` before the CLI starts. Keeps ``deeptutor`` /
``deeptutor_cli`` source free of PyInstaller-specific branches.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Sequence

ISOLATED_WORKER_FLAG = "--isolated-worker"
_WEB_DIR_ENV = "DEEPTUTOR_WEB_DIR"

_orig_popen: type[subprocess.Popen[Any]] | None = None
_patched = False


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def rewrite_command(args: Sequence[str]) -> list[str]:
    """Rewrite ``python -m …`` vectors that a frozen exe cannot execute."""

    cmd = [str(a) for a in args]
    if not cmd:
        return cmd
    exe = str(Path(sys.executable).resolve())
    try:
        same_exe = Path(cmd[0]).resolve() == Path(exe)
    except OSError:
        same_exe = cmd[0] == sys.executable or Path(cmd[0]).name.lower() in {
            Path(sys.executable).name.lower(),
            "deeptutor.exe",
            "deeptutor",
        }
    if not same_exe:
        return cmd

    # deeptutor.exe -m uvicorn deeptutor.api.main:app --host … --port N …
    if len(cmd) >= 4 and cmd[1:4] == ["-m", "uvicorn", "deeptutor.api.main:app"]:
        host, port = "0.0.0.0", None
        i = 4
        while i < len(cmd):
            if cmd[i] == "--host" and i + 1 < len(cmd):
                host = cmd[i + 1]
                i += 2
                continue
            if cmd[i] == "--port" and i + 1 < len(cmd):
                port = cmd[i + 1]
                i += 2
                continue
            i += 1
        out = [cmd[0], "serve", "--host", host]
        if port is not None:
            out.extend(["--port", str(port)])
        return out

    # deeptutor.exe -m deeptutor_cli.main <subcommand> …
    if len(cmd) >= 3 and cmd[1:3] == ["-m", "deeptutor_cli.main"]:
        return [cmd[0], *cmd[3:]]

    # deeptutor.exe -m deeptutor.runtime.worker_process <req> <res>
    if len(cmd) >= 3 and cmd[1:3] == ["-m", "deeptutor.runtime.worker_process"]:
        return [cmd[0], ISOLATED_WORKER_FLAG, *cmd[3:]]

    return cmd


def _install_popen_rewrite() -> None:
    global _orig_popen
    if _orig_popen is not None:
        return

    _orig_popen = subprocess.Popen

    class RewritingPopen(_orig_popen):  # type: ignore[valid-type,misc]
        def __init__(self, args: Any = None, *a: Any, **kw: Any) -> None:
            if isinstance(args, (list, tuple)):
                args = rewrite_command(args)
            super().__init__(args, *a, **kw)

    subprocess.Popen = RewritingPopen  # type: ignore[misc,assignment]


def _patch_packaged_web_dir() -> None:
    import deeptutor.runtime.launcher as launcher

    original = launcher._packaged_web_dir

    def _packaged_web_dir() -> Path | None:
        raw = os.getenv(_WEB_DIR_ENV, "").strip()
        if raw:
            path = Path(raw).expanduser().resolve()
            if (path / "server.js").exists():
                return path
        return original()

    launcher._packaged_web_dir = _packaged_web_dir  # type: ignore[assignment]


def _patch_isolated_worker() -> None:
    import deeptutor.runtime.isolated_worker as isolated_worker

    def _command(request_path: Path, result_path: Path) -> list[str]:
        return [sys.executable, ISOLATED_WORKER_FLAG, str(request_path), str(result_path)]

    isolated_worker._command = _command  # type: ignore[assignment]


def apply_frozen_patches() -> None:
    """Install all packaging-only patches for a frozen process."""

    global _patched
    if _patched or not is_frozen():
        return
    _install_popen_rewrite()
    _patch_packaged_web_dir()
    _patch_isolated_worker()
    _patched = True


def maybe_run_isolated_worker(argv: list[str] | None = None) -> int | None:
    """If argv is an isolated-worker invocation, run it and return an exit code."""

    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] != ISOLATED_WORKER_FLAG:
        return None
    from deeptutor.runtime.worker_process import main as worker_main

    return int(worker_main(args[1:]))
