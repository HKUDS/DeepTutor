"""Drive xAI's Grok CLI using its native ``streaming-json`` headless protocol.

The CLI owns authentication and session storage. DeepTutor only retains the
``end.sessionId`` needed for ``--resume`` in the connection's working directory.
Text and tool events stream to Activity; private ``thought`` payloads and opaque
usage signatures are deliberately not forwarded or stored in the trace.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
from typing import Any

from deeptutor.services.subagent.base import OnEvent, SubagentBackend
from deeptutor.services.subagent.config import BackendConfig, default_backend_config
from deeptutor.services.subagent.process import (
    compact_field,
    not_found_detail,
    probe_version,
    stream_process_lines,
    truncate_field,
)
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

_NOT_FOUND_DETAIL = (
    "Install xAI's Grok CLI on the DeepTutor server, sign in with `grok login`, "
    "and ensure `grok` is on PATH. Requires native `--output-format streaming-json`."
)


@dataclass(slots=True)
class _StreamState:
    ended: bool = False
    text: str = ""
    text_index: int = 0
    new_text_block: bool = True
    tools: dict[str, dict[str, Any]] = field(default_factory=dict)


class GrokBackend(SubagentBackend):
    """Consult a locally installed, authenticated xAI Grok CLI."""

    kind = "grok"
    display_name = "Grok CLI"
    cli_command = "grok"

    async def detect(self) -> DetectResult:
        ok, version = await probe_version([self.cli_command, "--version"])
        detail = "" if ok else not_found_detail(version, _NOT_FOUND_DETAIL)
        if ok:
            # Several unrelated packages also install a binary named `grok`.
            # Version alone cannot establish the headless protocol we consume.
            help_ok, help_text = await probe_version([self.cli_command, "--help"])
            ok = help_ok and all(
                flag in help_text
                for flag in ("streaming-json", "--single", "--resume", "--permission-mode")
            )
            if not ok:
                detail = "Incompatible grok command. " + _NOT_FOUND_DETAIL
        return DetectResult(
            kind=self.kind,
            display_name=self.display_name,
            available=ok,
            version=version if ok else "",
            detail=detail,
        )

    def _build_command(
        self, question: str, *, session_id: str | None, config: BackendConfig
    ) -> list[str]:
        cmd = [
            self.cli_command,
            "--output-format",
            "streaming-json",
            "--permission-mode",
            config.permission_mode or "dontAsk",
            # Keep session context, but do not mix independent DeepTutor chats
            # through Grok's cross-session memory.
            "--no-memory",
            "--verbatim",
        ]
        if config.model:
            cmd += ["--model", config.model]
        if config.effort:
            cmd += ["--reasoning-effort", config.effort]
        if config.system_prompt:
            cmd += ["--rules", config.system_prompt]
        if session_id:
            cmd += ["--resume", session_id]
        cmd += list(config.extra_args)
        # Equals form keeps a prompt beginning with '-' a value, not a flag.
        cmd.append(f"--single={question}")
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
        partner_id: str | None = None,  # noqa: ARG002 — partner-only
    ) -> ConsultResult:
        config = config or default_backend_config(self.kind)
        result = ConsultResult(session_id=session_id)
        state = _StreamState()

        async def emit(
            kind: str, text: str, raw: dict[str, Any], meta: dict[str, Any] | None = None
        ) -> None:
            result.event_count += 1
            await on_event(SubagentEvent(kind=kind, text=text, raw=raw, meta=meta or {}))

        async def fail(message: str) -> None:
            if result.success:
                result.success = False
                result.error = message
                await emit(EVENT_ERROR, message, {})

        if images:
            await fail("Grok CLI image forwarding is not supported by this connector.")
            return result

        cmd = self._build_command(question, session_id=session_id, config=config)
        try:
            async for channel, line in stream_process_lines(cmd, cwd=cwd):
                if channel == "exit":
                    if line != "0":
                        await fail(f"grok exited with code {line}")
                    continue
                if channel == "stderr":
                    if line.strip():
                        await emit(EVENT_LOG, truncate_field(line), {"stream": channel})
                    continue
                try:
                    event = json.loads(line)
                except (ValueError, TypeError):
                    if line.strip():
                        # Do not echo malformed frames: they may contain a
                        # truncated thought or other private protocol payload.
                        await fail("Grok CLI emitted invalid streaming JSON.")
                    continue
                if not isinstance(event, dict):
                    await fail("Grok CLI emitted an invalid streaming event.")
                    continue
                await self._handle_event(event, result, state, emit, fail)
        except Exception as exc:  # cancellation propagates to the process cleanup
            logger.warning("grok consult failed: %s", exc)
            await fail(str(exc))

        if not state.ended:
            await fail("Grok CLI stream ended without a completion event.")
        elif not result.final_text.strip():
            await fail("Grok CLI completed without an answer.")
        return result

    async def _handle_event(
        self,
        event: dict[str, Any],
        result: ConsultResult,
        state: _StreamState,
        emit: Any,
        fail: Any,
    ) -> None:
        etype = str(event.get("type") or "")
        if etype in ("thought", "available_commands"):
            return
        if etype == "usage":
            state.new_text_block = True
            return
        if etype == "text":
            delta = event.get("data")
            if not isinstance(delta, str) or not delta:
                return
            if state.new_text_block:
                state.text = ""
                state.text_index += 1
                state.new_text_block = False
            state.text += delta
            result.final_text = state.text
            await emit(
                EVENT_TEXT,
                state.text,
                {"type": etype},
                {"merge_id": f"grok-text-{state.text_index}"},
            )
            return
        if etype in ("tool_call", "tool_call_update"):
            # A preamble before a tool is not the final answer to the consult.
            if etype == "tool_call":
                state.new_text_block = True
                result.final_text = ""
            tool_id = str(event.get("toolCallId") or "")
            # Updates are sparse, and the UI replaces a merged row in full.
            # Retain the name and input when later frames only carry output.
            tool = state.tools.setdefault(tool_id, {}) if tool_id else {}
            tool.update({key: value for key, value in event.items() if value is not None})
            name = str(tool.get("toolName") or tool.get("title") or "Tool")
            status = str(tool.get("status") or "")
            fields = [name]
            if status:
                fields.append(status)
            for key in ("rawInput", "rawOutput", "content"):
                if tool.get(key):
                    fields.append(compact_field(tool[key]))
            completed = etype == "tool_call_update" and status in ("completed", "failed")
            await emit(
                EVENT_TOOL_RESULT if completed else EVENT_TOOL,
                truncate_field(" · ".join(fields)),
                {"type": etype, "toolCallId": tool_id, "status": status},
                {"merge_id": f"grok-tool-{tool_id}"} if tool_id else None,
            )
            return
        if etype == "end":
            state.ended = True
            sid = event.get("sessionId") or event.get("session_id")
            if isinstance(sid, str) and sid:
                result.session_id = sid
            reason = event.get("stopReason") or event.get("stop_reason")
            if reason != "end_turn":
                await fail(f"Grok CLI stopped without completing the turn: {reason or 'unknown'}")
            return
        if etype == "error":
            await fail(truncate_field(str(event.get("message") or "Grok CLI error")))
            return
        # New protocol events are visible by type, without exposing unknown
        # payloads (which can include internal reasoning or opaque signatures).
        if etype:
            await emit(EVENT_LOG, f"Grok CLI: {etype}", {"type": etype})
