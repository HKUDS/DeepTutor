"""Two ways an MCP server can be wrong about its own state.

Both cases here shipped as silent failures, and both were expensive to diagnose
because the symptom named the wrong thing:

* rotating a credential left every live session using the *old* key, because the
  reload diff fingerprints a config that stores ``${secret:...}`` references
  rather than values — so the bytes it compares never change;
* a transport-level failure on a tool call (an auth rejection, most often) is
  raised inside the SDK's own task group and never resolves the caller's
  request, so the call was reported as a timeout — the one explanation that
  rules out the cause.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from deeptutor.services.mcp.config import MCPServerConfig
from deeptutor.services.mcp.manager import (
    MCPConnectionManager,
    _ServerConnection,
)
from deeptutor.services.mcp.secrets import secret_reference, store_secrets

OWNER = "u_ada"
SERVER = "maps"


@pytest.fixture(autouse=True)
def _isolated_data_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point the secrets store at a temp tree; it writes to ``data/system``."""
    from deeptutor.multi_user import paths

    root = (tmp_path / "data").resolve()
    monkeypatch.setattr(paths, "ADMIN_WORKSPACE_ROOT", root)
    monkeypatch.setattr(paths, "USERS_ROOT", root / "users")
    monkeypatch.setattr(paths, "SYSTEM_ROOT", root / "system")


@pytest.fixture(autouse=True)
def _offline_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Saving a user server validates the host; these tests must not hit DNS."""
    import socket

    monkeypatch.setattr(
        "deeptutor.services.mcp.network.socket.getaddrinfo",
        lambda host, *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))],
    )


def _config_with_secret_header() -> MCPServerConfig:
    return MCPServerConfig(
        url="https://maps.example/mcp",
        headers={"X-Api-Key": secret_reference(SERVER, "header.X-Api-Key")},
    )


# ── the credential a connection is actually using ──────────────────────


def test_rotating_a_secret_changes_the_connection_signature() -> None:
    """The bug: the stored config is byte-identical before and after a rotation."""
    cfg = _config_with_secret_header()
    store_secrets(OWNER, SERVER, {"header.X-Api-Key": "old-key"})
    before = MCPConnectionManager._signature(cfg, OWNER)

    store_secrets(OWNER, SERVER, {"header.X-Api-Key": "new-key"})
    after = MCPConnectionManager._signature(cfg, OWNER)

    assert cfg.connection_signature() == cfg.connection_signature(), "config itself is unchanged"
    assert before != after


def test_a_signature_never_carries_the_credential() -> None:
    """A signature is held on a live connection and compared near logs."""
    cfg = _config_with_secret_header()
    store_secrets(OWNER, SERVER, {"header.X-Api-Key": "super-secret-value"})

    assert "super-secret-value" not in MCPConnectionManager._signature(cfg, OWNER)


def test_a_config_without_references_keeps_its_plain_signature() -> None:
    """Upgrading must not invalidate — and so drop — every live session."""
    cfg = MCPServerConfig(url="https://maps.example/mcp", headers={"X-Api-Key": "literal"})

    assert MCPConnectionManager._signature(cfg, OWNER) == cfg.connection_signature()


@pytest.mark.asyncio
async def test_reload_reconnects_a_server_whose_secret_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End to end: the account must stop talking to the server with the old key."""
    from deeptutor.runtime.registry.tool_registry import ToolRegistry
    from deeptutor.services.mcp.user_config import save_user_server

    monkeypatch.setattr(MCPConnectionManager, "_registry", staticmethod(ToolRegistry))

    sessions: list[object] = []

    async def _fake_run_server(self, conn, ready) -> None:  # type: ignore[no-untyped-def]
        conn.session = object()
        sessions.append(conn.session)
        if not ready.done():
            ready.set_result(None)
        await conn.shutdown.wait()

    monkeypatch.setattr(MCPConnectionManager, "_run_server", _fake_run_server)

    save_user_server(OWNER, SERVER, _config_with_secret_header())
    store_secrets(OWNER, SERVER, {"header.X-Api-Key": "old-key"})

    manager = MCPConnectionManager()
    await manager.ensure_scope(OWNER)
    assert len(sessions) == 1

    # Only the credential changes — the server config file is untouched.
    store_secrets(OWNER, SERVER, {"header.X-Api-Key": "new-key"})
    await manager.reload_scope(OWNER)

    assert len(sessions) == 2, "the session still holding the old key was kept"
    await manager.shutdown()


# ── what a call reports when the transport fails under it ──────────────


class _HangingSession:
    """A session whose request future never resolves, as in the real failure."""

    async def call_tool(self, tool_name, arguments, progress_callback=None):  # type: ignore[no-untyped-def]
        await asyncio.Event().wait()


@pytest.mark.asyncio
async def test_a_dead_connection_is_reported_as_itself_not_as_a_timeout() -> None:
    """The diagnosis this used to cost: 45s of waiting, then the wrong cause."""
    manager = MCPConnectionManager()
    conn = _ServerConnection(
        name=SERVER,
        config=MCPServerConfig(url="https://maps.example/mcp", tool_timeout=45),
        signature="sig",
        owner=OWNER,
        status="connected",
        session=_HangingSession(),
    )

    async def _connection_that_dies() -> None:
        await asyncio.sleep(0.01)
        conn.error = "HTTPStatusError: Client error '403 Forbidden'"

    conn.task = asyncio.create_task(_connection_that_dies())
    manager._connections[(OWNER, SERVER)] = conn

    result = await asyncio.wait_for(
        manager.call_tool(OWNER, SERVER, "compute_routes", {}, timeout=45),
        timeout=5,  # the point: it must not sit out the 45s tool timeout
    )

    assert "403 Forbidden" in result
    assert "timed out" not in result


@pytest.mark.asyncio
async def test_a_live_connection_still_lets_a_call_time_out() -> None:
    """The watcher must not turn a genuinely slow server into a lost connection."""
    manager = MCPConnectionManager()
    conn = _ServerConnection(
        name=SERVER,
        config=MCPServerConfig(url="https://maps.example/mcp"),
        signature="sig",
        owner=OWNER,
        status="connected",
        session=_HangingSession(),
    )
    conn.task = asyncio.create_task(asyncio.Event().wait())
    manager._connections[(OWNER, SERVER)] = conn

    result = await manager.call_tool(OWNER, SERVER, "compute_routes", {}, timeout=1)

    assert "timed out after 1s" in result
    conn.task.cancel()


# ── what a cancelled turn leaves behind ────────────────────────────────


@pytest.mark.asyncio
async def test_cancelling_the_turn_does_not_orphan_the_call() -> None:
    """``asyncio.wait`` leaves its futures running when the waiter is cancelled.

    The call is a free-standing task, so nothing else would ever stop it:
    clicking Stop would leave the tool running against the server with its
    result thrown away.
    """
    manager = MCPConnectionManager()
    started = asyncio.Event()
    finished = False

    class _SlowSession:
        async def call_tool(self, *_args, **_kwargs):
            nonlocal finished
            started.set()
            await asyncio.sleep(30)
            finished = True

    conn = _ServerConnection(
        name=SERVER,
        config=MCPServerConfig(url="https://maps.example/mcp"),
        signature="sig",
        owner=OWNER,
        status="connected",
        session=_SlowSession(),
    )
    conn.task = asyncio.create_task(asyncio.Event().wait())
    manager._connections[(OWNER, SERVER)] = conn

    turn = asyncio.create_task(manager.call_tool(OWNER, SERVER, "compute_routes", {}, timeout=45))
    await asyncio.wait_for(started.wait(), timeout=5)
    turn.cancel()
    with pytest.raises(asyncio.CancelledError):
        await turn

    # Give an orphaned task a chance to be scheduled before asserting.
    await asyncio.sleep(0)
    inflight = [
        task
        for task in asyncio.all_tasks()
        if task is not asyncio.current_task() and task is not conn.task and not task.done()
    ]
    assert inflight == [], f"call outlived its cancelled turn: {inflight}"
    assert finished is False
    conn.task.cancel()


# ── what the model is allowed to see ───────────────────────────────────


def test_a_credential_in_the_url_never_reaches_the_caller() -> None:
    """Several curated servers authenticate with a query parameter.

    httpx names the full request URL in its message, and that string is now
    returned to the model as a tool result, not just shown in settings.
    """
    from deeptutor.services.mcp.manager import describe_connect_failure

    exc = httpx.HTTPStatusError(
        "Client error '403 Forbidden' for url "
        "'https://mapstools.googleapis.com/mcp?key=AIzaSyREALSECRET&v=1'",
        request=httpx.Request("POST", "https://mapstools.googleapis.com/mcp"),
        response=httpx.Response(403, request=httpx.Request("POST", "https://x/")),
    )

    described = describe_connect_failure(exc)

    assert "AIzaSyREALSECRET" not in described
    # The part that helps whoever is debugging survives.
    assert "403 Forbidden" in described
    assert "mapstools.googleapis.com/mcp" in described


def test_redaction_keeps_a_plain_url_readable() -> None:
    from deeptutor.services.mcp.manager import describe_connect_failure

    exc = RuntimeError("connect failed for url 'https://maps.example:8443/mcp'")

    described = describe_connect_failure(exc)

    assert "https://maps.example:8443/mcp" in described


def test_userinfo_credentials_are_redacted() -> None:
    from deeptutor.services.mcp.manager import describe_connect_failure

    exc = RuntimeError("connect failed for url 'https://user:pw@maps.example/mcp'")

    described = describe_connect_failure(exc)

    assert "pw@" not in described
    assert "maps.example/mcp" in described


# ── the cost of fingerprinting on the turn's critical path ─────────────


def test_a_config_without_references_is_fingerprinted_without_touching_disk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_signature`` runs per live connection on every reload, once per turn."""
    cfg = MCPServerConfig(url="https://maps.example/mcp", headers={"X-Api-Key": "literal"})

    def _explode(*_args, **_kwargs):
        raise AssertionError("materialized a config that holds no references")

    monkeypatch.setattr(MCPConnectionManager, "_materialize", staticmethod(_explode))

    assert MCPConnectionManager._signature(cfg, OWNER) == cfg.connection_signature()
