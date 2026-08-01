"""Typed, secret-free GraphRAG model errors for API and task reporting."""

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


class GraphRagModelError(RuntimeError):
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


def classify_model_error(error: BaseException) -> GraphRagModelError | None:
    """Map known provider failures to stable GraphRAG errors without exposing details."""
    if isinstance(error, GraphRagModelError):
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
    status_code = getattr(error, "status_code", None)
    if error_name == "APIError" and isinstance(status_code, int) and status_code >= 500:
        return GraphRagModelConnectionError(MODEL_CONNECTION_MESSAGE)
    return None


__all__ = [
    "GraphRagModelAuthenticationError",
    "GraphRagModelConnectionError",
    "GraphRagModelEndpointError",
    "GraphRagModelError",
    "GraphRagModelIncompatibleError",
    "GraphRagModelRateLimitError",
    "GraphRagStructuredOutputError",
    "GraphRagStructuredOutputTruncatedError",
    "GraphRagUnsupportedProviderError",
    "MODEL_AUTHENTICATION_MESSAGE",
    "MODEL_CONNECTION_MESSAGE",
    "MODEL_INCOMPATIBLE_MESSAGE",
    "MODEL_OUTPUT_TRUNCATED_MESSAGE",
    "MODEL_RATE_LIMIT_MESSAGE",
    "classify_model_error",
    "is_unsupported_schema_error",
]
