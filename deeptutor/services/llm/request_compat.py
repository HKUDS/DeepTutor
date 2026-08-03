"""Provider-error classifiers used by retry and graceful-degradation paths."""

from __future__ import annotations


def error_text(exc: Exception) -> str:
    """Return the best available lowercase provider error body."""
    response = getattr(exc, "response", None)
    body = (
        getattr(exc, "body", None)
        or getattr(exc, "doc", None)
        or getattr(response, "text", None)
        or getattr(exc, "message", None)
        or str(exc)
    )
    return str(body).lower()


def is_stream_options_unsupported(exc: Exception) -> bool:
    """Whether a provider rejected OpenAI's ``stream_options`` parameter."""
    text = error_text(exc)
    return any(
        marker in text
        for marker in (
            "stream_options",
            "stream options",
            "unknown parameter",
            "unrecognized request argument",
            "unsupported parameter",
            "extra inputs are not permitted",
            "unexpected keyword",
        )
    )


def is_tool_schema_unsupported(exc: Exception) -> bool:
    """Whether a provider rejected native tool/function-calling schemas."""
    text = error_text(exc)
    return any(
        marker in text
        for marker in (
            "tool",
            "function_declaration",
            "function declaration",
            "function_declarations",
            "tool_choice",
            "parameters.properties",
            "404_not_found",
            "404 not_found",
        )
    )


def is_image_input_unsupported(exc: Exception) -> bool:
    """Whether a provider or model rejected multimodal message content."""
    text = error_text(exc)
    return any(
        marker in text
        for marker in (
            "image",
            "vision",
            "multimodal",
            "image_url",
            "content type",
            "must be a string",
            "expected a string",
            "expected string",
            "invalid type for 'messages",
        )
    )


__all__ = [
    "error_text",
    "is_image_input_unsupported",
    "is_stream_options_unsupported",
    "is_tool_schema_unsupported",
]
