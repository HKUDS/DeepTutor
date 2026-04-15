"""Tests for the circuit breaker state machine."""

from __future__ import annotations

import time
from unittest.mock import patch

from deeptutor.utils.network.circuit_breaker import (
    CircuitBreaker,
    alert_callback,
    is_call_allowed,
    record_call_failure,
    record_call_success,
)


# ---------------------------------------------------------------------------
# CircuitBreaker class
# ---------------------------------------------------------------------------


class TestCircuitBreakerStates:
    """Verify the closed → open → half-open → closed lifecycle."""

    def test_initial_state_is_closed(self) -> None:
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60)
        assert cb.call("provider_a") is True

    def test_stays_closed_below_threshold(self) -> None:
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60)
        cb.record_failure("p")
        cb.record_failure("p")
        assert cb.call("p") is True  # 2 failures < threshold of 3

    def test_opens_at_threshold(self) -> None:
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60)
        for _ in range(3):
            cb.record_failure("p")
        assert cb.state["p"] == "open"
        assert cb.call("p") is False

    def test_transitions_to_half_open_after_recovery_timeout(self) -> None:
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=1)
        cb.record_failure("p")
        cb.record_failure("p")
        assert cb.call("p") is False

        with patch.object(time, "time", return_value=time.time() + 2):
            assert cb.call("p") is True
            assert cb.state["p"] == "half-open"

    def test_half_open_to_closed_on_success(self) -> None:
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0)
        cb.record_failure("p")
        cb.record_failure("p")
        cb.state["p"] = "half-open"
        cb.record_success("p")
        assert cb.state["p"] == "closed"
        assert cb.failure_count["p"] == 0

    def test_success_resets_failure_count_when_explicitly_closed(self) -> None:
        cb = CircuitBreaker(failure_threshold=5, recovery_timeout=60)
        cb.state["p"] = "closed"
        cb.record_failure("p")
        cb.record_failure("p")
        cb.record_success("p")
        assert cb.failure_count["p"] == 0

    def test_success_noop_when_state_unset(self) -> None:
        """When state is not explicitly set, record_success is a no-op."""
        cb = CircuitBreaker(failure_threshold=5, recovery_timeout=60)
        cb.record_failure("p")
        cb.record_success("p")
        assert cb.failure_count["p"] == 1

    def test_independent_providers(self) -> None:
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=60)
        cb.record_failure("a")
        cb.record_failure("a")
        assert cb.call("a") is False
        assert cb.call("b") is True  # different provider unaffected


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------


class TestModuleFunctions:
    def test_alert_callback_records_failure(self) -> None:
        from deeptutor.utils.network import circuit_breaker as mod

        cb = CircuitBreaker(failure_threshold=100, recovery_timeout=60)
        original = mod.circuit_breaker
        mod.circuit_breaker = cb
        try:
            alert_callback("test_provider", 0.5)
            assert cb.failure_count.get("test_provider", 0) == 1
        finally:
            mod.circuit_breaker = original

    def test_is_call_allowed_delegates(self) -> None:
        from deeptutor.utils.network import circuit_breaker as mod

        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=9999)
        original = mod.circuit_breaker
        mod.circuit_breaker = cb
        try:
            assert is_call_allowed("fresh") is True
            record_call_failure("fresh")
            assert is_call_allowed("fresh") is False
            record_call_success("fresh")
        finally:
            mod.circuit_breaker = original

    def test_record_call_success_delegates(self) -> None:
        from deeptutor.utils.network import circuit_breaker as mod

        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0)
        original = mod.circuit_breaker
        mod.circuit_breaker = cb
        try:
            record_call_failure("x")
            cb.state["x"] = "half-open"
            record_call_success("x")
            assert cb.state["x"] == "closed"
        finally:
            mod.circuit_breaker = original
