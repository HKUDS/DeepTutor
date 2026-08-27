"""Antigravity CLI backend — drive the local ``agy`` CLI in headless mode.

Google retired Gemini CLI on 2026-06-18 and pointed its users at Antigravity
CLI, so for anyone on a Google AI Pro/Ultra or Gemini Code Assist plan the
``gemini`` backend simply stopped having a CLI to detect (#828). This backend is
the replacement path. The old one is deliberately kept: Gemini CLI still runs
for anyone holding a Gemini API key, and a working connection must not break on
upgrade.

Invocation is ``agy -p <question> --output-format stream-json``. The event
vocabulary is the CLI's own and is *not* Gemini CLI's, despite the shared
lineage — events are tagged with ``event`` (not ``type``) and carry their body
in a same-named field:

* ``init`` — ``conversation_id`` plus ``init.{cwd,tools,permission_mode,model}``
* ``step_update`` — ``step_update.{step_index,state,step_type,text_delta,
  tool_name,tool_info,usage}``; assistant text arrives as ``text_delta`` chunks
  with no aggregate, so we accumulate per step index
* ``result`` — ``result.{status,response,num_turns,usage}``

Sessions resume with ``--conversation <conversation_id>`` (the id the ``init``
event hands back), the model is pinned with ``--model`` and reasoning depth with
``--effort low|medium|high``.

Permissions differ from Gemini CLI in a way worth stating: headless ``agy``
*soft-denies* tools that would need approval rather than blocking on them, so an
unattended run degrades instead of hanging. That makes the cautious mapping the
correct default — only the explicitly permissive modes pass
``--dangerously-skip-permissions``.

⚠️ Upstream issue google-antigravity/antigravity-cli#76: ``-p`` has been
reported to emit nothing at all when stdout is not a TTY, which is exactly how
this backend runs it. It is a plain-print bug and ``--output-format stream-json``
takes a different output path, but if a build regresses the whole stream, a
consult would otherwise look like the agent answering with silence. So an empty
stream is reported as a failure that names the cause — see ``_EMPTY_STREAM_HINT``.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from deeptutor.services.subagent.base import OnEvent, SubagentBackend
from deeptutor.services.subagent.config import BackendConfig
from deeptutor.services.subagent.process import (
    not_found_detail,
    probe_version,
    stream_process_lines,
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
    "Antigravity CLI (agy) not found on PATH. Install it from https://antigravity.google/docs/cli."
)

_MAX_FIELD_CHARS = 4000
_TOOL_HEADER_CHARS = 160

# Stored permission modes use Claude Code's spellings as the shared vocabulary.
# Only the two permissive ones waive approval; `default` and `plan` leave the
# CLI's soft-deny in place, which is safe here precisely because soft-deny does
# not stall a headless run.
_SKIP_PERMISSION_MODES = frozenset({"bypassPermissions", "acceptEdits"})

# `--effort` accepts exactly these; anything else is dropped rather than passed
# through to a non-zero exit on an unknown value.
_EFFORTS = frozenset({"low", "medium", "high"})

# Terminal statuses the CLI reports in its `result` event.
_FAILED_STATUSES = frozenset({"ERROR", "CANCELED", "INTERRUPTED", "INVALID"})

_EMPTY_STREAM_HINT = (
    "agy produced no output. If it answers normally in a terminal but not here, "
    "this is antigravity-cli#76 (stdout suppressed when not a TTY); upgrade the CLI."
)

# The salient argument to put in a tool header — `Shell(cmd …)` rather than raw
# JSON, matching how the other CLI backends render their tool rows.
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


def _parse_json(line: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _clip(text: str, limit: int = _MAX_FIELD_CHARS) -> str:
    return text if len(text) <= limit else f"{text[:limit]}…"


def _tool_header(name: str, info: Any) -> str:
    """``name(salient arg)`` for the sidebar row."""
    if not isinstance(info, dict):
        return name
    args = info.get("args") if isinstance(info.get("args"), dict) else info
    for key in _TOOL_PRIMARY_ARGS:
        value = args.get(key) if isinstance(args, dict) else None
        if isinstance(value, str) and value.strip():
            return f"{name}({_clip(value.strip(), _TOOL_HEADER_CHARS)})"
    return name


class AntigravityBackend(SubagentBackend):
    """Consult Google's Antigravity CLI (``agy``) as a subagent."""

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
            detail="" if ok else not_found_detail(text, _NOT_FOUND_DETAIL),
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
        # No system-prompt flag, so the delegate instruction is prepended once on
        # the session-creating consult; a resumed conversation already carries it.
        if config.system_prompt.strip() and not session_id:
            prompt = f"{config.system_prompt.strip()}\n\n{question}"
        # Headless `agy` documents no attachment flag, so images are named as
        # paths and left to the agent's own file-reading tools — the same
        # arrangement Claude Code uses.
        if images:
            listing = "\n".join(images)
            prompt = f"{prompt}\n\nAttached image files (read them from disk):\n{listing}"
        cmd = [
            self.cli_command,
            "-p",
            prompt,
            "--output-format",
            "stream-json",
        ]
        if config.permission_mode in _SKIP_PERMISSION_MODES:
            cmd.append("--dangerously-skip-permissions")
        if session_id:
            cmd += ["--conversation", session_id]
        if config.model:
            cmd += ["--model", config.model]
        if config.effort in _EFFORTS:
            cmd += ["--effort", config.effort]
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
        # Assistant text arrives as `text_delta` chunks with no aggregate, so
        # accumulate per step index; a step that is not text closes the current
        # block, letting post-tool prose stream as its own row.
        stream: dict[str, Any] = {"blocks": [], "open_step": None}
        saw_stream_event = False

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
                saw_stream_event = True
                await self._handle_event(event, result, stream, emit)
        except Exception as exc:  # pragma: no cover - defensive: surface, don't crash the turn
            logger.warning("antigravity consult failed: %s", exc, exc_info=True)
            result.success = False
            result.error = str(exc)
            await emit(EVENT_ERROR, str(exc), {})

        if not result.final_text:
            result.final_text = "\n\n".join(b for b in stream["blocks"] if b.strip()).strip()
        # Silence is not an answer: name the known cause rather than handing the
        # caller an empty reply that reads like the agent had nothing to say.
        if result.success and not result.final_text and not saw_stream_event:
            result.success = False
            result.error = _EMPTY_STREAM_HINT
            await emit(EVENT_ERROR, result.error, {})
        return result

    async def _handle_event(
        self,
        event: dict[str, Any],
        result: ConsultResult,
        stream: dict[str, Any],
        emit: Any,
    ) -> None:
        name = str(event.get("event") or "")
        body = event.get(name)
        body = body if isinstance(body, dict) else {}

        # Every event carries the conversation id; the `init` one is simply the
        # first, and taking it wherever it appears keeps resume working even if a
        # build stops emitting `init`.
        conversation = str(event.get("conversation_id") or body.get("conversation_id") or "")
        if conversation:
            result.session_id = conversation

        if name == "init":
            model = str(body.get("model") or "")
            await emit(EVENT_LOG, f"Session started{f' · {model}' if model else ''}", event)
            return

        if name == "step_update":
            await self._handle_step(body, stream, emit, event)
            return

        if name == "result":
            status = str(body.get("status") or "").upper()
            response = str(body.get("response") or "")
            if response:
                result.final_text = response
            if status in _FAILED_STATUSES:
                result.success = False
                result.error = str(body.get("error") or "") or f"agy reported status {status}"
                await emit(EVENT_ERROR, result.error, event)
            return

    async def _handle_step(
        self,
        step: dict[str, Any],
        stream: dict[str, Any],
        emit: Any,
        raw: dict[str, Any],
    ) -> None:
        index = step.get("step_index")
        delta = str(step.get("text_delta") or "")
        tool_name = str(step.get("tool_name") or "")

        if delta:
            if stream["open_step"] != index:
                stream["blocks"].append("")
                stream["open_step"] = index
            stream["blocks"][-1] += delta
            await emit(EVENT_TEXT, delta, raw, {"partial": True, "step": index})
            return

        if tool_name:
            # A tool ends the current text block so later prose starts a new row.
            stream["open_step"] = None
            info = step.get("tool_info")
            state = str(step.get("state") or "").upper()
            if state == "DONE":
                output = ""
                if isinstance(info, dict):
                    output = str(info.get("result") or info.get("output") or "")
                await emit(EVENT_TOOL_RESULT, _clip(output), raw, {"tool": tool_name})
            else:
                await emit(EVENT_TOOL, _tool_header(tool_name, info), raw, {"tool": tool_name})


__all__ = ["AntigravityBackend"]
