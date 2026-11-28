"""system.json plumbing for the two SSRF policy keys."""

from __future__ import annotations

import json
from pathlib import Path

from deeptutor.services.config.runtime_settings import (
    DEFAULT_SYSTEM_SETTINGS,
    RuntimeSettingsService,
    _network_cidr_list,
)

_ENV_KEYS = (
    "DEEPTUTOR_SSRF_PROTECTION_ENABLED",
    "DEEPTUTOR_SSRF_SYNTHETIC_RANGES",
    "DEEPTUTOR_MCP_FAKE_IP_RANGES",
)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_defaults_leave_the_guards_untouched(tmp_path: Path) -> None:
    service = RuntimeSettingsService(tmp_path / "settings")

    system = service.load_system(include_process_overrides=False)

    assert system["ssrf_protection_enabled"] is True
    assert system["network_synthetic_ranges"] == []
    # Written out too, so the keys are discoverable in the settings file an
    # operator is told to edit.
    stored = _read_json(service.path_for("system"))
    assert stored["ssrf_protection_enabled"] is True
    assert stored["network_synthetic_ranges"] == []


def test_saved_ranges_survive_a_reload(tmp_path: Path) -> None:
    service = RuntimeSettingsService(tmp_path / "settings")

    service.save_system(
        {
            "ssrf_protection_enabled": False,
            "network_synthetic_ranges": ["fd27:712::/32", "198.18.0.0/15"],
        }
    )

    system = service.load_system(include_process_overrides=False)
    assert system["ssrf_protection_enabled"] is False
    assert system["network_synthetic_ranges"] == ["fd27:712::/32", "198.18.0.0/15"]


def test_invalid_ranges_are_dropped_not_fatal(tmp_path: Path) -> None:
    service = RuntimeSettingsService(tmp_path / "settings")

    service.save_system({"network_synthetic_ranges": ["fd27:712::/32", "nonsense", ""]})

    assert service.load_system(include_process_overrides=False)["network_synthetic_ranges"] == [
        "fd27:712::/32"
    ]


def test_process_env_overrides_both_keys(tmp_path: Path) -> None:
    service = RuntimeSettingsService(
        tmp_path / "settings",
        process_env={
            "DEEPTUTOR_SSRF_PROTECTION_ENABLED": "0",
            "DEEPTUTOR_SSRF_SYNTHETIC_RANGES": "fd27:712::/32, 198.18.0.0/15",
        },
    )

    system = service.load_system()

    assert system["ssrf_protection_enabled"] is False
    assert system["network_synthetic_ranges"] == ["fd27:712::/32", "198.18.0.0/15"]


def test_legacy_mcp_env_name_still_feeds_the_setting(tmp_path: Path) -> None:
    service = RuntimeSettingsService(
        tmp_path / "settings",
        process_env={"DEEPTUTOR_MCP_FAKE_IP_RANGES": "fd27:712::/32"},
    )

    assert service.load_system()["network_synthetic_ranges"] == ["fd27:712::/32"]


def test_network_cidr_list_accepts_strings_lists_and_junk() -> None:
    assert _network_cidr_list("10.0.0.0/8; 172.16.0.0/12") == ["10.0.0.0/8", "172.16.0.0/12"]
    assert _network_cidr_list(["10.0.0.0/8", "10.0.0.0/8", "oops"]) == ["10.0.0.0/8"]
    assert _network_cidr_list(None) == []


def test_defaults_include_the_documented_keys() -> None:
    assert DEFAULT_SYSTEM_SETTINGS["ssrf_protection_enabled"] is True
    assert DEFAULT_SYSTEM_SETTINGS["network_synthetic_ranges"] == []
