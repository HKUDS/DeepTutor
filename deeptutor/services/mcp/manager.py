"""
MCP connection manager
======================

App-level singleton that owns the lifecycle of every configured MCP server
connection and exposes their tools as chat :class:`BaseTool` adapters.

Lifecycle model
---------------

DeepTutor's chat runs as per-turn tasks inside one event loop, while MCP
sessions must be opened and closed inside the same task (the SDK's anyio
cancel scopes are task-bound). Each server therefore gets a dedicated
*connection task* that owns its ``AsyncExitStack`` end-to-end::

    connect → enter transports/session in the task → publish adapters →
    wait on a shutdown event → exit the stack in the same task

``ensure_started()`` is lazy (first turn pays the connect cost, capped by a
per-server timeout) and cheap afterwards. ``reload()`` diffs the persisted
config against live connections and only restarts servers whose
configuration actually changed.

Tool adapters are flagged ``deferred`` — their schemas reach the model via
the ``load_tools`` progressive-disclosure flow, not the initial tool list —
and are synced into the global :class:`ToolRegistry` so the regular dispatch
path executes them.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import logging
import re
from typing import Any

import httpx

from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolResult
from deeptutor.services.mcp.config import (
    MCPConfig,
    MCPServerConfig,
    load_mcp_config,
)

logger = logging.getLogger(__name__)

_CONNECT_TIMEOUT_S = 15
_NAME_SANITIZE_RE = re.compile(r"[^a-zA-Z0-9_-]")

# Transient transport errors worth exactly one retry (mirrors nanobot).
_TRANSIENT_ERRORS = (
    BrokenPipeError,
    ConnectionResetError,
)


def wrapped_tool_name(server: str, tool: str) -> str:
    """``mcp_<server>_<tool>`` with non-identifier characters sanitised."""
    return f"mcp_{_NAME_SANITIZE_RE.sub('_', server)}_{_NAME_SANITIZE_RE.sub('_', tool)}"


class MCPToolAdapter(BaseTool):
    """One MCP server tool exposed as a chat tool (deferred by default)."""

    deferred = True

    def __init__(
        self,
        *,
        manager: "MCPConnectionManager",
        server_name: str,
        original_name: str,
        description: str,
        input_schema: dict[str, Any] | None,
        tool_timeout: int,
    ) -> None:
        self._manager = manager
        self._server_name = server_name
        self._original_name = original_name
        self._wrapped_name = wrapped_tool_name(server_name, original_name)
        self._description = description or original_name
        self._input_schema = input_schema or {"type": "object", "properties": {}}
        self._tool_timeout = tool_timeout

    @property
    def server_name(self) -> str:
        return self._server_name

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self._wrapped_name,
            description=f"[{self._server_name}] {self._description}",
            raw_parameters=self._input_schema,
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        kwargs.pop("event_sink", None)
        text = await self._manager.call_tool(
            self._server_name,
            self._original_name,
            kwargs,
            timeout=self._tool_timeout,
        )
        return ToolResult(
            content=text,
            metadata={"mcp_server": self._server_name, "mcp_tool": self._original_name},
        )


@dataclass
class _ServerConnection:
    """Live state for one configured server."""

    name: str
    config: MCPServerConfig
    signature: str
    status: str = "connecting"  # connecting | connected | error | disabled
    error: str = ""
    adapters: list[MCPToolAdapter] = field(default_factory=list)
    session: Any = None
    task: asyncio.Task | None = None
    shutdown: asyncio.Event = field(default_factory=asyncio.Event)


class MCPConnectionManager:
    """Owns all MCP server connections; one instance per process."""

    def __init__(self) -> None:
        self._connections: dict[str, _ServerConnection] = {}
        self._lock = asyncio.Lock()
        self._started = False

    # ── public lifecycle ───────────────────────────────────────────────

    async def ensure_started(self) -> None:
        """Connect every enabled configured server that isn't live yet.

        Lazy: callers invoke this at turn start; after the first call it
        returns immediately unless the config gained new servers via
        :meth:`reload`.
        """
        if self._started:
            return
        async with self._lock:
            if self._started:
                return
            await self._sync_to_config(load_mcp_config())
            self._started = True

    async def reload(self) -> None:
        """Re-read the persisted config and apply the diff to live connections."""
        async with self._lock:
            await self._sync_to_config(load_mcp_config())
            self._started = True

    async def shutdown(self) -> None:
        async with self._lock:
            for conn in list(self._connections.values()):
                await self._disconnect(conn)
            self._connections.clear()
            self._started = False

    # ── public queries ─────────────────────────────────────────────────

    def status(self) -> list[dict[str, Any]]:
        """Connection status rows for the settings UI."""
        rows: list[dict[str, Any]] = []
        for name, conn in sorted(self._connections.items()):
            rows.append(
                {
                    "name": name,
                    "transport": conn.config.resolved_type() or "",
                    "status": conn.status,
                    "error": conn.error,
                    "tools": [
                        {
                            "name": a.name,
                            "description": a.get_definition().description,
                        }
                        for a in conn.adapters
                    ],
                }
            )
        return rows

    def tool_adapters(self) -> list[MCPToolAdapter]:
        out: list[MCPToolAdapter] = []
        for conn in self._connections.values():
            out.extend(conn.adapters)
        return out

    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        timeout: int,
    ) -> str:
        """Invoke a tool on a connected server; one retry on transient errors."""
        conn = self._connections.get(server_name)
        if conn is None or conn.session is None or conn.status != "connected":
            return f"(MCP server {server_name!r} is not connected)"
        try:
            return await self._call_once(conn, tool_name, arguments, timeout)
        except _TRANSIENT_ERRORS:
            logger.warning(
                "MCP tool %s/%s hit a transient transport error; retrying once",
                server_name,
                tool_name,
            )
            try:
                return await self._call_once(conn, tool_name, arguments, timeout)
            except Exception as exc:
                return f"(MCP tool call failed after retry: {type(exc).__name__})"
        except asyncio.TimeoutError:
            return f"(MCP tool call timed out after {timeout}s)"
        except asyncio.CancelledError:
            # The MCP SDK's anyio scopes can leak CancelledError on internal
            # failures; re-raise only when our own task was cancelled.
            task = asyncio.current_task()
            if task is not None and task.cancelling() > 0:
                raise
            return "(MCP tool call was cancelled)"
        except Exception as exc:
            logger.exception("MCP tool %s/%s failed", server_name, tool_name)
            return f"(MCP tool call failed: {type(exc).__name__}: {exc})"

    @staticmethod
    async def _call_once(
        conn: _ServerConnection,
        tool_name: str,
        arguments: dict[str, Any],
        timeout: int,
    ) -> str:
        from mcp import types

        result = await asyncio.wait_for(
            conn.session.call_tool(tool_name, arguments=arguments),
            timeout=timeout,
        )
        parts: list[str] = []
        for block in result.content:
            if isinstance(block, types.TextContent):
                parts.append(block.text)
            else:
                parts.append(str(block))
        return "\n".join(parts) or "(no output)"

    # ── connection internals ───────────────────────────────────────────

    async def _sync_to_config(self, config: MCPConfig) -> None:
        """Diff live connections against *config*; caller holds the lock."""
        desired = {name: cfg for name, cfg in config.servers.items() if cfg.enabled}
        # Drop removed/disabled/changed servers.
        for name in list(self._connections):
            cfg = desired.get(name)
            if cfg is None or cfg.connection_signature() != self._connections[name].signature:
                await self._disconnect(self._connections.pop(name))
        # Connect new/changed servers concurrently.
        pending = [
            self._connect(name, cfg)
            for name, cfg in desired.items()
            if name not in self._connections
        ]
        if pending:
            await asyncio.gather(*pending)

    async def _connect(self, name: str, cfg: MCPServerConfig) -> None:
        conn = _ServerConnection(
            name=name,
            config=cfg,
            signature=cfg.connection_signature(),
        )
        self._connections[name] = conn
        ready: asyncio.Future = asyncio.get_running_loop().create_future()
        conn.task = asyncio.create_task(self._run_server(conn, ready), name=f"mcp-server-{name}")
        try:
            await asyncio.wait_for(ready, timeout=_CONNECT_TIMEOUT_S)
            conn.status = "connected"
            conn.error = ""
            self._register_adapters(conn)
            logger.info("MCP server %r connected (%d tools)", name, len(conn.adapters))
        except asyncio.TimeoutError:
            conn.status = "error"
            conn.error = f"connect timed out after {_CONNECT_TIMEOUT_S}s"
            conn.shutdown.set()
            logger.error("MCP server %r: %s", name, conn.error)
        except Exception as exc:
            conn.status = "error"
            conn.error = f"{type(exc).__name__}: {exc}"
            conn.shutdown.set()
            logger.error("MCP server %r failed to connect: %s", name, conn.error)

    async def _run_server(self, conn: _ServerConnection, ready: asyncio.Future) -> None:
        """Connection task: owns the AsyncExitStack for one server."""
        from contextlib import AsyncExitStack

        from mcp import ClientSession

        try:
            async with AsyncExitStack() as stack:
                read, write = await self._open_transport(stack, conn.config)
                session = await stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                listing = await session.list_tools()
                adapters = [
                    MCPToolAdapter(
                        manager=self,
                        server_name=conn.name,
                        original_name=tool_def.name,
                        description=tool_def.description or "",
                        input_schema=tool_def.inputSchema,
                        tool_timeout=conn.config.tool_timeout,
                    )
                    for tool_def in listing.tools
                    if conn.config.tool_allowed(
                        tool_def.name, wrapped_tool_name(conn.name, tool_def.name)
                    )
                ]
                conn.session = session
                conn.adapters = adapters
                if not ready.done():
                    ready.set_result(None)
                await conn.shutdown.wait()
        except Exception as exc:
            if not ready.done():
                ready.set_exception(exc)
            else:
                logger.warning("MCP server %r connection task ended: %s", conn.name, exc)
                conn.status = "error"
                conn.error = f"{type(exc).__name__}: {exc}"
        finally:
            conn.session = None

    @staticmethod
    async def _open_transport(stack: Any, cfg: MCPServerConfig) -> tuple[Any, Any]:
        """Enter the configured transport on *stack*; return (read, write)."""
        from mcp import StdioServerParameters
        from mcp.client.sse import sse_client
        from mcp.client.stdio import stdio_client
        from mcp.client.streamable_http import streamable_http_client

        transport = cfg.resolved_type()
        if transport == "stdio":
            params = StdioServerParameters(
                command=cfg.command,
                args=list(cfg.args),
                env=dict(cfg.env) or None,
                cwd=cfg.cwd or None,
            )
            read, write = await stack.enter_async_context(stdio_client(params))
            return read, write
        if transport == "sse":

            def httpx_client_factory(
                headers: dict[str, str] | None = None,
                timeout: httpx.Timeout | None = None,
                auth: httpx.Auth | None = None,
            ) -> httpx.AsyncClient:
                merged = {**(cfg.headers or {}), **(headers or {})}
                return httpx.AsyncClient(
                    headers=merged or None,
                    follow_redirects=True,
                    timeout=timeout,
                    auth=auth,
                )

            read, write = await stack.enter_async_context(
                sse_client(cfg.url, httpx_client_factory=httpx_client_factory)
            )
            return read, write
        if transport == "streamableHttp":
            # Explicit client so the transport doesn't inherit httpx's 5s
            # default timeout and preempt the per-tool timeout.
            http_client = await stack.enter_async_context(
                httpx.AsyncClient(
                    headers=cfg.headers or None,
                    follow_redirects=True,
                    timeout=httpx.Timeout(60.0, connect=10.0),
                )
            )
            read, write, _ = await stack.enter_async_context(
                streamable_http_client(cfg.url, http_client=http_client)
            )
            return read, write
        raise ValueError(f"MCP server has no usable transport (type={cfg.type!r})")

    async def _disconnect(self, conn: _ServerConnection) -> None:
        self._unregister_adapters(conn)
        conn.shutdown.set()
        if conn.task is not None:
            try:
                await asyncio.wait_for(conn.task, timeout=10)
            except (asyncio.TimeoutError, Exception):
                conn.task.cancel()
        conn.status = "disabled"
        conn.adapters = []

    # ── registry sync ──────────────────────────────────────────────────

    @staticmethod
    def _registry():
        from deeptutor.runtime.registry.tool_registry import get_tool_registry

        return get_tool_registry()

    def _register_adapters(self, conn: _ServerConnection) -> None:
        registry = self._registry()
        for adapter in conn.adapters:
            registry.register(adapter)

    def _unregister_adapters(self, conn: _ServerConnection) -> None:
        registry = self._registry()
        for adapter in conn.adapters:
            registry.unregister(adapter.name)


async def probe_server(
    cfg: MCPServerConfig, *, timeout: int = _CONNECT_TIMEOUT_S
) -> dict[str, Any]:
    """One-off connect + list_tools for the settings page's Test button.

    Opens and closes its own connection; never touches the live manager.
    """
    from contextlib import AsyncExitStack

    from mcp import ClientSession

    async def _probe() -> list[dict[str, str]]:
        async with AsyncExitStack() as stack:
            read, write = await MCPConnectionManager._open_transport(stack, cfg)
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            listing = await session.list_tools()
            return [{"name": t.name, "description": t.description or ""} for t in listing.tools]

    try:
        tools = await asyncio.wait_for(_probe(), timeout=timeout)
        return {"ok": True, "tools": tools, "error": ""}
    except asyncio.TimeoutError:
        return {"ok": False, "tools": [], "error": f"connect timed out after {timeout}s"}
    except Exception as exc:
        return {"ok": False, "tools": [], "error": f"{type(exc).__name__}: {exc}"}


_manager: MCPConnectionManager | None = None


def get_mcp_manager() -> MCPConnectionManager:
    global _manager
    if _manager is None:
        _manager = MCPConnectionManager()
    return _manager


__all__ = [
    "MCPConnectionManager",
    "MCPToolAdapter",
    "get_mcp_manager",
    "probe_server",
    "wrapped_tool_name",
]
