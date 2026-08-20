"""PageIndex credential storage in RuntimeSettingsService."""

from __future__ import annotations

from pathlib import Path

from deeptutor.services.config.runtime_settings import RuntimeSettingsService


def test_pageindex_settings_roundtrip(tmp_path: Path) -> None:
    svc = RuntimeSettingsService(tmp_path, process_env={})
    svc.save_pageindex({"api_key": "sk-abc123"})

    loaded = svc.load_pageindex(include_process_overrides=False)
    assert loaded["api_key"] == "sk-abc123"
    assert set(loaded) == {"version", "api_key"}

    # Persisted to its own file beside other per-feature settings.
    assert (tmp_path / "pageindex.json").exists()


def test_pageindex_defaults_when_absent(tmp_path: Path) -> None:
    svc = RuntimeSettingsService(tmp_path, process_env={})
    loaded = svc.load_pageindex(include_process_overrides=False)
    assert loaded["api_key"] == ""
    assert set(loaded) == {"version", "api_key"}


def test_pageindex_env_override(tmp_path: Path) -> None:
    svc = RuntimeSettingsService(
        tmp_path,
        process_env={"PAGEINDEX_API_KEY": "from-env", "PAGEINDEX_API_BASE_URL": "https://x.test"},
    )
    loaded = svc.load_pageindex(include_process_overrides=True)
    assert loaded["api_key"] == "from-env"
    assert "api_base_url" not in loaded
