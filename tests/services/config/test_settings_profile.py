from __future__ import annotations

from copy import deepcopy
import json

import pytest

from deeptutor.api.routers import settings as settings_router
from deeptutor.services.config.runtime_settings import RuntimeSettingsService
from deeptutor.services.config.settings_profile import (
    PROFILE_SCHEMA_VERSION,
    SettingsProfileError,
    export_settings_profile,
    review_settings_profile_import,
)


def _runtime_service(tmp_path) -> RuntimeSettingsService:
    return RuntimeSettingsService(tmp_path / "settings", process_env={})


def _catalog() -> dict:
    return {
        "version": 1,
        "services": {
            "llm": {
                "active_profile_id": "llm-profile",
                "active_model_id": "model-id",
                "profiles": [
                    {
                        "id": "llm-profile",
                        "binding": "openai",
                        "base_url": "https://provider.example.test/v1",
                        "api_key": "secret-api-key",
                        "extra_headers": {"Authorization": "Bearer secret-header"},
                        "models": [{"id": "model-id", "model": "model-name", "dimension": "1536"}],
                    }
                ],
            }
        },
    }


def _configured_service(tmp_path) -> RuntimeSettingsService:
    service = _runtime_service(tmp_path)
    service.save_system(
        {
            "backend_port": 9101,
            "backend_workers": 3,
            "next_public_api_base_external": "https://deep.example.test",
            "cors_origins": ["https://ui.example.test"],
            "chat_attachment_max_file_mb": 40,
        }
    )
    service.save_auth({"enabled": True, "cookie_secure": True})
    service.save_integrations(
        {
            "pocketbase_admin_password": "secret-password",
            "turn_coordination": {
                "backend": "redis",
                "redis_url": "redis://redis.example.test:6379",
                "key_prefix": "university",
            },
        }
    )
    service.save_document_parsing(
        {
            "engine": "tika",
            "engines": {
                "mineru": {
                    "mode": "cloud",
                    "api_base_url": "https://mineru.example.test",
                    "api_token": "secret-token",
                    "local_cli_path": "/private/mineru",
                    "model_version": "vlm",
                },
                "tika": {"server_url": "http://tika.example.test:9998"},
            },
        }
    )
    return service


def _export(service: RuntimeSettingsService) -> dict:
    return export_settings_profile(service=service, catalog=_catalog())


def test_export_is_value_free_and_preserves_safe_configuration(tmp_path) -> None:
    service = _configured_service(tmp_path)
    exported = _export(service)
    profile = exported["profile"]
    serialized = json.dumps(profile)

    assert exported["schema_version"] == PROFILE_SCHEMA_VERSION
    assert profile["settings"]["system"]["backend_workers"] == 3
    assert profile["settings"]["system"]["chat_attachment_max_file_mb"] == 40
    assert profile["settings"]["auth"] == {
        "enabled": True,
        "token_expire_hours": 24,
        "cookie_secure": True,
    }
    assert profile["settings"]["integrations"]["turn_coordination"] == {
        "backend": "redis",
        "key_prefix": "university",
        "lease_ttl_seconds": 30,
        "renew_interval_seconds": 10,
        "recovery_interval_seconds": 10,
        "stream_retention_seconds": 86_400,
    }
    assert profile["settings"]["document_parsing"]["engine"] == "tika"
    assert profile["settings"]["document_parsing"]["engines"]["mineru"] == {
        "mode": "cloud",
        "model_download_source": "huggingface",
        "model_version": "vlm",
        "language": "auto",
        "enable_formula": True,
        "enable_table": True,
        "is_ocr": False,
        "allow_local_model_download": False,
    }
    assert profile["settings"]["document_parsing"]["engines"]["tika"] == {
        "server_url_present": True
    }
    llm = profile["settings"]["catalog"]["services"]["llm"]["profiles"][0]
    assert llm["id"] == "llm-profile"
    assert llm["binding"] == "openai"
    assert llm["api_key"] == {"present": True}
    assert llm["extra_headers"] == {"Authorization": {"present": True}}

    for secret in (
        "secret-api-key",
        "secret-header",
        "secret-password",
        "secret-token",
        "provider.example.test",
        "deep.example.test",
        "ui.example.test",
        "redis.example.test",
        "mineru.example.test",
        "tika.example.test",
        "/private/mineru",
    ):
        assert secret not in serialized

    # Deployment-specific values stay outside the portable profile.
    assert "backend_port" not in profile["settings"]["system"]
    assert "cors_origins" not in profile["settings"]["system"]
    assert "redis_url" not in profile["settings"]["integrations"]["turn_coordination"]


def test_profile_shape_is_stable_across_export_calls(tmp_path) -> None:
    service = _configured_service(tmp_path)

    assert _export(service)["profile"] == _export(service)["profile"]


def test_review_diff_reports_effective_changes_without_mutation(tmp_path) -> None:
    service = _configured_service(tmp_path)
    exported = _export(service)
    before = service.load_system()
    exported["profile"]["settings"]["system"]["backend_workers"] = 8

    review = review_settings_profile_import(
        exported,
        service=service,
        catalog=_catalog(),
    )

    assert review["changes"] == [
        {
            "path": "settings.system.backend_workers",
            "kind": "changed",
            "current": 3,
            "proposed": 8,
        }
    ]
    assert review["summary"] == {"changed": 1, "unsupported": 0, "compatible": True}
    assert service.load_system() == before


def test_review_marks_unknown_secret_and_deployment_fields_unsupported(tmp_path) -> None:
    service = _configured_service(tmp_path)
    exported = _export(service)
    exported["profile"]["settings"]["unknown_section"] = {}
    exported["profile"]["settings"]["system"]["backend_port"] = 9000
    exported["profile"]["settings"]["catalog"]["services"]["llm"]["profiles"][0]["api_key"] = {
        "present": "raw-secret"
    }
    exported["profile"]["settings"]["catalog"]["services"]["llm"]["profiles"][0][
        "extra_headers"
    ] = {"Authorization": "raw-secret-header"}

    review = review_settings_profile_import(
        exported,
        service=service,
        catalog=_catalog(),
    )

    assert review["unsupported"] == [
        {
            "path": "settings.catalog.services.llm.profiles.0.api_key",
            "reason": "secret_not_exported",
        },
        {
            "path": "settings.catalog.services.llm.profiles.0.extra_headers",
            "reason": "secret_not_exported",
        },
        {"path": "settings.system.backend_port", "reason": "deployment_value_not_exported"},
        {"path": "settings.unknown_section", "reason": "unknown_field"},
    ]
    assert review["summary"]["compatible"] is False


def test_review_rejects_unknown_profile_level_fields(tmp_path) -> None:
    service = _runtime_service(tmp_path)
    payload = {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "profile": {"settings": {}, "runtime_values": {}},
    }

    with pytest.raises(SettingsProfileError, match="unknown profile fields: runtime_values"):
        review_settings_profile_import(payload, service=service, catalog=_catalog())


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({}, "unsupported schema_version"),
        ({"schema_version": PROFILE_SCHEMA_VERSION}, "profile.settings"),
    ],
)
def test_review_rejects_invalid_profile_schema(
    tmp_path,
    payload: dict,
    message: str,
) -> None:
    service = _runtime_service(tmp_path)

    with pytest.raises(SettingsProfileError, match=message):
        review_settings_profile_import(payload, service=service, catalog=_catalog())


@pytest.mark.asyncio
async def test_profile_endpoints_are_admin_guarded_and_review_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    guarded = 0
    service = _configured_service(tmp_path)
    exported = _export(service)

    def require_admin() -> None:
        nonlocal guarded
        guarded += 1

    def export_profile() -> dict:
        return exported

    def review(payload: dict) -> dict:
        return review_settings_profile_import(payload, service=service, catalog=_catalog())

    monkeypatch.setattr(settings_router, "_require_settings_admin", require_admin)
    monkeypatch.setattr(settings_router, "export_settings_profile", export_profile)
    monkeypatch.setattr(settings_router, "review_settings_profile_import", review)

    profile = await settings_router.get_settings_profile()
    diff = await settings_router.diff_settings_profile(
        settings_router.SettingsProfileImportPayload(**exported)
    )

    assert profile is exported
    assert diff["summary"]["changed"] == 0
    assert guarded == 2
