"""Discover paginated tools through the real SDK and HTTP transport."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time
from typing import Any

import pytest

from deeptutor.runtime.registry.tool_registry import ToolRegistry
from deeptutor.services.mcp.config import MCPServerConfig
from deeptutor.services.mcp.manager import (
    SHARED_OWNER,
    MCPConnectionManager,
    probe_server,
)


def _tool(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "description": f"Synthetic {name} tool",
        "inputSchema": {"type": "object", "properties": {}},
    }


class _PagedServer:
    """A stateless MCP fixture with an opaque cursor and an empty middle page."""

    def __init__(self) -> None:
        self.mode = "paged"
        self.cursors: list[str | None] = []
        self.slow_page_started = threading.Event()
        state = self

        class Handler(BaseHTTPRequestHandler):
            """Serve synthetic MCP requests without contacting other services."""

            protocol_version = "HTTP/1.1"
            timeout = 4

            def log_message(self, _format: str, *args: Any) -> None:
                """Keep expected protocol traffic out of pytest output."""

            def _reply(self, status: int, payload: dict[str, Any] | None = None) -> None:
                raw = json.dumps(payload).encode() if payload is not None else b""
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Connection", "close")
                self.end_headers()
                if raw:
                    try:
                        self.wfile.write(raw)
                    except (BrokenPipeError, ConnectionResetError):
                        # Timing out a listing closes the local client while
                        # this synthetic peer is still preparing its response.
                        pass

            def do_GET(self) -> None:
                """No standalone SSE channel is needed for this stateless server."""
                self._reply(405)

            def do_POST(self) -> None:
                """Serve initialize, tools/list and tools/call without a model."""
                request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if "id" not in request:
                    self._reply(202)
                    return
                response: dict[str, Any] = {"jsonrpc": "2.0", "id": request["id"]}
                method = request["method"]
                if method == "initialize":
                    response["result"] = {
                        "protocolVersion": request["params"]["protocolVersion"],
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "pagination-fixture", "version": "1"},
                    }
                elif method == "tools/list":
                    cursor = request.get("params", {}).get("cursor")
                    state.cursors.append(cursor)
                    if cursor is None:
                        result = {"tools": [_tool("first")]}
                        if state.mode != "single":
                            result["nextCursor"] = "opaque:+/="
                        response["result"] = result
                    elif state.mode == "error":
                        response["error"] = {"code": -32603, "message": "later page failed"}
                    elif state.mode == "cycle":
                        response["result"] = {"tools": [], "nextCursor": "opaque:+/="}
                    elif state.mode == "slow":
                        state.slow_page_started.set()
                        time.sleep(3)
                        response["result"] = {"tools": [_tool("later")]}
                    elif cursor == "opaque:+/=":
                        response["result"] = {"tools": [], "nextCursor": "last"}
                    elif cursor == "last":
                        response["result"] = {"tools": [_tool("later"), _tool("blocked")]}
                    else:
                        response["error"] = {"code": -32602, "message": "unknown cursor"}
                elif method == "tools/call":
                    response["result"] = {
                        "content": [
                            {"type": "text", "text": "called:" + request["params"]["name"]}
                        ],
                        "isError": False,
                    }
                else:
                    response["error"] = {"code": -32601, "message": "unsupported method"}
                self._reply(200, response)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        # server_close joins request workers, including a cancelled slow page.
        self.server.daemon_threads = False
        self.thread = threading.Thread(
            target=lambda: self.server.serve_forever(poll_interval=0.01), daemon=True
        )
        self.thread.start()

    @property
    def config(self) -> MCPServerConfig:
        return MCPServerConfig(url=f"http://127.0.0.1:{self.server.server_port}/mcp")

    def close(self) -> None:
        """Stop the fixture listener after the SDK has closed its transports."""
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        assert not self.thread.is_alive()


@pytest.fixture
def paged_server(monkeypatch: pytest.MonkeyPatch) -> Iterator[_PagedServer]:
    """Use only loopback traffic and an isolated real tool registry."""
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    registry = ToolRegistry()
    monkeypatch.setattr(MCPConnectionManager, "_registry", staticmethod(lambda: registry))
    server = _PagedServer()
    try:
        yield server
    finally:
        server.close()


@pytest.mark.asyncio
async def test_later_page_tools_are_registered_and_callable(paged_server: _PagedServer) -> None:
    """An empty intermediate page does not hide a callable tool after it."""
    manager = MCPConnectionManager()
    try:
        await asyncio.wait_for(manager._connect("paged", paged_server.config), timeout=5)
        conn = manager._connections[(SHARED_OWNER, "paged")]
        assert conn.status == "connected", conn.error
        assert [tool.name for tool in conn.adapters] == [
            "mcp_paged_first",
            "mcp_paged_later",
            "mcp_paged_blocked",
        ]
        tool = manager._registry().get("mcp_paged_later")
        assert tool is not None
        assert "called:later" in (await tool.execute()).content
        assert paged_server.cursors == [None, "opaque:+/=", "last"]
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_probe_reports_tools_from_every_page(paged_server: _PagedServer) -> None:
    """The Test button and the live connection see the same complete inventory."""
    result = await probe_server(paged_server.config, timeout=5)
    assert result["ok"], result["error"]
    assert [tool["name"] for tool in result["tools"]] == ["first", "later", "blocked"]
    assert paged_server.cursors == [None, "opaque:+/=", "last"]


@pytest.mark.asyncio
async def test_tool_filters_also_apply_to_later_pages(paged_server: _PagedServer) -> None:
    """Wrapped allowlist names and blocked names still govern later pages."""
    cfg = paged_server.config.model_copy(
        update={"enabled_tools": ["mcp_paged_later", "blocked"], "disabled_tools": ["blocked"]}
    )
    manager = MCPConnectionManager()
    try:
        await asyncio.wait_for(manager._connect("paged", cfg), timeout=5)
        conn = manager._connections[(SHARED_OWNER, "paged")]
        assert conn.status == "connected", conn.error
        assert [tool.name for tool in conn.adapters] == ["mcp_paged_later"]
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_single_page_servers_need_no_extra_request(paged_server: _PagedServer) -> None:
    """Keep the common one-page case unchanged for connection and probe."""
    paged_server.mode = "single"
    manager = MCPConnectionManager()
    try:
        await asyncio.wait_for(manager._connect("paged", paged_server.config), timeout=5)
        conn = manager._connections[(SHARED_OWNER, "paged")]
        assert conn.status == "connected", conn.error
        assert [tool.name for tool in conn.adapters] == ["mcp_paged_first"]
        result = await probe_server(paged_server.config, timeout=5)
        assert result["ok"], result["error"]
        assert [tool["name"] for tool in result["tools"]] == ["first"]
        assert paged_server.cursors == [None, None]
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("consumer", ["manager", "probe"])
@pytest.mark.parametrize("mode", ["error", "cycle"])
async def test_incomplete_listing_does_not_publish_partial_tools(
    paged_server: _PagedServer, consumer: str, mode: str
) -> None:
    """A later failure or repeated cursor must not advertise the first page."""
    paged_server.mode = mode
    expected = "later page failed" if mode == "error" else "repeated tools/list cursor"
    if consumer == "probe":
        result = await probe_server(paged_server.config, timeout=5)
        assert result["ok"] is False
        assert result["tools"] == []
        assert expected in result["error"]
    else:
        manager = MCPConnectionManager()
        try:
            await asyncio.wait_for(manager._connect("paged", paged_server.config), timeout=5)
            conn = manager._connections[(SHARED_OWNER, "paged")]
            assert conn.status == "error"
            assert conn.adapters == []
            assert expected in conn.error
            assert manager._registry().get("mcp_paged_first") is None
            assert conn.task is not None
            await asyncio.wait_for(conn.task, timeout=5)
        finally:
            await manager.shutdown()
    assert paged_server.cursors == [None, "opaque:+/="]


@pytest.mark.asyncio
@pytest.mark.parametrize("consumer", ["manager", "probe"])
async def test_slow_later_page_stays_within_the_discovery_timeout(
    paged_server: _PagedServer, consumer: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A later page cannot leave the connection task waiting after its budget."""
    from deeptutor.services.mcp import manager as manager_module

    paged_server.mode = "slow"
    monkeypatch.setattr(manager_module, "_CONNECT_TIMEOUT_S", 1)
    if consumer == "probe":
        result = await probe_server(paged_server.config, timeout=1)
        assert result["ok"] is False
        assert result["tools"] == []
        assert "timed out" in result["error"]
    else:
        manager = MCPConnectionManager()
        try:
            await asyncio.wait_for(manager._connect("paged", paged_server.config), timeout=5)
            conn = manager._connections[(SHARED_OWNER, "paged")]
            assert conn.status == "error"
            assert conn.adapters == []
            assert manager._registry().get("mcp_paged_first") is None
            assert conn.task is not None
            # Shield so a regression does not get cleaned up by this assertion;
            # shutdown remains responsible for the real connection's lifetime.
            await asyncio.wait_for(asyncio.shield(conn.task), timeout=2)
        finally:
            await manager.shutdown()
    assert paged_server.slow_page_started.is_set()
    assert paged_server.cursors == [None, "opaque:+/="]
