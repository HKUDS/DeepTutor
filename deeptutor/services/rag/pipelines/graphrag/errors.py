"""Typed, secret-free GraphRAG pipeline errors for API and task reporting."""

from __future__ import annotations

from typing import ClassVar

MODEL_INCOMPATIBLE_MESSAGE = (
    "The model did not accept or return the structured output required by GraphRAG."
)
MODEL_AUTHENTICATION_MESSAGE = (
    "GraphRAG compatibility could not be verified because the model credentials were rejected."
)
MODEL_RATE_LIMIT_MESSAGE = (
    "GraphRAG compatibility could not be verified because the model provider is rate limiting "
    "requests. Try again later."
)
MODEL_CONNECTION_MESSAGE = (
    "GraphRAG compatibility could not be verified because the model provider could not be "
    "reached. Try again later."
)
MODEL_OUTPUT_TRUNCATED_MESSAGE = (
    "GraphRAG compatibility could not be verified because the model response reached its "
    "output token limit. Try again."
)
EMBEDDING_AUTHENTICATION_MESSAGE = (
    "GraphRAG could not use the active embedding model because its credentials were rejected."
)
EMBEDDING_RATE_LIMIT_MESSAGE = (
    "GraphRAG could not use the active embedding model because the provider is rate limiting "
    "requests. Try again later."
)
EMBEDDING_CONNECTION_MESSAGE = (
    "GraphRAG could not reach the active embedding provider. Try again later."
)
EMBEDDING_ENDPOINT_MESSAGE = (
    "The configured GraphRAG embedding model or endpoint was not found. Check the embedding "
    "provider URL and model."
)
EMBEDDING_RESPONSE_MESSAGE = (
    "The active embedding model did not accept or return the vector response required by GraphRAG."
)
EMBEDDING_PROVIDER_UNSUPPORTED_MESSAGE = (
    "GraphRAG currently requires an OpenAI-compatible embedding endpoint. The active embedding "
    "provider uses a native transport; choose its OpenAI-compatible endpoint or another "
    "embedding profile."
)


class GraphRagPipelineError(RuntimeError):
    """Base error carrying stable metadata for GraphRAG pipeline failures."""

    code: ClassVar[str] = "graphrag_failed"
    retryable: ClassVar[bool] = False


class GraphRagModelError(GraphRagPipelineError):
    """Base error carrying stable metadata for GraphRAG model failures."""

    code: ClassVar[str] = "graphrag_model_failed"
    retryable: ClassVar[bool] = False


class GraphRagModelIncompatibleError(GraphRagModelError):
    """Raised when a model cannot satisfy GraphRAG's structured-output contract."""

    code = "graphrag_model_incompatible"


class GraphRagStructuredOutputError(GraphRagModelIncompatibleError, ValueError):
    """Raised when both native and fallback output fail strict schema validation."""


class GraphRagStructuredOutputTruncatedError(GraphRagModelError, ValueError):
    """Raised when strict validation fails because the provider truncated its response."""

    code = "graphrag_model_output_truncated"
    retryable = True

    def __init__(self, _provider_detail: str | None = None) -> None:
        """Discard provider response details and retain only the safe public message."""
        super().__init__(MODEL_OUTPUT_TRUNCATED_MESSAGE)


class GraphRagUnsupportedProviderError(GraphRagModelIncompatibleError):
    """Raised when GraphRAG cannot use a provider's authentication transport."""

    code = "graphrag_provider_unsupported"


class GraphRagModelAuthenticationError(GraphRagModelError):
    """Raised when the provider rejects the configured credentials."""

    code = "graphrag_model_authentication_failed"


class GraphRagModelRateLimitError(GraphRagModelError):
    """Raised when compatibility cannot be checked because of provider throttling."""

    code = "graphrag_model_rate_limited"
    retryable = True


class GraphRagModelConnectionError(GraphRagModelError):
    """Raised when a transient provider or network failure prevents a model call."""

    code = "graphrag_model_connection_failed"
    retryable = True


class GraphRagModelEndpointError(GraphRagModelError):
    """Raised when the configured endpoint or model cannot be found."""

    code = "graphrag_model_endpoint_failed"


class GraphRagEmbeddingError(GraphRagPipelineError):
    """Base error for GraphRAG embedding transport and response failures."""

    code = "graphrag_embedding_failed"


class GraphRagEmbeddingProviderUnsupportedError(GraphRagEmbeddingError):
    """Raised before indexing when the active embedding transport is not supported."""

    code = "graphrag_embedding_provider_unsupported"

    def __init__(self) -> None:
        super().__init__(EMBEDDING_PROVIDER_UNSUPPORTED_MESSAGE)


class GraphRagEmbeddingAuthenticationError(GraphRagEmbeddingError):
    """Raised when GraphRAG embedding credentials are rejected."""

    code = "graphrag_embedding_authentication_failed"


class GraphRagEmbeddingRateLimitError(GraphRagEmbeddingError):
    """Raised when the embedding provider throttles the preflight or indexing call."""

    code = "graphrag_embedding_rate_limited"
    retryable = True


class GraphRagEmbeddingConnectionError(GraphRagEmbeddingError):
    """Raised when the GraphRAG embedding provider cannot be reached."""

    code = "graphrag_embedding_connection_failed"
    retryable = True


class GraphRagEmbeddingEndpointError(GraphRagEmbeddingError):
    """Raised when the GraphRAG embedding model or endpoint returns not found."""

    code = "graphrag_embedding_endpoint_failed"


class GraphRagEmbeddingResponseError(GraphRagEmbeddingError, ValueError):
    """Raised when the embedding provider returns an unusable vector response."""

    code = "graphrag_embedding_incompatible"


class GraphRagEmbeddingProbeError(GraphRagEmbeddingError):
    """Raised when an unexpected internal failure prevents embedding validation."""

    code = "graphrag_embedding_probe_failed"

    def __init__(self) -> None:
        super().__init__(
            "GraphRAG embedding compatibility could not be verified because of an internal error."
        )


class GraphRagEmbeddingDimensionError(GraphRagEmbeddingError, ValueError):
    """Raised when the configured dimension differs from the provider response."""

    code = "graphrag_embedding_dimension_mismatch"

    def __init__(self, *, configured: int, actual: int) -> None:
        super().__init__(
            "The active embedding model returned "
            f"{actual} dimensions, but DeepTutor is configured for {configured}. "
            "Correct the embedding dimension before indexing with GraphRAG."
        )


_FORMAT_MARKERS = (
    "response_format",
    "response format",
    "json_schema",
    "json schema",
    "structured output",
)
_UNSUPPORTED_MARKERS = (
    "unavailable",
    "unsupported",
    "not supported",
    "does not support",
    "not available",
    "not valid",
    "must be",
    "rejected",
)


def is_unsupported_schema_error(error: BaseException) -> bool:
    """Return whether a provider explicitly rejected structured-output format support."""
    if type(error).__name__ not in {
        "BadRequestError",
        "InvalidRequestError",
        "UnsupportedParamsError",
        "UnprocessableEntityError",
    }:
        return False
    message = str(error).lower()
    return any(marker in message for marker in _FORMAT_MARKERS) and any(
        marker in message for marker in _UNSUPPORTED_MARKERS
    )


def _status_code(error: BaseException) -> int | None:
    """Return a provider HTTP status without inspecting or exposing its body."""
    value = getattr(error, "status_code", None)
    if value is None:
        value = getattr(error, "status", None)
    return value if isinstance(value, int) else None


def classify_embedding_error(error: BaseException) -> GraphRagPipelineError | None:
    """Map embedding failures to stable, secret-free GraphRAG error metadata."""
    if isinstance(error, GraphRagPipelineError):
        return error

    error_name = type(error).__name__
    status_code = _status_code(error)
    if error_name in {"AuthenticationError", "PermissionDeniedError"} or status_code in {
        401,
        403,
    }:
        return GraphRagEmbeddingAuthenticationError(EMBEDDING_AUTHENTICATION_MESSAGE)
    if error_name == "RateLimitError" or status_code == 429:
        return GraphRagEmbeddingRateLimitError(EMBEDDING_RATE_LIMIT_MESSAGE)
    if error_name in {"NotFoundError"} or status_code == 404:
        return GraphRagEmbeddingEndpointError(EMBEDDING_ENDPOINT_MESSAGE)
    if error_name in {
        "APIConnectionError",
        "ConnectError",
        "ConnectTimeout",
        "ReadTimeout",
        "ServiceUnavailableError",
        "Timeout",
        "TimeoutError",
    } or (status_code is not None and status_code >= 500):
        return GraphRagEmbeddingConnectionError(EMBEDDING_CONNECTION_MESSAGE)
    if error_name in {
        "BadRequestError",
        "InvalidRequestError",
        "UnprocessableEntityError",
        "UnsupportedParamsError",
    } or status_code in {400, 409, 422}:
        return GraphRagEmbeddingResponseError(EMBEDDING_RESPONSE_MESSAGE)
    return None


def classify_model_error(error: BaseException) -> GraphRagPipelineError | None:
    """Map known provider failures to stable GraphRAG errors without exposing details."""
    if isinstance(error, GraphRagPipelineError):
        return error
    if is_unsupported_schema_error(error):
        return GraphRagModelIncompatibleError(MODEL_INCOMPATIBLE_MESSAGE)

    error_name = type(error).__name__
    if error_name in {"AuthenticationError", "PermissionDeniedError"}:
        return GraphRagModelAuthenticationError(MODEL_AUTHENTICATION_MESSAGE)
    if error_name == "RateLimitError":
        return GraphRagModelRateLimitError(MODEL_RATE_LIMIT_MESSAGE)
    if error_name in {
        "APIConnectionError",
        "ServiceUnavailableError",
        "Timeout",
        "TimeoutError",
    }:
        return GraphRagModelConnectionError(MODEL_CONNECTION_MESSAGE)
    if error_name in {"NotFoundError"} or getattr(error, "status_code", None) == 404:
        return GraphRagModelEndpointError(
            "The configured GraphRAG model or endpoint was not found. Check its provider URL."
        )
    status_code = _status_code(error)
    if error_name == "APIError" and isinstance(status_code, int) and status_code >= 500:
        return GraphRagModelConnectionError(MODEL_CONNECTION_MESSAGE)
    return None


__all__ = [
    "EMBEDDING_AUTHENTICATION_MESSAGE",
    "EMBEDDING_CONNECTION_MESSAGE",
    "EMBEDDING_ENDPOINT_MESSAGE",
    "EMBEDDING_PROVIDER_UNSUPPORTED_MESSAGE",
    "EMBEDDING_RATE_LIMIT_MESSAGE",
    "EMBEDDING_RESPONSE_MESSAGE",
    "GraphRagEmbeddingAuthenticationError",
    "GraphRagEmbeddingConnectionError",
    "GraphRagEmbeddingDimensionError",
    "GraphRagEmbeddingEndpointError",
    "GraphRagEmbeddingError",
    "GraphRagEmbeddingProviderUnsupportedError",
    "GraphRagEmbeddingProbeError",
    "GraphRagEmbeddingRateLimitError",
    "GraphRagEmbeddingResponseError",
    "GraphRagModelAuthenticationError",
    "GraphRagModelConnectionError",
    "GraphRagModelEndpointError",
    "GraphRagModelError",
    "GraphRagModelIncompatibleError",
    "GraphRagModelRateLimitError",
    "GraphRagPipelineError",
    "GraphRagStructuredOutputError",
    "GraphRagStructuredOutputTruncatedError",
    "GraphRagUnsupportedProviderError",
    "MODEL_AUTHENTICATION_MESSAGE",
    "MODEL_CONNECTION_MESSAGE",
    "MODEL_INCOMPATIBLE_MESSAGE",
    "MODEL_OUTPUT_TRUNCATED_MESSAGE",
    "MODEL_RATE_LIMIT_MESSAGE",
    "classify_embedding_error",
    "classify_model_error",
    "is_unsupported_schema_error",
]
