"""A failed provider call must name its own cause instead of only "retry"."""

from __future__ import annotations

from deeptutor.services.llm.exceptions import LLMProviderTransportError
from deeptutor.services.llm.utils import provider_failure_hint


def _transport(message: str) -> LLMProviderTransportError:
    return LLMProviderTransportError(message)


def test_revoked_key_points_at_the_model_settings() -> None:
    hint = provider_failure_hint(
        _transport("Error code: 401 - {'error': {'message': 'Incorrect API key provided'}}")
    )

    assert "API key" in hint
    assert "Settings" in hint


def test_forbidden_is_treated_as_a_rejected_key() -> None:
    hint = provider_failure_hint(_transport("Error code: 403 - forbidden"))

    assert "API key" in hint


def test_rate_limit_is_named_as_such() -> None:
    hint = provider_failure_hint(_transport("Error code: 429 - rate limit reached for requests"))

    assert "rate limiting" in hint


def test_provider_outage_is_attributed_to_the_provider() -> None:
    hint = provider_failure_hint(_transport("Error code: 502 - upstream connect error"))

    assert "HTTP 502" in hint
    assert "provider side" in hint


def test_upstream_marker_without_a_status_still_explains_itself() -> None:
    hint = provider_failure_hint(
        _transport(
            "Error calling LLM: Response failed: upstream_error: "
            "Upstream service temporarily unavailable"
        )
    )

    assert "upstream" in hint
    assert "retry" in hint


def test_missing_channel_names_the_model_setting() -> None:
    hint = provider_failure_hint(
        _transport('{"error":{"code":"model_not_found","message":"No available channel"}}')
    )

    assert "Settings" in hint


def test_timeout_suggests_the_timeout_setting() -> None:
    hint = provider_failure_hint(_transport("Error code: 408 - request timed out"))

    assert "timeout" in hint


def test_unrecognized_failure_adds_nothing() -> None:
    assert provider_failure_hint(_transport("stream stalled for more than 90 seconds")) == ""
