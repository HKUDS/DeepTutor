"""A per-turn view over the process tool registry.

Two things the process-global :class:`~deeptutor.runtime.registry.tool_registry.ToolRegistry`
cannot express, both of which a user-facing external-tool store needs:

* **Tools that belong to one user.** ``register()`` is a last-writer-wins dict
  keyed by tool name, so two tenants whose MCP servers happen to share a name
  would clobber each other — and ``unregister()`` would evict the survivor.
  Owner-scoped tools therefore never enter the process registry; they live in
  this view's *overlay*, which exists only for the turn that built it.
* **Authorisation at dispatch time.** The tool dispatcher executes whatever
  name the model produced (``tool_dispatch.py``), and a text-protocol fallback
  can synthesise a name that was never offered. Filtering the *manifest* is
  therefore not a gate. This view refuses an unauthorised provider tool at
  ``execute``, which is the one place every call path goes through.

Built-in tools are untouched by the allowlist: which built-ins mount is
already decided per turn by ``tool_composition``. The allowlist here governs
only *provider* (deferred) tools.
"""

from __future__ import annotations

from collections.abc import Iterable
import logging
from typing import Any

from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolLookup, ToolResult
from deeptutor.runtime.providers.allowlist import Allowlist
from deeptutor.tools.prompting import compose_prompt_text

logger = logging.getLogger(__name__)

_DEFAULT_REFUSAL = (
    "This tool is not available in this conversation. Only the tools listed in "
    "the prompt can be called."
)


class ScopedToolRegistry:
    """Read-through view: *overlay* first, then the shared process registry.

    Satisfies :class:`~deeptutor.core.tool_protocol.ToolLookup`. Intentionally
    has no ``register`` / ``unregister``: tool lifetime stays owned by the
    process registry and by whoever built the overlay.
    """

    def __init__(
        self,
        *,
        base: ToolLookup,
        overlay: Iterable[BaseTool] = (),
        allowed: Allowlist | None = None,
        refusal_message: str = "",
    ) -> None:
        self._base = base
        self._allowed = allowed or Allowlist.unrestricted()
        self._refusal_message = refusal_message or _DEFAULT_REFUSAL
        self._overlay: dict[str, BaseTool] = {}
        for tool in overlay:
            name = tool.name
            if self._base.get(name) is not None:
                # Two tenants must never resolve one name. The write paths
                # refuse colliding server names, so reaching here means a
                # guard upstream is missing — drop the overlay entry rather
                # than shadow a shared tool with a user-owned one.
                logger.error(
                    "scoped registry: overlay tool %r collides with a shared tool; dropping it",
                    name,
                )
                continue
            self._overlay[name] = tool

    # ── lookup ─────────────────────────────────────────────────────────

    def get(self, name: str) -> BaseTool | None:
        tool = self._overlay.get(name)
        if tool is not None:
            return tool
        return self._base.get(name)

    def get_enabled(self, names: list[str]) -> list[BaseTool]:
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
        tools = self._visible_tools() if names is None else self.get_enabled(names)
        return [t.get_definition() for t in tools]

    def deferred_tools(self) -> list[BaseTool]:
        """Provider tools this turn may see (already allowlist-filtered)."""
        return [t for t in self._visible_tools() if getattr(t, "deferred", False)]

    def list_tools(self) -> list[str]:
        return [t.name for t in self._visible_tools()]

    def build_openai_schemas(self, names: list[str] | None = None) -> list[dict[str, Any]]:
        return [d.to_openai_schema() for d in self.get_definitions(names)]

    def get_prompt_hints(self, names: list[str], language: str = "en") -> list[tuple[str, Any]]:
        return [
            (tool.name, tool.get_prompt_hints(language=language))
            for tool in self.get_enabled(names)
        ]

    def build_prompt_text(
        self,
        names: list[str],
        format: str = "list",
        language: str = "en",
        **opts: Any,
    ) -> str:
        return compose_prompt_text(
            self.get_prompt_hints(names, language=language),
            format=format,
            language=language,
            **opts,
        )

    # ── execution ──────────────────────────────────────────────────────

    async def execute(self, name: str, /, **kwargs: Any) -> Any:
        """Execute *name*, refusing provider tools outside the allowlist.

        ``name`` is positional-only to match the process registry: a tool's
        own schema may declare a ``name`` parameter.
        """
        overlay_tool = self._overlay.get(name)
        if overlay_tool is not None:
            if not self._allowed.allows(overlay_tool.name):
                return self._refuse(overlay_tool.name)
            return await overlay_tool.execute(**kwargs)

        # Shared path: resolve through the base registry so tool aliases keep
        # working, but gate provider tools before anything runs.
        base_tool = self._base.get(name)
        if (
            base_tool is not None
            and getattr(base_tool, "deferred", False)
            and not self._allowed.allows(base_tool.name)
        ):
            return self._refuse(base_tool.name)
        return await self._base.execute(name, **kwargs)

    def _refuse(self, name: str) -> ToolResult:
        logger.info("scoped registry refused unauthorised provider tool %r", name)
        return ToolResult(content=self._refusal_message, success=False)

    # ── internals ──────────────────────────────────────────────────────

    def _visible_tools(self) -> list[BaseTool]:
        """Shared tools plus the overlay, minus disallowed provider tools."""
        out: list[BaseTool] = []
        seen: set[str] = set()
        for candidate in (
            *(self._base.get(name) for name in self._base.list_tools()),
            *self._overlay.values(),
        ):
            if candidate is None or candidate.name in seen:
                continue
            if getattr(candidate, "deferred", False) and not self._allowed.allows(candidate.name):
                continue
            out.append(candidate)
            seen.add(candidate.name)
        return out


__all__ = ["ScopedToolRegistry"]
