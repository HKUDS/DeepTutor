"""
Sandbox backends: one class per isolation mechanism.

* :class:`RunnerSidecarBackend` — submits the command to a separate runner
  container over HTTP (SYSTEM isolation). The deployment answer for Docker:
  the main app stays least-privileged and never executes untrusted shell.
* :class:`BwrapBackend` — wraps the command in ``bwrap`` mount namespaces on
  Linux bare-metal (SYSTEM isolation).
* :class:`RestrictedSubprocessBackend` — a plain subprocess with cleaned env
  and path-confined cwd (APPLICATION isolation). Degraded fallback for local
  dev (e.g. macOS); admin-opt-in only because it does not OS-isolate.

Every backend is constructed from :class:`SandboxSettings` and reports the
isolation level it actually provides via :attr:`level`.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
import os
from pathlib import Path
import shutil
import sys

import httpx

from deeptutor.services.sandbox.spec import (
    ExecRequest,
    ExecResult,
    IsolationLevel,
)


class SandboxBackend:
    """Abstract execution backend."""

    level: IsolationLevel = IsolationLevel.OFF

    async def exec(self, request: ExecRequest) -> ExecResult:
        raise NotImplementedError

    async def health(self) -> tuple[bool, str]:
        """Return ``(available, detail)`` — whether the backend can run now."""
        return True, ""


class RunnerSidecarBackend(SandboxBackend):
    """Delegate execution to the runner sidecar over HTTP."""

    level = IsolationLevel.SYSTEM

    def __init__(self, base_url: str, *, connect_timeout_s: float = 5.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._connect_timeout_s = connect_timeout_s

    async def exec(self, request: ExecRequest) -> ExecResult:
        payload = {
            # Both spellings travel. A runner that understands ``argv`` prefers
            # it and runs without a shell; an older image ignores the unknown
            # field and executes the equivalent shell string. That keeps a
            # rolling deploy correct in either order, with no version handshake.
            "command": request.command,
            "argv": list(request.argv),
            "workdir": request.workdir,
            "env": request.env,
            "mounts": [
                {
                    "host_path": m.host_path,
                    "sandbox_path": m.sandbox_path,
                    "read_only": m.read_only,
                }
                for m in request.mounts
            ],
            "limits": {
                "timeout_s": request.limits.timeout_s,
                "memory_mb": request.limits.memory_mb,
                "cpu_seconds": request.limits.cpu_seconds,
                "max_output_chars": request.limits.max_output_chars,
            },
        }
        # Allow the HTTP call to outlast the command's own timeout a little so
        # the runner can report a clean timeout result instead of us aborting.
        http_timeout = httpx.Timeout(
            request.limits.timeout_s + 15,
            connect=self._connect_timeout_s,
        )
        try:
            async with httpx.AsyncClient(timeout=http_timeout) as client:
                resp = await client.post(f"{self._base_url}/exec", json=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            return ExecResult(error=f"runner unavailable: {type(exc).__name__}: {exc}")
        return ExecResult(
            stdout=str(data.get("stdout", "")),
            stderr=str(data.get("stderr", "")),
            exit_code=int(data.get("exit_code", 0)),
            timed_out=bool(data.get("timed_out", False)),
            error=str(data.get("error", "")),
        )

    async def health(self) -> tuple[bool, str]:
        try:
            async with httpx.AsyncClient(timeout=self._connect_timeout_s) as client:
                resp = await client.get(f"{self._base_url}/health")
                resp.raise_for_status()
            return True, "runner reachable"
        except httpx.HTTPError as exc:
            return False, f"runner unreachable: {type(exc).__name__}"


class BwrapBackend(SandboxBackend):
    """Bubblewrap mount-namespace isolation (Linux only)."""

    level = IsolationLevel.SYSTEM

    _RO_SYSTEM_DIRS = ("/usr", "/usr/local", "/bin", "/lib", "/lib64", "/etc", "/sbin")
    _DEFAULT_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

    def __init__(
        self,
        bwrap_path: str = "bwrap",
        *,
        venv_path: str | Path | None = None,
        inherit_virtualenv: bool = True,
    ) -> None:
        self._bwrap = bwrap_path
        detected_virtualenv = (
            venv_path is None and inherit_virtualenv and sys.prefix != sys.base_prefix
        )
        if venv_path is not None:
            candidate = Path(venv_path).resolve()
        elif detected_virtualenv:
            candidate = Path(sys.prefix).resolve()
        else:
            candidate = None
        self._venv_path = candidate if candidate is not None and candidate.is_dir() else None
        self._python_runtime_mounts = (
            self._detect_python_runtime_mounts() if self._venv_path and detected_virtualenv else ()
        )

    @classmethod
    def _detect_python_runtime_mounts(cls) -> tuple[tuple[Path, Path], ...]:
        """Return narrowly scoped base-Python mounts needed by managed venvs."""
        candidates: list[tuple[Path, Path]] = []
        for prefix in {sys.base_prefix, sys.base_exec_prefix}:
            path = Path(prefix)
            candidates.append((path.resolve(), path.absolute()))

        base_executable = Path(getattr(sys, "_base_executable", sys.executable))
        runtime_root = base_executable.parent.parent
        candidates.append((runtime_root.resolve(), runtime_root.absolute()))

        system_roots = tuple(Path(path).resolve() for path in cls._RO_SYSTEM_DIRS)
        home = Path.home().resolve()
        mounts: list[tuple[Path, Path]] = []
        for source, destination in candidates:
            if not source.is_dir() or source == Path("/") or source == home:
                continue
            if len(source.parts) < 3:
                continue
            if any(destination == root or root in destination.parents for root in system_roots):
                continue
            binding = (source, destination)
            if binding not in mounts:
                mounts.append(binding)
        return tuple(mounts)

    def _build_argv(self, request: ExecRequest) -> list[str]:
        argv = [
            self._bwrap,
            "--die-with-parent",
            "--unshare-all",
            "--new-session",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--tmpfs",
            "/tmp",  # nosec B108 — path inside the bwrap mount namespace, not the host
        ]
        for system_dir in self._RO_SYSTEM_DIRS:
            if Path(system_dir).exists():
                argv += ["--ro-bind", system_dir, system_dir]
        for mount in request.mounts:
            flag = "--ro-bind" if mount.read_only else "--bind"
            argv += [flag, mount.host_path, mount.sandbox_path]
        # uv-managed venvs can link their interpreter to a versioned runtime
        # outside /usr. Mount only those concrete runtime roots, never their
        # shared manager/home parent. Both the resolved and alias destinations
        # may be needed because venv shebangs preserve the alias path.
        for source, destination in self._python_runtime_mounts:
            argv += ["--ro-bind", str(source), str(destination)]
        # Mount only the environment itself, never its workspace or home-dir
        # parent. Keeping the original absolute path preserves venv shebangs
        # and direct sys.executable argv while the later mount order ensures a
        # writable request mount cannot make the environment writable.
        if self._venv_path is not None and self._venv_path.is_dir():
            venv = str(self._venv_path)
            argv += ["--ro-bind", venv, venv]
        if request.workdir:
            argv += ["--chdir", request.workdir]
        env = dict(request.env)
        if self._venv_path is not None and self._venv_path.is_dir():
            venv = str(self._venv_path)
            venv_bin = str(self._venv_path / "bin")
            base_path = env.get("PATH") or os.environ.get("PATH") or self._DEFAULT_PATH
            path_entries = [part for part in base_path.split(os.pathsep) if part != venv_bin]
            env["PATH"] = os.pathsep.join([venv_bin, *path_entries])
            # The mounted environment is authoritative. A model-supplied env
            # must not redirect Python tooling to an unmounted host path.
            env["VIRTUAL_ENV"] = venv
        for key, value in env.items():
            argv += ["--setenv", key, value]
        if request.argv:
            # No shell in between: bwrap execs the vector directly.
            argv += ["--", *request.argv]
        else:
            argv += ["/bin/sh", "-c", request.command]
        return argv

    async def exec(self, request: ExecRequest) -> ExecResult:
        argv = self._build_argv(request)
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            return ExecResult(error="bwrap not found on host")
        return await _communicate(process, request.limits.timeout_s)

    async def health(self) -> tuple[bool, str]:
        if shutil.which(self._bwrap) is None:
            return False, "bwrap not installed"
        # bwrap needs unprivileged user namespaces; a default-seccomp Docker
        # container blocks them, so confirm a trivial sandbox actually runs.
        probe = ExecRequest(command="true")
        result = await self.exec(probe)
        if result.error:
            return False, result.error
        return True, "bwrap functional"


class RestrictedSubprocessBackend(SandboxBackend):
    """Plain subprocess with a scrubbed env and confined cwd (no OS isolation)."""

    level = IsolationLevel.APPLICATION

    _SAFE_ENV_KEYS = ("PATH", "PATHEXT", "HOME", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT")

    @staticmethod
    def _powershell_executable() -> str:
        """Return the PowerShell executable available on PATH.

        Prefer ``pwsh`` (PowerShell 7+) when present: it defaults to UTF-8 and
        is the version still receiving updates. The commands we generate are
        written for Windows PowerShell 5.1 syntax, which 7 also accepts, so
        either host works.
        """
        return (
            shutil.which("pwsh")
            or shutil.which("powershell.exe")
            or shutil.which("powershell")
            or "powershell.exe"
        )

    @staticmethod
    def _powershell_command(command: str) -> str:
        # PowerShell 5 defaults to the active console code page.  Force UTF-8
        # before running model-authored commands so Chinese output survives the
        # byte-oriented asyncio pipe consistently.
        return (
            "$OutputEncoding = [Console]::OutputEncoding = "
            "[System.Text.UTF8Encoding]::new($false); " + command
        )

    async def exec(self, request: ExecRequest) -> ExecResult:
        env = {k: os.environ[k] for k in self._SAFE_ENV_KEYS if k in os.environ}
        env.update(request.env)
        cwd = request.workdir or None
        try:
            if request.argv:
                process = await asyncio.create_subprocess_exec(
                    *request.argv,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd,
                    env=env,
                )
            elif sys.platform == "win32":
                process = await asyncio.create_subprocess_exec(
                    self._powershell_executable(),
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    self._powershell_command(request.command),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd,
                    env=env,
                )
            else:
                process = await asyncio.create_subprocess_shell(
                    request.command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd,
                    env=env,
                )
        except Exception as exc:
            return ExecResult(error=f"{type(exc).__name__}: {exc}")
        return await _communicate(process, request.limits.timeout_s)


async def _communicate(process: asyncio.subprocess.Process, timeout_s: int) -> ExecResult:
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:
        if sys.platform == "win32" and process.pid:
            # ``Process.kill`` only terminates powershell.exe; taskkill's /T
            # flag also tears down python/compiler children started by it.
            try:
                killer = await asyncio.create_subprocess_exec(
                    "taskkill",
                    "/PID",
                    str(process.pid),
                    "/T",
                    "/F",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                with suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(killer.wait(), timeout=5.0)
            except OSError:
                # Extremely unusual (PATH corruption / stripped-down host),
                # but still return a timeout result instead of masking it.
                process.kill()
        else:
            process.kill()
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(process.wait(), timeout=5.0)
        return ExecResult(timed_out=True, exit_code=124)
    return ExecResult(
        stdout=stdout.decode("utf-8", errors="replace") if stdout else "",
        stderr=stderr.decode("utf-8", errors="replace") if stderr else "",
        exit_code=process.returncode if process.returncode is not None else 0,
    )


__all__ = [
    "BwrapBackend",
    "RestrictedSubprocessBackend",
    "RunnerSidecarBackend",
    "SandboxBackend",
]
