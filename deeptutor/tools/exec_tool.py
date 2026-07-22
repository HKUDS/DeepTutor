"""
Sandboxed shell execution tool for chat.

This is the chat-side counterpart to TutorBot's ExecTool, but every command
runs through the :mod:`deeptutor.services.sandbox` layer rather than a raw
subprocess. The pipeline mounts the turn's workspace read-write and exposes
it as the working directory; the deny-pattern guard from TutorBot is reused
as defence-in-depth on top of OS isolation.

Mounting and the policy gate (who may call this) live in the chat pipeline —
the tool itself just builds an :class:`ExecRequest` and renders the result.
"""

from __future__ import annotations

import re
from typing import Any

from deeptutor.core.i18n import t
from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolParameter, ToolResult
from deeptutor.tools.prompting import load_prompt_hints

# NOTE: ``deeptutor.services.sandbox`` is imported lazily inside ``execute``
# (not at module top). This tool is loaded by ``deeptutor.tools.builtin``,
# which the tool registry imports; pulling the whole ``services`` package in
# here at import time creates a tools→services→runtime→registry→tools import
# cycle. Every other builtin tool imports its service deps inside ``execute``
# for the same reason.

# Defence-in-depth deny list (mirrors TutorBot's ExecTool). The sandbox is the
# real boundary; these patterns stop obviously destructive commands early.
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
    """Run a shell command inside the execution sandbox."""

    def get_prompt_hints(self, language: str = "en"):
        return load_prompt_hints(self.name, language=language)

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="exec",
            description=(
                "Run a shell command inside an isolated sandbox and return "
                "its output. The command runs in this turn's workspace "
                "directory. Use for data processing, running skill scripts, "
                "and CLI tools — not for destructive or system-management "
                "commands."
            ),
            parameters=[
                ToolParameter(
                    name="command",
                    type="string",
                    description="The shell command to execute.",
                ),
                ToolParameter(
                    name="timeout",
                    type="integer",
                    description=f"Timeout in seconds (default {_DEFAULT_TIMEOUT}, max {_MAX_TIMEOUT}).",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        command = str(kwargs.get("command") or "").strip()
        if not command:
            raise ValueError("exec requires a non-empty command.")

        lowered = command.lower()
        for pattern in _DENY_PATTERNS:
            if re.search(pattern, lowered):
                return ToolResult(
                    content=t("sandbox.command_blocked"),
                    success=False,
                )

        from deeptutor.services.sandbox import (
            ExecRequest,
            ResourceLimits,
            get_sandbox_service,
        )

        # ``_sandbox_*`` kwargs are injected server-side by the pipeline; the
        # LLM never supplies them.
        user_id = str(kwargs.get("_sandbox_user_id") or "anonymous")
        workdir = str(kwargs.get("_sandbox_workdir") or "")
        mounts = kwargs.get("_sandbox_mounts") or ()

        try:
            timeout = int(kwargs.get("timeout") or _DEFAULT_TIMEOUT)
        except (TypeError, ValueError):
            timeout = _DEFAULT_TIMEOUT
        timeout = max(1, min(timeout, _MAX_TIMEOUT))
        limits = ResourceLimits(timeout_s=timeout)

        request = ExecRequest(
            command=command,
            workdir=workdir,
            mounts=tuple(mounts),
            limits=limits,
        )
        result = await get_sandbox_service().run(request, user_id=user_id)
        artifacts = []
        artifact_rows: list[dict[str, object]] = []
        if workdir:
            from deeptutor.services.sandbox.artifacts import (
                collect_public_artifacts,
                render_artifacts_for_tool,
            )

            artifacts = collect_public_artifacts(workdir)
            artifact_rows = [artifact.to_dict() for artifact in artifacts]
        content_parts = [result.render(limits.max_output_chars)]
        artifact_text = render_artifacts_for_tool(artifacts)
        if artifact_text:
            content_parts.append(artifact_text)
        return ToolResult(
            content="\n\n".join(content_parts),
            success=result.ok and result.exit_code == 0,
            sources=[
                {
                    "type": "artifact",
                    "filename": row["filename"],
                    "url": row["url"],
                    "path": row["path"],
                    "mime_type": row["mime_type"],
                    "size_bytes": row["size_bytes"],
                }
                for row in artifact_rows
            ],
            metadata={
                "exit_code": result.exit_code,
                "timed_out": result.timed_out,
                "sandbox_error": result.error,
                "artifacts": artifact_rows,
            },
        )


__all__ = ["ExecTool"]
