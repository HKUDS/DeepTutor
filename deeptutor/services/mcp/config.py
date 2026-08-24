"""
MCP configuration
=================

Pydantic models + persistence for the deployment's MCP server registry.

This file's config is deployment-global (``settings/mcp.json`` in the admin
workspace): every account talks to the same set of connected servers, and only
an administrator writes it. The servers an individual configures for themselves
live in :mod:`deeptutor.services.mcp.user_config` and reuse
:class:`MCPServerConfig` unchanged — one server shape, two stores.
"""

from __future__ import annotations

import json
import os
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
    # Blocklist applied after ``enabled_tools`` — for "everything except X".
    disabled_tools: list[str] = Field(default_factory=list)
    enabled: bool = True
    # authentication
    #: ``"oauth"`` when this server requires an OAuth 2.1 authorization the
    #: account has to grant interactively; ``""`` when a static credential in
    #: ``headers`` (or none at all) is enough. Opt-in rather than detected: a
    #: server that answers 401 might need a token the user simply has not entered
    #: yet, and silently starting a consent flow on that guess would be wrong.
    auth: Literal["", "oauth"] = ""
    # provenance
    #: Catalog entry this server was installed from, or "" for a hand-written
    #: one. Recorded because the local name is the installer's to choose: without
    #: it, "is this service already installed?" can only be answered by comparing
    #: names, and anyone who installed under a different name is told no.
    catalog_entry: str = ""

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
        """Stable fingerprint used by reload to detect changed servers.

        Provenance is excluded: ``catalog_entry`` records where a definition came
        from, not how to reach it, so stamping it onto a server that predates the
        field must not look like a changed connection and drop a live session.
        """
        data = self.model_dump(mode="json")
        data.pop("catalog_entry", None)
        return json.dumps(data, sort_keys=True, ensure_ascii=False)

    def tool_allowed(self, raw_name: str, wrapped_name: str) -> bool:
        blocked = set(self.disabled_tools or [])
        if raw_name in blocked or wrapped_name in blocked:
            return False
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
    """Persist the config atomically.

    A torn write here costs every server in the deployment: ``load_mcp_config``
    falls back to an *empty* config on a JSON error, so a crash mid-write would
    silently disconnect everything on next start.
    """
    path = mcp_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(config.model_dump(mode="json"), ensure_ascii=False, indent=2)
    tmp = path.with_name(f"{path.name}.tmp")
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


__all__ = [
    "MCP_CONFIG_FILENAME",
    "MCPConfig",
    "MCPServerConfig",
    "load_mcp_config",
    "mcp_config_path",
    "save_mcp_config",
]
