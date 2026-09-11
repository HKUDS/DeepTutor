"""The single sandboxed execution tool exposed to DeepTutor agents."""

from __future__ import annotations

from pathlib import Path, PureWindowsPath
import re
import shlex
import sys
from typing import Any
import uuid

from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolResult
from deeptutor.services.i18n import t
from deeptutor.tools.prompting import load_prompt_hints

# Imported lazily inside methods to avoid the tools -> services -> runtime ->
# registry -> tools cycle during built-in tool discovery.

_DENY_PATTERNS: tuple[str, ...] = (
    r"\brm\s+-[rf]{1,2}\b",
    r"\bdel\s+/[fq]\b",
    r"\brmdir\s+/s\b",
    r"(?:^|[;&|]\s*)format\b",
    r"\b(mkfs|diskpart)\b",
    r"\bdd\s+if=",
    r">\s*/dev/sd",
    r"\b(shutdown|reboot|poweroff)\b",
    r":\(\)\s*\{.*\};\s*:",
    r"(?:^|[;&|]\s*)(useradd|usermod|passwd|chpasswd|crontab)\b",
)

_DEFAULT_TIMEOUT = 30
_MAX_TIMEOUT = 300


class ExecTool(BaseTool):
    """Run source code or a shell script through one sandbox contract."""

    _LANGUAGES: dict[str, tuple[str, str]] = {
        "python": ("main.py", "python3 {src} {stdin}"),
        "c": ("main.c", "cc {src} -O2 -o prog && ./prog {stdin}"),
        "cpp": ("main.cpp", "c++ -std=c++17 -O2 {src} -o prog && ./prog {stdin}"),
    }
    _LANGUAGE_ALIASES: dict[str, str] = {
        "py": "python",
        "python3": "python",
        "c++": "cpp",
        "cxx": "cpp",
        "cc": "c",
        "sh": "shell",
    }

    def get_prompt_hints(self, language: str = "en"):
        return load_prompt_hints(self.name, language=language)

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="exec",
            description=(
                "Run complete source code or an explicit shell script inside "
                "the turn's isolated workspace. Put source or shell text in "
                "`code`; `language` defaults to python and also accepts c, cpp, "
                "or shell. Python/C/C++ source is written to a file before it is "
                "run, so never embed it in python -c or a heredoc. Generated "
                "files saved with relative paths are returned automatically."
            ),
            raw_parameters={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": (
                            "Complete source code, or a shell script when language=shell."
                        ),
                    },
                    "language": {
                        "type": "string",
                        "enum": ["python", "c", "cpp", "shell"],
                        "default": "python",
                        "description": "Execution language. Omit for Python.",
                    },
                    "stdin": {
                        "type": "string",
                        "description": "Optional stdin for Python/C/C++ source.",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": (
                            f"Timeout in seconds (default {_DEFAULT_TIMEOUT}, max {_MAX_TIMEOUT})."
                        ),
                    },
                },
                "required": ["code"],
                "additionalProperties": False,
            },
        )

    @staticmethod
    def _powershell_path(value: str) -> str:
        """Quote a PowerShell path only when its spelling requires it."""

        if not re.search(r"[\s']", value):
            return value
        return "'" + value.replace("'", "''") + "'"

    @classmethod
    def _command_for_platform(
        cls,
        language: str,
        *,
        has_stdin: bool,
        call_dir: str = "",
    ) -> str:
        source_name, _command_template = cls._LANGUAGES[language]
        if sys.platform != "win32":
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
        source_arg = cls._powershell_path(source)
        stdin_arg = cls._powershell_path(stdin_path)
        program_arg = cls._powershell_path(program)
        executable_arg = cls._powershell_path(executable)
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

    @classmethod
    def _resolve_language(cls, raw: Any) -> str:
        language = str(raw or "python").strip().lower()
        language = cls._LANGUAGE_ALIASES.get(language, language)
        if language not in {*cls._LANGUAGES, "shell"}:
            raise ValueError(
                f"Unsupported exec language {language!r}; supported: python, c, cpp, shell."
            )
        return language

    @staticmethod
    def _limits(raw_timeout: Any):
        from deeptutor.services.sandbox import ResourceLimits

        try:
            timeout = int(raw_timeout or _DEFAULT_TIMEOUT)
        except (TypeError, ValueError):
            timeout = _DEFAULT_TIMEOUT
        return ResourceLimits(timeout_s=max(1, min(timeout, _MAX_TIMEOUT)))

    async def execute(self, **kwargs: Any) -> ToolResult:
        code = str(kwargs.get("code") or "").strip()
        if not code:
            raise ValueError("exec requires non-empty 'code'.")

        language = self._resolve_language(kwargs.get("language"))
        if language == "shell":
            return await self._execute_shell(code=code, kwargs=kwargs)
        return await self._execute_source(code=code, language=language, kwargs=kwargs)

    async def _execute_shell(self, *, code: str, kwargs: dict[str, Any]) -> ToolResult:
        for pattern in _DENY_PATTERNS:
            if re.search(pattern, code.lower()):
                return ToolResult(content=t("sandbox.command_blocked"), success=False)

        from deeptutor.services.sandbox import ExecRequest, get_sandbox_service
        from deeptutor.services.sandbox.artifacts import snapshot_public_artifact_files

        limits = self._limits(kwargs.get("timeout"))
        workdir = str(kwargs.get("_sandbox_workdir") or "")
        artifact_snapshot = snapshot_public_artifact_files(workdir) if workdir else {}
        request = ExecRequest(
            command=code,
            workdir=workdir,
            mounts=tuple(kwargs.get("_sandbox_mounts") or ()),
            env=dict(kwargs.get("_sandbox_env") or {}),
            limits=limits,
        )
        result = await get_sandbox_service().run(
            request,
            user_id=str(kwargs.get("_sandbox_user_id") or "anonymous"),
        )
        return self._render_result(
            result=result,
            limits=limits,
            artifact_dir=workdir,
            artifact_snapshot=artifact_snapshot,
            kwargs=kwargs,
            metadata={"language": "shell"},
        )

    async def _execute_source(
        self,
        *,
        code: str,
        language: str,
        kwargs: dict[str, Any],
    ) -> ToolResult:
        from deeptutor.services.sandbox import ExecRequest, Mount, get_sandbox_service
        from deeptutor.services.sandbox.artifacts import snapshot_public_artifact_files

        workdir = str(
            kwargs.get("_sandbox_code_workdir") or kwargs.get("_sandbox_workdir") or ""
        ).strip()
        mounts = tuple(kwargs.get("_sandbox_mounts") or ())
        if not workdir:
            from deeptutor.services.path_service import get_path_service

            workdir = str(get_path_service().get_exec_workspace_dir())
            mounts = (Mount(host_path=workdir, sandbox_path=workdir, read_only=False),)

        stable_dir = Path(workdir)
        stable_dir.mkdir(parents=True, exist_ok=True)
        artifact_snapshot = snapshot_public_artifact_files(stable_dir)
        source_name, _command_template = self._LANGUAGES[language]
        source_root_raw = str(kwargs.get("_sandbox_source_dir") or "").strip()
        if source_root_raw:
            source_root = Path(source_root_raw).expanduser().resolve()
            call_dir = source_root / f"{language}_{uuid.uuid4().hex[:12]}"
            command_dir = str(call_dir)
        else:
            call_relative = (
                Path(".deeptutor") / "exec_calls" / (f"{language}_{uuid.uuid4().hex[:12]}")
            )
            call_dir = stable_dir / call_relative
            command_dir = call_relative.as_posix()
        call_dir.mkdir(parents=True, exist_ok=True)
        (call_dir / source_name).write_text(code, encoding="utf-8")

        has_stdin = str(kwargs.get("stdin") or "") != ""
        if has_stdin:
            (call_dir / "stdin.txt").write_text(str(kwargs["stdin"]), encoding="utf-8")
        command = self._command_for_platform(
            language,
            has_stdin=has_stdin,
            call_dir=command_dir,
        )
        limits = self._limits(kwargs.get("timeout"))
        request = ExecRequest(
            command=command,
            workdir=str(stable_dir),
            mounts=mounts,
            env=dict(kwargs.get("_sandbox_env") or {}),
            limits=limits,
        )
        result = await get_sandbox_service().run(
            request,
            user_id=str(kwargs.get("_sandbox_user_id") or "anonymous"),
        )

        from deeptutor.services.workspace.execution import logical_workspace_path

        return self._render_result(
            result=result,
            limits=limits,
            artifact_dir=str(stable_dir),
            artifact_snapshot=artifact_snapshot,
            kwargs=kwargs,
            metadata={
                "language": language,
                "code": code,
                "command": command,
                "run_dir": logical_workspace_path(
                    stable_dir, str(kwargs.get("_workspace_root") or "")
                ),
            },
        )

    @staticmethod
    def _render_result(
        *,
        result: Any,
        limits: Any,
        artifact_dir: str,
        kwargs: dict[str, Any],
        artifact_snapshot: dict[str, tuple[int, int, int]] | None = None,
        ignored_files: set[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ToolResult:
        from deeptutor.services.sandbox.artifacts import (
            collect_public_artifact_batch,
            render_artifacts_for_tool,
        )
        from deeptutor.services.workspace.execution import logicalize_workspace_text

        workspace_id = str(kwargs.get("_workspace_id") or "")
        batch = (
            collect_public_artifact_batch(
                artifact_dir,
                workspace_id=workspace_id,
                changed_since=artifact_snapshot,
            )
            if artifact_dir
            else None
        )
        artifacts = list(batch.artifacts) if batch is not None else []
        ignored = ignored_files or set()
        artifacts = [artifact for artifact in artifacts if artifact.filename not in ignored]
        artifact_rows = [artifact.to_dict() for artifact in artifacts]

        workspace_root = str(kwargs.get("_workspace_root") or "")
        internal_root = str(kwargs.get("_sandbox_internal_root") or "")

        def _logicalize(value: str) -> str:
            rendered = logicalize_workspace_text(value, workspace_root)
            return logicalize_workspace_text(rendered, internal_root)

        content_parts = [_logicalize(result.render(limits.max_output_chars))]
        artifact_text = render_artifacts_for_tool(
            artifacts,
            already_presented=not bool(workspace_id),
            total_count=batch.total_count if batch is not None else 0,
            empty_message="No new or changed artifacts were produced by this call.",
        )
        if artifact_text:
            content_parts.append(artifact_text)

        result_metadata = {
            key: _logicalize(value) if isinstance(value, str) else value
            for key, value in dict(metadata or {}).items()
        }
        result_metadata.update(
            {
                "exit_code": result.exit_code,
                "timed_out": result.timed_out,
                "sandbox_error": _logicalize(result.error),
                "artifacts": artifact_rows,
                "workspace_items": [],
                "artifact_total_count": batch.total_count if batch is not None else 0,
                "artifacts_truncated": batch.truncated if batch is not None else False,
            }
        )
        return ToolResult(
            content="\n\n".join(content_parts),
            success=result.ok and result.exit_code == 0,
            sources=(
                []
                if workspace_id
                else [
                    {
                        "type": "artifact",
                        "filename": row["filename"],
                        "url": row["url"],
                        "path": row["path"],
                        "mime_type": row["mime_type"],
                        "size_bytes": row["size_bytes"],
                    }
                    for row in artifact_rows
                ]
            ),
            metadata=result_metadata,
        )


__all__ = ["ExecTool"]
