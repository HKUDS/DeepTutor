"""Gemini CLI backend — drive the local ``gemini`` CLI in headless print mode.

Uses ``gemini -p <question> --output-format stream-json`` (stream-json exists
since v0.11.0): a newline-delimited JSON event stream with a small, fixed event
vocabulary — ``init`` (session id + model), ``message`` (assistant text arrives
as incremental ``delta`` chunks; there is no final aggregated message event),
``tool_use`` / ``tool_result`` (paired by ``tool_id``), ``error`` and a closing
``result``. We accumulate the deltas per text block so the answer types out
live in the sidebar, exactly like Claude Code's partial messages.

Two headless quirks worth knowing: thought summaries are dropped by the CLI's
non-interactive loop (so no reasoning channel), and the policy engine treats
``ask_user`` as deny — mutating tools only run under ``--approval-mode=yolo``
or ``auto_edit``, which is why the config's permission mode maps onto those.

Auth and config are inherited automatically: the spawned ``gemini`` reads the
user's existing ``~/.gemini`` credentials (or ``GEMINI_API_KEY``-style env
vars), so no token is ever handled here. Sessions are project-scoped on disk,
so resuming requires the same working directory — a connection's fixed ``cwd``
satisfies that by construction.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from deeptutor.services.subagent.base import OnEvent, SubagentBackend
from deeptutor.services.subagent.config import BackendConfig
from deeptutor.services.subagent.process import probe_version, stream_process_lines
from deeptutor.services.subagent.types import (
    EVENT_ERROR,
    EVENT_LOG,
    EVENT_TEXT,
    EVENT_TOOL,
    EVENT_TOOL_RESULT,
    ConsultResult,
    DetectResult,
    SubagentEvent,
)

logger = logging.getLogger(__name__)

_MAX_FIELD_CHARS = 4000
_TOOL_HEADER_CHARS = 160

# The stored permission mode uses Claude Code's spellings as the canonical
# vocabulary (the two CLIs' modes are semantically parallel); translate to
# Gemini's ``--approval-mode`` values here. Unknown values fall back to yolo —
# a headless run that blocks on approval would hang the turn forever.
_APPROVAL_MODES = {
    "bypassPermissions": "yolo",
    "acceptEdits": "auto_edit",
    "default": "default",
    "plan": "plan",
}

# The salient argument to surface in a tool header (same idea as Claude Code's
# renderer): show ``Shell(cmd …)`` / ``ReadFile(path)`` instead of raw JSON.
_TOOL_PRIMARY_ARGS = (
    "command",
    "file_path",
    "path",
    "pattern",
    "query",
    "url",
    "prompt",
    "description",
)


class GeminiBackend(SubagentBackend):
    kind = "gemini"
    display_name = "Gemini CLI"
    cli_command = "gemini"

    async def detect(self) -> DetectResult:
        ok, text = await probe_version([self.cli_command, "--version"])
        return DetectResult(
            kind=self.kind,
            display_name=self.display_name,
            available=ok,
            version=text if ok else "",
            detail="" if ok else (text or "gemini CLI not found on PATH"),
        )

    def _build_command(
        self,
        question: str,
        *,
        session_id: str | None,
        config: BackendConfig,
        images: list[str] | None = None,
    ) -> list[str]:
        prompt = question
        # No system-prompt flag exists, so the delegate instruction is prepended
        # once, on the session-creating consult; resumed sessions already have it.
        if config.system_prompt.strip() and not session_id:
            prompt = f"{config.system_prompt.strip()}\n\n{question}"
        # Images attach via the @path syntax (routed through read_many_files into
        # inline parts); --include-directories admits the staging dir, which is
        # outside the working dir.
        if images:
            listing = " ".join(f"@{path}" for path in images)
            prompt = f"{prompt}\n\n{listing}"
        cmd = [
            self.cli_command,
            "-p",
            prompt,
            "--output-format",
            "stream-json",
            "--approval-mode",
            _APPROVAL_MODES.get(config.permission_mode, "yolo"),
        ]
        if images:
            cmd += ["--include-directories", os.path.dirname(images[0])]
        if session_id:
            cmd += ["--resume", session_id]
        if config.model:
            cmd += ["--model", config.model]
        cmd += list(config.extra_args)
        return cmd

    async def consult(
        self,
        question: str,
        *,
        on_event: OnEvent,
        cwd: str | None = None,
        session_id: str | None = None,
        config: BackendConfig | None = None,
        images: list[str] | None = None,
        partner_id: str | None = None,  # noqa: ARG002 — partner-only; ignored here
    ) -> ConsultResult:
        config = config or BackendConfig()
        cmd = self._build_command(question, session_id=session_id, config=config, images=images)
        result = ConsultResult(session_id=session_id)
        # Delta accumulator: assistant text arrives as chunks with no final
        # aggregate, so we grow per-block running text; a tool_use closes the
        # current block so post-tool text streams as a new row.
        stream: dict[str, Any] = {"blocks": [], "open": False}

        async def emit(
            kind: str, text: str, raw: dict[str, Any], meta: dict[str, Any] | None = None
        ) -> None:
            result.event_count += 1
            await on_event(SubagentEvent(kind=kind, text=text, raw=raw, meta=meta or {}))

        try:
            async for channel, line in stream_process_lines(cmd, cwd=cwd):
                if channel == "exit":
                    if line != "0" and result.success and not result.final_text:
                        result.success = False
                        result.error = f"gemini exited with code {line}"
                        await emit(EVENT_ERROR, result.error, {"returncode": line})
                    continue
                if channel == "stderr":
                    if line.strip():
                        await emit(EVENT_LOG, line, {"stream": "stderr"})
                    continue
                event = _parse_json(line)
                if event is None:
                    if line.strip():
                        await emit(EVENT_LOG, line, {"stream": "stdout"})
                    continue
                await self._handle_event(event, result, stream, emit)
        except Exception as exc:  # pragma: no cover - defensive: surface, don't crash the turn
            logger.warning("gemini consult failed: %s", exc, exc_info=True)
            result.success = False
            result.error = str(exc)
            await emit(EVENT_ERROR, str(exc), {})

        if not result.final_text:
            result.final_text = "\n\n".join(b for b in stream["blocks"] if b.strip()).strip()
        return result

    async def _handle_event(
        self,
        event: dict[str, Any],
        result: ConsultResult,
        stream: dict[str, Any],
        emit: Any,
    ) -> None:
        etype = str(event.get("type") or "")

        if etype == "init":
            sid = str(event.get("session_id") or "")
            if sid:
                result.session_id = sid
            model = str(event.get("model") or "")
            await emit(EVENT_LOG, f"Session started{f' · {model}' if model else ''}", event)
            return

        if etype == "message":
            if str(event.get("role") or "") != "assistant":
                return  # the echoed user prompt; the consult tool already heads the round
            content = str(event.get("content") or "")
            if not content:
                return
            blocks: list[str] = stream["blocks"]
            if event.get("delta") and stream["open"] and blocks:
                blocks[-1] += content
            else:
                blocks.append(content)
                stream["open"] = True
            await emit(
                EVENT_TEXT,
                blocks[-1].strip(),
                event,
                {"merge_id": f"txt:{len(blocks) - 1}"},
            )
            return

        if etype == "tool_use":
            stream["open"] = False  # post-tool text starts a fresh block/row
            await emit(EVENT_TOOL, _render_tool_use(event), event)
            return

        if etype == "tool_result":
            await emit(EVENT_TOOL_RESULT, _render_tool_result(event), event)
            return

        if etype == "error":
            message = str(event.get("message") or "gemini reported an error")
            if str(event.get("severity") or "") == "warning":
                await emit(EVENT_LOG, message, event)
            else:
                result.error = message
                await emit(EVENT_ERROR, message, event)
            return

        if etype == "result":
            if str(event.get("status") or "") == "error":
                result.success = False
                error = event.get("error")
                if isinstance(error, dict) and error.get("message"):
                    result.error = str(error["message"])
            return

        # Unknown event type — keep it visible as a log rather than dropping it.
        await emit(EVENT_LOG, _compact(event), event)


def _parse_json(line: str) -> dict[str, Any] | None:
    line = line.strip()
    if not line or line[0] not in "{[":
        return None
    try:
        parsed = json.loads(line)
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _render_tool_use(event: dict[str, Any]) -> str:
    name = str(event.get("tool_name") or "tool")
    params = event.get("parameters")
    if not isinstance(params, dict) or not params:
        return name
    for key in _TOOL_PRIMARY_ARGS:
        value = params.get(key)
        if isinstance(value, str) and value.strip():
            return f"{name}({_inline(value)})"
    return f"{name}({_inline(_compact(params))})"


def _render_tool_result(event: dict[str, Any]) -> str:
    if str(event.get("status") or "") == "error":
        error = event.get("error")
        message = error.get("message") if isinstance(error, dict) else None
        return _truncate(str(message or "tool failed"))
    # ``output`` is present only when the tool's display result is a plain
    # string; other display shapes arrive as no output at all.
    return _truncate(str(event.get("output") or "")) or "(no output)"


def _inline(text: str) -> str:
    one_line = " ".join(text.split())
    if len(one_line) > _TOOL_HEADER_CHARS:
        return one_line[:_TOOL_HEADER_CHARS].rstrip() + " …"
    return one_line


def _compact(obj: Any) -> str:
    try:
        text = json.dumps(obj, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(obj)
    return _truncate(text)


def _truncate(text: str) -> str:
    text = text.strip()
    if len(text) > _MAX_FIELD_CHARS:
        return text[:_MAX_FIELD_CHARS].rstrip() + " …"
    return text


__all__ = ["GeminiBackend"]
