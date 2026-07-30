"""ScopedToolRegistry: read-through lookup plus the dispatch-time gate."""

from __future__ import annotations

import pytest

from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolResult
from deeptutor.runtime.providers.allowlist import Allowlist
from deeptutor.runtime.registry.scoped_registry import ScopedToolRegistry
from deeptutor.runtime.registry.tool_registry import ToolRegistry


class _Tool(BaseTool):
    def __init__(self, name: str, *, deferred: bool = False, provider: str = "") -> None:
        self._name = name
        self.deferred = deferred
        if provider:
            self.provider_id = provider
            self.provider_kind = "mcp"
        self.calls: list[dict[str, object]] = []

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(name=self._name, description=f"desc {self._name}")

    async def execute(self, **kwargs: object) -> ToolResult:
        self.calls.append(kwargs)
        return ToolResult(content=f"ran {self._name}")


def _base(*tools: BaseTool) -> ToolRegistry:
    reg = ToolRegistry()
    for tool in tools:
        reg.register(tool)
    return reg


def test_lookup_reads_through_to_the_base() -> None:
    rag = _Tool("rag")
    scoped = ScopedToolRegistry(base=_base(rag))
    assert scoped.get("rag") is rag
    assert scoped.get("ghost") is None


def test_overlay_tools_are_visible_without_touching_the_base() -> None:
    base = _base(_Tool("rag"))
    owned = _Tool("mcp_mynotion_search", deferred=True, provider="mynotion")
    scoped = ScopedToolRegistry(base=base, overlay=[owned])

    assert scoped.get("mcp_mynotion_search") is owned
    assert "mcp_mynotion_search" in scoped.list_tools()
    # The process registry must stay clean: another tenant's turn must not see it.
    assert base.get("mcp_mynotion_search") is None


def test_overlay_never_shadows_a_shared_tool() -> None:
    shared = _Tool("mcp_gh_search", deferred=True, provider="gh")
    impostor = _Tool("mcp_gh_search", deferred=True, provider="gh")
    scoped = ScopedToolRegistry(base=_base(shared), overlay=[impostor])
    assert scoped.get("mcp_gh_search") is shared


def test_deferred_tools_are_allowlist_filtered() -> None:
    allowed_tool = _Tool("mcp_gh_search", deferred=True, provider="gh")
    denied_tool = _Tool("mcp_secret_read", deferred=True, provider="secret")
    plain = _Tool("rag")
    scoped = ScopedToolRegistry(
        base=_base(allowed_tool, denied_tool, plain),
        allowed=Allowlist.of(["mcp_gh_search"]),
    )
    assert [t.name for t in scoped.deferred_tools()] == ["mcp_gh_search"]
    # Built-ins are governed by tool composition, not by this allowlist.
    assert "rag" in scoped.list_tools()


@pytest.mark.asyncio
async def test_execute_refuses_a_provider_tool_outside_the_allowlist() -> None:
    denied = _Tool("mcp_secret_read", deferred=True, provider="secret")
    scoped = ScopedToolRegistry(
        base=_base(denied),
        allowed=Allowlist.of([]),
        refusal_message="not available here",
    )
    result = await scoped.execute("mcp_secret_read")
    assert result.success is False
    assert result.content == "not available here"
    # The gate is before execution, not a filter on its output.
    assert denied.calls == []


@pytest.mark.asyncio
async def test_execute_refuses_an_off_list_overlay_tool() -> None:
    owned = _Tool("mcp_mynotion_search", deferred=True, provider="mynotion")
    scoped = ScopedToolRegistry(
        base=_base(),
        overlay=[owned],
        allowed=Allowlist.of(["something_else"]),
    )
    result = await scoped.execute("mcp_mynotion_search")
    assert result.success is False
    assert owned.calls == []


@pytest.mark.asyncio
async def test_execute_allows_builtins_regardless_of_the_allowlist() -> None:
    rag = _Tool("rag")
    scoped = ScopedToolRegistry(base=_base(rag), allowed=Allowlist.of([]))
    result = await scoped.execute("rag", query="hi")
    assert result.content == "ran rag"
    assert rag.calls == [{"query": "hi"}]


@pytest.mark.asyncio
async def test_execute_runs_an_authorised_overlay_tool() -> None:
    owned = _Tool("mcp_mynotion_search", deferred=True, provider="mynotion")
    scoped = ScopedToolRegistry(
        base=_base(),
        overlay=[owned],
        allowed=Allowlist.of(["mcp_mynotion_search"]),
    )
    result = await scoped.execute("mcp_mynotion_search", query="q")
    assert result.content == "ran mcp_mynotion_search"


@pytest.mark.asyncio
async def test_execute_preserves_base_alias_resolution() -> None:
    rag = _Tool("rag")
    scoped = ScopedToolRegistry(base=_base(rag))
    # ``rag_hybrid`` is a registered alias that injects mode="hybrid".
    result = await scoped.execute("rag_hybrid", query="q")
    assert result.content == "ran rag"
    assert rag.calls == [{"mode": "hybrid", "query": "q"}]


def test_build_prompt_text_covers_overlay_tools() -> None:
    """A loaded per-user tool must still reach the prompt's tool list.

    The chat pipeline appends already-loaded deferred names to the manifest
    request, so delegating this to the base registry would silently drop them.
    """
    owned = _Tool("mcp_mynotion_search", deferred=True, provider="mynotion")
    scoped = ScopedToolRegistry(base=_base(_Tool("rag")), overlay=[owned])
    text = scoped.build_prompt_text(["rag", "mcp_mynotion_search"])
    assert "mcp_mynotion_search" in text
    assert "rag" in text


def test_openai_schemas_come_from_the_merged_view() -> None:
    owned = _Tool("mcp_mynotion_search", deferred=True, provider="mynotion")
    scoped = ScopedToolRegistry(base=_base(_Tool("rag")), overlay=[owned])
    names = {
        s["function"]["name"] for s in scoped.build_openai_schemas(["rag", "mcp_mynotion_search"])
    }
    assert names == {"rag", "mcp_mynotion_search"}
