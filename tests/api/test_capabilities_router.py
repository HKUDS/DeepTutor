"""API surface tests for /api/v1/capabilities/registered.

The endpoint exists so a page can ask whether the capability it is about to
send actually exists here (#963): Whisper ships its pages in this repository
but its ``whisper_visitor`` / ``whisper_trainee`` capability comes from an
out-of-tree plugin, and a stock install used to offer the room anyway.
"""

from __future__ import annotations

import pytest

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except Exception:  # pragma: no cover
    FastAPI = None
    TestClient = None

pytestmark = pytest.mark.skipif(
    FastAPI is None or TestClient is None, reason="fastapi not installed"
)


@pytest.fixture
def client() -> TestClient:
    from deeptutor.api.routers import capabilities

    app = FastAPI()
    app.include_router(capabilities.router, prefix="/api/v1/capabilities")
    return TestClient(app)


def test_registered_lists_the_builtin_capabilities(client) -> None:
    """The names a turn can be started with, sorted and de-duplicated."""
    from deeptutor.runtime.bootstrap.builtin_capabilities import BUILTIN_CAPABILITY_CLASSES

    body = client.get("/api/v1/capabilities/registered").json()
    names = body["capabilities"]

    assert names == sorted(names)
    assert set(BUILTIN_CAPABILITY_CLASSES) <= set(names)


def test_a_stock_install_reports_whisper_missing(client) -> None:
    """#963: without the psych-academy plugin the seats are not startable.

    The page gates its entry on exactly this answer, so if Whisper ever moves
    in-tree this test failing is the signal to drop the gate — not to loosen
    the assertion.
    """
    names = client.get("/api/v1/capabilities/registered").json()["capabilities"]

    assert "whisper_visitor" not in names
    assert "whisper_trainee" not in names


def test_plugin_capabilities_are_reported(client, monkeypatch) -> None:
    """A registered plugin capability is visible, which is what un-gates a page."""
    from deeptutor.runtime.registry import capability_registry as registry_module

    class _StubCapability:
        name = "whisper_visitor"

    registry = registry_module.get_capability_registry()
    monkeypatch.setitem(registry._capabilities, "whisper_visitor", _StubCapability())

    names = client.get("/api/v1/capabilities/registered").json()["capabilities"]

    assert "whisper_visitor" in names
