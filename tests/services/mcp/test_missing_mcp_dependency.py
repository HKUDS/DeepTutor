"""A missing ``mcp`` package must fail a connect immediately, not time out.

Regression test for issue #792. ``_run_server`` used to import ``mcp`` at
function scope, above its own ``try``. With the package absent the connection
task therefore died before it could ever fail the ``ready`` future, so:

* the caller sat out the whole ``_CONNECT_TIMEOUT_S`` window (15s by default)
  and then reported ``connect timed out after 15s`` — the one explanation that
  rules out the real cause; and
* the ``ModuleNotFoundError`` surfaced only as asyncio's "Task exception was
  never retrieved" noise, detached from the server it belonged to.

The package is a core dependency now (see ``tests/test_packaging_metadata.py``),
so this should be unreachable on a supported install — but a broken environment
should still say what is broken instead of stalling every turn.
"""

from __future__ import annotations

import asyncio
import builtins
import time

import pytest

from deeptutor.services.mcp import manager as manager_mod
from deeptutor.services.mcp.config import MCPServerConfig
from deeptutor.services.mcp.manager import SHARED_OWNER, MCPConnectionManager

# Short enough that a regression (which waits out the full window) is obvious
# without making the suite slow.
_PATCHED_TIMEOUT_S = 3


@pytest.fixture
def _no_mcp_package(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every ``import mcp`` raise, as an install without the extra does."""
    real_import = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "mcp" or name.startswith("mcp."):
            raise ModuleNotFoundError("No module named 'mcp'", name="mcp")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", fake_import)


def test_missing_mcp_package_reports_real_cause_without_waiting_out_timeout(
    monkeypatch: pytest.MonkeyPatch,
    _no_mcp_package: None,
) -> None:
    """The connect fails fast, names the module, and orphans no task exception."""
    monkeypatch.setattr(manager_mod, "_CONNECT_TIMEOUT_S", _PATCHED_TIMEOUT_S)

    # The built-in pageindex entry's shape: a remote streamableHttp server. The
    # transport is never opened, so no network is involved.
    cfg = MCPServerConfig(
        type="streamableHttp",
        url="https://api.pageindex.ai/mcp",
        headers={"Authorization": "Bearer test-key"},
    )

    async def scenario() -> tuple[float, manager_mod._ServerConnection]:
        mgr = MCPConnectionManager()
        started = time.monotonic()
        await mgr._connect("pageindex", cfg)
        elapsed = time.monotonic() - started
        conn = mgr._connections[(SHARED_OWNER, "pageindex")]
        assert conn.task is not None
        await conn.task
        return elapsed, conn

    elapsed, conn = asyncio.run(scenario())

    # Fast-fail: nowhere near the connect timeout.
    assert elapsed < _PATCHED_TIMEOUT_S / 2
    assert conn.status == "error"
    # The reason names the missing module rather than a timeout.
    assert "No module named 'mcp'" in conn.error
    assert "timed out" not in conn.error
    # The task exception was consumed via the ready future, so asyncio has
    # nothing left to complain about at GC time.
    assert conn.task is not None and conn.task.done()
    assert conn.task.exception() is None
