"""Provider-error classifiers used by retry and graceful-degradation paths."""

from __future__ import annotations

import httpx

from .exceptions import LLMProviderTransportError, LLMTimeoutError


def _exception_chain(exc: Exception):
    """Yield an exception and its wrapped causes without looping forever."""
    pending = [exc]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        yield current
        nested = getattr(current, "exceptions", ())
        if isinstance(nested, tuple):
            pending.extend(item for item in nested if isinstance(item, Exception))
        cause = current.__cause__ or current.__context__
        if isinstance(cause, Exception):
            pending.append(cause)


_MAX_LOGGED_ERROR_CHARS = 2000


def logged_error_text(exc: Exception) -> str:
    """``error_text`` bounded for a log line.

    The compat predicates only scan this text, but a log line is different:
    ``data/user/logs/deeptutor.jsonl`` is what a user is asked to attach to a
    bug report, and some providers echo the rejected request back — the tool
    schemas, occasionally the messages themselves. The parameter a provider
    objects to is always near the front, so cap it rather than ship an
    unbounded copy of the request into a file destined for a public issue.
    """
    text = error_text(exc)
    if len(text) <= _MAX_LOGGED_ERROR_CHARS:
        return text
    dropped = len(text) - _MAX_LOGGED_ERROR_CHARS
    return f"{text[:_MAX_LOGGED_ERROR_CHARS]}… (+{dropped} chars)"


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


def is_transient_transport_error(exc: Exception) -> bool:
    """Return whether retrying can recover a provider transport failure.

    Authentication, rate-limit, HTTP-status and response-shape errors are
    intentionally excluded. OpenAI-compatible clients wrap httpx/httpcore
    failures, so the complete exception chain is inspected.
    """
    for current in _exception_chain(exc):
        if isinstance(
            current,
            (
                httpx.TransportError,
                LLMProviderTransportError,
                LLMTimeoutError,
                TimeoutError,
                ConnectionError,
            ),
        ):
            return True
        error_type = type(current)
        module = error_type.__module__
        name = error_type.__name__
        if module.startswith("openai") and name in {
            "APIConnectionError",
            "APITimeoutError",
        }:
            return True
        if module.startswith("httpcore") and name in {
            "ConnectError",
            "ConnectTimeout",
            "ReadError",
            "ReadTimeout",
            "RemoteProtocolError",
            "WriteError",
            "WriteTimeout",
        }:
            return True
    return False


__all__ = [
    "error_text",
    "is_image_input_unsupported",
    "is_stream_options_unsupported",
    "is_transient_transport_error",
    "is_tool_schema_unsupported",
]
