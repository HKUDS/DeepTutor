"""Built-in pageindex MCP server injection."""

from __future__ import annotations

import asyncio
import json

from deeptutor.services.mcp import pageindex_server
from deeptutor.services.mcp.config import MCPConfig, MCPServerConfig
from deeptutor.services.mcp.manager import MCPToolAdapter, wrapped_tool_name
from deeptutor.services.rag.pipelines.pageindex.config import (
    PageIndexConfig,
    PageIndexNotConfiguredError,
)


def _configured(monkeypatch, key: str = "sk-test") -> None:
    monkeypatch.setattr(
        "deeptutor.services.rag.pipelines.pageindex.config.get_pageindex_config",
        lambda **_: PageIndexConfig(api_key=key),
    )


def _unconfigured(monkeypatch) -> None:
    def _raise(**_):
        raise PageIndexNotConfiguredError("no key")

    monkeypatch.setattr(
        "deeptutor.services.rag.pipelines.pageindex.config.get_pageindex_config", _raise
    )


def test_injects_builtin_server_when_configured(monkeypatch) -> None:
    _configured(monkeypatch)
    config = pageindex_server.with_builtin_servers(MCPConfig())
    entry = config.servers["pageindex"]
    assert entry.url == "https://api.pageindex.ai/mcp"
    assert entry.headers["Authorization"] == "Bearer sk-test"
    assert entry.resolved_type() == "streamableHttp"


def test_no_injection_without_key(monkeypatch) -> None:
    _unconfigured(monkeypatch)
    config = pageindex_server.with_builtin_servers(MCPConfig())
    assert "pageindex" not in config.servers


def test_user_defined_entry_wins(monkeypatch) -> None:
    _configured(monkeypatch)
    user = MCPConfig(servers={"pageindex": MCPServerConfig(url="https://example.com/mcp")})
    config = pageindex_server.with_builtin_servers(user)
    assert config.servers["pageindex"].url == "https://example.com/mcp"


def test_builtin_blocks_remove_document(monkeypatch) -> None:
    _configured(monkeypatch)
    entry = pageindex_server.builtin_pageindex_server()
    assert entry is not None
    assert not entry.tool_allowed(
        "remove_document", wrapped_tool_name("pageindex", "remove_document")
    )
    # Everything else passes through untouched.
    assert entry.tool_allowed(
        "get_page_content", wrapped_tool_name("pageindex", "get_page_content")
    )


def test_disabled_tools_blocklist_beats_wildcard() -> None:
    cfg = MCPServerConfig(url="https://x/mcp", disabled_tools=["bad_tool"])
    assert not cfg.tool_allowed("bad_tool", wrapped_tool_name("x", "bad_tool"))
    assert cfg.tool_allowed("good_tool", wrapped_tool_name("x", "good_tool"))


def test_cloud_page_read_emits_structured_sources() -> None:
    class Manager:
        async def call_tool(self, *_args, **_kwargs):
            return json.dumps(
                {
                    "success": True,
                    "doc_name": "report.pdf",
                    "content": [{"page": 7, "text": "evidence"}],
                }
            )

    tool = MCPToolAdapter(
        manager=Manager(),
        server_name="pageindex",
        original_name="get_page_content",
        description="read",
        input_schema={},
        tool_timeout=30,
    )
    result = asyncio.run(tool.execute(doc_name="report.pdf", pages="7"))
    assert result.sources[0]["provider"] == "pageindex"
    assert result.sources[0]["document_name"] == "report.pdf"
    assert result.sources[0]["page"] == 7
