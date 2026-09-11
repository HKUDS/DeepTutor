"""Connections: one credential typed once, mirrored into linked profiles."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from deeptutor.services.config.model_catalog import (
    CATALOG_SECRET_MASK,
    ModelCatalogService,
    redact_catalog_secrets,
    restore_catalog_secrets,
)


def _linked_catalog(service: ModelCatalogService, **overrides: Any) -> dict[str, Any]:
    catalog = service.load()
    catalog["connections"] = [
        {
            "id": "conn-1",
            "name": "OpenRouter",
            "provider": "openrouter",
            "api_key": "sk-or-secret",
            "base_url": "https://openrouter.ai/api/v1",
            **overrides,
        }
    ]
    catalog["services"]["llm"]["profiles"] = [
        {
            "id": "llm-1",
            "name": "OpenRouter",
            "binding": "openrouter",
            "connection_id": "conn-1",
            "base_url": "",
            "api_key": "",
            "models": [{"id": "llm-model-1", "model": "anthropic/claude-sonnet-4"}],
        }
    ]
    catalog["services"]["embedding"]["profiles"] = [
        {
            "id": "emb-1",
            "name": "OpenRouter",
            "binding": "openrouter",
            "connection_id": "conn-1",
            "base_url": "",
            "api_key": "",
            "models": [{"id": "emb-model-1", "model": "text-embedding-3-large"}],
        }
    ]
    return catalog


def test_save_mirrors_connection_credentials_into_linked_profiles(tmp_path: Path) -> None:
    service = ModelCatalogService(path=tmp_path / "model_catalog.json")

    saved = service.save(_linked_catalog(service))

    llm_profile = saved["services"]["llm"]["profiles"][0]
    assert llm_profile["api_key"] == "sk-or-secret"
    assert llm_profile["base_url"] == "https://openrouter.ai/api/v1"


def test_embedding_profiles_take_the_endpoint_path_not_the_api_base(tmp_path: Path) -> None:
    service = ModelCatalogService(path=tmp_path / "model_catalog.json")

    saved = service.save(_linked_catalog(service))

    assert (
        saved["services"]["embedding"]["profiles"][0]["base_url"]
        == "https://openrouter.ai/api/v1/embeddings"
    )


def test_blank_connection_base_url_leaves_each_profile_endpoint_alone(tmp_path: Path) -> None:
    service = ModelCatalogService(path=tmp_path / "model_catalog.json")
    catalog = _linked_catalog(service, base_url="")
    catalog["services"]["embedding"]["profiles"][0]["base_url"] = (
        "https://api.jina.ai/v1/embeddings"
    )

    saved = service.save(catalog)

    assert (
        saved["services"]["embedding"]["profiles"][0]["base_url"]
        == "https://api.jina.ai/v1/embeddings"
    )
    assert saved["services"]["embedding"]["profiles"][0]["api_key"] == "sk-or-secret"


def test_rotating_the_key_reaches_every_linked_profile(tmp_path: Path) -> None:
    service = ModelCatalogService(path=tmp_path / "model_catalog.json")
    service.save(_linked_catalog(service))

    rotated = service.update(
        lambda catalog: catalog["connections"][0].update({"api_key": "sk-or-rotated"})
    )

    assert rotated["services"]["llm"]["profiles"][0]["api_key"] == "sk-or-rotated"
    assert rotated["services"]["embedding"]["profiles"][0]["api_key"] == "sk-or-rotated"


def test_deleting_a_connection_unlinks_without_wiping_credentials(tmp_path: Path) -> None:
    service = ModelCatalogService(path=tmp_path / "model_catalog.json")
    service.save(_linked_catalog(service))

    remaining = service.update(lambda catalog: catalog.update({"connections": []}))

    profile = remaining["services"]["llm"]["profiles"][0]
    assert "connection_id" not in profile
    # Deleting the place a key was typed must not break a working service.
    assert profile["api_key"] == "sk-or-secret"


def test_connection_secrets_survive_a_redact_edit_restore_round_trip(tmp_path: Path) -> None:
    service = ModelCatalogService(path=tmp_path / "model_catalog.json")
    current = service.save(_linked_catalog(service))

    redacted = redact_catalog_secrets(current)
    assert redacted["connections"][0]["api_key"] == CATALOG_SECRET_MASK

    redacted["connections"][0]["name"] = "Renamed"
    restored = restore_catalog_secrets(redacted, current)

    assert restored["connections"][0]["api_key"] == "sk-or-secret"
    assert restored["connections"][0]["name"] == "Renamed"
