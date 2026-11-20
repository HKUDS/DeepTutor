"""PageIndex credential storage in RuntimeSettingsService."""

from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.services.config.runtime_settings import RuntimeSettingsService


def test_pageindex_settings_roundtrip(tmp_path: Path) -> None:
    svc = RuntimeSettingsService(tmp_path, process_env={})
    svc.save_pageindex({"api_key": "sk-abc123"})

    loaded = svc.load_pageindex(include_process_overrides=False)
    assert loaded["api_key"] == "sk-abc123"
    assert set(loaded) == {"version", "api_key", "oss_summary_concurrency"}

    # Persisted to its own file beside other per-feature settings.
    assert (tmp_path / "pageindex.json").exists()


def test_pageindex_defaults_when_absent(tmp_path: Path) -> None:
    svc = RuntimeSettingsService(tmp_path, process_env={})
    loaded = svc.load_pageindex(include_process_overrides=False)
    assert loaded["api_key"] == ""
    assert set(loaded) == {"version", "api_key", "oss_summary_concurrency"}
    assert loaded["oss_summary_concurrency"] is None


def test_pageindex_env_override(tmp_path: Path) -> None:
    svc = RuntimeSettingsService(
        tmp_path,
        process_env={"PAGEINDEX_API_KEY": "from-env", "PAGEINDEX_API_BASE_URL": "https://x.test"},
    )
    loaded = svc.load_pageindex(include_process_overrides=True)
    assert loaded["api_key"] == "from-env"
    assert "api_base_url" not in loaded


def test_pageindex_oss_concurrency_roundtrip_and_reset(tmp_path: Path) -> None:
    service = RuntimeSettingsService(tmp_path, process_env={})
    service.save_pageindex({"api_key": "cloud-key", "oss_summary_concurrency": 2})
    assert service.load_pageindex()["oss_summary_concurrency"] == 2
    service.save_pageindex({"api_key": "cloud-key", "oss_summary_concurrency": None})
    assert service.load_pageindex()["oss_summary_concurrency"] is None
    assert service.load_pageindex()["api_key"] == "cloud-key"


@pytest.mark.parametrize(
    "value, expected", [(0, 1), (999, 128), ("4", 4), ("bad", None), (True, None)]
)
def test_pageindex_oss_concurrency_normalization(tmp_path: Path, value, expected) -> None:
    service = RuntimeSettingsService(tmp_path, process_env={})
    service.save_pageindex({"oss_summary_concurrency": value})
    assert service.load_pageindex()["oss_summary_concurrency"] == expected
