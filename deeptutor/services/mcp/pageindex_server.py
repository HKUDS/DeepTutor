"""Built-in PageIndex MCP server entry.

PageIndex retrieval is agentic: the chat agent reads documents through the
hosted PageIndex MCP server instead of a REST retrieval endpoint. When a
PageIndex API key is configured, the connection manager overlays a reserved
``pageindex`` server entry onto the user-editable MCP config at load time —
it is never persisted to ``mcp.json``, and a user-defined server of the same
name always wins. Credentials stay single-sourced in the pageindex runtime
settings; saving a new key hot-reloads the connection (the Bearer header
changes the connection signature).
"""

from __future__ import annotations

from deeptutor.services.mcp.config import MCPConfig, MCPServerConfig

PAGEINDEX_SERVER_NAME = "pageindex"


def builtin_pageindex_server() -> MCPServerConfig | None:
    """The injected server entry, or ``None`` when no API key is configured."""
    from deeptutor.services.rag.pipelines.pageindex.config import get_pageindex_config

    try:
        cfg = get_pageindex_config()
    except Exception:
        return None
    return MCPServerConfig(
        type="streamableHttp",
        url=cfg.api_base_url.rstrip("/") + "/mcp",
        headers={"Authorization": f"Bearer {cfg.api_key}"},
        tool_timeout=120,
        # remove_document is the one api-proxy tool DeepTutor blocks: an agent
        # deleting a cloud doc would silently orphan the doc_ids in the local
        # KB manifest. Everything else the server advertises passes through.
        disabled_tools=["remove_document"],
    )


def with_builtin_servers(config: MCPConfig) -> MCPConfig:
    """Overlay code-injected servers onto *config*; user entries win."""
    if PAGEINDEX_SERVER_NAME in config.servers:
        return config
    entry = builtin_pageindex_server()
    if entry is None:
        return config
    return MCPConfig(servers={**config.servers, PAGEINDEX_SERVER_NAME: entry})


__all__ = ["PAGEINDEX_SERVER_NAME", "builtin_pageindex_server", "with_builtin_servers"]
