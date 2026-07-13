"""
Plugins API Router
==================

Lists registered tools, capabilities, and playground plugins.
Provides direct tool execution for the Playground tester.
"""

import asyncio
import contextlib
import json
import logging
import re
import time
from typing import Any, AsyncGenerator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from deeptutor.core.i18n import t
from deeptutor.i18n.metadata_i18n import tool_description_i18n
from deeptutor.logging import (
    ProcessLogEvent,
    bind_log_context,
    capture_process_logs,
    current_log_context,
)
from deeptutor.runtime.registry.capability_registry import get_capability_registry
from deeptutor.runtime.registry.tool_registry import get_tool_registry

logger = logging.getLogger(__name__)

router = APIRouter()
ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")


def _discover_plugins() -> list[Any]:
    try:
        from deeptutor.plugins.loader import discover_plugins
    except Exception:
        logger.debug("Plugin loader unavailable; returning no plugins.", exc_info=True)
        return []
    return discover_plugins()


class ToolExecuteRequest(BaseModel):
    params: dict[str, Any] = Field(default_factory=dict)


class CapabilityExecuteRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    content: str
    tools: list[str] = Field(default_factory=list, alias="enabledTools")
    knowledge_bases: list[str] = Field(default_factory=list, alias="knowledgeBases")
    language: str = "en"
    config: dict[str, Any] = Field(default_factory=dict)
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    # ``bot_id`` is the legacy TutorBot field name; it now addresses a partner.
    partner_id: str | None = Field(default=None, alias="bot_id")
    session_id: str | None = None
    chat_id: str | None = None
    llm_selection: dict[str, str] | None = Field(default=None, alias="llmSelection")


@router.get("/list")
async def list_plugins():
    tool_registry = get_tool_registry()
    capability_registry = get_capability_registry()
    plugin_manifests = _discover_plugins()

    tools = [
        {
            "name": definition.name,
            "description": definition.description,
            "description_i18n": tool_description_i18n(definition.name, definition.description),
            "parameters": [
                {
                    "name": parameter.name,
                    "type": parameter.type,
                    "description": parameter.description,
                    "required": parameter.required,
                    "default": parameter.default,
                    "enum": parameter.enum,
                }
                for parameter in definition.parameters
            ],
        }
        for definition in tool_registry.get_definitions()
    ]

    capabilities = capability_registry.get_manifests()

    plugins = [
        {
            "name": plugin.name,
            "type": plugin.type,
            "description": plugin.description,
            "stages": plugin.stages,
            "version": plugin.version,
            "author": plugin.author,
        }
        for plugin in plugin_manifests
    ]

    return {
        "tools": tools,
        "capabilities": capabilities,
        "plugins": plugins,
    }


@router.post("/tools/{tool_name}/execute")
async def execute_tool(tool_name: str, body: ToolExecuteRequest):
    """Execute a single tool with explicit parameters (for Playground testing)."""
    registry = get_tool_registry()
    tool = registry.get(tool_name)
    if not tool:
        raise HTTPException(status_code=404, detail=t("api.tool_not_found", name=tool_name))

    try:
        result = await tool.execute(**body.params)
        return {
            "success": result.success,
            "content": result.content,
            "sources": result.sources,
            "metadata": result.metadata,
        }
    except Exception as exc:
        logger.exception("Tool execution failed: %s", tool_name)
        raise HTTPException(status_code=500, detail=str(exc))


def _sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


def _queue_process_emit(
    queue: asyncio.Queue[dict[str, Any]],
    loop: asyncio.AbstractEventLoop,
):
    def emit(event: ProcessLogEvent) -> None:
        loop.call_soon_threadsafe(
            queue.put_nowait,
            {"kind": "process_log", "payload": event.to_dict()},
        )

    return emit


class _QueueTextStream:
    """Capture stdout/stderr lines as process-log events."""

    def __init__(
        self,
        queue: asyncio.Queue[dict[str, Any]],
        loop: asyncio.AbstractEventLoop,
        stream,
        *,
        logger_name: str,
    ):
        self._queue = queue
        self._loop = loop
        self._stream = stream
        self._logger_name = logger_name
        self._buffer = ""

    def write(self, text: str) -> int:
        if self._stream is not None:
            self._stream.write(text)
            self._stream.flush()

        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._emit_line(line.rstrip("\r"))
        return len(text)

    def flush(self):
        if self._stream is not None:
            self._stream.flush()
        if self._buffer.strip():
            self._emit_line(self._buffer)
            self._buffer = ""

    def isatty(self) -> bool:
        return False

    def _emit_line(self, line: str) -> None:
        clean = ANSI_ESCAPE_RE.sub("", line).strip()
        if not clean:
            return
        event = ProcessLogEvent(
            level="INFO",
            message=clean,
            logger=self._logger_name,
            timestamp=time.time(),
            context=current_log_context(),
        )
        self._loop.call_soon_threadsafe(
            self._queue.put_nowait,
            {"kind": "process_log", "payload": event.to_dict()},
        )


async def _execute_stream(tool_name: str, params: dict[str, Any]) -> AsyncGenerator[str, None]:
    """Run a tool while streaming structured process logs and the final result."""
    registry = get_tool_registry()
    tool = registry.get(tool_name)
    if not tool:
        yield _sse("error", {"detail": t("api.tool_not_found", name=tool_name)})
        return

    event_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    loop = asyncio.get_running_loop()
    stdout_stream = _QueueTextStream(
        event_queue, loop, stream=None, logger_name="deeptutor.playground.stdout"
    )
    stderr_stream = _QueueTextStream(
        event_queue, loop, stream=None, logger_name="deeptutor.playground.stderr"
    )

    result_holder: dict[str, Any] = {}
    error_holder: dict[str, str] = {}
    done = asyncio.Event()
    task_id = f"playground_tool_{tool_name}_{int(time.time() * 1000)}"

    async def _run():
        try:
            import sys

            stdout_stream._stream = sys.stdout
            stderr_stream._stream = sys.stderr
            with bind_log_context(task_id=task_id, capability="playground", sink="ui"):
                with capture_process_logs(_queue_process_emit(event_queue, loop), task_id=task_id):
                    with (
                        contextlib.redirect_stdout(stdout_stream),
                        contextlib.redirect_stderr(stderr_stream),
                    ):
                        result = await tool.execute(**params)
            result_holder["data"] = {
                "success": result.success,
                "content": result.content,
                "sources": result.sources,
                "metadata": result.metadata,
            }
        except Exception as exc:
            error_holder["detail"] = str(exc)
        finally:
            stdout_stream.flush()
            stderr_stream.flush()
            done.set()

    task = asyncio.create_task(_run())
    t0 = time.monotonic()

    try:
        while not done.is_set():
            try:
                item = await asyncio.wait_for(event_queue.get(), timeout=0.15)
                yield _sse(item["kind"], item["payload"])
            except asyncio.TimeoutError:
                pass

        while not event_queue.empty():
            item = event_queue.get_nowait()
            yield _sse(item["kind"], item["payload"])

        elapsed_ms = round((time.monotonic() - t0) * 1000)
        if error_holder:
            yield _sse("error", {"detail": error_holder["detail"], "elapsed_ms": elapsed_ms})
        else:
            payload = {**result_holder.get("data", {}), "elapsed_ms": elapsed_ms}
            yield _sse("result", payload)
    finally:
        if not task.done():
            task.cancel()


@router.post("/tools/{tool_name}/execute-stream")
async def execute_tool_stream(tool_name: str, body: ToolExecuteRequest):
    """Execute a tool and stream process logs + result as SSE."""
    return StreamingResponse(
        _execute_stream(tool_name, body.params),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _execute_capability_stream(
    capability_name: str,
    body: CapabilityExecuteRequest,
) -> AsyncGenerator[str, None]:
    """Run a capability while streaming process logs, trace events, and the result."""
    partner_id = (body.partner_id or "").strip()
    if capability_name == "chat" and partner_id:
        from deeptutor.api.routers.partners import (
            ChatMessageRequest,
            _ensure_running_partner,
            _partner_chat_stream,
        )

        if not body.content.strip():
            yield _sse("error", {"detail": "content is required"})
            return
        try:
            await _ensure_running_partner(partner_id)
        except HTTPException as exc:
            yield _sse("error", {"detail": exc.detail, "status_code": exc.status_code})
            return
        request = ChatMessageRequest(
            content=body.content,
            session_id=body.session_id,
            chat_id=body.chat_id,
            llm_selection=body.llm_selection,
        )
        async for chunk in _partner_chat_stream(partner_id, request):
            yield chunk
        return

    from deeptutor.core.context import Attachment, UnifiedContext
    from deeptutor.runtime.orchestrator import ChatOrchestrator

    orch = ChatOrchestrator()
    if capability_name not in orch.list_capabilities():
        yield _sse("error", {"detail": f"Capability {capability_name!r} not found"})
        return

    attachments = [
        Attachment(
            type=a.get("type", "file"),
            url=a.get("url", ""),
            base64=a.get("base64", ""),
            filename=a.get("filename", ""),
            mime_type=a.get("mime_type", ""),
        )
        for a in body.attachments
    ]

    ctx = UnifiedContext(
        user_message=body.content,
        enabled_tools=body.tools,
        active_capability=capability_name,
        knowledge_bases=body.knowledge_bases,
        attachments=attachments,
        config_overrides=body.config,
        language=body.language,
    )

    event_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    loop = asyncio.get_running_loop()
    stdout_stream = _QueueTextStream(
        event_queue, loop, stream=None, logger_name="deeptutor.playground.stdout"
    )
    stderr_stream = _QueueTextStream(
        event_queue, loop, stream=None, logger_name="deeptutor.playground.stderr"
    )

    final_result: dict[str, Any] | None = None
    error_holder: dict[str, str] = {}
    done = asyncio.Event()
    task_id = f"playground_capability_{capability_name}_{int(time.time() * 1000)}"

    async def _run():
        nonlocal final_result
        try:
            import sys

            stdout_stream._stream = sys.stdout
            stderr_stream._stream = sys.stderr
            with bind_log_context(
                task_id=task_id,
                capability=capability_name,
                sink="ui",
            ):
                with capture_process_logs(_queue_process_emit(event_queue, loop), task_id=task_id):
                    with (
                        contextlib.redirect_stdout(stdout_stream),
                        contextlib.redirect_stderr(stderr_stream),
                    ):
                        async for event in orch.handle(ctx):
                            if event.type.value == "result":
                                final_result = dict(event.metadata)
                                continue
                            await event_queue.put({"kind": "stream", "payload": event.to_dict()})
        except Exception as exc:
            error_holder["detail"] = str(exc)
        finally:
            stdout_stream.flush()
            stderr_stream.flush()
            done.set()

    task = asyncio.create_task(_run())
    t0 = time.monotonic()

    try:
        while not done.is_set():
            try:
                item = await asyncio.wait_for(event_queue.get(), timeout=0.15)
                yield _sse(item["kind"], item["payload"])
            except asyncio.TimeoutError:
                pass

        while not event_queue.empty():
            item = event_queue.get_nowait()
            yield _sse(item["kind"], item["payload"])

        elapsed_ms = round((time.monotonic() - t0) * 1000)
        if error_holder:
            yield _sse("error", {"detail": error_holder["detail"], "elapsed_ms": elapsed_ms})
        else:
            yield _sse(
                "result",
                {"success": True, "data": final_result or {}, "elapsed_ms": elapsed_ms},
            )
    finally:
        if not task.done():
            task.cancel()


@router.post("/capabilities/{capability_name}/execute-stream")
async def execute_capability_stream(
    capability_name: str,
    body: CapabilityExecuteRequest,
):
    """Execute a capability and stream logs + trace + final result as SSE."""
    return StreamingResponse(
        _execute_capability_stream(capability_name, body),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
