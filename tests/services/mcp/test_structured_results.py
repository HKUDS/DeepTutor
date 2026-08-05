"""MED-02 MCP structured-result compatibility tests.

The manager must preserve TextContent, ImageContent, EmbeddedResource and
ResourceLink for media adapters while keeping the existing text-tool callers
byte-compatible (`call_tool` still returns text).  No real MCP server is
contacted.
"""

from __future__ import annotations

import base64
from typing import Any

import pytest

from deeptutor.services.mcp.config import MCPServerConfig
from deeptutor.services.mcp.manager import (
    MCPConnectionManager,
    MCPContentBlock,
    MCPStructuredResult,
    MCPToolAdapter,
    _ServerConnection,
)


def _png_b64() -> str:
    return base64.b64encode(b"\x89PNG\r\n\x1a\nFAKE").decode("ascii")


class _Session:
    def __init__(self, result: Any = None, error: Exception | None = None) -> None:
        from mcp import types

        if result is None:
            result = types.CallToolResult(content=[types.TextContent(type="text", text="done")])
        self._result = result
        self._error = error

    async def call_tool(self, tool_name: str, arguments: dict[str, Any], progress_callback=None):
        if self._error is not None:
            raise self._error
        return self._result


def _manager_with(session: _Session) -> MCPConnectionManager:
    manager = MCPConnectionManager()
    conn = _ServerConnection(
        name="crawler",
        config=MCPServerConfig(url="https://crawler.example/mcp"),
        signature="sig",
        owner="u_ada",
        status="connected",
    )
    conn.session = session
    manager._connections[("u_ada", "crawler")] = conn
    return manager


async def _structured(manager: MCPConnectionManager) -> MCPStructuredResult:
    return await manager._call_once(next(iter(manager._connections.values())), "crawl", {}, 5)


# ── content-block preservation ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_text_content_is_preserved() -> None:
    from mcp import types

    session = _Session(
        types.CallToolResult(content=[types.TextContent(type="text", text="hello world")])
    )
    result = await _structured(_manager_with(session))
    assert len(result.blocks) == 1
    assert result.blocks[0].kind == "text"
    assert result.blocks[0].text == "hello world"
    assert result.to_text() == "hello world"


@pytest.mark.asyncio
async def test_image_content_is_decoded_directly() -> None:
    from mcp import types

    session = _Session(
        types.CallToolResult(
            content=[types.ImageContent(type="image", data=_png_b64(), mimeType="image/png")]
        )
    )
    result = await _structured(_manager_with(session))
    block = result.blocks[0]
    assert block.kind == "image"
    assert block.data == b"\x89PNG\r\n\x1a\nFAKE"
    assert block.mime_type == "image/png"
    assert block.to_media_payload() == block.data


@pytest.mark.asyncio
async def test_blob_resource_is_decoded() -> None:
    from mcp import types

    resource = types.BlobResourceContents(
        uri="images://blob-1", mimeType="image/png", blob=_png_b64()
    )
    session = _Session(
        types.CallToolResult(content=[types.EmbeddedResource(type="resource", resource=resource)])
    )
    result = await _structured(_manager_with(session))
    block = result.blocks[0]
    assert block.kind == "resource"
    assert block.uri == "images://blob-1"
    assert block.data == b"\x89PNG\r\n\x1a\nFAKE"
    assert block.to_media_payload() == block.data


@pytest.mark.asyncio
async def test_text_resource_keeps_prose() -> None:
    from mcp import types

    resource = types.TextResourceContents(uri="notes://1", mimeType="text/plain", text="progress")
    session = _Session(
        types.CallToolResult(content=[types.EmbeddedResource(type="resource", resource=resource)])
    )
    result = await _structured(_manager_with(session))
    block = result.blocks[0]
    assert block.kind == "resource"
    assert block.resource_text == "progress"
    # A text resource is not an image payload.
    assert block.to_media_payload() is None


@pytest.mark.asyncio
async def test_resource_link_is_preserved() -> None:
    from mcp import types

    link = types.ResourceLink(
        type="resource_link",
        uri="https://cdn.example/img.png",
        name="img.png",
        title="Generated image",
        mimeType="image/png",
        size=1234,
    )
    session = _Session(types.CallToolResult(content=[link]))
    result = await _structured(_manager_with(session))
    block = result.blocks[0]
    assert block.kind == "resource_link"
    assert block.uri == "https://cdn.example/img.png"
    assert block.name == "img.png"


@pytest.mark.asyncio
async def test_mixed_blocks_render_text_compatibly() -> None:
    from mcp import types

    session = _Session(
        types.CallToolResult(
            content=[
                types.TextContent(type="text", text="done"),
                types.ImageContent(type="image", data=_png_b64(), mimeType="image/png"),
            ]
        )
    )
    result = await _structured(_manager_with(session))
    text = result.to_text()
    assert text.startswith("done")
    assert "[image: image/png" in text


# ── public API compatibility ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_call_tool_returns_text_for_existing_callers() -> None:
    from mcp import types

    session = _Session(types.CallToolResult(content=[types.TextContent(type="text", text="done")]))
    manager = _manager_with(session)
    text = await manager.call_tool("u_ada", "crawler", "crawl", {}, timeout=5)
    assert text == "done"


@pytest.mark.asyncio
async def test_tool_adapter_execute_still_returns_text() -> None:
    manager = _manager_with(_Session())
    adapter = MCPToolAdapter(
        manager=manager,
        owner="u_ada",
        server_name="crawler",
        original_name="crawl",
        description="d",
        input_schema=None,
        tool_timeout=5,
    )
    result = await adapter.execute(url="https://x.example")
    assert result.content == "done"
    assert result.metadata == {"mcp_server": "crawler", "mcp_tool": "crawl"}


@pytest.mark.asyncio
async def test_structured_error_is_error_with_sanitized_text() -> None:
    manager = _manager_with(_Session(error=RuntimeError("boom sk-abcdefghijklmnop")))
    result = await manager.call_tool_structured("u_ada", "crawler", "crawl", {}, timeout=5)
    assert result.is_error is True
    # The error text is sanitized: the exception type is visible, the secret
    # and the raw message are not.
    assert "RuntimeError" in result.to_text()
    assert "sk-abcdefghijklmnop" not in result.to_text()


@pytest.mark.asyncio
async def test_unconnected_server_returns_error_structured() -> None:
    manager = MCPConnectionManager()
    result = await manager.call_tool_structured("u_ada", "missing", "crawl", {}, timeout=5)
    assert result.is_error is True
    assert "not connected" in result.to_text()
