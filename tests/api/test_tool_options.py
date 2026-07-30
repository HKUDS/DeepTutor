"""Contract tests for the configurable-tool surface (``build_tool_options``).

The ``mcp_tools`` rows are what the partner tool picker and the admin grant
editor fold into one checkbox per service, so the provider identity fields are
a UI contract: ``kind`` + ``provider_id`` are the grouping key, ``server`` is
the legacy spelling that must keep working for clients built before them.
"""

from __future__ import annotations

from typing import Any

import pytest

from deeptutor.api.utils import tool_options as tool_options_mod
from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolResult
from deeptutor.runtime.registry import tool_registry as tool_registry_mod
from deeptutor.services import mcp as mcp_mod


class _FakeTool(BaseTool):
    """Minimal deferred tool; subclasses vary only the provider identity."""

    deferred = True

    def __init__(self, name: str) -> None:
        self._name = name

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(name=self._name, description=f"does {self._name}")

    async def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(content="")


class _McpTool(_FakeTool):
    provider_kind = "mcp"

    def __init__(self, name: str, provider_id: str) -> None:
        super().__init__(name)
        self._provider_id = provider_id

    @property
    def provider_id(self) -> str:
        return self._provider_id


class _LegacyTool(_FakeTool):
    """An adapter that predates ``provider_kind`` / ``provider_id``."""

    def __init__(self, name: str, server_name: str) -> None:
        super().__init__(name)
        self._server_name = server_name

    @property
    def server_name(self) -> str:
        return self._server_name


class _CliTool(_FakeTool):
    provider_kind = "cli"

    def __init__(self, name: str, provider_id: str) -> None:
        super().__init__(name)
        self._provider_id = provider_id

    @property
    def provider_id(self) -> str:
        return self._provider_id


class _BrokenTool(_FakeTool):
    provider_kind = "mcp"
    provider_id = "broken"

    def get_definition(self) -> ToolDefinition:
        raise RuntimeError("server went away mid-listing")


class _StubRegistry:
    def __init__(self, deferred: list[BaseTool]) -> None:
        self._deferred = deferred

    def get(self, name: str) -> BaseTool | None:
        return None

    def deferred_tools(self) -> list[BaseTool]:
        return list(self._deferred)


@pytest.fixture
def stub_registry(monkeypatch: pytest.MonkeyPatch):
    """Install a deferred-tool registry and neutralise MCP startup."""

    def _install(tools: list[BaseTool]) -> None:
        monkeypatch.setattr(tool_registry_mod, "get_tool_registry", lambda: _StubRegistry(tools))

    class _Manager:
        async def ensure_started(self) -> None:
            return None

    monkeypatch.setattr(mcp_mod, "get_mcp_manager", lambda: _Manager())
    return _install


@pytest.mark.asyncio
async def test_mcp_rows_carry_provider_identity(stub_registry) -> None:
    stub_registry(
        [
            _McpTool("mcp_notion_search", "notion"),
            _McpTool("mcp_notion_create_page", "notion"),
            _LegacyTool("mcp_github_list_issues", "github"),
            _CliTool("cli_claude", "claude"),
        ]
    )

    rows = (await tool_options_mod.build_tool_options())["mcp_tools"]
    by_name = {row["name"]: row for row in rows}

    assert by_name["mcp_notion_search"]["kind"] == "mcp"
    assert by_name["mcp_notion_search"]["provider_id"] == "notion"
    # Both Notion tools group under one provider — the whole point of the key.
    assert by_name["mcp_notion_create_page"]["provider_id"] == "notion"
    # A pre-provider adapter still groups by its server name, tagged as MCP
    # (every adapter written before ``provider_kind`` existed is an MCP one).
    assert by_name["mcp_github_list_issues"]["kind"] == "mcp"
    assert by_name["mcp_github_list_issues"]["provider_id"] == "github"
    # A CLI provider must NOT be offered in this list: it is written into
    # ``grant.mcp_tools``, and authorisation for CLI apps is a separate grant
    # field on purpose — an MCP whitelist must never be what unlocks a host
    # binary. CLI providers get their own list when they land.
    assert "cli_claude" not in by_name


@pytest.mark.asyncio
async def test_mcp_rows_keep_legacy_server_field(stub_registry) -> None:
    """``server`` is still populated so clients that read it keep grouping."""
    stub_registry(
        [
            _McpTool("mcp_notion_search", "notion"),
            _LegacyTool("mcp_github_list_issues", "github"),
        ]
    )

    rows = (await tool_options_mod.build_tool_options())["mcp_tools"]

    for row in rows:
        assert row["server"] == row["provider_id"], row["name"]
    assert {row["server"] for row in rows} == {"notion", "github"}


@pytest.mark.asyncio
async def test_unreadable_tool_is_skipped(stub_registry) -> None:
    """A server that fails mid-listing must not blank out the whole surface."""
    stub_registry([_BrokenTool("mcp_broken_thing"), _McpTool("mcp_notion_search", "notion")])

    payload = await tool_options_mod.build_tool_options()

    assert [row["name"] for row in payload["mcp_tools"]] == ["mcp_notion_search"]
    # The non-MCP halves of the surface are unaffected.
    assert isinstance(payload["tools"], list)
    assert isinstance(payload["builtin_tools"], list)
