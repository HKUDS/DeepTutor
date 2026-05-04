"""
SAGE Plugin Router
==================

Surfaces the SAGE Memory Companion plugin in the web Playground.

Endpoints:
    GET  /api/v1/plugins/sage/status   — probe SAGE node + plugin state.
    POST /api/v1/plugins/sage/toggle   — best-effort runtime enable/disable.

The router is intentionally tiny: it never raises if the plugin or the
``sage-agent-sdk`` package is not installed — the Playground tile must
degrade to a "SAGE not configured" muted card rather than break the page.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()

_DEFAULT_SAGE_URL = "http://localhost:8080"


def _env_truthy(value: str | None) -> bool:
    if not value:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _safe_get_client() -> Any | None:
    """Return the SAGE singleton client, or None if the plugin isn't present."""
    try:
        from deeptutor.plugins.sage.client import get_sage_client
    except Exception:
        logger.debug("SAGE plugin not importable", exc_info=True)
        return None
    try:
        return get_sage_client()
    except Exception:
        logger.debug("SAGE client init raised", exc_info=True)
        return None


class SageStatus(BaseModel):
    enabled: bool
    reachable: bool
    agent_id: str | None = None
    node_url: str
    last_observation_at: str | None = None
    sdk_installed: bool = False
    plugin_loaded: bool = False
    detail: str | None = None


class SageToggleRequest(BaseModel):
    enabled: bool


class SageToggleResponse(BaseModel):
    enabled: bool
    requires_restart: bool
    detail: str


@router.get("/sage/status", response_model=SageStatus)
async def sage_status() -> SageStatus:
    """Probe the SAGE plugin + node and report a state for the Playground tile."""
    node_url = os.environ.get("SAGE_URL", _DEFAULT_SAGE_URL)
    enabled = _env_truthy(os.environ.get("SAGE_ENABLED"))

    client = _safe_get_client()
    if client is None:
        return SageStatus(
            enabled=enabled,
            reachable=False,
            node_url=node_url,
            sdk_installed=False,
            plugin_loaded=False,
            detail="SAGE plugin not available in this build.",
        )

    sdk_installed = False
    try:
        import sage_sdk  # noqa: F401

        sdk_installed = True
    except Exception:
        sdk_installed = False

    if not enabled:
        return SageStatus(
            enabled=False,
            reachable=False,
            node_url=node_url,
            sdk_installed=sdk_installed,
            plugin_loaded=True,
            detail="SAGE_ENABLED is not set — plugin is loaded but inert.",
        )

    reachable = False
    try:
        reachable = bool(client.health_check())
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("SAGE health probe raised: %s", exc)
        reachable = False

    agent_id: str | None = None
    try:
        sdk = getattr(client, "_sdk_client", None)
        identity = getattr(sdk, "identity", None) if sdk is not None else None
        if identity is not None:
            agent_id = (
                getattr(identity, "agent_id", None)
                or getattr(identity, "public_key", None)
                or getattr(identity, "address", None)
            )
            if agent_id is not None:
                agent_id = str(agent_id)
    except Exception:
        agent_id = None

    return SageStatus(
        enabled=True,
        reachable=reachable,
        agent_id=agent_id,
        node_url=node_url,
        sdk_installed=sdk_installed,
        plugin_loaded=True,
        detail="Connected" if reachable else "SAGE node is unreachable.",
    )


@router.post("/sage/toggle", response_model=SageToggleResponse)
async def sage_toggle(body: SageToggleRequest) -> SageToggleResponse:
    """Best-effort runtime toggle.

    We flip the in-process ``SAGE_ENABLED`` env var and ask the plugin to
    re-install / uninstall its hooks. The toggle is *not* persisted across
    process restarts — the README documents that flipping the env var in
    the shell is still the source of truth.
    """
    os.environ["SAGE_ENABLED"] = "true" if body.enabled else "false"

    # Reset the singleton so the new env value takes effect on next call.
    try:
        from deeptutor.plugins.sage.client import SageClient

        SageClient.reset_instance()
    except Exception:
        logger.debug("Could not reset SAGE singleton", exc_info=True)

    requires_restart = False
    detail = "SAGE runtime flag flipped."
    try:
        from deeptutor.plugins.sage import capability as sage_cap

        if body.enabled:
            installed = sage_cap.install_hooks(force=True)
            detail = (
                "Hooks installed."
                if installed
                else "Toggle accepted but hooks could not install — restart the server."
            )
            requires_restart = not installed
        else:
            sage_cap.uninstall_hooks()
            detail = "Hooks uninstalled."
    except Exception as exc:
        logger.warning("SAGE toggle hook update failed: %s", exc)
        requires_restart = True
        detail = f"Toggle accepted but hooks did not update ({exc}). Restart required."

    return SageToggleResponse(
        enabled=body.enabled,
        requires_restart=requires_restart,
        detail=detail,
    )
