"""Mistral embedding provider registration tests."""

from deeptutor.services.config.embedding_endpoint import (
    EMBEDDING_PROVIDER_DEFAULT_ENDPOINTS,
    EMBEDDING_PROVIDER_LABELS,
    embedding_endpoint_validation_error,
    normalize_embedding_endpoint_for_display,
)
from deeptutor.services.config.provider_runtime import EMBEDDING_PROVIDERS


def test_mistral_embedding_provider_spec() -> None:
    spec = EMBEDDING_PROVIDERS["mistral"]

    assert spec.default_model == "mistral-embed"
    assert spec.default_dim == 1024
    assert spec.default_api_base == "https://api.mistral.ai/v1/embeddings"


def test_mistral_embedding_defaults() -> None:
    assert EMBEDDING_PROVIDER_LABELS["mistral"] == "Mistral"
    assert EMBEDDING_PROVIDER_DEFAULT_ENDPOINTS["mistral"] == "https://api.mistral.ai/v1/embeddings"
    assert (
        normalize_embedding_endpoint_for_display("mistral", "")
        == "https://api.mistral.ai/v1/embeddings"
    )


def test_mistral_embedding_endpoint_validation() -> None:
    valid = "https://api.mistral.ai/v1/embeddings"
    assert embedding_endpoint_validation_error("mistral", valid) is None
    assert embedding_endpoint_validation_error("mistral", "https://api.mistral.ai/v1") is not None
