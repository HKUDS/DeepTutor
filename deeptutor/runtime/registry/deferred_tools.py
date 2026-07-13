"""
Deferred tool loading (progressive disclosure for tool schemas).

Tools flagged ``BaseTool.deferred`` (all MCP tools, by default) are NOT part
of the initial per-turn tool list. The system prompt carries a one-line
manifest per deferred tool (:func:`render_deferred_tools_manifest`); when the
model decides it needs one, it calls the ``load_tools`` builtin with exact
names and the :class:`DeferredToolLoader` appends the full schemas to the
live ``tool_schemas`` list — ``run_agentic_loop`` re-reads that list every
iteration, so the tools become callable immediately. Loaded names persist
per chat session so later turns include those schemas from the start.

This keeps the always-on schema surface small, which measurably improves
tool selection on weaker models, while keeping every connected tool one
cheap call away.
"""

from __future__ import annotations

import logging
from typing import Any

from deeptutor.core.tool_protocol import BaseTool
from deeptutor.runtime.registry.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)


def render_deferred_tools_manifest(tools: list[BaseTool], *, language: str = "en") -> str:
    """System-prompt block listing deferred tools, grouped by MCP server."""
    if not tools:
        return ""
    zh = (language or "en").lower().startswith("zh")
    groups: dict[str, list[tuple[str, str]]] = {}
    for tool in tools:
        definition = tool.get_definition()
        group = getattr(tool, "server_name", "") or "other"
        groups.setdefault(group, []).append((definition.name, definition.description))
    if zh:
        lines: list[str] = [
            "## 扩展工具",
            "这些工具存在，但尚未加载；直接调用会失败。要使用其中任意工具，"
            "请先用准确的工具名称调用 `load_tools`，随后这些 schema 会在本会话中保持可用。",
            "",
        ]
    else:
        lines = [
            "## Extended Tools",
            "These tools exist but are NOT loaded yet; calling one directly "
            "will fail. To use any of them, first call `load_tools` with the "
            "exact tool names; their schemas then stay available for the rest "
            "of the session.",
            "",
        ]
    for group in sorted(groups):
        if group == "other":
            header = "### 其他" if zh else "### Other"
        else:
            header = f"### MCP 服务器：{group}" if zh else f"### MCP server: {group}"
        lines.append(header)
        for name, description in sorted(groups[group]):
            lines.append(f"- **{name}** - {description}")
        lines.append("")
    return "\n".join(lines).rstrip()


class DeferredToolLoader:
    """Per-turn handle that loads deferred tool schemas into the live list.

    Created by the chat pipeline once per turn and injected into
    ``load_tools`` calls server-side (the LLM never sees the handle).
    """

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        session_id: str,
        loaded: set[str],
        allowed: set[str] | None = None,
    ) -> None:
        self._registry = registry
        self._session_id = session_id
        self._loaded = set(loaded)
        # ``None`` = every deferred tool is loadable; a set restricts the
        # loadable pool (e.g. a partner's configured MCP tool whitelist).
        # Enforced here, not only at manifest time, so the model cannot load
        # an off-list tool by guessing its name.
        self._allowed = set(allowed) if allowed is not None else None
        self._live_schemas: list[dict[str, Any]] | None = None

    def _is_allowed(self, name: str) -> bool:
        return self._allowed is None or name in self._allowed

    @property
    def loaded_names(self) -> set[str]:
        return set(self._loaded)

    def bind_live_schemas(self, schemas: list[dict[str, Any]]) -> None:
        """Attach the turn's live ``tool_schemas`` list (mutated in place)."""
        self._live_schemas = schemas

    def initial_schemas(self) -> list[dict[str, Any]]:
        """Schemas for tools already loaded in this session (manifest-validated)."""
        schemas: list[dict[str, Any]] = []
        stale: set[str] = set()
        for name in sorted(self._loaded):
            tool = self._registry.get(name)
            if tool is None or not getattr(tool, "deferred", False):
                stale.add(name)
                continue
            if not self._is_allowed(name):
                continue
            schemas.append(tool.get_definition().to_openai_schema())
        if stale:
            # Server removed/renamed since last turn — drop quietly.
            self._loaded -= stale
            self._persist()
        return schemas

    def load(self, names: list[str]) -> dict[str, list[str]]:
        """Load the given deferred tools; returns name lists by outcome."""
        loaded: list[str] = []
        already: list[str] = []
        unknown: list[str] = []
        for raw in names:
            name = str(raw or "").strip()
            if not name:
                continue
            if name in self._loaded:
                already.append(name)
                continue
            tool = self._registry.get(name)
            if tool is None or not getattr(tool, "deferred", False) or not self._is_allowed(name):
                unknown.append(name)
                continue
            if self._live_schemas is not None:
                self._live_schemas.append(tool.get_definition().to_openai_schema())
            self._loaded.add(name)
            loaded.append(name)
        if loaded:
            self._persist()
        return {"loaded": loaded, "already_loaded": already, "unknown": unknown}

    def _persist(self) -> None:
        try:
            from deeptutor.services.mcp.session_state import record_loaded_tools

            record_loaded_tools(self._session_id, self._loaded)
        except Exception:
            logger.warning("failed to persist deferred-tool state", exc_info=True)


__all__ = ["DeferredToolLoader", "render_deferred_tools_manifest"]
