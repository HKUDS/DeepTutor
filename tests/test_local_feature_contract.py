"""Contract for fork-local features and the v1.5.16 MarginNote bridge."""

from deeptutor.__version__ import __version__
from deeptutor.api.main import app
from deeptutor.services.config.runtime_settings import (
    DEFAULT_AUTH_SETTINGS,
    RuntimeSettingsService,
)


def test_required_local_and_upstream_route_families_are_installed():
    paths = set(app.openapi()["paths"])

    assert any(path.startswith("/api/v1/kids/") for path in paths)
    assert any(path.startswith("/api/v1/kids-admin/") for path in paths)
    assert any(path.startswith("/api/v1/marginnote4/") for path in paths)
    assert __version__ == "1.5.16"


def test_registration_setting_survives_default_save_and_process_override(tmp_path):
    assert DEFAULT_AUTH_SETTINGS["allow_registration"] is False

    service = RuntimeSettingsService(tmp_path / "settings")
    saved = service.save_auth({"allow_registration": True})
    assert saved["allow_registration"] is True

    overridden = RuntimeSettingsService(
        tmp_path / "overridden",
        process_env={"AUTH_ALLOW_REGISTRATION": "true"},
    ).load_auth()
    assert overridden["allow_registration"] is True
