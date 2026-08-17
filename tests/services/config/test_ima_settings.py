"""Account-level Tencent IMA credential storage in RuntimeSettingsService."""

from __future__ import annotations

from pathlib import Path

from deeptutor.services.config.runtime_settings import RuntimeSettingsService


def test_ima_settings_roundtrip(tmp_path: Path) -> None:
    svc = RuntimeSettingsService(tmp_path, process_env={})
    svc.save_ima({"client_id": " cid-1 ", "api_key": " secret "})

    loaded = svc.load_ima(include_process_overrides=False)
    assert loaded["client_id"] == "cid-1"
    assert loaded["api_key"] == "secret"

    # Persisted to its own file beside other per-feature settings.
    assert (tmp_path / "ima.json").exists()


def test_ima_defaults_when_absent(tmp_path: Path) -> None:
    svc = RuntimeSettingsService(tmp_path, process_env={})
    loaded = svc.load_ima(include_process_overrides=False)
    assert loaded == {"version": 1, "client_id": "", "api_key": ""}


def test_ima_env_override(tmp_path: Path) -> None:
    svc = RuntimeSettingsService(
        tmp_path,
        process_env={"IMA_CLIENT_ID": "from-env", "IMA_API_KEY": "env-key"},
    )
    loaded = svc.load_ima(include_process_overrides=True)
    assert loaded["client_id"] == "from-env"
    assert loaded["api_key"] == "env-key"

    # The override is a deployment knob, not something the UI can overwrite.
    assert svc.load_ima(include_process_overrides=False)["client_id"] == ""
