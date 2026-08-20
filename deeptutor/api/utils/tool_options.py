"""Configurable-tool surface shared by the partners and multi-user admin APIs.

``tools`` mirrors the user-toggleable system tools (the same pool the chat
composer / settings expose); ``builtin_tools`` lists the auto-mounted built-in
tools (rag / read_memory / web_fetch / …) a partner owner can selectively
allow or deny; ``mcp_tools`` lists every configured MCP tool that a whitelist
(partner config or user grant) could allow.

Each ``mcp_tools`` row carries its provider identity — ``kind`` (``"mcp"``
today) and ``provider_id`` (the server name) — so the pickers can fold
hundreds of tools into one row per service. ``server`` is the pre-provider
spelling of ``provider_id`` and stays populated for existing clients.
"""

from __future__ import annotations

from collections.abc import Iterable
import logging
from typing import Any

from deeptutor.core.i18n import current_language
from deeptutor.i18n.metadata_i18n import localized_description, tool_description_i18n

logger = logging.getLogger(__name__)


async def build_tool_options(
    *,
    exclude_builtin: set[str] | None = None,
    optional_tools: Iterable[str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Build the configurable-tool surface.

    ``exclude_builtin`` drops built-in tools from the ``builtin_tools`` list —
    the partners API passes ``{"read_memory", "write_memory"}`` because partners
    use the mandatory ``partner_*`` memory tools instead and cannot configure
    chat's memory tools.

    ``optional_tools`` is an optional allow-list for the user-toggleable
    surface.  The generic builder intentionally owns no admin or partner
    policy: callers that need a restricted view pass it explicitly, while the
    multi-user grant editor keeps seeing the complete assignable catalog.
    """
    from deeptutor.agents._shared.tool_composition import (
        default_optional_tools,
    )
    from deeptutor.runtime.registry.deferred_tools import provider_identity
    from deeptutor.runtime.registry.tool_registry import get_tool_registry
    from deeptutor.tools.builtin import CONFIGURABLE_BUILTIN_TOOL_NAMES

    exclude = exclude_builtin or set()

    registry = get_tool_registry()
    language = current_language()
    try:
        from deeptutor.services.mcp import get_mcp_manager

        await get_mcp_manager().ensure_started()
    except Exception:
        logger.debug("MCP manager unavailable for tool options", exc_info=True)

    def _describe(name: str) -> dict[str, Any]:
        tool = registry.get(name)
        description = ""
        if tool is not None:
            try:
                description = tool.get_definition().description or ""
            except Exception:
                description = ""
        descriptions = tool_description_i18n(name, description)
        return {
            "name": name,
            "description": localized_description(descriptions, language),
            "description_i18n": descriptions,
        }

    allowed_optional = None if optional_tools is None else frozenset(optional_tools)
    tools: list[dict[str, Any]] = [
        _describe(name)
        for name in default_optional_tools()
        if allowed_optional is None or name in allowed_optional
    ]
    builtin_tools: list[dict[str, Any]] = [
        _describe(name) for name in CONFIGURABLE_BUILTIN_TOOL_NAMES if name not in exclude
    ]

    # Only MCP rows belong in ``mcp_tools``: that list is written into
    # ``grant.mcp_tools`` / a partner's ``mcp_tools``, and per
    # ``runtime.providers.authorize`` a CLI app must be governed by its own grant
    # field instead — collapsing the two is exactly how a CLI app ends up
    # authorised by an MCP whitelist. CLI providers get their own list when they
    # land; until then they are simply not offered here.
    mcp_tools: list[dict[str, Any]] = []
    for tool in registry.deferred_tools():
        try:
            definition = tool.get_definition()
        except Exception:
            continue
        kind, provider_id = provider_identity(tool)
        if (kind or "mcp") != "mcp":
            continue
        mcp_tools.append(
            {
                "name": definition.name,
                # Adapters written before ``provider_kind`` existed are all MCP,
                # so an absent kind means "mcp" rather than "unknown".
                "kind": kind or "mcp",
                "provider_id": provider_id,
                # Legacy alias — drop once no client reads ``server``.
                "server": provider_id,
                "description": definition.description or "",
                "description_i18n": {
                    "en": definition.description or "",
                    "zh": definition.description or "",
                },
            }
        )

    return {"tools": tools, "builtin_tools": builtin_tools, "mcp_tools": mcp_tools}


__all__ = ["build_tool_options"]
