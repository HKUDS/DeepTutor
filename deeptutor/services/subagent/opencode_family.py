"""opencode-family backends — opencode and its fork MiMo-Code, over serve+SSE.

Both CLIs share one integration because MiMo-Code is a source-level fork of
opencode: same server API, same bus events, same session model. Instead of the
part-granular ``run --format json`` subprocess mode, we drive the CLI's local
HTTP server (managed by :mod:`deeptutor.services.subagent.opencode_server`),
which exposes the full event bus over SSE — **token-level**
``message.part.delta`` chunks, every tool-state transition, and interactive
permission asks we answer programmatically. That makes these the richest
streams of the CLI backends: the answer types out live and tools surface the
moment they start running.

One consult = attach to ``GET /event`` (filtered by session), then a blocking
``POST /session/{id}/message`` whose return *is* the end of the turn and whose
response carries the authoritative final answer parts. Sessions are created via
``POST /session`` and live on the CLI's own disk storage keyed by the workdir,
so they survive server respawns.

Auth/config are inherited from the user's own CLI setup (``auth.json`` under
its data dir) — no token is ever handled here. Images ride as first-class
``file`` parts with a real mime type on the prompt body, which sidesteps the
CLI flag's mime-sniffing limitations.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import mimetypes
import os
from pathlib import Path
from typing import Any

import httpx

from deeptutor.services.subagent.base import OnEvent, SubagentBackend
from deeptutor.services.subagent.config import BackendConfig
from deeptutor.services.subagent.opencode_server import acquire_server
from deeptutor.services.subagent.process import probe_version
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
_TOOL_HEADER_CHARS = 160
# MiMo's first run performs a local DB migration, so give the version probe
# more headroom than the default.
_PROBE_TIMEOUT_SECONDS = 15.0
_ATTACH_TIMEOUT_SECONDS = 15.0

# No read timeout: per the product contract we wait unconditionally for the
# agent's own logic to finish — only the run ending closes the request/stream.
_HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=None, write=60.0, pool=10.0)

_TOOL_PRIMARY_ARGS = (
    "command",
    "filePath",
    "file_path",
    "path",
    "pattern",
    "query",
    "url",
    "prompt",
    "description",
)


class OpencodeFamilyBackend(SubagentBackend):
    """Shared driver for the opencode lineage; subclasses name the CLI."""

    # The CLI's server env-var family (`<PREFIX>_SERVER_PASSWORD` / `_USERNAME`)
    # and the basic-auth user it expects.
    env_prefix: str
    basic_auth_user: str

    async def detect(self) -> DetectResult:
        ok, text = await probe_version(
            [self.cli_command, "--version"], timeout=_PROBE_TIMEOUT_SECONDS
        )
        return DetectResult(
            kind=self.kind,
            display_name=self.display_name,
            available=ok,
            version=text if ok else "",
            detail="" if ok else (text or f"{self.cli_command} CLI not found on PATH"),
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
        result = ConsultResult(session_id=session_id)
        # Per-consult stream state: cumulative text per part id, each part's
        # channel (text vs reasoning), and any session error seen on the bus.
        state: dict[str, Any] = {"parts": {}, "kinds": {}, "error": ""}

        async def emit(
            kind: str, text: str, raw: dict[str, Any], meta: dict[str, Any] | None = None
        ) -> None:
            result.event_count += 1
            await on_event(SubagentEvent(kind=kind, text=text, raw=raw, meta=meta or {}))

        try:
            handle = await acquire_server(
                self.cli_command,
                cwd=cwd or "",
                env_prefix=self.env_prefix,
                username=self.basic_auth_user,
            )
        except Exception as exc:
            logger.warning("%s server failed to start: %s", self.kind, exc, exc_info=True)
            result.success = False
            result.error = f"failed to start {self.display_name} server: {exc}"
            await emit(EVENT_ERROR, result.error, {})
            return result

        listener: asyncio.Task | None = None
        try:
            async with httpx.AsyncClient(
                base_url=handle.base_url, auth=handle.auth, timeout=_HTTP_TIMEOUT
            ) as client:
                fresh_session = not session_id
                sid = session_id or await self._create_session(client)
                result.session_id = sid

                attached = asyncio.Event()
                listener = asyncio.create_task(
                    self._listen(client, sid, state, emit, attached, config)
                )
                await _wait_attached(listener, attached)

                body = self._prompt_body(
                    question, config=config, images=images, fresh_session=fresh_session
                )
                try:
                    response = await client.post(f"/session/{sid}/message", json=body)
                    response.raise_for_status()
                except asyncio.CancelledError:
                    # The user aborted the turn — best-effort stop the run so
                    # the agent doesn't keep working into a dead session.
                    with_abort = client.post(f"/session/{sid}/abort", timeout=5.0)
                    await asyncio.shield(_swallow(with_abort))
                    raise
                result.final_text = _text_from_parts(_response_parts(response))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("%s consult failed: %s", self.kind, exc, exc_info=True)
            result.success = False
            result.error = str(exc)
            await emit(EVENT_ERROR, str(exc), {})
        finally:
            if listener is not None:
                listener.cancel()
                await asyncio.gather(listener, return_exceptions=True)
            handle.touch()

        if not result.final_text:
            # Fallback: the cumulative text parts streamed over the bus.
            texts = [
                text
                for pid, text in state["parts"].items()
                if state["kinds"].get(pid) == "text" and str(text).strip()
            ]
            result.final_text = "\n\n".join(texts).strip()
        if state["error"] and not result.final_text:
            result.success = False
            result.error = result.error or state["error"]
        return result

    async def _create_session(self, client: httpx.AsyncClient) -> str:
        response = await client.post("/session", json={"title": "DeepTutor consult"})
        response.raise_for_status()
        data = response.json()
        sid = str(data.get("id") or "") if isinstance(data, dict) else ""
        if not sid:
            raise RuntimeError("server created a session without an id")
        return sid

    def _prompt_body(
        self,
        question: str,
        *,
        config: BackendConfig,
        images: list[str] | None,
        fresh_session: bool,
    ) -> dict[str, Any]:
        parts: list[dict[str, Any]] = [{"type": "text", "text": question}]
        for path in images or []:
            part = _image_part(path)
            if part is not None:
                parts.append(part)
        body: dict[str, Any] = {"parts": parts}
        model = (config.model or "").strip()
        if "/" in model:
            provider, model_id = model.split("/", 1)
            body["model"] = {"providerID": provider, "modelID": model_id}
        if config.effort:
            body["variant"] = config.effort
        # The delegate instruction rides the session-creating prompt as the
        # native system field; resumed sessions already have it.
        if fresh_session and config.system_prompt.strip():
            body["system"] = config.system_prompt.strip()
        return body

    async def _listen(
        self,
        client: httpx.AsyncClient,
        sid: str,
        state: dict[str, Any],
        emit: Any,
        attached: asyncio.Event,
        config: BackendConfig,
    ) -> None:
        """Consume the SSE bus, mapping this session's events onto the trace."""
        async with client.stream("GET", "/event") as response:
            response.raise_for_status()
            attached.set()
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                event = _parse_json(line[5:])
                if event is None:
                    continue
                await self._handle_bus_event(event, sid, state, emit, client, config)

    async def _handle_bus_event(
        self,
        event: dict[str, Any],
        sid: str,
        state: dict[str, Any],
        emit: Any,
        client: httpx.AsyncClient | None,
        config: BackendConfig,
    ) -> None:
        etype = str(event.get("type") or "")
        props = event.get("properties") if isinstance(event.get("properties"), dict) else {}

        if etype == "message.part.updated":
            part = props.get("part") if isinstance(props.get("part"), dict) else {}
            if str(part.get("sessionID") or "") != sid:
                return
            await self._handle_part(part, state, emit)
            return

        if etype == "message.part.delta":
            if str(props.get("sessionID") or "") != sid:
                return
            if str(props.get("field") or "text") != "text":
                return
            pid = str(props.get("partID") or "")
            if not pid:
                return
            acc = str(state["parts"].get(pid, "")) + str(props.get("delta") or "")
            state["parts"][pid] = acc
            kind = state["kinds"].setdefault(pid, "text")
            channel = EVENT_REASONING if kind == "reasoning" else EVENT_TEXT
            prefix = "rsn" if kind == "reasoning" else "txt"
            await emit(channel, acc.strip(), event, {"merge_id": f"{prefix}:{pid}"})
            return

        if etype == "permission.asked":
            if str(props.get("sessionID") or "") != sid:
                return
            await self._reply_permission(props, sid, emit, client, config)
            return

        if etype == "session.error":
            if str(props.get("sessionID") or sid) != sid:
                return
            message = _error_message(props)
            state["error"] = message
            await emit(EVENT_ERROR, message, event)
            return

        # message.updated / session.status / heartbeats — lifecycle noise here;
        # the blocking POST is our end-of-turn signal.

    async def _handle_part(self, part: dict[str, Any], state: dict[str, Any], emit: Any) -> None:
        ptype = str(part.get("type") or "")
        pid = str(part.get("id") or "")

        if ptype in ("text", "reasoning"):
            if not pid:
                return
            state["kinds"][pid] = ptype
            text = str(part.get("text") or "")
            if not text.strip():
                return
            # The updated part carries the authoritative cumulative text —
            # replaces whatever the deltas accumulated (same merge row).
            state["parts"][pid] = text
            prefix, channel = (
                ("rsn", EVENT_REASONING) if ptype == "reasoning" else ("txt", EVENT_TEXT)
            )
            await emit(channel, text.strip(), part, {"merge_id": f"{prefix}:{pid}"})
            return

        if ptype == "tool":
            tool_state = part.get("state") if isinstance(part.get("state"), dict) else {}
            status = str(tool_state.get("status") or "")
            if status == "running":
                await emit(
                    EVENT_TOOL,
                    _render_tool_header(part, tool_state),
                    part,
                    {"merge_id": f"tool:{pid}"} if pid else None,
                )
            elif status == "completed":
                await emit(
                    EVENT_TOOL,
                    _render_tool_header(part, tool_state),
                    part,
                    {"merge_id": f"tool:{pid}"} if pid else None,
                )
                output = _truncate(str(tool_state.get("output") or ""))
                await emit(EVENT_TOOL_RESULT, output or "(empty result)", part)
            elif status == "error":
                error = _truncate(str(tool_state.get("error") or "tool failed"))
                await emit(EVENT_TOOL_RESULT, error, part)
            return

        # step-start / step-finish / file / agent parts — no transcript row.

    async def _reply_permission(
        self,
        props: dict[str, Any],
        sid: str,
        emit: Any,
        client: httpx.AsyncClient | None,
        config: BackendConfig,
    ) -> None:
        permission_id = str(props.get("id") or "")
        reply = "once" if config.auto_approve else "reject"
        label = _permission_label(props)
        if client is not None and permission_id:
            try:
                await client.post(
                    f"/session/{sid}/permissions/{permission_id}",
                    json={"response": reply},
                    timeout=10.0,
                )
            except httpx.HTTPError as exc:  # pragma: no cover - defensive
                logger.warning("permission reply failed: %s", exc)
        note = "auto-approved" if reply == "once" else "rejected (auto-approval is off)"
        await emit(EVENT_LOG, f"permission {note}{f' · {label}' if label else ''}", props)


class OpencodeBackend(OpencodeFamilyBackend):
    kind = "opencode"
    display_name = "opencode"
    cli_command = "opencode"
    env_prefix = "OPENCODE"
    basic_auth_user = "opencode"


class MimoBackend(OpencodeFamilyBackend):
    kind = "mimo"
    display_name = "MiMo Code"
    cli_command = "mimo"
    env_prefix = "MIMOCODE"
    basic_auth_user = "mimocode"


async def _wait_attached(listener: asyncio.Task, attached: asyncio.Event) -> None:
    """Block until the SSE stream is attached (or surface the listener's error)."""
    waiter = asyncio.create_task(attached.wait())
    done, _ = await asyncio.wait(
        {listener, waiter},
        timeout=_ATTACH_TIMEOUT_SECONDS,
        return_when=asyncio.FIRST_COMPLETED,
    )
    if waiter in done:
        return
    waiter.cancel()
    if listener in done:
        exc = listener.exception()
        raise exc if exc else RuntimeError("event stream closed before attaching")
    raise RuntimeError("timed out attaching to the event stream")


async def _swallow(awaitable) -> None:
    try:
        await awaitable
    except Exception:  # pragma: no cover - best-effort abort
        pass


def _response_parts(response: httpx.Response) -> list[dict[str, Any]]:
    try:
        data = response.json()
    except ValueError:
        return []
    if not isinstance(data, dict):
        return []
    parts = data.get("parts")
    if not isinstance(parts, list):
        return []
    return [p for p in parts if isinstance(p, dict)]


def _text_from_parts(parts: list[dict[str, Any]]) -> str:
    texts = [
        str(p.get("text") or "").strip()
        for p in parts
        if str(p.get("type") or "") == "text" and not p.get("synthetic")
    ]
    return "\n\n".join(t for t in texts if t).strip()


def _image_part(path: str) -> dict[str, Any] | None:
    mime = mimetypes.guess_type(path)[0] or "image/png"
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None
    return {
        "type": "file",
        "mime": mime,
        "filename": os.path.basename(path),
        "url": f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}",
    }


def _render_tool_header(part: dict[str, Any], tool_state: dict[str, Any]) -> str:
    name = str(tool_state.get("title") or part.get("tool") or "tool")
    args = tool_state.get("input")
    if not isinstance(args, dict) or not args:
        return name
    for key in _TOOL_PRIMARY_ARGS:
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return f"{name}({_inline(value)})"
    return f"{name}({_inline(_compact(args))})"


def _permission_label(props: dict[str, Any]) -> str:
    """A short human label for a permission ask (title, or the permission name)."""
    title = props.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    permission = props.get("permission")
    if isinstance(permission, dict):
        inner = permission.get("title") or permission.get("id")
        if isinstance(inner, str) and inner.strip():
            return inner.strip()
    elif isinstance(permission, str) and permission.strip():
        return permission.strip()
    return ""


def _error_message(props: dict[str, Any]) -> str:
    error = props.get("error")
    if isinstance(error, dict):
        data = error.get("data")
        if isinstance(data, dict) and data.get("message"):
            return str(data["message"])
        if error.get("message"):
            return str(error["message"])
        if error.get("name"):
            return str(error["name"])
    return "the agent reported a session error"


def _parse_json(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if not text or text[0] not in "{[":
        return None
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


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


__all__ = ["OpencodeFamilyBackend", "OpencodeBackend", "MimoBackend"]
