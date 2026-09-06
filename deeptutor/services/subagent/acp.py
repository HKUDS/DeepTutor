"""ACP backend — drive any Agent Client Protocol (ACP) host as a subagent.

Part of #1028 (stage 1): DeepTutor plays the *client* side of the Agent Client
Protocol — a JSON-RPC 2.0 dialect over newline-delimited stdio — against a
spawnable ACP *host* process. The host command is not hard-coded (ACP is a
transport standard, not one binary): it comes from the ``DEEPTUTOR_ACP_COMMAND``
environment variable (a JSON array of argv, or a shell-quoted string), or from
the per-backend ``BackendConfig.extra_args`` when the env var is unset — so the
same backend can drive ``claude --acp``-style agent CLIs, ``acp-remote``
bridges, or any future ACP host, once those binaries exist on the machine.

Wire transcript this backend drives (client → host unless noted):

1. client ``initialize`` → host replies with the negotiated ``protocolVersion``
   and its capabilities (some hosts notify ``initialize_result`` instead; both
   shapes are accepted).
2. client ``session/new`` (fresh) or ``session/load`` with ``session_id``
   (resume) → the host returns the session id in the JSON-RPC result and/or
   announces acceptance with a ``session/update`` notification
   (``status: accepted | rejected``). Either source of the id ends the
   handshake; ``rejected`` fails the consult.
3. client ``prompt`` (the question plus ``tools: []``; the working directory is
   set on the process spawn, not carried in the message) → the host streams
   ``agent/message`` notifications whose content blocks are translated
   one-to-one into :class:`SubagentEvent` channels: ``text``/``textDelta`` →
   ``text`` (deltas stream as partial rows), ``tool_call`` → ``tool``,
   ``tool_call_result`` → ``tool_result``, ``progress``/``system``/unknown →
   ``log``, ``error`` → ``error`` (fails the run). A ``result`` content block
   closes the turn.
4. A host ``session/input_request`` is surfaced as a log event and auto-replied
   with an empty input (``{"input": ""}``) so a headless run never stalls; the
   request-reply shape and the empty-input default are the same headless
   contract the other backends use for approval prompts.

Consult waits for the host's own turn end — the ``result`` content block, an
``error`` block, or the process exiting. Only the protocol handshake
(initialize → session ready) is bounded by ``_HANDSHAKE_TIMEOUT_SECONDS``, so a
non-ACP binary pointed at this backend fails fast instead of hanging the turn;
once a turn is running, consult waits unconditionally, matching the subagent
driver contract. After the turn ends the child is reaped within a short grace
(``_SHUTDOWN_GRACE_SECONDS``) so a long-lived host cannot leak a process per
consult.

⚠️ Schema-verification note: this is stage 1 of #1028 and the ACP spec is still
settling. The method names, message directions, and framing above match the
widely deployed ACP v1 shape (``agentclientprotocol.com``), but the primary
schema could not be fetched from this environment, so every field this module
**emits** is deliberately minimal and each one this module **reads** is parsed
defensively. Fields a maintainer must check against the official JSON Schema /
TS types before wiring a real host: ``initialize`` params (``protocolVersion``
and ``clientCapabilities``) and the host's capability reply; the
``session/new`` vs ``session/load`` request params and whether acceptance is a
plain result, ``initialize_result``, or a ``session/update`` notification
(``status`` values and the ``session_id``/``sessionId`` key spellings); the
``prompt`` params (string vs structured ``content`` prompt, and where ``tools``
and ``cwd`` belong); the ``agent/message`` envelope (``message.content`` block
types and delta spellings such as ``textDelta``) and how turn end is signalled
(``result`` block vs a message-level completion flag); and the
``session/input_request`` request/response shape. Nothing here is asserted as
required beyond the JSON-RPC 2.0 envelope itself.
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
    EVENT_RESULT,
    EVENT_TEXT,
    EVENT_TOOL,
    EVENT_TOOL_RESULT,
    ConsultResult,
    DetectResult,
    SubagentEvent,
)

logger = logging.getLogger(__name__)

#: Env var naming the ACP host argv (JSON array preferred; else shell-quoted).
ACP_COMMAND_ENV = "DEEPTUTOR_ACP_COMMAND"

#: ACP v1 protocol version we negotiate. See the schema-verification note above.
_PROTOCOL_VERSION = 1
#: How long the initialize → session handshake may take before consult fails.
_HANDSHAKE_TIMEOUT_SECONDS = 30.0
#: How long to wait for the child to exit / drain after the turn ends.
_SHUTDOWN_GRACE_SECONDS = 5.0

_NOT_CONFIGURED = (
    f"No ACP host command configured: set {ACP_COMMAND_ENV} to the host argv "
    '(e.g. ["claude", "--acp"]) or provide it as the per-backend extra_args.'
)

#: Session id key spellings tolerated when parsing host frames.
_SESSION_ID_KEYS = ("sessionId", "session_id", "session.id")
#: ``session/update`` statuses that end a session attempt in failure.
_REJECTED_STATUSES = frozenset({"rejected", "refused", "error", "denied"})
#: ``session/update`` statuses that mean the session is usable.
_ACCEPTED_STATUSES = frozenset({"accepted", "ready", "ok", ""})
#: Content block types that carry assistant answer text.
_TEXT_BLOCK_TYPES = frozenset({"text"})
#: Content block types that close the current turn.
_RESULT_BLOCK_TYPES = frozenset({"result"})
#: Content block types that represent a tool invocation.
_TOOL_CALL_TYPES = frozenset({"tool_call", "tool_use"})
_TOOL_UPDATE_TYPES = frozenset({"tool_call_update", "tool_use_update"})
_TOOL_RESULT_TYPES = frozenset({"tool_call_result", "tool_result"})


class AcpHostError(Exception):
    """The ACP host violated the protocol (or the handshake failed)."""


class AcpBackend(SubagentBackend):
    """Consult any ACP host process as a subagent over stdio JSON-RPC."""

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
        """Optionally inject a host spawner for offline tests.

        The default spawns the configured ACP host command as a subprocess with
        its stdio piped (see :func:`_spawn_host`). ``host_factory`` — awaited
        with no arguments and expected to return an object exposing the same
        duck-typed surface as an :class:`asyncio.subprocess.Process` (``stdin``
        writer, ``stdout`` reader, ``returncode``, ``wait``/``terminate``/
        ``kill``) — is the seam tests use to drive consult against an in-process
        fake host when OS pipes are unavailable, mirroring the transport
        injection the remote Hermes backend already uses.
        """
        self._host_factory = host_factory

    async def detect(self) -> DetectResult:
        """Report whether an ACP host command is configured and resolvable.

        ACP is a transport, so there is no universal ``--version`` probe and
        none is attempted (an ACP-mode CLI would wait for the handshake and
        time out). Availability is "a host command is configured (env or
        per-backend extra_args) and its first token resolves on PATH".
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
            detail=f"configured ACP host command not found on PATH: {command[0]}",
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
            sid = await _handshake(session, resume=session_id)
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
    """The configured ACP host argv, or ``[]`` when nothing is configured.

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
        # Whatever the host is, ask it to talk clean UTF-8 text on the pipes.
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
            f"ACP host command not found: {command[0]} (configure {ACP_COMMAND_ENV})"
        ) from exc


class _HostSession:
    """One live host process plus the single queue its stdout feeds."""

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
            raise AcpHostError("ACP host stdin closed unexpectedly")
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


async def _handshake(session: _HostSession, *, resume: str | None) -> str:
    try:
        return await asyncio.wait_for(
            _establish_session(session, resume=resume),
            timeout=_HANDSHAKE_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as exc:
        raise AcpHostError(
            "ACP host did not complete the initialize/session handshake within "
            f"{_HANDSHAKE_TIMEOUT_SECONDS:.0f}s — is the configured command an ACP host?"
        ) from exc


async def _establish_session(session: _HostSession, *, resume: str | None) -> str:
    # 1. initialize
    await session.send_request("initialize", {"protocolVersion": _PROTOCOL_VERSION})
    await _await_initialize(session)
    # 2. session/new (fresh) or session/load (resume)
    method = "session/load" if resume else "session/new"
    params = {"session_id": resume} if resume else {}
    request_id = await session.send_request(method, params)
    saw_response_without_id = False
    while True:
        item = await session.frames.get()
        if item[0] == "eof":
            raise AcpHostError(_eof_during("the session handshake", session.process))
        if item[0] == "raw":
            if item[1].strip():
                await session.emit(EVENT_LOG, item[1], {"stream": "stdout"})
            continue
        frame: dict[str, Any] = item[1]
        if frame.get("id") == request_id:
            if "error" in frame:
                raise AcpHostError(
                    f"ACP host rejected the session request: {_rpc_error_text(frame)}"
                )
            sid = _pick_session_id(frame.get("result"))
            if sid:
                return sid
            saw_response_without_id = True
            continue
        if frame.get("method") == "session/update":
            status = _update_status(frame)
            if status in _REJECTED_STATUSES:
                detail = _update_detail(frame) or status
                raise AcpHostError(f"ACP host rejected the session: {detail}")
            if status in _ACCEPTED_STATUSES or saw_response_without_id:
                sid = _pick_session_id(frame.get("params"))
                if sid:
                    return sid
            continue
        await _log_unknown(frame, session)


async def _await_initialize(session: _HostSession) -> None:
    """Wait for the initialize reply: an id-matched result or a notification."""
    request_id = 1  # the initialize request is always the first one sent
    while True:
        item = await session.frames.get()
        if item[0] == "eof":
            raise AcpHostError(_eof_during("initialize", session.process))
        if item[0] == "raw":
            if item[1].strip():
                await session.emit(EVENT_LOG, item[1], {"stream": "stdout"})
            continue
        frame: dict[str, Any] = item[1]
        method = str(frame.get("method") or "")
        if method == "initialize_result":
            return
        if frame.get("id") == request_id:
            if "error" in frame:
                raise AcpHostError(f"ACP host initialize failed: {_rpc_error_text(frame)}")
            return
        if method and "id" in frame:
            # A host request before we are ready cannot be answered yet.
            await session.send_error(frame.get("id"), -32601, "method not found")
            continue
        await _log_unknown(frame, session)


def _eof_during(phase: str, process: asyncio.subprocess.Process) -> str:
    if process.returncode is None:
        # The pipe closed before the process was reaped; treat as an exit.
        code = "?"
    else:
        code = str(process.returncode)
    return f"ACP host closed its output during {phase} (exit {code})"


# ---- the prompt turn ----------------------------------------------------------------


async def _run_turn(
    session: _HostSession,
    result: ConsultResult,
    emit: Any,
    session_id: str,
    prompt: str,
) -> None:
    """Send the prompt and translate the host's stream until the turn ends."""
    request_id = await session.send_request(
        "prompt",
        {
            "session_id": session_id,
            "prompt": prompt,
            "tools": [],
        },
    )
    chunks: list[str] = []
    result_text = ""
    end_of_turn = False

    while not end_of_turn:
        item = await session.frames.get()
        if item[0] == "eof":
            break
        if item[0] == "raw":
            if item[1].strip():
                await emit(EVENT_LOG, item[1], {"stream": "stdout"})
            continue
        frame: dict[str, Any] = item[1]
        if frame.get("id") == request_id and "error" in frame:
            await _fail(result, emit, f"ACP host prompt failed: {_rpc_error_text(frame)}")
            return
        method = str(frame.get("method") or "")
        if method == "agent/message":
            message = frame.get("params")
            if not isinstance(message, dict):
                continue
            message = message.get("message")
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                kind, text, meta, is_error, closes_turn = _map_block(block)
                if is_error:
                    await _fail(result, emit, text)
                    return
                if kind and text:
                    await emit(kind, text, block, meta)
                if kind == EVENT_TEXT:
                    chunks.append(text)
                elif kind == EVENT_RESULT and text:
                    result_text = text
                if closes_turn:
                    end_of_turn = True
                    break
            continue
        if method == "session/update":
            status = _update_status(frame)
            if status in _REJECTED_STATUSES:
                detail = _update_detail(frame) or status
                await _fail(result, emit, f"ACP host ended the session: {detail}")
                return
            continue
        if method == "session/input_request":
            await _answer_input_request(session, emit, frame)
            continue
        await _log_unknown(frame, session)

    # EOF without a clean result block: only a non-zero exit with no answer text
    # is a failure — otherwise the streamed text stands on its own.
    if not end_of_turn and result.success and not chunks and not result_text:
        await session.process.wait()
        code = session.process.returncode
        if code not in (0, None):
            await _fail(result, emit, f"ACP host exited with code {code} before completing")
            return
    result.final_text = "".join(chunks) or result_text


async def _answer_input_request(session: _HostSession, emit: Any, frame: dict[str, Any]) -> None:
    """Surface a host input request and auto-reply so a headless run never stalls."""
    await emit(
        EVENT_LOG,
        "ACP host requested user input; auto-replied with empty input (headless consult).",
        frame,
    )
    request_id = frame.get("id")
    if request_id is not None:
        # Accepted shapes for the empty auto-answer: see the schema note.
        await session.send_response(request_id, {"input": ""})


# ---- content mapping ----------------------------------------------------------------


def _map_block(block: dict[str, Any]) -> tuple[str | None, str, dict[str, Any], bool, bool]:
    """Map one ``agent/message`` content block to (kind, text, meta, error, end)."""
    btype = str(block.get("type") or "")
    if btype in _TEXT_BLOCK_TYPES:
        delta = block.get("textDelta")
        if isinstance(delta, str) and delta:
            return EVENT_TEXT, delta, {"partial": True}, False, False
        text = block.get("text")
        if isinstance(text, str) and text:
            return EVENT_TEXT, text, {}, False, False
        return None, "", {}, False, False
    if btype in _TOOL_CALL_TYPES:
        return (
            EVENT_TOOL,
            _tool_header(block),
            {"tool": str(block.get("name") or "tool")},
            False,
            False,
        )
    if btype in _TOOL_UPDATE_TYPES:
        text = _tool_header(block)
        return (
            EVENT_TOOL,
            truncate_field(text),
            {"tool": str(block.get("name") or "tool")},
            False,
            False,
        )
    if btype in _TOOL_RESULT_TYPES:
        return (
            EVENT_TOOL_RESULT,
            truncate_field(_content_text(block.get("content")) or _compact(block)),
            {},
            False,
            False,
        )
    if btype == "progress":
        message = block.get("message")
        if not isinstance(message, str) or not message.strip():
            message = block.get("text")
        return EVENT_LOG, truncate_field(str(message or _compact(block))), {}, False, False
    if btype == "system":
        return (
            EVENT_LOG,
            truncate_field(_content_text(block.get("content")) or _compact(block)),
            {},
            False,
            False,
        )
    if btype == "error":
        message = block.get("message")
        if not isinstance(message, str) or not message.strip():
            message = block.get("text")
        return EVENT_ERROR, str(message or "ACP agent reported an error"), {}, True, True
    if btype in _RESULT_BLOCK_TYPES:
        text = block.get("text")
        text = str(text) if isinstance(text, str) and text.strip() else ""
        # The ``result`` block closes the turn; its text is only surfaced as the
        # answer when nothing was already streamed (avoids duplication).
        return (EVENT_RESULT, text, {}, False, True)
    # Unknown block: keep it visible as a log rather than dropping it.
    return EVENT_LOG, truncate_field(_compact(block)), {}, False, False


def _tool_header(block: dict[str, Any]) -> str:
    name = str(block.get("name") or block.get("tool") or "tool")
    args = block.get("arguments")
    if args is None:
        args = block.get("input")
    if not isinstance(args, (dict, list)) or not args:
        return name
    return truncate_field(f"{name} · {_compact(args)}")


def _content_text(content: Any) -> str:
    """Best-effort plain text of a content field (str, block dict, or list)."""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        return str(content.get("text") or content.get("content") or "")
    if isinstance(content, list):
        parts: list[str] = []
        for entry in content:
            if isinstance(entry, str):
                parts.append(entry)
            elif isinstance(entry, dict):
                parts.append(_content_text(entry))
        return "\n".join(parts)
    return ""


# ---- small frame helpers ---------------------------------------------------------------


def _pick_session_id(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in _SESSION_ID_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _update_status(frame: dict[str, Any]) -> str:
    params = frame.get("params")
    if not isinstance(params, dict):
        return ""
    value = params.get("status")
    if value is None:
        value = params.get("state")
    return str(value or "").lower()


def _update_detail(frame: dict[str, Any]) -> str:
    params = frame.get("params")
    if not isinstance(params, dict):
        return ""
    for key in ("detail", "message", "reason"):
        value = params.get(key)
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


async def _log_unknown(frame: dict[str, Any], session: _HostSession) -> None:
    """Anything not understood is kept visible (and answered) rather than dropped."""
    if "id" in frame and "method" in frame and "result" not in frame and "error" not in frame:
        # An unknown host request: tell the peer we cannot serve it so it can
        # proceed instead of waiting on a reply that will never come.
        await session.send_error(frame.get("id"), -32601, "method not found")
    method = str(frame.get("method") or "")
    if method:
        await session.emit(EVENT_LOG, truncate_field(_compact(frame)), frame)


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
