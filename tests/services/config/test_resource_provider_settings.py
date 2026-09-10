"""resource_providers.json settings round-trip and normalization."""

from __future__ import annotations

from pathlib import Path

from deeptutor.services.config.runtime_settings import RuntimeSettingsService


def test_resource_provider_roundtrip(tmp_path: Path) -> None:
    svc = RuntimeSettingsService(tmp_path, process_env={})
    svc.save_resource_providers(
        {"version": 1, "providers": {"example": {"enabled": False}}}
    )
    loaded = svc.load_resource_providers()
    assert loaded["providers"]["example"] == {"enabled": False}
    assert (tmp_path / "resource_providers.json").exists()


def test_resource_provider_defaults_when_absent(tmp_path: Path) -> None:
    svc = RuntimeSettingsService(tmp_path, process_env={})
    assert svc.load_resource_providers() == {"version": 1, "providers": {}}


def test_resource_provider_normalization_drops_invalid(tmp_path: Path) -> None:
    svc = RuntimeSettingsService(tmp_path, process_env={})
    payload = svc.save_resource_providers(
        {"version": 1, "providers": {"good": {"enabled": True}, "": {"enabled": True}, 42: None}}
    )
    assert payload["providers"] == {"good": {"enabled": True}}
