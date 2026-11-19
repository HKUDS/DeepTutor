"""Reusable source-code execution through the sandbox.

The agent's ``exec`` tool and the learner-facing code runner must write and
compile code the same way. Keeping the command assembly here means a feature
that exposes execution to learners cannot drift from the sandbox contract the
agent already uses (and that the runner sidecar already understands).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
import re
import shlex
import sys
from typing import Any
import uuid

from .spec import ExecRequest, ExecResult, Mount, ResourceLimits

DEFAULT_TIMEOUT = 30
MAX_TIMEOUT = 300

#: Language → (source filename, human-readable command template). The template
#: is documentation only; :func:`command_for_platform` builds the real command.
LANGUAGES: dict[str, tuple[str, str]] = {
    "python": ("main.py", "python3 {src} {stdin}"),
    "c": ("main.c", "cc {src} -O2 -o prog && ./prog {stdin}"),
    "cpp": ("main.cpp", "c++ -std=c++17 -O2 {src} -o prog && ./prog {stdin}"),
}

LANGUAGE_ALIASES: dict[str, str] = {
    "py": "python",
    "python3": "python",
    "c++": "cpp",
    "cxx": "cpp",
    "cc": "c",
}


def resolve_language(raw: Any, *, allow_shell: bool = False) -> str:
    """Normalize a caller/model language name or raise ``ValueError``."""
    language = str(raw or "python").strip().lower()
    language = LANGUAGE_ALIASES.get(language, language)
    supported = {*LANGUAGES, "shell"} if allow_shell else set(LANGUAGES)
    if language not in supported:
        names = ", ".join(sorted(supported))
        raise ValueError(f"Unsupported exec language {language!r}; supported: {names}.")
    return language


def resource_limits(raw_timeout: Any, *, default: int = DEFAULT_TIMEOUT) -> ResourceLimits:
    try:
        timeout = int(raw_timeout or default)
    except (TypeError, ValueError):
        timeout = default
    return ResourceLimits(timeout_s=max(1, min(timeout, MAX_TIMEOUT)))


def _powershell_path(value: str) -> str:
    """Quote a PowerShell path only when its spelling requires it."""

    if not re.search(r"[\s']", value):
        return value
    return "'" + value.replace("'", "''") + "'"


def command_for_platform(
    language: str,
    *,
    has_stdin: bool,
    call_dir: str = "",
    platform: str | None = None,
) -> str:
    """Build the shell command that compiles/runs *language* in *call_dir*."""
    source_name = LANGUAGES[language][0]
    if (platform or sys.platform) != "win32":
        prefix = f"{call_dir.rstrip('/')}/" if call_dir else ""
        source = f"{prefix}{source_name}"
        source_arg = shlex.quote(source)
        stdin_redirect = f"< {shlex.quote(f'{prefix}stdin.txt')}" if has_stdin else ""
        if language == "python":
            return f"python3 {source_arg} {stdin_redirect}".strip()
        compiler = "cc" if language == "c" else "c++ -std=c++17"
        program = f"{prefix}prog"
        program_arg = shlex.quote(program)
        return (
            f"{compiler} {source_arg} -O2 -o {program_arg} && {program_arg} {stdin_redirect}"
        ).strip()

    windows_call_dir = call_dir.replace("/", "\\").rstrip("\\")
    prefix = f"{windows_call_dir}\\" if windows_call_dir else ""
    source = f"{prefix}{source_name}"
    stdin_path = f"{prefix}stdin.txt"
    program = f"{prefix}prog.exe"
    executable = (
        program
        if call_dir and PureWindowsPath(windows_call_dir).is_absolute()
        else (f".\\{program}" if call_dir else ".\\prog.exe")
    )
    source_arg = _powershell_path(source)
    stdin_arg = _powershell_path(stdin_path)
    program_arg = _powershell_path(program)
    executable_arg = _powershell_path(executable)
    compiler, flags = ("gcc", "-O2") if language == "c" else ("g++", "-std=c++17 -O2")
    command = (
        f"python {source_arg}"
        if language == "python"
        else (
            f"{compiler} {flags} {source_arg} -o {program_arg}; "
            f"if ($LASTEXITCODE -eq 0) {{ & {executable_arg} }}"
        )
    )
    if not has_stdin:
        return command
    if language == "python":
        return f"Get-Content {stdin_arg} | python {source_arg}"
    return (
        f"$stdinText = Get-Content -Raw {stdin_arg}; "
        f"{compiler} {flags} {source_arg} -o {program_arg}; "
        f"if ($LASTEXITCODE -eq 0) {{ $stdinText | & {executable_arg} }}"
    )


@dataclass(frozen=True)
class SourceRun:
    """One source execution plus the paths the caller may need to report."""

    result: ExecResult
    command: str
    workdir: str
    call_dir: str


async def run_source(
    *,
    language: str,
    code: str,
    stdin: str = "",
    timeout_s: int = DEFAULT_TIMEOUT,
    user_id: str = "anonymous",
    workdir: str = "",
    mounts: tuple[Mount, ...] = (),
    env: dict[str, str] | None = None,
    source_root: str = "",
) -> SourceRun:
    """Write *code* to a per-call directory and execute it in the sandbox.

    ``workdir`` is the stable directory the sandbox mounts. When omitted the
    caller's exec workspace is used and mounted read-write, matching the agent
    tool. ``source_root`` lets a caller keep the source file outside that stable
    directory while still running from it.
    """
    language = resolve_language(language)
    if not str(code or "").strip():
        raise ValueError("run_source requires non-empty code")

    if workdir:
        stable_dir = Path(workdir)
        resolved_mounts = tuple(mounts)
    else:
        from deeptutor.services.path_service import get_path_service

        stable_dir = Path(get_path_service().get_exec_workspace_dir())
        resolved_mounts = (
            Mount(host_path=str(stable_dir), sandbox_path=str(stable_dir), read_only=False),
        )
    stable_dir.mkdir(parents=True, exist_ok=True)

    source_name = LANGUAGES[language][0]
    if source_root:
        source_root_path = Path(source_root).expanduser().resolve()
        call_dir = source_root_path / f"{language}_{uuid.uuid4().hex[:12]}"
        command_dir = str(call_dir)
    else:
        call_relative = Path(".deeptutor") / "exec_calls" / (f"{language}_{uuid.uuid4().hex[:12]}")
        call_dir = stable_dir / call_relative
        command_dir = call_relative.as_posix()
    call_dir.mkdir(parents=True, exist_ok=True)
    _ = (call_dir / source_name).write_text(str(code), encoding="utf-8")

    has_stdin = str(stdin) != ""
    if has_stdin:
        _ = (call_dir / "stdin.txt").write_text(str(stdin), encoding="utf-8")

    command = command_for_platform(language, has_stdin=has_stdin, call_dir=command_dir)
    limits = resource_limits(timeout_s)
    request = ExecRequest(
        command=command,
        workdir=str(stable_dir),
        mounts=resolved_mounts,
        env=dict(env or {}),
        limits=limits,
    )

    # Resolve the service through the package attribute at call time so tests
    # and embedders can substitute it without this module caching a stale
    # singleton.
    import deeptutor.services.sandbox as sandbox_pkg

    result = await sandbox_pkg.get_sandbox_service().run(
        request,
        user_id=str(user_id or "anonymous"),
    )
    return SourceRun(
        result=result,
        command=command,
        workdir=str(stable_dir),
        call_dir=str(call_dir),
    )


__all__ = [
    "DEFAULT_TIMEOUT",
    "LANGUAGES",
    "LANGUAGE_ALIASES",
    "MAX_TIMEOUT",
    "SourceRun",
    "command_for_platform",
    "resolve_language",
    "resource_limits",
    "run_source",
]
