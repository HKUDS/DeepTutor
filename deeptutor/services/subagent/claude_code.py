"""Claude Code backend — drive the local ``claude`` CLI in headless print mode.

Uses ``claude -p <question> --output-format stream-json --verbose``: a
newline-delimited JSON event stream that mirrors exactly what an interactive
session does — the system init, each assistant text block, every tool_use and
its tool_result, and a final ``result`` event. We map each event onto a
:class:`SubagentEvent` channel and forward it live, so the sidebar shows the
same intermediate steps the user would see in their own terminal.

Auth and config are inherited automatically: the spawned ``claude`` reads the
user's existing ``~/.claude`` credentials and settings, so no token is ever
handled here.
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
    EVENT_REASONING,
    EVENT_TEXT,
    EVENT_TOOL,
    EVENT_TOOL_RESULT,
    ConsultResult,
    DetectResult,
    SubagentEvent,
)

logger = logging.getLogger(__name__)

_MAX_FIELD_CHARS = 4000
# Single-line cap for a tool-call header (e.g. the command inside ``Bash(…)``).
_TOOL_HEADER_CHARS = 160
# Telemetry/system events that are noise in the transcript (the CLI doesn't show
# them as content either) — dropped rather than rendered as raw JSON.
_IGNORED_EVENT_TYPES = frozenset({"rate_limit_event", "control_request", "control_response"})
# The salient argument to surface in a tool header, in priority order, so a call
# reads like the CLI's ``Bash(cd …)`` / ``Read(path)`` instead of raw JSON.
_TOOL_PRIMARY_ARGS = (
    "command",
    "file_path",
    "path",
    "pattern",
    "query",
    "url",
    "prompt",
    "notebook_path",
    "description",
)


class ClaudeCodeBackend(SubagentBackend):
    kind = "claude_code"
    display_name = "Claude Code"
    cli_command = "claude"

    async def detect(self) -> DetectResult:
        ok, text = await probe_version([self.cli_command, "--version"])
        return DetectResult(
            kind=self.kind,
            display_name=self.display_name,
            available=ok,
            version=text if ok else "",
            detail="" if ok else (text or "claude CLI not found on PATH"),
        )

    def _build_command(
        self,
        question: str,
        *,
        session_id: str | None,
        config: BackendConfig,
        images: list[str] | None = None,
    ) -> list[str]:
        # Claude Code's ``-p`` mode has no image flag (only the stream-json stdin
        # channel does), so we point it at the forwarded images on disk and let
        # its own Read tool view them — the bypass permission mode runs Read
        # without prompting.
        prompt = question
        if images:
            listing = "\n".join(images)
            prompt = (
                f"{question}\n\n[The user attached image(s) for this question. View "
                f"them with your Read tool before answering:\n{listing}]"
            )
        cmd = [
            self.cli_command,
            "-p",
            prompt,
            "--output-format",
            "stream-json",
            "--verbose",
            # Token-level streaming: emit Anthropic ``stream_event`` deltas so the
            # answer types out live in the sidebar rather than landing whole.
            "--include-partial-messages",
        ]
        if images:
            # Allow Read access to the (temp) directory the images live in, which
            # is outside the working dir.
            cmd += ["--add-dir", os.path.dirname(images[0])]
        if session_id:
            cmd += ["--resume", session_id]
        if config.permission_mode:
            cmd += ["--permission-mode", config.permission_mode]
        if config.model:
            cmd += ["--model", config.model]
        if config.effort:
            cmd += ["--effort", config.effort]
        if config.system_prompt.strip():
            cmd += ["--append-system-prompt", config.system_prompt]
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
        assistant_text: list[str] = []
        # Token-streaming accumulator: per content-block running text, keyed by the
        # current message id, so partial ``stream_event`` deltas grow one row.
        stream: dict[str, Any] = {"msg_id": "", "blocks": {}}

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
                        result.error = f"claude exited with code {line}"
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
                await self._handle_event(event, result, assistant_text, stream, emit)
        except Exception as exc:  # pragma: no cover - defensive: surface, don't crash the turn
            logger.warning("claude consult failed: %s", exc, exc_info=True)
            result.success = False
            result.error = str(exc)
            await emit(EVENT_ERROR, str(exc), {})

        if not result.final_text and assistant_text:
            result.final_text = "\n".join(t for t in assistant_text if t).strip()
        return result

    async def _handle_event(
        self,
        event: dict[str, Any],
        result: ConsultResult,
        assistant_text: list[str],
        stream: dict[str, Any],
        emit: Any,
    ) -> None:
        sid = event.get("session_id")
        if isinstance(sid, str) and sid:
            result.session_id = sid
        etype = str(event.get("type") or "")

        if etype in _IGNORED_EVENT_TYPES:
            return

        # Token-level streaming: a partial Anthropic event. Accumulate text /
        # thinking deltas into the running block and emit the growing text under a
        # stable merge id, so the sidebar types the answer out live. The complete
        # block arrives later as a normal ``assistant`` event under the same merge
        # id and finalizes the row (no duplication).
        if etype == "stream_event":
            await self._handle_stream_event(event.get("event"), stream, emit)
            return

        if etype == "system":
            if event.get("subtype") == "init":
                model = str(event.get("model") or "")
                await emit(EVENT_LOG, f"Session started{f' · {model}' if model else ''}", event)
            return

        if etype == "assistant":
            msg_id = _message_id(event) or stream.get("msg_id") or ""
            for idx, block in enumerate(_content_blocks(event)):
                btype = str(block.get("type") or "")
                if btype == "text":
                    text = str(block.get("text") or "").strip()
                    if text:
                        assistant_text.append(text)
                        await emit(EVENT_TEXT, text, block, _merge("txt", msg_id, idx))
                elif btype == "tool_use":
                    await emit(EVENT_TOOL, _render_tool_use(block), block)
                elif btype == "thinking":
                    text = str(block.get("thinking") or block.get("text") or "").strip()
                    if text:
                        await emit(EVENT_REASONING, text, block, _merge("rsn", msg_id, idx))
            return

        if etype == "user":
            for block in _content_blocks(event):
                if str(block.get("type") or "") == "tool_result":
                    await emit(EVENT_TOOL_RESULT, _render_tool_result(block), block)
            return

        if etype == "result":
            text = str(event.get("result") or "").strip()
            if text:
                result.final_text = text
            if str(event.get("subtype") or "") not in ("", "success"):
                result.success = event.get("is_error") is not True
            # The answer already streamed as the final assistant text block, so we
            # don't re-emit it (that's the old duplicate). Only when no assistant
            # text was streamed at all — a degenerate run — surface the result
            # text so the user still sees an answer.
            if text and not assistant_text:
                await emit(EVENT_TEXT, text, event)
            return

        # Unknown event type — keep it visible as a log rather than dropping it.
        await emit(EVENT_LOG, _compact(event), event)

    async def _handle_stream_event(self, inner: Any, stream: dict[str, Any], emit: Any) -> None:
        """Accumulate a partial Anthropic streaming event into a growing row.

        ``stream_event`` wraps a raw Messages-API event. We track the message id
        and per-block running text, emitting the cumulative text under the merge
        id ``{txt|rsn}:{msg_id}:{index}`` on each delta. The frontend keeps the
        latest per merge id, so the answer types out and is finalized by the
        complete ``assistant`` block that follows (same merge id).
        """
        if not isinstance(inner, dict):
            return
        itype = str(inner.get("type") or "")
        if itype == "message_start":
            stream["msg_id"] = _message_id(inner)
            stream["blocks"] = {}
            return
        if itype == "content_block_start":
            block = inner.get("content_block")
            seed = str(block.get("text") or "") if isinstance(block, dict) else ""
            stream["blocks"][inner.get("index")] = seed
            return
        if itype != "content_block_delta":
            return
        delta = inner.get("delta")
        if not isinstance(delta, dict):
            return
        idx = inner.get("index")
        dtype = str(delta.get("type") or "")
        if dtype == "text_delta":
            acc = stream["blocks"].get(idx, "") + str(delta.get("text") or "")
            stream["blocks"][idx] = acc
            await emit(EVENT_TEXT, acc.strip(), inner, _merge("txt", stream.get("msg_id"), idx))
        elif dtype == "thinking_delta":
            acc = stream["blocks"].get(idx, "") + str(delta.get("thinking") or "")
            stream["blocks"][idx] = acc
            await emit(
                EVENT_REASONING, acc.strip(), inner, _merge("rsn", stream.get("msg_id"), idx)
            )


def _message_id(obj: dict[str, Any]) -> str:
    message = obj.get("message")
    if isinstance(message, dict) and message.get("id"):
        return str(message["id"])
    return ""


def _merge(prefix: str, msg_id: Any, idx: Any) -> dict[str, str] | None:
    """A stable merge id for one content block, or None when unidentifiable."""
    if not msg_id:
        return None
    return {"merge_id": f"{prefix}:{msg_id}:{idx}"}


def _parse_json(line: str) -> dict[str, Any] | None:
    line = line.strip()
    if not line or line[0] not in "{[":
        return None
    try:
        parsed = json.loads(line)
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _content_blocks(event: dict[str, Any]) -> list[dict[str, Any]]:
    message = event.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, list):
        return []
    return [b for b in content if isinstance(b, dict)]


def _render_tool_use(block: dict[str, Any]) -> str:
    """Render a tool call like the CLI: ``Bash(cd …)`` / ``Read(path)``.

    Surfaces the one salient argument (the command, the file, the query) on a
    single line; falls back to a compact dump only when no known arg is present.
    """
    name = str(block.get("name") or "tool")
    raw_input = block.get("input")
    if not isinstance(raw_input, dict) or not raw_input:
        return name
    for key in _TOOL_PRIMARY_ARGS:
        value = raw_input.get(key)
        if isinstance(value, str) and value.strip():
            return f"{name}({_inline(value)})"
    return f"{name}({_inline(_compact(raw_input))})"


def _inline(text: str) -> str:
    """Collapse to a single line and cap for a tool header."""
    one_line = " ".join(text.split())
    if len(one_line) > _TOOL_HEADER_CHARS:
        return one_line[:_TOOL_HEADER_CHARS].rstrip() + " …"
    return one_line


def _render_tool_result(block: dict[str, Any]) -> str:
    content = block.get("content")
    if isinstance(content, list):
        parts = [
            str(part.get("text") or "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        ]
        text = "\n".join(p for p in parts if p)
    else:
        text = str(content or "")
    return _truncate(text) or "(empty result)"


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


__all__ = ["ClaudeCodeBackend"]
