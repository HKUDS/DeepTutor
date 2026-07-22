"""
Tools API Router
================

Read-only listing of the chat agent's built-in tools, used by the Settings UI
to render the "Tools" sub-page. Returns each tool's definition (name,
description, parameters) alongside its bilingual prompt hints, so the frontend
can show authoritative copy without duplicating the catalog.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel

from deeptutor.api.routers.settings import get_enabled_optional_tools
from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolPromptHints
from deeptutor.i18n.metadata_i18n import tool_description_i18n
from deeptutor.tools.builtin import (
    BUILTIN_TOOL_TYPES,
    COMING_SOON_TOOL_TYPES,
    TOOL_ALIASES,
    USER_TOGGLEABLE_TOOL_NAMES,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class ToolParameterPayload(BaseModel):
    name: str
    type: str
    description: str = ""
    required: bool = True
    default: Any = None
    enum: list[str] | None = None


class ToolAliasPayload(BaseModel):
    name: str
    description: str = ""
    input_format: str = ""
    when_to_use: str = ""
    phase: str = ""


class ToolHintsPayload(BaseModel):
    short_description: str = ""
    when_to_use: str = ""
    input_format: str = ""
    guideline: str = ""
    note: str = ""
    phase: str = ""
    aliases: list[ToolAliasPayload] = []


class BuiltinToolPayload(BaseModel):
    name: str
    description: str
    description_i18n: dict[Literal["en", "zh"], str] = {}
    parameters: list[ToolParameterPayload]
    hints: dict[Literal["en", "zh"], ToolHintsPayload]
    aliases: list[str] = []
    # True iff the user is allowed to switch this tool on/off from the
    # /settings/tools UI. Locked-on tools (auto-mounted by the chat
    # pipeline under context gates) report ``False`` and the UI renders
    # them as informational entries only.
    toggleable: bool = False
    # Whether the tool is currently on. For toggleable tools this
    # reflects the user's saved preference; for locked-on tools this is
    # always ``True``.
    enabled: bool = True
    # ``coming_soon`` tools are NOT registered with the runtime — the chat
    # agent cannot invoke them. They are listed here only so the settings
    # page can render a placeholder card explaining the capability is on
    # the roadmap. The frontend should lock the toggle and show a badge.
    coming_soon: bool = False
    # The capability that owns this tool (e.g. ``solve`` / ``mastery``), or
    # ``None`` for a plain system built-in. Owned tools are reused by their
    # capability on top of the shared built-in surface; the settings UI groups
    # them under their owner, below the built-in section.
    capability: str | None = None


class ToolsListResponse(BaseModel):
    tools: list[BuiltinToolPayload]
    enabled_optional_tools: list[str]


def _serialise_definition(
    definition: ToolDefinition,
) -> tuple[str, str, list[ToolParameterPayload]]:
    params = [
        ToolParameterPayload(
            name=p.name,
            type=p.type,
            description=p.description,
            required=p.required,
            default=p.default,
            enum=p.enum,
        )
        for p in definition.parameters
    ]
    return definition.name, definition.description, params


def _serialise_hints(hints: ToolPromptHints) -> ToolHintsPayload:
    return ToolHintsPayload(
        short_description=hints.short_description,
        when_to_use=hints.when_to_use,
        input_format=hints.input_format,
        guideline=hints.guideline,
        note=hints.note,
        phase=hints.phase,
        aliases=[
            ToolAliasPayload(
                name=alias.name,
                description=alias.description,
                input_format=alias.input_format,
                when_to_use=alias.when_to_use,
                phase=alias.phase,
            )
            for alias in hints.aliases
        ],
    )


def _collect_aliases_for(tool_name: str) -> list[str]:
    return sorted(alias for alias, (target, _) in TOOL_ALIASES.items() if target == tool_name)


def _build_tool_payload(
    tool: BaseTool,
    *,
    enabled_optional: set[str],
    coming_soon: bool = False,
    capability: str | None = None,
) -> BuiltinToolPayload:
    name, description, parameters = _serialise_definition(tool.get_definition())
    descriptions = tool_description_i18n(name, description)
    toggleable = (not coming_soon) and (name in USER_TOGGLEABLE_TOOL_NAMES)
    if coming_soon:
        enabled = False
    elif toggleable:
        enabled = name in enabled_optional
    else:
        enabled = True
    return BuiltinToolPayload(
        name=name,
        description=descriptions.get("en") or description,
        description_i18n=descriptions,
        parameters=parameters,
        hints={
            "en": _serialise_hints(tool.get_prompt_hints(language="en")),
            "zh": _serialise_hints(tool.get_prompt_hints(language="zh")),
        },
        aliases=_collect_aliases_for(name),
        toggleable=toggleable,
        enabled=enabled,
        coming_soon=coming_soon,
        capability=capability,
    )


@router.get("", response_model=ToolsListResponse)
async def list_builtin_tools() -> ToolsListResponse:
    """Return all built-in tools the chat agent can invoke, plus any
    coming-soon placeholders for the settings page."""
    from deeptutor.capabilities import capability_tool_owners

    enabled_optional = set(get_enabled_optional_tools())
    owners = capability_tool_owners()
    payloads: list[BuiltinToolPayload] = []
    for tool_type in BUILTIN_TOOL_TYPES:
        try:
            instance = tool_type()
            payloads.append(
                _build_tool_payload(
                    instance,
                    enabled_optional=enabled_optional,
                    capability=owners.get(instance.name),
                )
            )
        except Exception:
            logger.exception("Failed to serialise tool %s", tool_type.__name__)
    for tool_type in COMING_SOON_TOOL_TYPES:
        try:
            instance = tool_type()
            payloads.append(
                _build_tool_payload(
                    instance,
                    enabled_optional=enabled_optional,
                    coming_soon=True,
                )
            )
        except Exception:
            logger.exception("Failed to serialise coming-soon tool %s", tool_type.__name__)
    # Guard against the unlikely case of name collision (e.g. someone
    # accidentally registers the same tool both as built-in and coming-soon).
    seen: set[str] = set()
    deduped: list[BuiltinToolPayload] = []
    for payload in payloads:
        if payload.name in seen:
            continue
        seen.add(payload.name)
        deduped.append(payload)
    # Toggleable tools outside the user's admin grant don't exist for them:
    # hidden here so the settings page and composer match what turn_runtime
    # will actually allow.
    from deeptutor.multi_user.tool_access import allowed_optional_tools

    allowed = allowed_optional_tools()
    if allowed is not None:
        deduped = [p for p in deduped if not p.toggleable or p.name in allowed]
    return ToolsListResponse(
        tools=deduped,
        enabled_optional_tools=sorted(enabled_optional),
    )
