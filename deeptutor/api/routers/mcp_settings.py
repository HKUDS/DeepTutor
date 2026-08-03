"""
MCP Settings API Router
=======================

Manage the deployment-global MCP server registry: read/update the config,
inspect live connection status, and probe a server before saving.

Mounted at ``/api/v1/settings/mcp``. Admin-gated: the registry is
deployment-global state, and a stdio server's ``command`` runs on the host
as the app user — letting non-admins edit it would be privilege escalation.
Per-user MCP access is granted through the multi-user grant whitelist
(``mcp_tools``), not by sharing this registry.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError

from deeptutor.api.routers.auth import require_admin
from deeptutor.core.i18n import t
from deeptutor.services.mcp import (
    MCPConfig,
    MCPServerConfig,
    get_mcp_manager,
    load_mcp_config,
    save_mcp_config,
    validate_mcp_url,
)
from deeptutor.services.mcp.manager import probe_server

router = APIRouter(dependencies=[Depends(require_admin)])


class MCPSettingsPayload(BaseModel):
    servers: dict[str, MCPServerConfig] = Field(default_factory=dict)


def _validate_servers(config: MCPConfig) -> None:
    for name, cfg in config.servers.items():
        transport = cfg.resolved_type()
        if transport is None:
            raise HTTPException(
                status_code=400,
                detail=t("mcp.configure_command_or_url", name=name),
            )
        if transport in {"sse", "streamableHttp"}:
            ok, error = validate_mcp_url(cfg.url)
            if not ok:
                raise HTTPException(
                    status_code=400, detail=t("mcp.server_error", name=name, error=error)
                )


@router.get("")
async def get_mcp_settings() -> dict[str, Any]:
    config = load_mcp_config()
    manager = get_mcp_manager()
    await manager.ensure_started()
    return {
        "servers": {name: cfg.model_dump(mode="json") for name, cfg in config.servers.items()},
        "status": manager.status(),
    }


@router.put("")
async def update_mcp_settings(payload: MCPSettingsPayload) -> dict[str, Any]:
    try:
        config = MCPConfig(servers=payload.servers)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _validate_servers(config)
    save_mcp_config(config)
    manager = get_mcp_manager()
    await manager.reload()
    return {"status": manager.status()}


@router.put("/servers/{name}")
async def upsert_mcp_server(name: str, cfg: MCPServerConfig) -> dict[str, Any]:
    """Upsert one server, leaving every other entry byte-identical.

    The whole-map ``PUT`` above cannot express "change this one": a client has to
    send back everything it read, so it silently drops any field it does not
    model (a hand-written ``disabled_tools`` blocklist) and overwrites whatever
    a second administrator saved in between.
    """
    config = load_mcp_config()
    servers = dict(config.servers)
    servers[name] = cfg
    try:
        updated = MCPConfig(servers=servers)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _validate_servers(MCPConfig(servers={name: cfg}))
    save_mcp_config(updated)
    manager = get_mcp_manager()
    await manager.reload()
    return {
        "servers": {key: value.model_dump(mode="json") for key, value in updated.servers.items()},
        "status": manager.status(),
    }


@router.delete("/servers/{name}")
async def delete_mcp_server(name: str) -> dict[str, Any]:
    config = load_mcp_config()
    servers = {key: value for key, value in config.servers.items() if key != name}
    updated = MCPConfig(servers=servers)
    save_mcp_config(updated)
    manager = get_mcp_manager()
    await manager.reload()
    return {
        "servers": {key: value.model_dump(mode="json") for key, value in updated.servers.items()},
        "status": manager.status(),
    }


@router.post("/test")
async def test_mcp_server(cfg: MCPServerConfig) -> dict[str, Any]:
    transport = cfg.resolved_type()
    if transport is None:
        raise HTTPException(
            status_code=400,
            detail=t("mcp.configure_before_testing"),
        )
    if transport in {"sse", "streamableHttp"}:
        ok, error = validate_mcp_url(cfg.url)
        if not ok:
            raise HTTPException(status_code=400, detail=error)
    return await probe_server(cfg)
