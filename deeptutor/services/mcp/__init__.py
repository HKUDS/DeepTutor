"""MCP integration: deployment-global server registry + deferred tool adapters."""

from deeptutor.services.mcp.config import (
    MCPConfig,
    MCPServerConfig,
    load_mcp_config,
    mcp_config_path,
    save_mcp_config,
)
from deeptutor.services.mcp.manager import (
    MCPConnectionManager,
    MCPToolAdapter,
    get_mcp_manager,
    wrapped_tool_name,
)
from deeptutor.services.mcp.network import validate_mcp_url
from deeptutor.services.mcp.session_state import load_loaded_tools, record_loaded_tools

__all__ = [
    "MCPConfig",
    "MCPConnectionManager",
    "MCPServerConfig",
    "MCPToolAdapter",
    "get_mcp_manager",
    "load_loaded_tools",
    "load_mcp_config",
    "mcp_config_path",
    "record_loaded_tools",
    "save_mcp_config",
    "validate_mcp_url",
    "wrapped_tool_name",
]
