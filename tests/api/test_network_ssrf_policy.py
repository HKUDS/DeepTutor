"""Network settings API: the two SSRF policy knobs (#2889)."""

from __future__ import annotations

from fastapi import HTTPException
import pytest

from deeptutor.api.routers import settings as settings_router
from deeptutor.services.config.runtime_settings import RuntimeSettingsService


def _service(tmp_path, process_env: dict[str, str] | None = None):
    service = RuntimeSettingsService(tmp_path / "settings", process_env=process_env or {})
    service.save_system({"backend_port": 8001, "frontend_port": 3782})
    return service


@pytest.mark.asyncio
async def test_defaults_are_strict_and_undeclared(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings_router, "get_runtime_settings_service", lambda: _service(tmp_path))

    payload = settings_router._network_settings_payload()

    assert payload["settings"]["ssrf_protection_enabled"] is True
    assert payload["settings"]["network_synthetic_ranges"] == []
    assert payload["effective"]["ssrf_protection_enabled"] is True
    assert payload["effective"]["ssrf_policy_env_override"] is False


@pytest.mark.asyncio
async def test_saving_the_policy_round_trips(monkeypatch, tmp_path) -> None:
    service = _service(tmp_path)
    monkeypatch.setattr(settings_router, "get_runtime_settings_service", lambda: service)

    response = await settings_router.update_network_settings(
        settings_router.NetworkSettingsUpdate(
            backend_port=8001,
            frontend_port=3782,
            ssrf_protection_enabled=False,
            network_synthetic_ranges=["fd27:712::/32", "198.18.0.0/15", "fd27:712::/32"],
        )
    )

    assert response["settings"]["ssrf_protection_enabled"] is False
    # Duplicates collapse, order is the operator's.
    assert response["settings"]["network_synthetic_ranges"] == [
        "fd27:712::/32",
        "198.18.0.0/15",
    ]
    assert response["effective"]["network_synthetic_ranges"] == [
        "fd27:712::/32",
        "198.18.0.0/15",
    ]


@pytest.mark.asyncio
async def test_invalid_cidr_is_rejected_instead_of_dropped(monkeypatch, tmp_path) -> None:
    service = _service(tmp_path)
    monkeypatch.setattr(settings_router, "get_runtime_settings_service", lambda: service)

    with pytest.raises(HTTPException) as excinfo:
        await settings_router.update_network_settings(
            settings_router.NetworkSettingsUpdate(
                backend_port=8001,
                frontend_port=3782,
                network_synthetic_ranges=["not-a-cidr"],
            )
        )

    assert excinfo.value.status_code == 422
    assert "not-a-cidr" in str(excinfo.value.detail)
    # Nothing was written: the page keeps failing loudly rather than silently
    # saving a policy that does not do what was typed.
    assert service.load_system(include_process_overrides=False)["network_synthetic_ranges"] == []


@pytest.mark.asyncio
async def test_omitting_the_policy_keeps_saved_values(monkeypatch, tmp_path) -> None:
    """An older frontend that posts only ports/CORS must not reset the policy."""
    service = _service(tmp_path)
    service.save_system(
        {
            "ssrf_protection_enabled": False,
            "network_synthetic_ranges": ["198.18.0.0/15"],
        }
    )
    monkeypatch.setattr(settings_router, "get_runtime_settings_service", lambda: service)

    response = await settings_router.update_network_settings(
        settings_router.NetworkSettingsUpdate(backend_port=8002, frontend_port=3782)
    )

    assert response["settings"]["ssrf_protection_enabled"] is False
    assert response["settings"]["network_synthetic_ranges"] == ["198.18.0.0/15"]


@pytest.mark.asyncio
async def test_env_override_is_surfaced(monkeypatch, tmp_path) -> None:
    service = _service(tmp_path, process_env={"DEEPTUTOR_SSRF_SYNTHETIC_RANGES": "fd27:712::/32"})
    monkeypatch.setattr(settings_router, "get_runtime_settings_service", lambda: service)

    payload = settings_router._network_settings_payload()

    assert payload["settings"]["network_synthetic_ranges"] == []
    assert payload["effective"]["network_synthetic_ranges"] == ["fd27:712::/32"]
    assert payload["effective"]["ssrf_policy_env_override"] is True
