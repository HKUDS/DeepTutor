"""Configurable-tool surface shared by the partners and multi-user admin APIs.

``tools`` mirrors the user-toggleable system tools (the same pool the chat
composer / settings expose); ``builtin_tools`` lists the auto-mounted built-in
tools (rag / read_memory / web_fetch / …) a partner owner can selectively
allow or deny; ``mcp_tools`` lists every configured MCP tool that a whitelist
(partner config or user grant) could allow.
"""

from __future__ import annotations

import logging
from typing import Any

from deeptutor.core.i18n import current_language
from deeptutor.i18n.metadata_i18n import localized_description, tool_description_i18n

logger = logging.getLogger(__name__)


async def build_tool_options(
    *, exclude_builtin: set[str] | None = None
) -> dict[str, list[dict[str, Any]]]:
    """Build the configurable-tool surface.

    ``exclude_builtin`` drops built-in tools from the ``builtin_tools`` list —
    the partners API passes ``{"read_memory", "write_memory"}`` because partners
    use the mandatory ``partner_*`` memory tools instead and cannot configure
    chat's memory tools.
    """
    from deeptutor.agents._shared.tool_composition import default_optional_tools
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

    tools: list[dict[str, Any]] = [_describe(name) for name in default_optional_tools()]
    builtin_tools: list[dict[str, Any]] = [
        _describe(name) for name in CONFIGURABLE_BUILTIN_TOOL_NAMES if name not in exclude
    ]

    mcp_tools: list[dict[str, Any]] = []
    for tool in registry.deferred_tools():
        try:
            definition = tool.get_definition()
        except Exception:
            continue
        mcp_tools.append(
            {
                "name": definition.name,
                "server": str(getattr(tool, "server_name", "") or ""),
                "description": definition.description or "",
                "description_i18n": {
                    "en": definition.description or "",
                    "zh": definition.description or "",
                },
            }
        )

    return {"tools": tools, "builtin_tools": builtin_tools, "mcp_tools": mcp_tools}


__all__ = ["build_tool_options"]
