"""Tests for normalized embedding runtime resolution."""

from __future__ import annotations

import pytest

from deeptutor.services.config.embedding_endpoint import normalize_embedding_endpoint_for_display
from deeptutor.services.config.provider_runtime import (
    EMBEDDING_PROVIDERS,
    resolve_embedding_runtime_config,
)
from deeptutor.services.embedding.config import get_embedding_config

NATIVE_GEMINI2_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-2:batchEmbedContents"
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


def test_lemonade_embedding_is_local_even_for_qwen_model_and_docker_hostname() -> None:
    catalog = _build_catalog(
        embedding_profile={
            "id": "embedding-p",
            "name": "Lemonade Server",
            "binding": "lemonade",
            "base_url": "http://lemonade:13305/api/v1/embeddings",
            "api_key": "",
            "models": [
                {
                    "id": "embedding-m",
                    "name": "Qwen3",
                    "model": "Qwen3-Embedding-0.6B-GGUF",
                }
            ],
        }
    )

    resolved = resolve_embedding_runtime_config(catalog=catalog)
    assert resolved.provider_name == "lemonade"
    assert resolved.provider_mode == "local"
    assert resolved.api_key == ""
    assert get_embedding_config(catalog=catalog).effective_url == (
        "http://lemonade:13305/api/v1/embeddings"
    )
    assert normalize_embedding_endpoint_for_display("lemonade", "http://localhost:13305/v1") == (
        "http://localhost:13305/v1/embeddings"
    )


def test_lemonade_connection_shared_from_llm_resolves_embedding_endpoint() -> None:
    catalog = _build_catalog(
        embedding_profile={
            "id": "embedding-p",
            "name": "Lemonade embedding",
            "provider_ref": {"connection_id": "lemonade-connection"},
            "models": [
                {
                    "id": "embedding-m",
                    "model": "Qwen3-Embedding-0.6B-GGUF",
                }
            ],
        }
    )
    catalog["connections"] = [
        {
            "id": "lemonade-connection",
            "name": "Lemonade Server",
            "binding": "lemonade",
            "base_url": "http://lemonade:13305/api/v1",
            "api_key": "",
            "source_service": "llm",
        }
    ]

    resolved = resolve_embedding_runtime_config(catalog=catalog)
    assert resolved.provider_name == "lemonade"
    assert resolved.provider_mode == "local"
    assert resolved.effective_url == "http://lemonade:13305/api/v1/embeddings"
    assert get_embedding_config(catalog=catalog).api_key == ""


def test_legacy_custom_lemonade_endpoint_stays_keyless() -> None:
    catalog = _build_catalog(
        embedding_profile={
            "id": "embedding-p",
            "binding": "custom",
            "base_url": "http://localhost:13305/v1/embeddings",
            "api_key": "",
            "models": [
                {
                    "id": "embedding-m",
                    "model": "Qwen3-Embedding-0.6B-GGUF",
                }
            ],
        }
    )

    resolved = resolve_embedding_runtime_config(catalog=catalog)
    assert resolved.provider_name == "lemonade"
    assert get_embedding_config(catalog=catalog).api_key == ""


def test_explicit_openai_binding_to_local_lemonade_is_keyless() -> None:
    catalog = _build_catalog(
        embedding_profile={
            "id": "embedding-p",
            "binding": "openai",
            "base_url": "http://lemonade:13305/api/v1/embeddings",
            "api_key": "",
            "models": [
                {
                    "id": "embedding-m",
                    "model": "Qwen3-Embedding-0.6B-GGUF",
                }
            ],
        }
    )

    resolved = resolve_embedding_runtime_config(catalog=catalog)
    assert resolved.provider_name == "lemonade"
    assert resolved.provider_mode == "local"
    assert get_embedding_config(catalog=catalog).api_key == ""


def test_lan_lemonade_openai_binding_is_keyless() -> None:
    """Unraid/Docker OpenAI-compatible Lemonade roots must not demand a key."""
    catalog = _build_catalog(
        embedding_profile={
            "id": "embedding-p",
            "binding": "openai",
            "base_url": "http://192.168.1.40:13305/api/v1",
            "api_key": "",
            "models": [
                {
                    "id": "embedding-m",
                    "model": "Qwen3-Embedding-0.6B-GGUF",
                }
            ],
        }
    )

    resolved = resolve_embedding_runtime_config(catalog=catalog)
    assert resolved.provider_name == "lemonade"
    assert resolved.provider_mode == "local"
    assert resolved.effective_url == "http://192.168.1.40:13305/api/v1/embeddings"
    assert get_embedding_config(catalog=catalog).api_key == ""


def test_docker_host_lemonade_root_is_keyless() -> None:
    catalog = _build_catalog(
        embedding_profile={
            "id": "embedding-p",
            "binding": "custom",
            "base_url": "http://host.docker.internal:13305",
            "api_key": "",
            "models": [
                {
                    "id": "embedding-m",
                    "model": "Qwen3-Embedding-0.6B-GGUF",
                }
            ],
        }
    )

    resolved = resolve_embedding_runtime_config(catalog=catalog)
    assert resolved.provider_name == "lemonade"
    assert resolved.provider_mode == "local"
    assert resolved.effective_url == "http://host.docker.internal:13305/v1/embeddings"
    config = get_embedding_config(catalog=catalog)
    assert config.api_key == ""
    assert config.effective_url == "http://host.docker.internal:13305/v1/embeddings"


def test_remote_openai_compatible_endpoint_still_requires_key() -> None:
    catalog = _build_catalog(
        embedding_profile={
            "id": "embedding-p",
            "binding": "openai",
            "base_url": "https://api.example.com:13305/api/v1/embeddings",
            "api_key": "",
            "models": [
                {
                    "id": "embedding-m",
                    "model": "Qwen3-Embedding-0.6B-GGUF",
                }
            ],
        }
    )

    resolved = resolve_embedding_runtime_config(catalog=catalog)
    assert resolved.provider_name == "openai"
    assert resolved.provider_mode != "local"
    with pytest.raises(ValueError, match="Embedding API key not set"):
        get_embedding_config(catalog=catalog)


def test_embedding_orcarouter_uses_explicit_custom_endpoint() -> None:
    catalog = _build_catalog(
        embedding_profile={
            "id": "embedding-p",
            "name": "Embedding",
            "binding": "custom",
            "base_url": "https://api.orcarouter.ai/v1/embeddings",
            "api_key": "sk-orca-test-key",
            "api_version": "",
            "extra_headers": {},
            "models": [
                {
                    "id": "embedding-m",
                    "name": "orcarouter",
                    "model": "openai/text-embedding-3-large",
                    "dimension": "3072",
                }
            ],
        }
    )
    resolved = resolve_embedding_runtime_config(catalog=catalog)
    assert resolved.provider_name == "custom"
    assert resolved.provider_mode == "direct"
    assert resolved.effective_url == "https://api.orcarouter.ai/v1/embeddings"
    assert resolved.dimension == 3072


def test_embedding_opper_binding_uses_default_endpoint() -> None:
    catalog = _build_catalog(
        embedding_profile={
            "id": "embedding-p",
            "name": "Embedding",
            "binding": "opper",
            "base_url": "",
            "api_key": "opper-key",
            "api_version": "",
            "extra_headers": {},
            "models": [
                {
                    "id": "embedding-m",
                    "name": "opper",
                    "model": "openai/text-embedding-3-large",
                    "dimension": "3072",
                }
            ],
        }
    )
    resolved = resolve_embedding_runtime_config(catalog=catalog)
    assert resolved.provider_name == "opper"
    assert resolved.provider_mode == "standard"
    assert resolved.effective_url == "https://api.opper.ai/v3/compat/embeddings"
    assert resolved.dimension == 3072


def test_embedding_runtime_preserves_api_key_array() -> None:
    catalog = _build_catalog(
        embedding_profile={
            "id": "embedding-p",
            "name": "Embedding pool",
            "binding": "openai",
            "base_url": "https://api.example.com/v1/embeddings",
            "api_key": ["key-a", "key-b"],
            "api_version": "",
            "extra_headers": {},
            "models": [
                {
                    "id": "embedding-m",
                    "name": "m",
                    "model": "text-embedding-3-small",
                    "dimension": "1536",
                }
            ],
        }
    )
    assert resolve_embedding_runtime_config(catalog=catalog).api_key == ["key-a", "key-b"]


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
    """An existing gemini-embedding-001 profile with no explicit endpoint must
    keep the OpenAI-compatible URL — the native route sends a taskType and
    L2-normalizes, so moving it would invalidate the index built from it."""
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


def test_embedding_gemini_defaults_to_stable_embedding2() -> None:
    spec = EMBEDDING_PROVIDERS["gemini"]

    assert spec.adapter == "gemini"
    assert spec.default_model == "gemini-embedding-2"
    assert spec.default_dim == 3072
    assert spec.default_api_base == NATIVE_GEMINI2_ENDPOINT


def test_embedding_gemini_embedding2_defaults_to_the_native_endpoint() -> None:
    """Embedding 2 is new, so nothing has an index on it yet — it can default
    straight to the native batch endpoint that carries its features."""
    catalog = _build_catalog(
        embedding_profile={
            "id": "embedding-p",
            "name": "Embedding",
            "binding": "gemini",
            "base_url": "",
            "api_key": "gemini-test-key",
            "api_version": "",
            "extra_headers": {},
            "models": [
                {
                    "id": "embedding-m",
                    "name": "m",
                    "model": "gemini-embedding-2",
                }
            ],
        }
    )

    resolved = resolve_embedding_runtime_config(catalog=catalog)

    assert resolved.effective_url == NATIVE_GEMINI2_ENDPOINT


def test_embedding_gemini_explicit_native_endpoint_opts_any_model_in() -> None:
    """A saved native URL is used verbatim, which is how an older model can
    still be pointed at the native route deliberately."""
    catalog = _build_catalog(
        embedding_profile={
            "id": "embedding-p",
            "name": "Embedding",
            "binding": "gemini",
            "base_url": NATIVE_GEMINI2_ENDPOINT,
            "api_key": "gemini-test-key",
            "api_version": "",
            "extra_headers": {},
            "models": [
                {
                    "id": "embedding-m",
                    "name": "m",
                    "model": "gemini-embedding-2",
                }
            ],
        }
    )

    resolved = resolve_embedding_runtime_config(catalog=catalog)

    assert resolved.effective_url == NATIVE_GEMINI2_ENDPOINT


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


@pytest.mark.parametrize("binding", ["openai", "custom"])
def test_generic_local_embedding_endpoint_accepts_empty_key(binding):
    catalog = _build_catalog(
        embedding_profile={
            "id": "embedding-p",
            "binding": binding,
            "base_url": "http://localhost:1234/v1/embeddings",
            "api_key": "",
            "models": [{"id": "embedding-m", "model": "local-embedding"}],
        }
    )
    config = get_embedding_config(catalog=catalog)
    assert config.provider_mode == "local"
    assert config.api_key == ""
    assert config.effective_url == "http://localhost:1234/v1/embeddings"


def test_invalid_lemonade_port_does_not_raise_during_detection():
    from deeptutor.services.config.provider_runtime import _is_legacy_lemonade_endpoint

    assert not _is_legacy_lemonade_endpoint("http://localhost:not-a-port/v1")


@pytest.mark.parametrize(
    "endpoint, expected",
    [
        ("http://localhost:11434/v1/embeddings", "vllm"),
        ("http://localhost:1234/v1/embeddings?model=11434", "vllm"),
        ("http://localhost:11434/api/embed", "ollama"),
        ("http://localhost:9000/api/embed", "ollama"),
    ],
)
def test_local_embedding_protocol_follows_endpoint_path(endpoint, expected):
    catalog = _build_catalog(
        embedding_profile={
            "id": "embedding-p",
            "binding": "openai",
            "base_url": endpoint,
            "api_key": "",
            "models": [{"id": "embedding-m", "model": "nomic-embed-text"}],
        }
    )
    config = get_embedding_config(catalog=catalog)
    assert config.binding == expected
    assert config.effective_url == endpoint
    assert config.api_key == ""
