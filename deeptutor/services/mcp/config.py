"""
MCP configuration
=================

Pydantic models + persistence for the deployment's MCP server registry.

The config is deployment-global (one shared file, ``settings/mcp.json`` in
the admin workspace): every user talks to the same set of connected servers.
Per-user MCP connections are intentionally out of scope for v1.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from deeptutor.multi_user.paths import get_admin_path_service

_SERVER_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")

MCP_CONFIG_FILENAME = "mcp.json"


class MCPServerConfig(BaseModel):
    """One MCP server entry.

    ``type`` is auto-detected when omitted: ``command`` ⇒ stdio; a ``url``
    ending in ``/sse`` ⇒ sse; any other ``url`` ⇒ streamableHttp.
    """

    type: Literal["stdio", "sse", "streamableHttp"] | None = None
    # stdio transport
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str = ""
    # http transports
    url: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    # behaviour
    tool_timeout: int = Field(default=30, ge=1, le=600)
    enabled_tools: list[str] = Field(default_factory=lambda: ["*"])
    enabled: bool = True

    @field_validator("command", "url", "cwd", mode="before")
    @classmethod
    def _strip(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    def resolved_type(self) -> str | None:
        if self.type:
            return self.type
        if self.command:
            return "stdio"
        if self.url:
            return "sse" if self.url.rstrip("/").endswith("/sse") else "streamableHttp"
        return None

    def connection_signature(self) -> str:
        """Stable fingerprint used by reload to detect changed servers."""
        return json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            ensure_ascii=False,
        )

    def tool_allowed(self, raw_name: str, wrapped_name: str) -> bool:
        allowed = set(self.enabled_tools or ["*"])
        return "*" in allowed or raw_name in allowed or wrapped_name in allowed


class MCPConfig(BaseModel):
    servers: dict[str, MCPServerConfig] = Field(default_factory=dict)

    @field_validator("servers")
    @classmethod
    def _validate_names(cls, value: dict[str, MCPServerConfig]) -> dict[str, MCPServerConfig]:
        for name in value:
            if not _SERVER_NAME_RE.match(name):
                raise ValueError(
                    f"Invalid MCP server name {name!r}: must match "
                    "^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$"
                )
        return value


def mcp_config_path() -> Path:
    return get_admin_path_service().get_settings_dir() / MCP_CONFIG_FILENAME


def load_mcp_config() -> MCPConfig:
    path = mcp_config_path()
    if not path.exists():
        return MCPConfig()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return MCPConfig()
    try:
        return MCPConfig.model_validate(data)
    except Exception:
        return MCPConfig()


def save_mcp_config(config: MCPConfig) -> None:
    path = mcp_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(config.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


__all__ = [
    "MCP_CONFIG_FILENAME",
    "MCPConfig",
    "MCPServerConfig",
    "load_mcp_config",
    "mcp_config_path",
    "save_mcp_config",
]
