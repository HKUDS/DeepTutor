"""Deferred tool loading: manifest rendering + DeferredToolLoader behaviour."""

from __future__ import annotations

import pytest

from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolResult
from deeptutor.runtime.registry.deferred_tools import (
    DeferredToolLoader,
    render_deferred_tools_manifest,
)
from deeptutor.runtime.registry.tool_registry import ToolRegistry


class _FakeDeferredTool(BaseTool):
    deferred = True

    def __init__(self, name: str, server: str = "") -> None:
        self._name = name
        if server:
            self.server_name = server

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self._name,
            description=f"desc for {self._name}",
            raw_parameters={"type": "object", "properties": {}},
        )

    async def execute(self, **kwargs: object) -> ToolResult:
        return ToolResult(content="ok")


@pytest.fixture(autouse=True)
def _no_persist(monkeypatch):
    """Stop DeferredToolLoader persistence from touching disk."""
    monkeypatch.setattr(
        "deeptutor.services.mcp.session_state.record_loaded_tools",
        lambda session_id, names: None,
    )


def _registry(*tools: BaseTool) -> ToolRegistry:
    reg = ToolRegistry()
    for t in tools:
        reg.register(t)
    return reg


def test_manifest_groups_by_server() -> None:
    tools = [
        _FakeDeferredTool("mcp_gh_search", server="gh"),
        _FakeDeferredTool("mcp_gh_create", server="gh"),
        _FakeDeferredTool("mcp_fs_read", server="fs"),
    ]
    manifest = render_deferred_tools_manifest(tools)
    assert "MCP server: gh" in manifest
    assert "MCP server: fs" in manifest
    assert "mcp_gh_search" in manifest
    assert "load_tools" in manifest


def test_manifest_empty() -> None:
    assert render_deferred_tools_manifest([]) == ""


def test_loader_appends_to_live_schemas() -> None:
    tool = _FakeDeferredTool("mcp_gh_search", server="gh")
    reg = _registry(tool)
    loader = DeferredToolLoader(registry=reg, session_id="s1", loaded=set())
    live: list[dict] = []
    loader.bind_live_schemas(live)

    outcome = loader.load(["mcp_gh_search"])
    assert outcome["loaded"] == ["mcp_gh_search"]
    assert len(live) == 1
    assert live[0]["function"]["name"] == "mcp_gh_search"

    # second load is a no-op (already loaded)
    outcome2 = loader.load(["mcp_gh_search"])
    assert outcome2["already_loaded"] == ["mcp_gh_search"]
    assert len(live) == 1


def test_loader_rejects_unknown_and_non_deferred() -> None:
    class _Regular(BaseTool):
        def get_definition(self) -> ToolDefinition:
            return ToolDefinition(name="regular", description="d")

        async def execute(self, **kwargs: object) -> ToolResult:
            return ToolResult(content="ok")

    reg = _registry(_Regular())
    loader = DeferredToolLoader(registry=reg, session_id="s1", loaded=set())
    loader.bind_live_schemas([])
    outcome = loader.load(["regular", "ghost"])
    assert set(outcome["unknown"]) == {"regular", "ghost"}
    assert outcome["loaded"] == []


def test_loader_initial_schemas_drops_stale() -> None:
    tool = _FakeDeferredTool("mcp_gh_search", server="gh")
    reg = _registry(tool)
    # session previously loaded one tool that still exists and one that's gone
    loader = DeferredToolLoader(
        registry=reg,
        session_id="s1",
        loaded={"mcp_gh_search", "mcp_gone_tool"},
    )
    schemas = loader.initial_schemas()
    names = {s["function"]["name"] for s in schemas}
    assert names == {"mcp_gh_search"}
    assert "mcp_gone_tool" not in loader.loaded_names


def test_registry_deferred_tools_filter() -> None:
    class _Regular(BaseTool):
        def get_definition(self) -> ToolDefinition:
            return ToolDefinition(name="regular", description="d")

        async def execute(self, **kwargs: object) -> ToolResult:
            return ToolResult(content="ok")

    reg = _registry(_FakeDeferredTool("mcp_a"), _Regular())
    deferred = reg.deferred_tools()
    assert [t.name for t in deferred] == ["mcp_a"]
    reg.unregister("mcp_a")
    assert reg.deferred_tools() == []
