from pathlib import Path

import pytest

import deeptutor.services.config as config_module
from deeptutor.services.config.runtime_settings import RuntimeSettingsService
from deeptutor.services.rag.preflight import engine_preflight


@pytest.fixture
def ima_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> RuntimeSettingsService:
    """Point the account-level IMA credentials at a throwaway settings dir."""
    service = RuntimeSettingsService(tmp_path, process_env={})
    monkeypatch.setattr(config_module, "get_runtime_settings_service", lambda: service)
    return service


def test_ima_preflight_is_not_ready_without_credentials(
    ima_settings: RuntimeSettingsService,
) -> None:
    report = engine_preflight("ima")

    assert report["ok"] is False
    assert report["checks"] == [
        {
            "key": "credentials",
            "label": "IMA Client ID and API key configured",
            "ok": False,
            "detail": (
                "Add them under Credentials, or supply a pair per knowledge base "
                "when connecting one."
            ),
            "optional": False,
        }
    ]


def test_ima_preflight_reports_the_configured_client_id(
    ima_settings: RuntimeSettingsService,
) -> None:
    ima_settings.save_ima({"client_id": "cid-1", "api_key": "secret"})

    report = engine_preflight("ima")

    assert report["ok"] is True
    assert report["checks"][0]["ok"] is True
    # The Client ID is not a secret and identifies which account is wired up;
    # the API key must never reach the report.
    assert report["checks"][0]["detail"] == "cid-1"


def test_ima_preflight_needs_both_halves(ima_settings: RuntimeSettingsService) -> None:
    ima_settings.save_ima({"client_id": "cid-1", "api_key": ""})

    assert engine_preflight("ima")["ok"] is False
