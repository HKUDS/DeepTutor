"""Antigravity CLI backend — drive the local ``agy`` CLI in headless print mode.

Google retired Gemini CLI for consumer tiers in favor of Antigravity CLI
(``agy``). Headless mode shares the ``-p`` / ``--output-format stream-json``
surface, but the NDJSON vocabulary differs: events use an ``event`` key
(``init``, ``step_update``, ``result``) instead of Gemini's ``type`` field
(``message`` / ``tool_use`` / …). Auth still lives under ``~/.gemini``.

Permission asks have no interactive TUI in headless mode; ``auto_approve``
maps onto ``--dangerously-skip-permissions``. Sessions resume with
``--conversation <id>`` (not Gemini's ``--resume``).
"""

from __future__ import annotations

import json
import logging
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

_TOOL_PRIMARY_ARGS = (
    "CommandLine",
    "command",
    "file_path",
    "path",
    "pattern",
    "query",
    "url",
    "prompt",
    "description",
)

_EFFORTS = frozenset({"low", "medium", "high"})


class AntigravityBackend(SubagentBackend):
    kind = "antigravity"
    display_name = "Antigravity CLI"
    cli_command = "agy"

    async def detect(self) -> DetectResult:
        ok, text = await probe_version([self.cli_command, "--version"])
        return DetectResult(
            kind=self.kind,
            display_name=self.display_name,
            available=ok,
            version=text if ok else "",
            detail="" if ok else (text or "agy CLI not found on PATH"),
        )

    def _build_command(
        self,
        question: str,
        *,
        session_id: str | None,
        config: BackendConfig,
    ) -> list[str]:
        prompt = question
        # No system-prompt flag — prefix once on the session-creating consult.
        if config.system_prompt.strip() and not session_id:
            prompt = f"{config.system_prompt.strip()}\n\n{question}"
        cmd = [
            self.cli_command,
            "-p",
            prompt,
            "--output-format",
            "stream-json",
        ]
        # Unattended runs soft-deny shell/mutating tools unless we skip asks.
        if config.auto_approve is not False:
            cmd.append("--dangerously-skip-permissions")
        if session_id:
            cmd += ["--conversation", session_id]
        if config.model:
            cmd += ["--model", config.model]
        effort = str(config.effort or "").strip().lower()
        if effort in _EFFORTS:
            cmd += ["--effort", effort]
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
        images: list[str] | None = None,  # noqa: ARG002 — no documented @path attach
        partner_id: str | None = None,  # noqa: ARG002 — partner-only; ignored here
    ) -> ConsultResult:
        config = config or BackendConfig()
        cmd = self._build_command(question, session_id=session_id, config=config)
        result = ConsultResult(session_id=session_id)
        # Accumulate agent_response text_delta fragments into blocks; a tool
        # step closes the current block so post-tool text starts a new row.
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
                        result.error = f"agy exited with code {line}"
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
            logger.warning("antigravity consult failed: %s", exc, exc_info=True)
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
        etype = str(event.get("event") or "")

        if etype == "init":
            sid = str(event.get("conversation_id") or "")
            if sid:
                result.session_id = sid
            init = event.get("init") if isinstance(event.get("init"), dict) else {}
            model = str(init.get("model") or "")
            await emit(EVENT_LOG, f"Session started{f' · {model}' if model else ''}", event)
            return

        if etype == "step_update":
            step = event.get("step_update")
            if not isinstance(step, dict):
                return
            step_type = str(step.get("step_type") or "")

            if step_type == "agent_response":
                delta = str(step.get("text_delta") or "")
                if not delta:
                    return
                blocks: list[str] = stream["blocks"]
                if stream["open"] and blocks:
                    blocks[-1] += delta
                else:
                    blocks.append(delta)
                    stream["open"] = True
                await emit(
                    EVENT_TEXT,
                    blocks[-1].strip(),
                    event,
                    {"merge_id": f"txt:{len(blocks) - 1}"},
                )
                return

            if step_type == "tool":
                stream["open"] = False
                await emit(EVENT_TOOL, _render_tool_use(step), event)
                # tool_info arrives with both call and result on the DONE step.
                if str(step.get("state") or "") == "DONE":
                    await emit(EVENT_TOOL_RESULT, _render_tool_result(step), event)
                return

            return

        if etype == "result":
            payload = event.get("result") if isinstance(event.get("result"), dict) else {}
            sid = str(payload.get("conversation_id") or event.get("conversation_id") or "")
            if sid:
                result.session_id = sid
            status = str(payload.get("status") or "").upper()
            if status and status != "SUCCESS":
                result.success = False
                error = payload.get("error")
                if isinstance(error, str) and error.strip():
                    result.error = error.strip()
                elif isinstance(error, dict) and error.get("message"):
                    result.error = str(error["message"])
                elif not result.error:
                    result.error = f"agy ended with status {status}"
                if result.error:
                    await emit(EVENT_ERROR, result.error, event)
            response = str(payload.get("response") or "").strip()
            if response and not result.final_text:
                result.final_text = response
            return

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


def _render_tool_use(step: dict[str, Any]) -> str:
    info = step.get("tool_info") if isinstance(step.get("tool_info"), dict) else {}
    name = str(info.get("name") or step.get("tool_name") or "tool")
    params = info.get("parameters")
    if not isinstance(params, dict) or not params:
        return name
    for key in _TOOL_PRIMARY_ARGS:
        value = params.get(key)
        if isinstance(value, str) and value.strip():
            return f"{name}({_inline(value)})"
    return f"{name}({_inline(_compact(params))})"


def _render_tool_result(step: dict[str, Any]) -> str:
    info = step.get("tool_info") if isinstance(step.get("tool_info"), dict) else {}
    error = info.get("error")
    if isinstance(error, dict) and error.get("message"):
        return _truncate(str(error["message"]))
    if isinstance(error, str) and error.strip():
        return _truncate(error)
    return _truncate(str(info.get("output") or "")) or "(no output)"


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


__all__ = ["AntigravityBackend"]
