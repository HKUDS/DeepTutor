"""
Tool Registry
=============

Central registry that discovers and manages all tools (built-in and plugin).
Provides lookup, listing, and OpenAI schema generation.
"""

from __future__ import annotations

import logging
from typing import Any

from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolPromptHints
from deeptutor.tools.builtin import BUILTIN_TOOL_TYPES, TOOL_ALIASES
from deeptutor.tools.prompting import ToolPromptComposer

logger = logging.getLogger(__name__)


class ToolRegistry:
    """
    Singleton-ish registry of all available tools.

    Usage::

        registry = ToolRegistry()
        registry.load_builtins()
        rag = registry.get("rag")
        result = await rag.execute(query="hello")
    """

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        name = tool.name
        self._tools[name] = tool
        logger.debug("Registered tool: %s", name)

    def unregister(self, name: str) -> None:
        """Remove a tool (no-op when absent). Used by MCP reloads."""
        self._tools.pop(name, None)

    def deferred_tools(self) -> list[BaseTool]:
        """Tools flagged for progressive disclosure (see ``BaseTool.deferred``)."""
        return [t for t in self._tools.values() if getattr(t, "deferred", False)]

    def load_builtins(self) -> None:
        """Instantiate and register all built-in tools."""
        for tool_type in BUILTIN_TOOL_TYPES:
            try:
                tool = tool_type()
            except Exception:
                logger.warning("Failed to instantiate built-in tool %s", tool_type, exc_info=True)
                continue
            if tool.name in self._tools:
                continue
            self.register(tool)

    def _resolve_request(
        self,
        name: str,
        kwargs: dict[str, Any] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        if name in self._tools:
            return name, dict(kwargs or {})

        resolved_name, default_kwargs = TOOL_ALIASES.get(name, (name, {}))
        merged_kwargs = {**default_kwargs, **(kwargs or {})}

        return resolved_name, merged_kwargs

    def get(self, name: str) -> BaseTool | None:
        resolved_name, _ = self._resolve_request(name)
        return self._tools.get(resolved_name)

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())

    def get_enabled(self, names: list[str]) -> list[BaseTool]:
        """Return tool instances for the given names (skipping unknown)."""
        enabled: list[BaseTool] = []
        seen: set[str] = set()
        for name in names:
            tool = self.get(name)
            if tool is None or tool.name in seen:
                continue
            enabled.append(tool)
            seen.add(tool.name)
        return enabled

    def get_definitions(self, names: list[str] | None = None) -> list[ToolDefinition]:
        """Return definitions for *names* (or all if None)."""
        tools = self._tools.values() if names is None else self.get_enabled(names)
        return [t.get_definition() for t in tools]

    def get_prompt_hints(
        self,
        names: list[str],
        language: str = "en",
    ) -> list[tuple[str, ToolPromptHints]]:
        """Return prompt hints for the given tool names."""
        entries: list[tuple[str, ToolPromptHints]] = []
        for tool in self.get_enabled(names):
            entries.append((tool.name, tool.get_prompt_hints(language=language)))
        return entries

    def build_prompt_text(
        self,
        names: list[str],
        format: str = "list",
        language: str = "en",
        **opts: Any,
    ) -> str:
        """Compose prompt text for the given tools."""
        composer = ToolPromptComposer(language=language)
        hints = self.get_prompt_hints(names, language=language)
        if format == "list":
            return composer.format_list(hints)
        if format == "list_with_usage":
            return composer.format_list_with_usage(hints)
        if format == "table":
            return composer.format_table(
                hints,
                control_actions=opts.get("control_actions"),
            )
        if format == "aliases":
            return composer.format_aliases(hints)
        if format == "phased":
            return composer.format_phased(hints)
        raise ValueError(f"Unsupported prompt format: {format}")

    def build_openai_schemas(self, names: list[str] | None = None) -> list[dict[str, Any]]:
        """Build OpenAI function-calling tool schemas."""
        return [d.to_openai_schema() for d in self.get_definitions(names)]

    async def execute(self, name: str, /, **kwargs: Any):
        """Resolve aliases, execute the tool, and return its ToolResult.

        ``name`` (the tool to run) is positional-only so it never collides
        with a tool argument that happens to also be called ``name`` — e.g.
        ``read_skill(name=...)`` or an MCP tool whose schema declares a
        ``name`` parameter. All callers already pass the tool name
        positionally.
        """
        resolved_name, resolved_kwargs = self._resolve_request(name, kwargs)
        tool = self._tools.get(resolved_name)
        if tool is None:
            raise KeyError(f"Unknown tool: {name}")
        return await tool.execute(**resolved_kwargs)


_default_registry: ToolRegistry | None = None


def get_tool_registry() -> ToolRegistry:
    """Return the global ToolRegistry (creating & loading builtins on first call)."""
    global _default_registry
    if _default_registry is None:
        _default_registry = ToolRegistry()
        _default_registry.load_builtins()
    return _default_registry
