"""Codex backend — drive the local ``codex`` CLI non-interactively.

Uses ``codex exec --json``: a JSONL event stream (``thread.started`` carries the
session id; ``item.*`` events carry reasoning, command executions, file changes,
MCP tool calls and the agent's messages; ``turn.completed`` / ``turn.failed``
close it out). We run sandboxed to the working directory with approvals off so a
headless run never blocks. Continuation is ``codex exec resume <session_id>``.

The Codex JSON schema is still evolving, so the event mapper is deliberately
defensive: it reads ids and item types from whatever fields are present and
renders any unrecognised item as a log line rather than dropping it — nothing
the CLI emitted is lost from the sidebar.

Auth/config come from the user's existing ``~/.codex`` — no token handled here.
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

# Sandbox values that mean "turn the sandbox off entirely" — mapped to the
# explicit Codex flag instead of a ``sandbox_mode`` config override.
_BYPASS_SANDBOX = frozenset(
    {"bypass", "danger-full-access-bypass", "dangerously-bypass-approvals-and-sandbox"}
)

# Item types whose start/finish render to ONE evolving row (placeholder on
# start, content filled on completion) — tagged with the item id so the UI
# merges both phases. (command_execution is intentionally NOT here: its command
# and output are two distinct rows.)
_FILL_IN_ITEMS = frozenset({"web_search"})

# Item types that stream their text incrementally ("*.updated" frames): the
# answer and its reasoning. They share one merge id across the updates and the
# completion so the row types out live and finalizes in place.
_STREAM_TEXT_ITEMS = frozenset({"agent_message", "assistant_message", "reasoning"})


class CodexBackend(SubagentBackend):
    kind = "codex"
    display_name = "Codex"
    cli_command = "codex"

    async def detect(self) -> DetectResult:
        ok, text = await probe_version([self.cli_command, "--version"])
        return DetectResult(
            kind=self.kind,
            display_name=self.display_name,
            available=ok,
            version=text if ok else "",
            detail="" if ok else (text or "codex CLI not found on PATH"),
        )

    def _build_command(
        self,
        question: str,
        *,
        session_id: str | None,
        config: BackendConfig,
        images: list[str] | None = None,
    ) -> list[str]:
        cmd = [self.cli_command, "exec"]
        if session_id:
            cmd += ["resume", session_id]
        cmd += ["--json", "--skip-git-repo-check"]
        # ``--ephemeral`` (don't persist the session) only makes sense for a
        # fresh run, not when resuming an existing session.
        if config.ephemeral and not session_id:
            cmd.append("--ephemeral")
        sandbox = (config.sandbox or "workspace-write").strip()
        bypass = sandbox in _BYPASS_SANDBOX
        if bypass:
            cmd.append("--dangerously-bypass-approvals-and-sandbox")
        elif sandbox:
            # ``-c`` works on both ``exec`` and ``exec resume`` (resume has no
            # ``-s`` flag). Approval policy + network access are config keys too.
            cmd += ["-c", f'sandbox_mode="{sandbox}"']
            if config.approval:
                cmd += ["-c", f'approval_policy="{config.approval}"']
            if config.network_access:
                cmd += ["-c", "sandbox_workspace_write.network_access=true"]
        if config.model:
            cmd += ["-m", config.model]
        if config.effort:
            cmd += ["-c", f'model_reasoning_effort="{config.effort}"']
        # Forwarded images attach natively (``-i`` works on both ``exec`` and
        # ``exec resume``). Repeat the flag per file so the variadic form never
        # swallows the trailing prompt positional.
        for path in images or []:
            cmd += ["-i", path]
        cmd += list(config.extra_args)
        cmd.append(question)
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
                        result.error = f"codex exited with code {line}"
                        await emit(EVENT_ERROR, result.error, {"returncode": line})
                    continue
                event = _parse_json(line)
                if event is None:
                    if line.strip():
                        await emit(EVENT_LOG, line, {"stream": channel})
                    continue
                await self._handle_event(event, result, emit)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("codex consult failed: %s", exc, exc_info=True)
            result.success = False
            result.error = str(exc)
            await emit(EVENT_ERROR, str(exc), {})

        return result

    async def _handle_event(self, event: dict[str, Any], result: ConsultResult, emit: Any) -> None:
        sid = _find_session_id(event)
        if sid:
            result.session_id = sid
        etype = str(event.get("type") or "")

        if etype == "thread.started":
            await emit(EVENT_LOG, "Session started", event)
            return
        if etype in ("turn.failed", "error"):
            message = _error_message(event)
            result.success = False
            result.error = message
            await emit(EVENT_ERROR, message, event)
            return
        if etype == "turn.completed":
            return  # the agent_message item already carried the answer text

        item = event.get("item") if isinstance(event.get("item"), dict) else None

        # Token-level streaming: interim "*.updated" frames carry the item's
        # growing text. For streaming-text items (the answer + its reasoning) emit
        # the running text under a stable merge id so the row types out live; the
        # ".completed" frame finalizes the same row. Other item types carry
        # nothing useful mid-flight, so they're ignored until they complete.
        if item is not None and etype.endswith(".updated"):
            itype = _item_type(item)
            mid = _item_id(item)
            if mid and itype in _STREAM_TEXT_ITEMS:
                text = _item_text(item)
                if text:
                    kind = EVENT_REASONING if itype == "reasoning" else EVENT_TEXT
                    await emit(kind, text, item, {"merge_id": mid})
            return

        if item is not None and (etype.endswith(".completed") or etype.endswith(".started")):
            itype = _item_type(item)
            started = etype.endswith(".started")
            # ``_FILL_IN_ITEMS`` (web_search …) show a placeholder on start that
            # fills in on completion. Streaming-text items finalize, on completion,
            # the row they streamed under their item id — both correlate the two
            # phases by a merge id. ``command_execution`` shows command on start +
            # output on completion (two distinct rows). Everything else renders
            # once, on completion.
            merge_id = ""
            if itype in _FILL_IN_ITEMS or (itype in _STREAM_TEXT_ITEMS and not started):
                merge_id = _item_id(item)
            if started and itype != "command_execution" and not merge_id:
                return
            self._handle_item(item, etype, result)
            kind, text = _render_item(item, etype)
            if text:
                await emit(kind, text, item, {"merge_id": merge_id} if merge_id else None)
            return

        # No recognised item — keep raw events visible unless they are pure
        # lifecycle markers we already handle.
        if etype and not etype.startswith(("item.", "turn.")):
            await emit(EVENT_LOG, _compact(event), event)

    def _handle_item(self, item: dict[str, Any], etype: str, result: ConsultResult) -> None:
        if etype.endswith(".completed") and _item_type(item) in (
            "agent_message",
            "assistant_message",
        ):
            text = _item_text(item)
            if text:
                result.final_text = text


def _parse_json(line: str) -> dict[str, Any] | None:
    line = line.strip()
    if not line or line[0] not in "{[":
        return None
    try:
        parsed = json.loads(line)
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _item_type(item: dict[str, Any]) -> str:
    return str(item.get("type") or item.get("item_type") or "")


def _item_id(item: dict[str, Any]) -> str:
    return str(item.get("id") or item.get("item_id") or "")


def _item_text(item: dict[str, Any]) -> str:
    for key in ("text", "message", "content", "summary"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _render_item(item: dict[str, Any], etype: str) -> tuple[str, str]:
    itype = _item_type(item)
    if itype in ("agent_message", "assistant_message"):
        # The answer renders as the terminal text of the run (its updates + this
        # completion collapse to one merged row); ConsultResult.final_text carries
        # it back to the chat model separately.
        return EVENT_TEXT, _item_text(item)
    if itype == "reasoning":
        return EVENT_REASONING, _item_text(item)
    if itype == "command_execution":
        command = str(item.get("command") or item.get("cmd") or "").strip()
        if etype.endswith(".started"):
            return EVENT_TOOL, f"$ {command}" if command else "command"
        output = str(item.get("aggregated_output") or item.get("output") or "").strip()
        exit_code = item.get("exit_code")
        header = f"$ {command}" if command else "command"
        suffix = f" (exit {exit_code})" if exit_code not in (None, "") else ""
        return EVENT_TOOL_RESULT, _truncate(f"{header}{suffix}\n{output}".strip())
    if itype == "file_change":
        changes = item.get("changes") or item.get("files") or item.get("path")
        return EVENT_TOOL, _truncate(f"file change · {_compact(changes)}")
    if itype in ("mcp_tool_call", "tool_call"):
        name = str(item.get("name") or item.get("tool") or "tool")
        return EVENT_TOOL, _truncate(
            f"{name} · {_compact(item.get('arguments') or item.get('input') or {})}"
        )
    if itype == "web_search":
        query = str(item.get("query") or item.get("action") or "").strip()
        # Start (or no query yet) → placeholder; completion → fill in the query.
        if etype.endswith(".started") or not query:
            return EVENT_TOOL, "web search"
        return EVENT_TOOL, _truncate(f"web search · {query}")
    if itype in ("todo_list", "plan_update", "plan"):
        return EVENT_LOG, _truncate(_compact(item.get("items") or item.get("plan") or item))
    # Unknown item type: render whatever text we can find, else the raw object.
    return EVENT_LOG, _item_text(item) or _compact(item)


def _find_session_id(event: dict[str, Any]) -> str:
    for key in ("thread_id", "session_id", "threadId", "sessionId"):
        value = event.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _error_message(event: dict[str, Any]) -> str:
    for key in ("message", "error", "reason", "detail"):
        value = event.get(key)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, dict):
            inner = value.get("message")
            if isinstance(inner, str) and inner:
                return inner
    return "Codex reported a failure"


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


__all__ = ["CodexBackend"]
