from __future__ import annotations

from deeptutor.services.config.model_catalog import (
    CATALOG_SECRET_MASK,
    ModelCatalogService,
    redact_catalog_secrets,
    restore_catalog_secrets,
)


def _catalog() -> dict:
    return {
        "version": 1,
        "services": {
            "llm": {
                "profiles": [
                    {
                        "id": "profile-a",
                        "name": "A",
                        "api_key": "sk-secret-a",
                        "extra_headers": {
                            "Authorization": "Bearer secret",
                            "X-Tenant": "tenant-secret",
                        },
                    },
                    {
                        "id": "profile-b",
                        "name": "B",
                        "api_key": "sk-secret-b",
                        "extra_headers": '{"Authorization":"Bearer secret"}',
                    },
                ]
            }
        },
    }


def test_redact_catalog_secrets_masks_credentials_without_mutating_source() -> None:
    catalog = _catalog()

    redacted = redact_catalog_secrets(catalog)

    first, second = redacted["services"]["llm"]["profiles"]
    assert first["api_key"] == CATALOG_SECRET_MASK
    assert first["extra_headers"] == {
        "Authorization": CATALOG_SECRET_MASK,
        "X-Tenant": CATALOG_SECRET_MASK,
    }
    assert second["extra_headers"] == CATALOG_SECRET_MASK
    assert catalog["services"]["llm"]["profiles"][0]["api_key"] == "sk-secret-a"


def test_restore_catalog_secrets_matches_profiles_by_id_after_reorder() -> None:
    current = _catalog()
    proposed = redact_catalog_secrets(current)
    proposed["services"]["llm"]["profiles"].reverse()
    proposed["services"]["llm"]["profiles"][0]["name"] = "Renamed B"
    proposed["services"]["llm"]["profiles"][1]["api_key"] = "sk-replaced-a"

    restored = restore_catalog_secrets(proposed, current)

    first, second = restored["services"]["llm"]["profiles"]
    assert first["id"] == "profile-b"
    assert first["api_key"] == "sk-secret-b"
    assert first["extra_headers"] == '{"Authorization":"Bearer secret"}'
    assert first["name"] == "Renamed B"
    assert second["api_key"] == "sk-replaced-a"
    assert second["extra_headers"]["Authorization"] == "Bearer secret"


def test_restore_catalog_secrets_keeps_explicit_clear() -> None:
    current = _catalog()
    proposed = redact_catalog_secrets(current)
    proposed["services"]["llm"]["profiles"][0]["api_key"] = ""

    restored = restore_catalog_secrets(proposed, current)

    assert restored["services"]["llm"]["profiles"][0]["api_key"] == ""


def test_model_catalog_reset_clears_all_profiles_connections_and_secrets(tmp_path) -> None:
    service = ModelCatalogService(tmp_path / "model_catalog.json")
    catalog = service.load()
    catalog["connections"] = [
        {
            "id": "provider",
            "name": "Provider",
            "provider": "custom",
            "api_key": "secret",
            "base_url": "https://example.invalid",
            "api_version": "",
        }
    ]
    service.save(catalog)

    reset = service.reset_to_defaults()

    assert reset["connections"] == []
    assert all(not service_data["profiles"] for service_data in reset["services"].values())
    assert service.load() == reset
