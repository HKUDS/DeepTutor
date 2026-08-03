"""Tests for exact, user-visible embedding endpoint normalization."""

from deeptutor.services.config.embedding_endpoint import (
    embedding_endpoint_validation_error,
    gemini_embedding_endpoint,
    normalize_embedding_endpoint_for_display,
    redact_embedding_endpoint_for_display,
)


def test_gemini_native_endpoint_uses_selected_model() -> None:
    endpoint = gemini_embedding_endpoint("models/gemini-embedding-001")

    assert endpoint == (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "gemini-embedding-001:batchEmbedContents"
    )


def test_embedding_endpoint_display_redacts_query_credentials() -> None:
    displayed = redact_embedding_endpoint_for_display(
        "https://proxy.example.com/v1/embeddings?tenant=demo&key=secret"
    )

    assert displayed == ("https://proxy.example.com/v1/embeddings?tenant=demo&key=%5BREDACTED%5D")


def test_blank_gemini_endpoint_defaults_to_native_stable_model() -> None:
    endpoint = normalize_embedding_endpoint_for_display("gemini", "")

    assert endpoint == (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "gemini-embedding-2:batchEmbedContents"
    )


def test_blank_gemini_endpoint_keeps_older_models_on_the_openai_path() -> None:
    """Only Embedding 2 defaults to the native route: the native one sends a
    taskType and L2-normalizes, so defaulting an existing 001 profile there
    would change its document vectors and invalidate its index."""
    endpoint = normalize_embedding_endpoint_for_display(
        "gemini",
        "",
        model="gemini-embedding-001",
    )

    assert endpoint == "https://generativelanguage.googleapis.com/v1beta/openai/embeddings"


def test_official_gemini_native_endpoint_tracks_model_selection() -> None:
    endpoint = normalize_embedding_endpoint_for_display(
        "gemini",
        (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            "gemini-embedding-2:batchEmbedContents"
        ),
        model="gemini-embedding-001",
    )

    assert endpoint.endswith("/models/gemini-embedding-001:batchEmbedContents")


def test_custom_gemini_native_gateway_preserves_prefix_and_tracks_model() -> None:
    endpoint = normalize_embedding_endpoint_for_display(
        "gemini",
        (
            "https://proxy.example.com/google/v1beta/models/"
            "gemini-embedding-001:batchEmbedContents?tenant=demo"
        ),
        model="gemini-embedding-2",
    )

    assert endpoint == (
        "https://proxy.example.com/google/v1beta/models/"
        "gemini-embedding-2:batchEmbedContents?tenant=demo"
    )


def test_gemini_legacy_openai_endpoint_is_preserved() -> None:
    endpoint = normalize_embedding_endpoint_for_display(
        "gemini",
        "https://generativelanguage.googleapis.com/v1beta/openai/embeddings",
        model="gemini-embedding-001",
    )

    assert endpoint.endswith("/v1beta/openai/embeddings")


def test_gemini_custom_v1_base_keeps_legacy_normalization() -> None:
    endpoint = normalize_embedding_endpoint_for_display(
        "gemini",
        "https://proxy.example.com/google/v1",
        model="gemini-embedding-2",
    )

    assert endpoint == "https://proxy.example.com/google/v1/embeddings"

    no_scheme = normalize_embedding_endpoint_for_display(
        "gemini",
        "localhost:8000/v1?tenant=demo",
        model="gemini-embedding-2",
    )
    assert no_scheme == "localhost:8000/v1/embeddings?tenant=demo"


def test_gemini_validation_accepts_native_and_legacy_endpoint_shapes() -> None:
    native = gemini_embedding_endpoint("gemini-embedding-2")
    legacy = "https://generativelanguage.googleapis.com/v1beta/openai/embeddings"
    custom_legacy = "https://proxy.example.com/google/v1/embeddings"

    assert embedding_endpoint_validation_error("gemini", native) is None
    assert embedding_endpoint_validation_error("gemini", legacy) is None
    assert embedding_endpoint_validation_error("gemini", custom_legacy) is None


def test_gemini_validation_rejects_non_embedding_endpoint() -> None:
    problem = embedding_endpoint_validation_error(
        "gemini", "https://generativelanguage.googleapis.com/v1beta/models"
    )

    assert problem is not None
    assert ":batchEmbedContents" in problem

    malformed_native = embedding_endpoint_validation_error(
        "gemini", "https://proxy.example.com/embed:batchEmbedContents"
    )
    assert malformed_native is not None
    assert "/models/" in malformed_native
