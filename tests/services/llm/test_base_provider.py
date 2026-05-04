"""Tests for BaseLLMProvider retry behavior."""

from __future__ import annotations

import asyncio
from unittest import mock as unittest_mock

import pytest

from deeptutor.services.llm.config import LLMConfig
from deeptutor.services.llm.exceptions import LLMRateLimitError
from deeptutor.services.llm.provider_core.base import LLMProvider, LLMResponse
from deeptutor.services.llm.providers.base_provider import BaseLLMProvider


class DummyProvider(BaseLLMProvider):
    """Minimal provider used for retry tests."""

    async def complete(self, prompt: str, **kwargs: object):
        raise NotImplementedError

    async def stream(self, prompt: str, **kwargs: object):
        raise NotImplementedError


class TestIsTransientError:
    """Tests for _is_transient_error marker detection."""

    def test_stalled_is_transient(self) -> None:
        assert LLMProvider._is_transient_error("stream stalled for more than 30 seconds") is True

    def test_stalled_in_longer_message_is_transient(self) -> None:
        content = "Error calling LLM: stream stalled for more than 30 seconds"
        assert LLMProvider._is_transient_error(content) is True

    def test_rate_limit_is_transient(self) -> None:
        assert LLMProvider._is_transient_error("429 rate limit exceeded") is True

    def test_server_errors_are_transient(self) -> None:
        for code in ("500", "502", "503", "504"):
            assert LLMProvider._is_transient_error(f"{code} server error") is True

    def test_connection_error_is_transient(self) -> None:
        assert LLMProvider._is_transient_error("connection refused") is True

    def test_timeout_is_transient(self) -> None:
        assert LLMProvider._is_transient_error("timeout exceeded") is True

    def test_non_transient_errors_return_false(self) -> None:
        assert LLMProvider._is_transient_error("invalid request") is False
        assert LLMProvider._is_transient_error("unauthorized") is False

    def test_none_returns_false(self) -> None:
        assert LLMProvider._is_transient_error(None) is False

    def test_empty_string_returns_false(self) -> None:
        assert LLMProvider._is_transient_error("") is False


class TestStalledMarkerInProvider:
    """Integration tests verifying 'stalled' marker is in provider transient markers."""

    def test_stalled_marker_present_in_llm_provider(self) -> None:
        assert "stalled" in LLMProvider._TRANSIENT_ERROR_MARKERS

    def test_stalled_marker_is_case_insensitive(self) -> None:
        # _is_transient_error lowercases the content
        assert LLMProvider._is_transient_error("STREAM STALLED") is True
        assert LLMProvider._is_transient_error("Stream Stalled") is True

    def test_stalled_marker_includes_in_longer_error_message(self) -> None:
        """'stalled' is detected even when embedded in a full error message."""
        full_error = "LLMAPIError: [minimax_anthropic] Error calling LLM: stream stalled for more than 300 seconds"
        assert LLMProvider._is_transient_error(full_error) is True


# ---------------------------------------------------------------------------
# Legacy / existing tests
# ---------------------------------------------------------------------------

def test_execute_with_retry_succeeds_after_rate_limit() -> None:
    """execute_with_retry should retry on rate limit errors."""
    config = LLMConfig(model="test", api_key="", base_url="http://localhost:1234")
    provider = DummyProvider(config)
    attempts = {"count": 0}

    async def _call() -> str:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise LLMRateLimitError("rate limited", provider="test")
        return "ok"

    async def _no_sleep(_delay: float) -> None:
        return None

    result = asyncio.run(provider.execute_with_retry(_call, max_retries=2, sleep=_no_sleep))

    assert result == "ok"
    assert attempts["count"] == 3