"""Owner-scoped MCP connections: routing, containment, and bounds.

Connections are keyed ``(owner, server_name)`` because two accounts may
legitimately name a server the same thing. If a tool call resolved by name
alone it would reach whichever session happened to be registered under it —
executing against another person's account with their credentials. That is the
property most of this file exists to pin.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from deeptutor.runtime.registry.tool_registry import ToolRegistry
from deeptutor.services.mcp.config import MCPServerConfig
from deeptutor.services.mcp.manager import (
    SHARED_OWNER,
    MCPConnectionManager,
    MCPToolAdapter,
)


class _FakeSession:
    """Records which (owner, server) it belongs to so routing is observable."""

    def __init__(self, owner: str, server: str) -> None:
        self.owner = owner
        self.server = server
        #: What the manager asked for. Kept so a test can assert that progress is
        #: requested only when there is a sub-trace to publish it into.
        self.progress_callback: object = "unset"

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, object],
        progress_callback: object = None,
    ):
        from mcp import types

        self.progress_callback = progress_callback
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=f"{self.owner}/{self.server}/{tool_name}")]
        )


@pytest.fixture
def manager(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> MCPConnectionManager:
    """A manager whose connections come up instantly with one fake tool each."""
    from deeptutor.multi_user import paths

    admin_root = (tmp_path / "data").resolve()
    monkeypatch.setattr(paths, "ADMIN_WORKSPACE_ROOT", admin_root)
    monkeypatch.setattr(paths, "USERS_ROOT", admin_root / "users")
    monkeypatch.setattr(paths, "SYSTEM_ROOT", admin_root / "system")

    # An isolated registry: the assertion that owner tools stay OUT of the
    # process registry is meaningless against a shared global one.
    registry = ToolRegistry()
    monkeypatch.setattr(MCPConnectionManager, "_registry", staticmethod(lambda: registry))

    connect_delay = {"seconds": 0.0}

    async def _fake_run_server(self, conn, ready) -> None:  # type: ignore[no-untyped-def]
        if connect_delay["seconds"]:
            await asyncio.sleep(connect_delay["seconds"])
        conn.session = _FakeSession(conn.owner, conn.name)
        conn.adapters = [
            MCPToolAdapter(
                manager=self,
                owner=conn.owner,
                server_name=conn.name,
                original_name="ping",
                description="d",
                input_schema=None,
                tool_timeout=5,
            )
        ]
        if not ready.done():
            ready.set_result(None)
        await conn.shutdown.wait()

    monkeypatch.setattr(MCPConnectionManager, "_run_server", _fake_run_server)

    instance = MCPConnectionManager()
    instance._test_registry = registry  # type: ignore[attr-defined]
    instance._test_delay = connect_delay  # type: ignore[attr-defined]
    return instance


def _write_user_servers(owner: str, **urls: str) -> None:
    from deeptutor.services.mcp.user_config import save_user_server

    for name, url in urls.items():
        save_user_server(owner, name, MCPServerConfig(url=url))


@pytest.fixture(autouse=True)
def _offline_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    monkeypatch.setattr(
        "deeptutor.services.mcp.network.socket.getaddrinfo",
        lambda host, *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))],
    )


@pytest.mark.asyncio
async def test_two_owners_with_the_same_server_name_stay_separate(
    manager: MCPConnectionManager,
) -> None:
    """The cross-tenant case: same name, two sessions, no crossover."""
    _write_user_servers("u_ada", notion="https://ada.example/mcp")
    _write_user_servers("u_bob", notion="https://bob.example/mcp")

    ada = await manager.ensure_scope("u_ada")
    bob = await manager.ensure_scope("u_bob")

    assert [tool.name for tool in ada] == ["mcp_notion_ping"]
    assert [tool.name for tool in bob] == ["mcp_notion_ping"]

    # The adapters carry their owner, and the call must reach that owner's
    # session — not whichever one a name-keyed lookup would find.
    assert (await ada[0].execute()).content == "u_ada/notion/ping"
    assert (await bob[0].execute()).content == "u_bob/notion/ping"

    await manager.shutdown()


@pytest.mark.asyncio
async def test_owner_tools_never_enter_the_process_registry(
    manager: MCPConnectionManager,
) -> None:
    """The registry is last-writer-wins by name; per-user tools must stay out."""
    _write_user_servers("u_ada", notion="https://ada.example/mcp")

    tools = await manager.ensure_scope("u_ada")

    assert tools, "the scope must have connected"
    registry = manager._test_registry  # type: ignore[attr-defined]
    assert registry.get("mcp_notion_ping") is None
    await manager.shutdown()


@pytest.mark.asyncio
async def test_a_stdio_entry_in_a_users_file_is_never_connected(
    manager: MCPConnectionManager,
) -> None:
    """The API refuses stdio, and so must the loader for a hand-edited file."""
    from deeptutor.services.mcp.user_config import user_mcp_path

    user_mcp_path("u_ada").write_text(
        '{"servers": {"local": {"command": "/bin/sh"}}}', encoding="utf-8"
    )

    assert await manager.ensure_scope("u_ada") == []
    await manager.shutdown()


@pytest.mark.asyncio
async def test_reload_scope_applies_a_change_immediately(
    manager: MCPConnectionManager,
) -> None:
    """Otherwise an account keeps talking to the server it just edited."""
    _write_user_servers("u_ada", one="https://one.example/mcp")
    assert len(await manager.ensure_scope("u_ada")) == 1

    _write_user_servers("u_ada", two="https://two.example/mcp")
    await manager.reload_scope("u_ada")

    assert {tool.provider_id for tool in manager.adapters_for("u_ada")} == {"one", "two"}
    await manager.shutdown()


@pytest.mark.asyncio
async def test_removing_a_server_disconnects_it(manager: MCPConnectionManager) -> None:
    from deeptutor.services.mcp.user_config import delete_user_server

    _write_user_servers("u_ada", one="https://one.example/mcp")
    await manager.ensure_scope("u_ada")

    delete_user_server("u_ada", "one")
    await manager.reload_scope("u_ada")

    assert manager.adapters_for("u_ada") == []
    await manager.shutdown()


@pytest.mark.asyncio
async def test_the_shared_scope_does_not_read_a_users_file(
    manager: MCPConnectionManager,
) -> None:
    _write_user_servers(SHARED_OWNER, sneaky="https://sneaky.example/mcp")
    assert await manager.ensure_scope(SHARED_OWNER) == []
    await manager.shutdown()


@pytest.mark.asyncio
async def test_an_idle_scope_is_dropped_when_another_arrives(
    manager: MCPConnectionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every connected server is a live session in one process.

    A deployment with hundreds of accounts must not accumulate them, and the
    next turn for a dropped account simply reconnects.
    """
    from deeptutor.services.mcp import manager as manager_module

    monkeypatch.setattr(manager_module, "_SCOPE_IDLE_TTL_S", -1.0)
    _write_user_servers("u_ada", one="https://one.example/mcp")
    _write_user_servers("u_bob", two="https://two.example/mcp")

    await manager.ensure_scope("u_ada")
    await manager.ensure_scope("u_bob")

    assert manager.adapters_for("u_ada") == []
    assert len(manager.adapters_for("u_bob")) == 1
    await manager.shutdown()


@pytest.mark.asyncio
async def test_the_scope_count_is_bounded(
    manager: MCPConnectionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deeptutor.services.mcp import manager as manager_module

    monkeypatch.setattr(manager_module, "_MAX_OWNER_SCOPES", 2)
    for index in range(4):
        owner = f"u_{index}"
        _write_user_servers(owner, one=f"https://{index}.example/mcp")
        await manager.ensure_scope(owner)

    live = {owner for owner, _name in manager._connections}
    assert len(live) <= 2, live
    # The scope that just asked is always among the survivors.
    assert "u_3" in live
    await manager.shutdown()


@pytest.mark.asyncio
async def test_one_owners_slow_connect_does_not_serialise_another(
    manager: MCPConnectionManager,
) -> None:
    """A single manager-wide lock would make one cold scope everyone's stall.

    ``ensure_scope`` runs before the turn's first stream event, so a shared lock
    turns one slow third-party host into a hang for every account at once.
    """
    manager._test_delay["seconds"] = 0.25  # type: ignore[attr-defined]
    _write_user_servers("u_ada", one="https://one.example/mcp")
    _write_user_servers("u_bob", two="https://two.example/mcp")

    loop = asyncio.get_running_loop()
    started = loop.time()
    await asyncio.gather(manager.ensure_scope("u_ada"), manager.ensure_scope("u_bob"))
    elapsed = loop.time() - started

    # Serialised would be ~0.50s; concurrent ~0.25s. The midpoint keeps this
    # meaningful without being flaky on a loaded machine.
    assert elapsed < 0.40, f"per-owner connects serialised ({elapsed:.3f}s)"
    await manager.shutdown()


@pytest.mark.asyncio
async def test_shutdown_closes_every_scope(manager: MCPConnectionManager) -> None:
    _write_user_servers("u_ada", one="https://one.example/mcp")
    await manager.ensure_scope("u_ada")

    await manager.shutdown()

    assert manager._connections == {}
    assert manager.adapters_for("u_ada") == []
