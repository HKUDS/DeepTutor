from __future__ import annotations

import httpx

from deeptutor.services.llm.request_compat import (
    error_text,
    is_image_input_unsupported,
    is_stream_options_unsupported,
    is_tool_schema_unsupported,
    is_transient_transport_error,
)


class _Response:
    text = "Unsupported parameter: stream_options"


class _ProviderError(Exception):
    response = _Response()


def test_error_text_prefers_provider_response_body() -> None:
    assert error_text(_ProviderError("generic message")) == (
        "unsupported parameter: stream_options"
    )


def test_request_compatibility_classifiers_match_known_provider_errors() -> None:
    assert is_stream_options_unsupported(ValueError("unknown parameter: stream_options"))
    assert is_tool_schema_unsupported(ValueError("function_declaration is unsupported"))
    assert is_image_input_unsupported(ValueError("content must be a string"))


def test_request_compatibility_classifiers_ignore_unrelated_errors() -> None:
    error = RuntimeError("rate limit exceeded")

    assert not is_stream_options_unsupported(error)
    assert not is_tool_schema_unsupported(error)
    assert not is_image_input_unsupported(error)


def test_transient_transport_classifier_walks_wrapped_causes() -> None:
    try:
        try:
            raise httpx.ReadError("peer closed the stream")
        except httpx.ReadError as cause:
            raise RuntimeError("provider request failed") from cause
    except RuntimeError as error:
        assert is_transient_transport_error(error)


def test_transient_transport_classifier_excludes_provider_rejections() -> None:
    assert not is_transient_transport_error(RuntimeError("401 invalid API key"))
    assert not is_transient_transport_error(RuntimeError("429 rate limit exceeded"))


def test_logged_error_text_is_bounded() -> None:
    """A provider that echoes the request back must not fill the log with it.

    The log line exists so a user can attach it to a bug report, so an
    unbounded body would put the request — tool schemas, sometimes the
    messages — into a file headed for a public issue.
    """
    from deeptutor.services.llm.request_compat import (
        _MAX_LOGGED_ERROR_CHARS,
        logged_error_text,
    )

    short = ValueError("unsupported parameter: tools")
    assert logged_error_text(short) == "unsupported parameter: tools"

    huge = ValueError("x" * (_MAX_LOGGED_ERROR_CHARS + 500))
    bounded = logged_error_text(huge)
    assert bounded.startswith("x" * 50)
    assert len(bounded) < _MAX_LOGGED_ERROR_CHARS + 40
    assert bounded.endswith("(+500 chars)")
