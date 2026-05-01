"""Tests for the SAGE Memory Companion Playground status endpoint."""

from __future__ import annotations

import pytest

from deeptutor.api.routers import plugins_sage as plugins_sage_router


class _FakeSageClient:
    def __init__(self, *, healthy: bool = True) -> None:
        self._healthy = healthy
        self._sdk_client = type(
            "_FakeSdk",
            (),
            {"identity": type("_Id", (), {"agent_id": "agent-deadbeef"})()},
        )()

    def health_check(self) -> bool:
        return self._healthy


@pytest.mark.asyncio
async def test_sage_status_disabled_when_env_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SAGE_ENABLED", raising=False)
    monkeypatch.setenv("SAGE_URL", "http://example:9090")

    monkeypatch.setattr(
        plugins_sage_router,
        "_safe_get_client",
        lambda: _FakeSageClient(healthy=True),
    )

    payload = await plugins_sage_router.sage_status()

    assert payload.enabled is False
    assert payload.reachable is False
    assert payload.plugin_loaded is True
    assert payload.node_url == "http://example:9090"


@pytest.mark.asyncio
async def test_sage_status_connected_when_enabled_and_healthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SAGE_ENABLED", "true")
    monkeypatch.setenv("SAGE_URL", "http://sage.local:8080")

    fake = _FakeSageClient(healthy=True)
    monkeypatch.setattr(plugins_sage_router, "_safe_get_client", lambda: fake)

    payload = await plugins_sage_router.sage_status()

    assert payload.enabled is True
    assert payload.reachable is True
    assert payload.plugin_loaded is True
    assert payload.node_url == "http://sage.local:8080"
    assert payload.agent_id == "agent-deadbeef"


@pytest.mark.asyncio
async def test_sage_status_disconnected_when_health_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SAGE_ENABLED", "true")
    monkeypatch.setenv("SAGE_URL", "http://sage.local:8080")

    monkeypatch.setattr(
        plugins_sage_router,
        "_safe_get_client",
        lambda: _FakeSageClient(healthy=False),
    )

    payload = await plugins_sage_router.sage_status()

    assert payload.enabled is True
    assert payload.reachable is False
    assert "unreachable" in (payload.detail or "").lower()


@pytest.mark.asyncio
async def test_sage_status_unavailable_when_plugin_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SAGE_ENABLED", raising=False)
    monkeypatch.setattr(plugins_sage_router, "_safe_get_client", lambda: None)

    payload = await plugins_sage_router.sage_status()

    assert payload.plugin_loaded is False
    assert payload.reachable is False
    assert payload.detail and "not available" in payload.detail.lower()
