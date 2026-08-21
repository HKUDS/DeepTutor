"""Tests for LLM error mapping helpers."""

from datetime import datetime, timezone

from deeptutor.services.llm.error_mapping import map_error, retry_after_seconds
from deeptutor.services.llm.exceptions import (
    LLMAPIError,
    LLMAuthenticationError,
    LLMProviderTransportError,
    LLMRateLimitError,
    ProviderContextWindowError,
)


class DummyError(Exception):
    """Custom error used for mapping tests."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def test_map_error_status_code_auth() -> None:
    """401 errors should map to authentication failures."""
    mapped = map_error(DummyError("auth failed", status_code=401), provider="openai")
    assert isinstance(mapped, LLMAuthenticationError)


def test_map_error_status_code_rate_limit() -> None:
    """429 errors should map to rate limit failures."""
    mapped = map_error(DummyError("rate limited", status_code=429), provider="openai")
    assert isinstance(mapped, LLMRateLimitError)


def test_map_error_preserves_retry_after_header() -> None:
    error = DummyError("rate limited", status_code=429)
    error.response = type(
        "Response",
        (),
        {"headers": {"Retry-After": "12.5"}},
    )()

    mapped = map_error(error, provider="openai")

    assert isinstance(mapped, LLMRateLimitError)
    assert mapped.retry_after == 12.5


def test_retry_after_seconds_parses_http_date() -> None:
    error = DummyError("temporarily unavailable", status_code=503)
    error.response = type(
        "Response",
        (),
        {"headers": {"Retry-After": "Wed, 21 Oct 2015 07:28:10 GMT"}},
    )()

    delay = retry_after_seconds(
        error,
        now=datetime(2015, 10, 21, 7, 28, tzinfo=timezone.utc),
    )

    assert delay == 10.0


def test_map_error_message_context_window() -> None:
    """Context length errors should map to the provider context window error."""
    mapped = map_error(DummyError("maximum context length exceeded"), provider="openai")
    assert isinstance(mapped, ProviderContextWindowError)


def test_map_error_falls_back_to_api_error() -> None:
    """Unknown errors should fall back to generic API error mapping."""
    mapped = map_error(DummyError("boom", status_code=500), provider="openai")
    assert isinstance(mapped, LLMAPIError)
    assert mapped.status_code == 500


def test_map_error_preserves_structured_transport_error() -> None:
    error = LLMProviderTransportError("provider connection failed")

    mapped = map_error(error, provider="openai_codex")

    assert mapped is error
    assert mapped.provider == "openai_codex"
