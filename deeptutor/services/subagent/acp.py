"""ACP backend — drive an Agent Client Protocol (ACP) agent as a subagent.

Part of #1028 (stage 1): DeepTutor plays the ACP *client* side — JSON-RPC 2.0
over newline-delimited stdio — against a spawnable ACP *agent* process. The
agent command is not hard-coded (ACP is a transport standard, not one binary):
it comes from the ``DEEPTUTOR_ACP_COMMAND`` environment variable (a JSON array
of argv, or a shell-quoted string), or from the per-backend
``BackendConfig.extra_args`` when the env var is unset.

Wire transcript (schema-verified against ACP v1; see the note below for what
was and was not confirmed):

1. client → agent: ``initialize`` (``protocolVersion`` + ``clientCapabilities``).
   The agent replies with the negotiated version and its capabilities.
2. client → agent: ``session/new`` with ``cwd`` (absolute) + ``mcpServers: []``,
   or ``session/load`` with ``mcpServers: []`` + ``cwd`` + ``sessionId`` when
   resuming a prior session. The agent replies with the ``sessionId`` in the
   JSON-RPC result (a JSON-RPC error rejects the request).
3. client → agent: ``session/prompt`` with ``sessionId`` and a ``prompt`` array
   of content blocks (``[{"type": "text", "text": …}]``). While it works, the
   agent streams ``session/update`` notifications whose ``update.sessionUpdate``
   discriminator picks the shape:
   ``agent_message_chunk`` → ``text`` (streamed text pieces),
   ``agent_thought_chunk`` → ``reasoning``, ``tool_call`` → ``tool``,
   ``tool_call_update`` (``completed``/``failed``) → ``tool_result`` (tool start
   and finish share a ``merge_id`` of the ``toolCallId`` so the UI collapses
   them), ``plan*`` / ``session_info_update`` / ``usage_update`` /
   ``compaction*`` / mode/config/command updates → ``log``, and any unknown
   ``sessionUpdate`` kind is kept visible as ``log`` rather than dropped.
   The turn ends when the ``session/prompt`` request gets its JSON-RPC response
   (``result.stopReason``); ``refusal``/``cancelled`` fail the consult, other
   stop reasons succeed with whatever text streamed.
4. Interactive prompts in v1 are *elicitation*, not ``input_request``: the agent
   sends an ``elicitation/create`` **request** and the client answers with a
   ``CreateElicitationResponse``. This backend answers ``{"action": "decline"}``
   (no input from a headless run — a valid v1 response for any elicitation
   mode) and surfaces a log event; the follow-up ``elicitation/complete``
   notification is consumed. Full elicitation (form/URL/text collection) is
   future work. ``session/request_permission`` and any other unsolicited agent
   request (``fs/*``, ``terminal/*``, ``mcp/*``) are answered with JSON-RPC
   method-not-found — this client advertises none of those capabilities, so a
   conformant agent should not call them; auto-approving permissions is
   deliberately not done.

Consult waits for the agent's own turn end — the ``session/prompt`` response,
or the process exiting. Only the protocol handshake (initialize → session
ready) is bounded by ``_HANDSHAKE_TIMEOUT_SECONDS``, so a non-ACP binary
pointed at this backend fails fast instead of hanging the turn; once a turn is
running, consult waits unconditionally, matching the subagent driver contract.
After the turn ends the child is reaped within a short grace
(``_SHUTDOWN_GRACE_SECONDS``) so a long-lived host cannot leak a process per
consult.

✏️ Schema-verification note (updated): stage-1 shapes were verified against the
official ACP v1 schema — ``schema/v1/schema.json`` in
``agentclientprotocol/agent-client-protocol``, cross-checked with the types
generated from it in ``@agentclientprotocol/sdk`` (``InitializeRequest``,
``NewSessionRequest`` ``{cwd, mcpServers}``, ``LoadSessionRequest``
``{mcpServers, cwd, sessionId}``, ``PromptRequest`` ``{sessionId,
prompt: ContentBlock[]}``, the ``session/update`` notification envelope
``{sessionId, update}`` with the ``SessionUpdate`` variant union, the
``elicitation/create`` request with its ``CreateElicitationResponse`` result,
and ``session/prompt`` → ``PromptResponse.stopReason``). Fields still only
documented, not exercised against a real agent: the full ``ClientCapabilities``
/``AgentCapabilities`` matrices (we send an empty client-capabilities object),
the auth flows some agents gate on ``authenticate`` (not implemented — such an
agent will surface its own error at the handshake), the exact
``session/request_permission`` response shape (answered method-not-found), and
elicitation form/URL content formats (answered with a universal ``decline``).
Nothing here is asserted as required beyond the JSON-RPC 2.0 envelope and the
schema fields listed above.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import contextlib
import json
import logging
import os
import shlex
import shutil
from typing import Any

from deeptutor.services.subagent.base import OnEvent, SubagentBackend
from deeptutor.services.subagent.config import BackendConfig, load_subagent_settings
from deeptutor.services.subagent.process import (
    compact_field as _compact,
)
from deeptutor.services.subagent.process import (
    resolve_cli_command,
    truncate_field,
)
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

#: Env var naming the ACP agent argv (JSON array preferred; else shell-quoted).
ACP_COMMAND_ENV = "DEEPTUTOR_ACP_COMMAND"

#: ACP protocol version we negotiate (v1 — see the schema-verification note).
_PROTOCOL_VERSION = 1
#: How long the initialize → session handshake may take before consult fails.
_HANDSHAKE_TIMEOUT_SECONDS = 30.0
#: How long to wait for the child to exit / drain after the turn ends.
_SHUTDOWN_GRACE_SECONDS = 5.0

_NOT_CONFIGURED = (
    f"No ACP agent command configured: set {ACP_COMMAND_ENV} to the agent argv "
    '(e.g. ["claude", "--acp"]) or provide it as the per-backend extra_args.'
)

#: Session id key spellings tolerated when reading agent frames (v1 uses
#: ``sessionId``; the snake_case spellings are kept defensively for forward
#: compat with builds that leak them).
_SESSION_ID_KEYS = ("sessionId", "session_id", "session.id")

#: ``session/update`` kinds that carry the assistant's answer text pieces.
_AGENT_TEXT_KINDS = frozenset({"agent_message_chunk"})
#: ``session/update`` kinds that carry the agent's visible thinking.
_THOUGHT_KINDS = frozenset({"agent_thought_chunk"})
#: ``session/update`` kinds that echo the user's own message back (ignored —
#: the question was already streamed by the capability that called consult).
_USER_TEXT_KINDS = frozenset({"user_message_chunk"})
#: ``session/update`` kinds that announce a tool invocation / its progress.
_TOOL_CALL_KINDS = frozenset({"tool_call"})
_TOOL_UPDATE_KINDS = frozenset({"tool_call_update"})
#: ``session/update`` kinds rendered as plain log lines.
_LOG_UPDATE_KINDS = frozenset(
    {
        "plan",
        "plan_update",
        "plan_removed",
        "session_info_update",
        "usage_update",
        "current_mode_update",
        "config_option_update",
        "available_commands_update",
        "compaction_update",
        "compaction_summary_chunk",
    }
)

#: ``session/prompt`` stop reasons that mean the agent declined to answer.
_FAILED_STOP_REASONS = frozenset({"refusal", "cancelled"})


class AcpHostError(Exception):
    """The ACP agent violated the protocol (or the handshake failed)."""


class AcpBackend(SubagentBackend):
    """Consult any ACP agent process as a subagent over stdio JSON-RPC."""

    kind = "acp"
    display_name = "ACP (Agent Client Protocol)"
    # No fixed binary — the command is configured per machine (env / settings).
    cli_command = ""
    local_cli = True
    detectable = True

    def __init__(
        self,
        host_factory: Callable[[], Awaitable[Any]] | None = None,
    ) -> None:
        """Optionally inject a process spawner for offline tests.

        The default spawns the configured ACP agent command as a subprocess with
        its stdio piped (see :func:`_spawn_host`). ``host_factory`` — awaited
        with no arguments and expected to return an object exposing the same
        duck-typed surface as an :class:`asyncio.subprocess.Process` (``stdin``
        writer, ``stdout`` reader, ``returncode``, ``wait``/``terminate``/
        ``kill``) — is the seam tests use to drive consult against an in-process
        fake agent when OS pipes are unavailable, mirroring the transport
        injection the remote Hermes backend already uses.
        """
        self._host_factory = host_factory

    async def detect(self) -> DetectResult:
        """Report whether an ACP agent command is configured and resolvable.

        ACP is a transport, so there is no universal ``--version`` probe and
        none is attempted (an ACP-mode CLI would wait for the handshake and
        time out). Availability is "a command is configured (env or per-backend
        extra_args) and its first token resolves on PATH".
        """
        command = acp_host_command(load_subagent_settings().backend(self.kind))
        if not command:
            return DetectResult(
                kind=self.kind,
                display_name=self.display_name,
                available=False,
                detail=_NOT_CONFIGURED,
            )
        if _command_resolves(command):
            return DetectResult(
                kind=self.kind,
                display_name=self.display_name,
                available=True,
            )
        return DetectResult(
            kind=self.kind,
            display_name=self.display_name,
            available=False,
            detail=f"configured ACP agent command not found on PATH: {command[0]}",
        )

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
        command = acp_host_command(config)
        result = ConsultResult(session_id=session_id)

        async def emit(
            kind: str,
            text: str,
            raw: dict[str, Any] | None = None,
            meta: dict[str, Any] | None = None,
        ) -> None:
            result.event_count += 1
            await on_event(SubagentEvent(kind=kind, text=text, raw=raw or {}, meta=meta or {}))

        if not command and self._host_factory is None:
            return await _fail(result, emit, _NOT_CONFIGURED)

        prompt = _build_prompt(
            question,
            system_prompt=config.system_prompt,
            images=images,
            resumed=session_id is not None,
        )

        process = None
        reader_task = None
        try:
            spawn = self._host_factory or (lambda: _spawn_host(command, cwd=cwd))
            process = await spawn()
            session = _HostSession(process, emit)
            reader_task = asyncio.create_task(_pump_frames(process.stdout, session.frames))
            sid = await _handshake(session, resume=session_id, cwd=cwd)
            result.session_id = sid
            await emit(EVENT_LOG, f"ACP session {sid} started", {})
            await _run_turn(session, result, emit, sid, prompt)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - defensive: surface, don't crash the turn
            logger.warning("acp consult failed: %s", exc, exc_info=True)
            await _fail(result, emit, str(exc))
        finally:
            if process is not None:
                await _teardown(process, reader_task)
        return result


# ---- command resolution ---------------------------------------------------------


def acp_host_command(config: BackendConfig | None = None) -> list[str]:
    """The configured ACP agent argv, or ``[]`` when nothing is configured.

    Precedence: the :data:`ACP_COMMAND_ENV` variable (JSON array of strings, or
    a shell-quoted string) wins; otherwise ``config.extra_args`` is treated as
    the full argv. When the env var supplies the command, ``extra_args`` are
    appended as trailing flags.
    """
    raw = os.environ.get(ACP_COMMAND_ENV, "").strip()
    if raw:
        command = _parse_command(raw)
        if command:
            extra = list((config.extra_args or []) if config else [])
            return [*command, *extra]
    if config and config.extra_args:
        return list(config.extra_args)
    return []


def _parse_command(raw: str) -> list[str]:
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list) and all(isinstance(item, str) for item in parsed):
            return parsed
    except (ValueError, TypeError):
        pass
    try:
        parts = shlex.split(raw)
    except ValueError:
        return []
    return parts


def _command_resolves(command: list[str]) -> bool:
    head = command[0]
    resolved = shutil.which(head, path=os.environ.get("PATH")) if head else None
    if resolved:
        return True
    # An absolute path that shutil.which could not resolve may still be a file.
    return bool(os.path.isabs(head) and os.path.isfile(head))


# ---- prompt assembly -------------------------------------------------------------


def _build_prompt(
    question: str,
    *,
    system_prompt: str,
    images: list[str] | None = None,
    resumed: bool = False,
) -> str:
    text = question
    # The delegate instruction rides on the session-creating consult only; a
    # resumed session already carries it (mirrors the other CLI backends).
    if system_prompt.strip() and not resumed:
        text = f"{system_prompt.strip()}\n\n{text}"
    if images:
        listing = "\n".join(str(path) for path in images)
        text = f"{text}\n\nAttached image files (read them from disk):\n{listing}"
    return text


# ---- process plumbing --------------------------------------------------------------


async def _spawn_host(command: list[str], *, cwd: str | None) -> asyncio.subprocess.Process:
    env = {
        **os.environ,
        # Whatever the agent is, ask it to talk clean UTF-8 text on the pipes.
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",
    }
    resolved = resolve_cli_command(command, path=env.get("PATH"))
    try:
        return await asyncio.create_subprocess_exec(
            *resolved,
            cwd=cwd or None,
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except FileNotFoundError as exc:
        raise AcpHostError(
            f"ACP agent command not found: {command[0]} (configure {ACP_COMMAND_ENV})"
        ) from exc


class _HostSession:
    """One live agent process plus the single queue its stdout feeds."""

    def __init__(self, process: asyncio.subprocess.Process, emit: Any) -> None:
        self.process = process
        self.emit = emit
        self.frames: asyncio.Queue = asyncio.Queue()
        self._seq = 0

    def next_request_id(self) -> int:
        self._seq += 1
        return self._seq

    async def send_request(self, method: str, params: dict[str, Any]) -> int:
        request_id = self.next_request_id()
        await self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        return request_id

    async def send_response(self, request_id: Any, result: dict[str, Any]) -> None:
        await self._write({"jsonrpc": "2.0", "id": request_id, "result": result})

    async def send_error(self, request_id: Any, code: int, message: str) -> None:
        await self._write(
            {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
        )

    async def _write(self, obj: dict[str, Any]) -> None:
        stdin = self.process.stdin
        if stdin is None:
            raise AcpHostError("ACP agent stdin closed unexpectedly")
        stdin.write((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
        await stdin.drain()


async def _pump_frames(stream: asyncio.StreamReader | None, queue: asyncio.Queue) -> None:
    """Read newline-delimited frames; raw lines and EOF are queue items too."""
    if stream is None:  # pragma: no cover - defensive
        await queue.put(("eof", None))
        return
    while True:
        raw = await stream.readline()
        if not raw:
            await queue.put(("eof", None))
            return
        line = raw.decode("utf-8", "replace").strip()
        if not line:
            continue
        if line[0] == "{":
            try:
                parsed = json.loads(line)
            except (ValueError, TypeError):
                parsed = None
            if isinstance(parsed, dict):
                await queue.put(("frame", parsed))
                continue
        await queue.put(("raw", line))


# ---- handshake ---------------------------------------------------------------------


async def _handshake(session: _HostSession, *, resume: str | None, cwd: str | None) -> str:
    try:
        return await asyncio.wait_for(
            _establish_session(session, resume=resume, cwd=cwd),
            timeout=_HANDSHAKE_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as exc:
        raise AcpHostError(
            "ACP agent did not complete the initialize/session handshake within "
            f"{_HANDSHAKE_TIMEOUT_SECONDS:.0f}s — is the configured command an ACP agent?"
        ) from exc


async def _establish_session(_session: _HostSession, *, resume: str | None, cwd: str | None) -> str:
    # 1. initialize
    request_id = await _session.send_request("initialize", {"protocolVersion": _PROTOCOL_VERSION})
    await _await_initialize(_session, request_id)
    # 2. session/new (fresh) or session/load (resume) — both carry cwd + mcpServers.
    workdir = os.path.abspath(cwd) if cwd else os.getcwd()
    if resume:
        method = "session/load"
        params: dict[str, Any] = {"mcpServers": [], "cwd": workdir, "sessionId": resume}
    else:
        method = "session/new"
        params = {"cwd": workdir, "mcpServers": []}
    request_id = await _session.send_request(method, params)
    while True:
        item = await _session.frames.get()
        if item[0] == "eof":
            raise AcpHostError(_eof_during("the session handshake", _session.process))
        if item[0] == "raw":
            if item[1].strip():
                await _session.emit(EVENT_LOG, item[1], {"stream": "stdout"})
            continue
        frame: dict[str, Any] = item[1]
        if frame.get("id") == request_id:
            if "error" in frame:
                raise AcpHostError(
                    f"ACP agent rejected the session request: {_rpc_error_text(frame)}"
                )
            sid = _pick_session_id(frame.get("result"))
            if sid:
                return sid
            raise AcpHostError("ACP agent accepted the session request but returned no sessionId")
        if str(frame.get("method") or "") == "session/update":
            # Pre-prompt session state (e.g. after a load) is just logged.
            await _log_update(frame, _session)
            continue
        await _handle_agent_frame(frame, _session)


async def _await_initialize(session: _HostSession, request_id: int) -> None:
    """Wait for the id-matched initialize response (error → fail)."""
    while True:
        item = await session.frames.get()
        if item[0] == "eof":
            raise AcpHostError(_eof_during("initialize", session.process))
        if item[0] == "raw":
            if item[1].strip():
                await session.emit(EVENT_LOG, item[1], {"stream": "stdout"})
            continue
        frame: dict[str, Any] = item[1]
        if frame.get("id") == request_id:
            if "error" in frame:
                raise AcpHostError(f"ACP agent initialize failed: {_rpc_error_text(frame)}")
            return
        if frame.get("method"):
            await _handle_agent_frame(frame, session)


def _eof_during(phase: str, process: asyncio.subprocess.Process) -> str:
    if process.returncode is None:
        # The pipe closed before the process was reaped; treat as an exit.
        code = "?"
    else:
        code = str(process.returncode)
    return f"ACP agent closed its output during {phase} (exit {code})"


# ---- the prompt turn ----------------------------------------------------------------


async def _run_turn(
    session: _HostSession,
    result: ConsultResult,
    emit: Any,
    session_id: str,
    prompt: str,
) -> None:
    """Send ``session/prompt`` and translate the stream until the agent responds.

    v1 streams the run through ``session/update`` notifications and ends the
    turn with the JSON-RPC *response* to the prompt request (``stopReason``).
    """
    request_id = await session.send_request(
        "session/prompt",
        {"sessionId": session_id, "prompt": [{"type": "text", "text": prompt}]},
    )
    chunks: list[str] = []
    got_response = False

    while True:
        item = await session.frames.get()
        if item[0] == "eof":
            break
        if item[0] == "raw":
            if item[1].strip():
                await emit(EVENT_LOG, item[1], {"stream": "stdout"})
            continue
        frame: dict[str, Any] = item[1]
        if frame.get("id") == request_id:
            if "error" in frame:
                await _fail(result, emit, f"ACP agent prompt failed: {_rpc_error_text(frame)}")
                return
            got_response = True
            stop_reason = str((frame.get("result") or {}).get("stopReason") or "")
            if stop_reason in _FAILED_STOP_REASONS:
                await _fail(result, emit, f"ACP agent stopped the turn ({stop_reason})")
                return
            break
        method = str(frame.get("method") or "")
        if method == "session/update":
            await _handle_update(frame, result, chunks, emit)
            continue
        await _handle_agent_frame(frame, session)

    if not got_response:
        # The agent closed its output without answering the prompt.
        await session.process.wait()
        code = session.process.returncode
        suffix = f" (exit {code})" if code not in (None, 0) else ""
        await _fail(
            result, emit, f"ACP agent closed its output before completing the prompt{suffix}"
        )
        return
    result.final_text = "".join(chunks)


# ---- session/update mapping ------------------------------------------------------------


async def _handle_update(
    frame: dict[str, Any], result: ConsultResult, chunks: list[str], emit: Any
) -> None:
    """Map one ``session/update`` notification into SubagentEvents."""
    params = frame.get("params")
    if not isinstance(params, dict):
        return
    update = params.get("update")
    if not isinstance(update, dict):
        await emit(EVENT_LOG, truncate_field(_compact(params)), params)
        return
    kind = str(update.get("sessionUpdate") or update.get("type") or "")

    if kind in _USER_TEXT_KINDS:
        return  # an echo of our own prompt — the capability already streamed it
    if kind in _AGENT_TEXT_KINDS or kind in _THOUGHT_KINDS:
        text = _content_text(update.get("content"))
        if not text:
            return
        out_kind = EVENT_REASONING if kind in _THOUGHT_KINDS else EVENT_TEXT
        if out_kind == EVENT_TEXT:
            chunks.append(text)
        await emit(
            out_kind,
            text,
            update,
            {"partial": True, "message_id": update.get("messageId")},
        )
        return
    if kind in _TOOL_CALL_KINDS:
        tool_call_id = str(update.get("toolCallId") or "")
        await emit(
            EVENT_TOOL,
            _tool_call_header(update),
            update,
            {
                "merge_id": tool_call_id,
                "tool": str(update.get("name") or update.get("kind") or ""),
            },
        )
        return
    if kind in _TOOL_UPDATE_KINDS:
        tool_call_id = str(update.get("toolCallId") or "")
        status = str(update.get("status") or "")
        if status in ("completed", "failed"):
            title = str(update.get("title") or "")
            label = f"{title} ({status})" if title else f"tool call {status}"
            output = _tool_call_content(update)
            await emit(
                EVENT_TOOL_RESULT,
                truncate_field(f"{label}\n{output}".strip() or label),
                update,
                {"merge_id": tool_call_id},
            )
        else:
            # pending / in_progress — the row started by tool_call stays open.
            title = str(update.get("title") or "")
            await emit(
                EVENT_TOOL,
                truncate_field(f"{title} …" if title else "tool call …"),
                update,
                {"merge_id": tool_call_id},
            )
        return
    if kind in _LOG_UPDATE_KINDS:
        await emit(EVENT_LOG, _update_summary(update), update)
        return
    # Unknown sessionUpdate kind: keep it visible rather than dropping it.
    await emit(EVENT_LOG, truncate_field(_compact(update)), update)


def _tool_call_header(update: dict[str, Any]) -> str:
    title = str(update.get("title") or "").strip()
    name = str(update.get("name") or update.get("kind") or "").strip()
    if title and name:
        return f"{title} ({name})"
    return title or name or "tool call"


def _tool_call_content(update: dict[str, Any]) -> str:
    """Plain text of a completed tool call's ``content`` (tool results)."""
    content = update.get("content")
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for entry in content:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("type") or "") in ("content", "diff", "terminal"):
            if "content" in entry:
                parts.append(_content_text(entry.get("content")))
            else:
                parts.append(_compact(entry))
            continue
        parts.append(_content_text(entry))
    return "\n".join(part for part in parts if part)


def _update_summary(update: dict[str, Any]) -> str:
    """One readable line for lifecycle / status session updates."""
    kind = str(update.get("sessionUpdate") or update.get("type") or "")
    if kind in ("plan", "plan_update"):
        # Plans carry their own content list of text blocks.
        text = _content_text(update.get("content"))
        if text:
            return truncate_field(text)
    return truncate_field(_compact(update))


def _content_text(content: Any) -> str:
    """Best-effort plain text of a ContentBlock / content field."""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        if content.get("type") == "text":
            return str(content.get("text") or "")
        text = content.get("text")
        if isinstance(text, str):
            return text
        return str(content.get("content") or "") if "content" in content else ""
    if isinstance(content, list):
        parts: list[str] = []
        for entry in content:
            text = _content_text(entry)
            if text:
                parts.append(text)
        return "\n".join(parts)
    return ""


# ---- other agent-initiated messages ---------------------------------------------------


async def _handle_agent_frame(frame: dict[str, Any], session: _HostSession) -> None:
    """Respond to agent requests we cannot serve; log the rest."""
    method = str(frame.get("method") or "")
    request_id = frame.get("id")
    is_request = request_id is not None and "result" not in frame and "error" not in frame
    if not method:
        return  # a stray response to a request we never tracked
    if method == "session/update":
        await _log_update(frame, session)
        return
    if method == "elicitation/create":
        await _answer_elicitation(session, frame)
        return
    if not is_request:
        # A notification we do not model (e.g. elicitation/complete) — the
        # lifecycle it announces is already handled at its request side.
        return
    # An unsolicited request (session/request_permission, fs/*, terminal/*,
    # mcp/* …). This client advertises none of those capabilities, so say so —
    # never auto-approve a permission or run a tool for the agent.
    await session.emit(EVENT_LOG, f"ACP agent requested unsupported method {method!r}", frame)
    await session.send_error(request_id, -32601, "method not found")


async def _answer_elicitation(session: _HostSession, frame: dict[str, Any]) -> None:
    """Auto-answer an ``elicitation/create`` request so a headless run never stalls.

    The reply is a ``CreateElicitationResponse``; ``{"action": "decline"}`` is
    valid for every elicitation mode and means "no input provided". The agent's
    follow-up ``elicitation/complete`` notification is consumed by
    :func:`_handle_agent_frame`. Full form/URL elicitation is future work.
    """
    request_id = frame.get("id")
    message = ""
    params = frame.get("params")
    if isinstance(params, dict):
        message = str(params.get("message") or "")
    detail = f" ({message})" if message else ""
    await session.emit(
        EVENT_LOG,
        f"ACP agent requested input; auto-replied decline (headless consult){detail}.",
        frame,
    )
    if request_id is not None:
        await session.send_response(request_id, {"action": "decline"})


async def _log_update(frame: dict[str, Any], session: _HostSession) -> None:
    """Pre-prompt session state: keep it visible but do not touch the answer."""
    params = frame.get("params")
    update = params.get("update") if isinstance(params, dict) else None
    if isinstance(update, dict):
        text = _update_summary(update)
    else:
        text = _compact(params) if params else ""
    if text:
        await session.emit(EVENT_LOG, text, frame)


# ---- small frame helpers ---------------------------------------------------------------


def _pick_session_id(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in _SESSION_ID_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _rpc_error_text(frame: dict[str, Any]) -> str:
    error = frame.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message:
            return message
        return _compact(error)
    return "JSON-RPC error"


async def _fail(result: ConsultResult, emit: Any, message: str) -> ConsultResult:
    if not result.error:
        result.success = False
        result.error = message
        await emit(EVENT_ERROR, message, {})
    return result


# ---- teardown ---------------------------------------------------------------------------


async def _teardown(process: asyncio.subprocess.Process, reader_task: asyncio.Task | None) -> None:
    """Close stdin, drain briefly, then reap the child (terminate → kill)."""
    if process.stdin is not None:
        with contextlib.suppress(Exception):
            process.stdin.close()
    if reader_task is not None and not reader_task.done():
        with contextlib.suppress(Exception):
            await asyncio.wait_for(reader_task, timeout=_SHUTDOWN_GRACE_SECONDS)
        if not reader_task.done():
            reader_task.cancel()
            with contextlib.suppress(Exception):
                await asyncio.gather(reader_task, return_exceptions=True)
    if process.returncode is None:
        try:
            await asyncio.wait_for(process.wait(), timeout=_SHUTDOWN_GRACE_SECONDS)
        except asyncio.TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=_SHUTDOWN_GRACE_SECONDS)
            except (TimeoutError, asyncio.TimeoutError):
                with contextlib.suppress(ProcessLookupError):
                    process.kill()
                with contextlib.suppress(Exception):
                    await process.wait()


__all__ = ["ACP_COMMAND_ENV", "AcpBackend"]
