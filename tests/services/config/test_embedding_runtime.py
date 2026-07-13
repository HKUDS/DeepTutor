"""Tests for normalized embedding runtime resolution."""

from __future__ import annotations

import pytest

from deeptutor.services.config.provider_runtime import (
    EMBEDDING_PROVIDERS,
    resolve_embedding_runtime_config,
)


def _build_catalog(
    *,
    embedding_profile: dict | None = None,
    embedding_model: dict | None = None,
) -> dict:
    embedding_profile = embedding_profile or {
        "id": "embedding-p",
        "name": "Embedding",
        "binding": "openai",
        "base_url": "",
        "api_key": "",
        "api_version": "",
        "extra_headers": {},
        "models": [{"id": "embedding-m", "name": "m", "model": "text-embedding-3-large"}],
    }
    if embedding_model is not None:
        # Replace whichever model lives at the active slot so the override is
        # actually visible to ``resolve_embedding_runtime_config``.
        embedding_profile["models"] = [embedding_model]
    embedding_model = embedding_profile["models"][0]
    return {
        "version": 1,
        "services": {
            "llm": {"active_profile_id": None, "active_model_id": None, "profiles": []},
            "embedding": {
                "active_profile_id": embedding_profile["id"],
                "active_model_id": embedding_model["id"],
                "profiles": [embedding_profile],
            },
            "search": {"active_profile_id": None, "profiles": []},
        },
    }


def test_embedding_explicit_binding_and_headers() -> None:
    catalog = _build_catalog(
        embedding_profile={
            "id": "embedding-p",
            "name": "Embedding",
            "binding": "jina",
            "base_url": "",
            "api_key": "jina-key",
            "api_version": "",
            "extra_headers": {"X-App": "demo"},
            "models": [
                {
                    "id": "embedding-m",
                    "name": "jina",
                    "model": "jina-embeddings-v3",
                    "dimension": "1024",
                }
            ],
        }
    )
    resolved = resolve_embedding_runtime_config(catalog=catalog)
    assert resolved.provider_name == "jina"
    assert resolved.provider_mode == "standard"
    assert resolved.effective_url == "https://api.jina.ai/v1/embeddings"
    assert resolved.extra_headers == {"X-App": "demo"}
    assert resolved.dimension == 1024


def test_embedding_alias_canonicalization_google_to_gemini() -> None:
    catalog = _build_catalog(
        embedding_profile={
            "id": "embedding-p",
            "name": "Embedding",
            "binding": "google",
            "base_url": "",
            "api_key": "k",
            "api_version": "",
            "extra_headers": {},
            "models": [{"id": "embedding-m", "name": "m", "model": "text-embedding-3-small"}],
        }
    )
    resolved = resolve_embedding_runtime_config(catalog=catalog)
    assert resolved.provider_name == "gemini"
    assert resolved.binding == "gemini"


def test_embedding_gemini_default_base_and_profile_key() -> None:
    catalog = _build_catalog(
        embedding_profile={
            "id": "embedding-p",
            "name": "Embedding",
            "binding": "gemini",
            "base_url": "",
            "api_key": "gemini-test-key",
            "api_version": "",
            "extra_headers": {},
            "models": [{"id": "embedding-m", "name": "m", "model": "gemini-embedding-001"}],
        }
    )
    resolved = resolve_embedding_runtime_config(catalog=catalog)
    assert resolved.provider_name == "gemini"
    assert resolved.binding == "gemini"
    assert resolved.api_key == "gemini-test-key"
    assert (
        resolved.effective_url
        == "https://generativelanguage.googleapis.com/v1beta/openai/embeddings"
    )


def test_embedding_local_fallback_from_base_url() -> None:
    catalog = _build_catalog(
        embedding_profile={
            "id": "embedding-p",
            "name": "Embedding",
            "binding": "",
            "base_url": "http://localhost:11434",
            "api_key": "",
            "api_version": "",
            "extra_headers": {},
            "models": [{"id": "embedding-m", "name": "m", "model": "nomic-embed-text"}],
        }
    )
    resolved = resolve_embedding_runtime_config(catalog=catalog)
    assert resolved.provider_name == "ollama"
    assert resolved.provider_mode == "local"
    assert resolved.api_key == ""


def test_embedding_local_vllm_uses_profile_key() -> None:
    catalog = _build_catalog(
        embedding_profile={
            "id": "embedding-p",
            "name": "Embedding",
            "binding": "vllm",
            "base_url": "http://localhost:1234/v1/embeddings",
            "api_key": "local-secret",
            "api_version": "",
            "extra_headers": {},
            "models": [{"id": "embedding-m", "name": "m", "model": "text-embedding-model"}],
        }
    )
    resolved = resolve_embedding_runtime_config(catalog=catalog)
    assert resolved.provider_name == "vllm"
    assert resolved.provider_mode == "local"
    assert resolved.api_key == "local-secret"


def test_embedding_openai_default_base_injected() -> None:
    catalog = _build_catalog(
        embedding_profile={
            "id": "embedding-p",
            "name": "Embedding",
            "binding": "openai",
            "base_url": "",
            "api_key": "sk-test",
            "api_version": "",
            "extra_headers": {},
            "models": [{"id": "embedding-m", "name": "m", "model": "text-embedding-3-large"}],
        }
    )
    resolved = resolve_embedding_runtime_config(catalog=catalog)
    assert resolved.provider_name == "openai"
    # v1.3.0: provider defaults are full embedding endpoint URLs.
    assert resolved.effective_url == "https://api.openai.com/v1/embeddings"


def test_embedding_send_dimensions_default_is_none() -> None:
    """Catalogs without the field should resolve to ``None`` (Auto behaviour)."""
    catalog = _build_catalog()  # default model has no `send_dimensions`
    resolved = resolve_embedding_runtime_config(catalog=catalog)
    assert resolved.send_dimensions is None


@pytest.mark.parametrize(
    ("catalog_value", "expected"),
    [
        (True, True),
        (False, False),
        ("true", True),
        ("false", False),
        ("on", True),
        ("off", False),
        ("", None),
        ("garbage", None),
    ],
)
def test_embedding_send_dimensions_parsed_from_catalog(
    catalog_value: object,
    expected: bool | None,
) -> None:
    catalog = _build_catalog(
        embedding_model={
            "id": "embedding-m",
            "name": "m",
            "model": "text-embedding-v4",
            "dimension": "1024",
            "send_dimensions": catalog_value,
        }
    )
    resolved = resolve_embedding_runtime_config(catalog=catalog)
    assert resolved.send_dimensions is expected


def test_embedding_send_dimensions_catalog_unset_stays_auto() -> None:
    catalog = _build_catalog()
    resolved = resolve_embedding_runtime_config(catalog=catalog)
    assert resolved.send_dimensions is None


def test_embedding_send_dimensions_resolves_from_catalog() -> None:
    catalog = _build_catalog(
        embedding_model={
            "id": "embedding-m",
            "name": "m",
            "model": "text-embedding-3-large",
            "dimension": "3072",
            "send_dimensions": True,
        }
    )
    resolved = resolve_embedding_runtime_config(catalog=catalog)
    assert resolved.send_dimensions is True


def test_embedding_custom_openai_sdk_uses_user_supplied_base_url() -> None:
    """Legacy `custom_openai_sdk` configs still resolve for backwards compatibility."""
    catalog = _build_catalog(
        embedding_profile={
            "id": "embedding-p",
            "name": "Embedding",
            "binding": "custom_openai_sdk",
            "base_url": "https://my-proxy.example.com/v1",
            "api_key": "sk-custom",
            "api_version": "",
            "extra_headers": {},
            "models": [
                {
                    "id": "embedding-m",
                    "name": "m",
                    "model": "text-embedding-3-large",
                    "dimension": "3072",
                }
            ],
        }
    )
    resolved = resolve_embedding_runtime_config(catalog=catalog)
    assert resolved.provider_name == "custom_openai_sdk"
    assert resolved.binding == "custom_openai_sdk"
    assert resolved.effective_url == "https://my-proxy.example.com/v1"
    assert resolved.api_key == "sk-custom"


def test_embedding_openrouter_default_base_url_injected() -> None:
    """When no base URL is set, the OpenRouter spec's default fills in."""
    catalog = _build_catalog(
        embedding_profile={
            "id": "embedding-p",
            "name": "Embedding",
            "binding": "openrouter",
            "base_url": "",
            "api_key": "sk-or-xxxxx",
            "api_version": "",
            "extra_headers": {},
            "models": [
                {
                    "id": "embedding-m",
                    "name": "m",
                    "model": "qwen/qwen3-embedding-8b",
                }
            ],
        }
    )
    resolved = resolve_embedding_runtime_config(catalog=catalog)
    assert resolved.provider_name == "openrouter"
    assert resolved.binding == "openrouter"
    assert resolved.effective_url == "https://openrouter.ai/api/v1/embeddings"
    assert EMBEDDING_PROVIDERS["openrouter"].adapter == "openai_compat"


def test_embedding_openrouter_profile_key() -> None:
    catalog = _build_catalog(
        embedding_profile={
            "id": "embedding-p",
            "name": "Embedding",
            "binding": "openrouter",
            "base_url": "",
            "api_key": "sk-or-from-profile",
            "api_version": "",
            "extra_headers": {},
            "models": [{"id": "embedding-m", "name": "m", "model": "qwen/qwen3-embedding-8b"}],
        }
    )
    resolved = resolve_embedding_runtime_config(catalog=catalog)
    assert resolved.provider_name == "openrouter"
    assert resolved.api_key == "sk-or-from-profile"


def test_embedding_provider_profile_key() -> None:
    catalog = _build_catalog(
        embedding_profile={
            "id": "embedding-p",
            "name": "Embedding",
            "binding": "cohere",
            "base_url": "",
            "api_key": "cohere-test-key",
            "api_version": "",
            "extra_headers": {},
            "models": [{"id": "embedding-m", "name": "m", "model": "embed-v4.0"}],
        }
    )
    resolved = resolve_embedding_runtime_config(catalog=catalog)
    assert resolved.provider_name == "cohere"
    assert resolved.api_key == "cohere-test-key"
