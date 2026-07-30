"""build_tool_view: what a turn actually ends up with, end to end."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolResult
from deeptutor.runtime.providers.scope import ToolScope
from deeptutor.runtime.providers.view import build_tool_view
from deeptutor.runtime.registry.scoped_registry import ScopedToolRegistry
from deeptutor.runtime.registry.tool_registry import ToolRegistry

PAGEINDEX = "pageindex"


class _McpTool(BaseTool):
    deferred = True

    def __init__(self, name: str, provider: str) -> None:
        self._name = name
        self.provider_id = provider
        self.provider_kind = "mcp"

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self._name,
            description=f"desc {self._name}",
            raw_parameters={"type": "object", "properties": {}},
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(content="ok")


class _FakeManager:
    def __init__(self) -> None:
        self.started = 0
        self.scopes: dict[str, list[_McpTool]] = {}
        self.scope_calls: list[str] = []
        self.scope_delay = 0.0

    async def ensure_started(self) -> None:
        self.started += 1

    async def ensure_scope(self, owner: str) -> list[_McpTool]:
        self.scope_calls.append(owner)
        if self.scope_delay:
            await asyncio.sleep(self.scope_delay)
        return self.scopes.get(owner, [])


@pytest.fixture
def registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(_McpTool("mcp_gh_search", "gh"))
    reg.register(_McpTool("mcp_pageindex_search", PAGEINDEX))
    return reg


@pytest.fixture(autouse=True)
def _stub_providers(monkeypatch) -> _FakeManager:
    manager = _FakeManager()
    monkeypatch.setattr("deeptutor.services.mcp.get_mcp_manager", lambda: manager)
    monkeypatch.setattr("deeptutor.services.mcp.load_loaded_tools", lambda session_id: set())
    monkeypatch.setattr("deeptutor.multi_user.tool_access.allowed_mcp_tools", lambda: None)
    return manager


def _grant(monkeypatch, value: set[str] | None) -> None:
    monkeypatch.setattr("deeptutor.multi_user.tool_access.allowed_mcp_tools", lambda: value)


@pytest.mark.asyncio
async def test_empty_pool_yields_an_empty_view() -> None:
    view = await build_tool_view(base_registry=ToolRegistry(), scope=ToolScope(session_id="s"))
    assert view.loader is None
    assert view.pool == ()
    assert view.manifest == ""


@pytest.mark.asyncio
async def test_admin_sees_every_provider_tool(registry, monkeypatch) -> None:
    _grant(monkeypatch, None)
    view = await build_tool_view(base_registry=registry, scope=ToolScope(session_id="s"))
    assert {t.name for t in view.pool} == {"mcp_gh_search", "mcp_pageindex_search"}
    assert view.loader is not None
    assert "MCP server: gh" in view.manifest


@pytest.mark.asyncio
async def test_ungranted_user_gets_no_tools_but_keeps_the_gate(registry, monkeypatch) -> None:
    _grant(monkeypatch, set())
    view = await build_tool_view(base_registry=registry, scope=ToolScope(session_id="s"))
    assert view.pool == ()
    assert view.loader is None
    assert view.manifest == ""
    # Still a scoped view: dispatch must refuse a name the model invents.
    assert isinstance(view.registry, ScopedToolRegistry)
    result = await view.registry.execute("mcp_gh_search")
    assert result.success is False


@pytest.mark.asyncio
async def test_attached_pageindex_kb_authorises_and_preloads_that_server(
    registry, monkeypatch
) -> None:
    _grant(monkeypatch, set())
    view = await build_tool_view(
        base_registry=registry,
        scope=ToolScope(session_id="s", implicit_provider_ids=frozenset({PAGEINDEX})),
    )
    assert {t.name for t in view.pool} == {"mcp_pageindex_search"}
    assert view.loader is not None
    # Preloaded: holding the KB is the permission, so no load_tools round-trip.
    assert view.loader.loaded_names == {"mcp_pageindex_search"}


@pytest.mark.asyncio
async def test_exclusive_capability_suppresses_the_manifest_but_keeps_preloads(
    registry, monkeypatch
) -> None:
    _grant(monkeypatch, None)
    view = await build_tool_view(
        base_registry=registry,
        scope=ToolScope(
            session_id="s",
            implicit_provider_ids=frozenset({PAGEINDEX}),
            exclusive_capability=True,
        ),
    )
    # Nothing is advertised (load_tools is not even mounted on such a turn) …
    assert view.manifest == ""
    # … but the resource-authorised tool is still usable.
    assert {t.name for t in view.pool} == {"mcp_pageindex_search"}
    assert view.loader is not None
    assert view.loader.loaded_names == {"mcp_pageindex_search"}


@pytest.mark.asyncio
async def test_partner_uses_its_own_filter(registry, monkeypatch) -> None:
    _grant(monkeypatch, set())  # would deny everything if it were consulted
    view = await build_tool_view(
        base_registry=registry,
        scope=ToolScope(
            session_id="s",
            is_partner=True,
            caller_whitelist=frozenset({"mcp_gh_search"}),
        ),
    )
    assert {t.name for t in view.pool} == {"mcp_gh_search"}


@pytest.mark.asyncio
async def test_a_failing_provider_degrades_instead_of_killing_the_turn(
    registry, monkeypatch
) -> None:
    def _boom() -> Any:
        raise RuntimeError("mcp is down")

    monkeypatch.setattr("deeptutor.services.mcp.get_mcp_manager", _boom)
    view = await build_tool_view(base_registry=registry, scope=ToolScope(session_id="s"))
    assert view.loader is None
    assert view.pool == ()
    assert view.registry is registry


@pytest.mark.asyncio
async def test_attach_adds_loaded_schemas_and_binds_the_live_list(registry, monkeypatch) -> None:
    _grant(monkeypatch, None)
    monkeypatch.setattr(
        "deeptutor.services.mcp.load_loaded_tools", lambda session_id: {"mcp_gh_search"}
    )
    view = await build_tool_view(base_registry=registry, scope=ToolScope(session_id="s"))
    live: list[dict[str, Any]] = []
    view.attach(live)
    assert [s["function"]["name"] for s in live] == ["mcp_gh_search"]

    # Bound: a later load_tools call reaches the same list the loop re-reads.
    assert view.loader is not None
    view.loader.load(["mcp_pageindex_search"])
    assert [s["function"]["name"] for s in live] == ["mcp_gh_search", "mcp_pageindex_search"]


@pytest.mark.asyncio
async def test_attach_is_a_no_op_without_a_loader() -> None:
    view = await build_tool_view(base_registry=ToolRegistry(), scope=ToolScope(session_id="s"))
    live: list[dict[str, Any]] = []
    view.attach(live)
    assert live == []


@pytest.mark.asyncio
async def test_self_configured_servers_are_usable_without_an_admin_grant(
    registry, monkeypatch, _stub_providers
) -> None:
    """The headline of self-service: your own server works for you.

    ``grant.mcp_tools`` is deny-by-default, so routing an account's own server
    through it would make configuring one silently pointless.
    """
    _grant(monkeypatch, set())
    owned = _McpTool("mcp_mynotion_search", "mynotion")
    _stub_providers.scopes["u_ada"] = [owned]

    view = await build_tool_view(
        base_registry=registry,
        scope=ToolScope(owner_id="u_ada", session_id="s"),
    )

    assert {t.name for t in view.pool} == {"mcp_mynotion_search"}
    # Deployment servers stay denied — ownership authorises only what it owns.
    assert not any(t.name == "mcp_gh_search" for t in view.pool)


@pytest.mark.asyncio
async def test_owned_tools_live_in_the_overlay_not_the_process_registry(
    registry, monkeypatch, _stub_providers
) -> None:
    """Two accounts may legitimately name a server the same thing.

    The process registry is keyed by tool name and last-writer-wins, so a
    per-user tool published there would resolve one account's call into
    another's session.
    """
    _grant(monkeypatch, set())
    owned = _McpTool("mcp_mynotion_search", "mynotion")
    _stub_providers.scopes["u_ada"] = [owned]

    view = await build_tool_view(
        base_registry=registry,
        scope=ToolScope(owner_id="u_ada", session_id="s"),
    )

    assert view.registry.get("mcp_mynotion_search") is owned
    assert registry.get("mcp_mynotion_search") is None


@pytest.mark.asyncio
async def test_a_partner_does_not_inherit_its_owners_own_servers(
    registry, monkeypatch, _stub_providers
) -> None:
    """A self-configured server carries the owner's personal API key.

    An IM-facing companion must not spend it; its surface is the deployment's,
    filtered by the whitelist its owner set for it.
    """
    _grant(monkeypatch, set())
    _stub_providers.scopes["owner"] = [_McpTool("mcp_mynotion_search", "mynotion")]

    view = await build_tool_view(
        base_registry=registry,
        scope=ToolScope(
            owner_id="owner",
            is_partner=True,
            caller_whitelist=frozenset({"mcp_gh_search"}),
            session_id="s",
        ),
    )

    assert {t.name for t in view.pool} == {"mcp_gh_search"}
    assert _stub_providers.scope_calls == []


@pytest.mark.asyncio
async def test_a_slow_personal_server_costs_only_its_own_tools(
    registry, monkeypatch, _stub_providers
) -> None:
    """This runs before the turn's first stream event.

    A third-party host that hangs must not present to the user as DeepTutor
    hanging, so the scope connect is bounded and the turn proceeds without it.
    """
    from deeptutor.runtime.providers import view as view_module

    monkeypatch.setattr(view_module, "_OWNER_SCOPE_TIMEOUT_S", 0.01)
    _grant(monkeypatch, None)
    _stub_providers.scope_delay = 1.0
    _stub_providers.scopes["u_ada"] = [_McpTool("mcp_slow_thing", "slow")]

    view = await build_tool_view(
        base_registry=registry,
        scope=ToolScope(owner_id="u_ada", session_id="s"),
    )

    assert not any(t.name == "mcp_slow_thing" for t in view.pool)
    # The deployment's tools still made it — the turn is not degraded further.
    assert {t.name for t in view.pool} == {"mcp_gh_search", "mcp_pageindex_search"}
