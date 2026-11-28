"""Ordered fallback, cooldown and failback (#2693 P1/P2 core)."""

from __future__ import annotations

import pytest

from deeptutor.services.llm import failover
from deeptutor.services.llm.exceptions import (
    LLMAuthenticationError,
    LLMProviderTransportError,
    LLMRateLimitError,
)


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _candidate(profile: str, model: str = "m") -> failover.Candidate:
    return failover.Candidate(profile, model, None)  # type: ignore[arg-type]


def test_rate_limit_cools_down_then_fails_back() -> None:
    clock = _Clock()
    registry = failover.ProviderHealthRegistry(clock=clock)
    candidate = _candidate("primary")

    assert registry.record_failure("u1", candidate, LLMRateLimitError("429")) == "rate_limit"
    assert registry.is_available("u1", candidate) is False

    clock.advance(failover.RATE_LIMIT_COOLDOWN_S + 1)
    # Cooldown expiry is the failback: the primary is tried again.
    assert registry.is_available("u1", candidate) is True
    assert registry.state_for("u1", candidate) == "closed"


def test_auth_failure_disables_until_config_changes() -> None:
    registry = failover.ProviderHealthRegistry(clock=_Clock())
    candidate = _candidate("primary")

    registry.record_failure("u1", candidate, LLMAuthenticationError("401"))

    assert registry.is_available("u1", candidate) is False
    assert registry.state_for("u1", candidate) == "disabled"


def test_repeated_transport_failures_escalate_the_cooldown() -> None:
    clock = _Clock()
    registry = failover.ProviderHealthRegistry(clock=clock)
    candidate = _candidate("primary")

    registry.record_failure("u1", candidate, LLMProviderTransportError("boom"))
    assert registry.is_available("u1", candidate) is False
    clock.advance(failover.TRANSPORT_COOLDOWN_S + 1)

    # Second failure uses the ladder, not the first-step cooldown again.
    registry.record_failure("u1", candidate, LLMProviderTransportError("boom"))
    clock.advance(failover.TRANSPORT_COOLDOWN_S + 1)
    assert registry.is_available("u1", candidate) is False


def test_health_is_per_owner() -> None:
    registry = failover.ProviderHealthRegistry(clock=_Clock())
    candidate = _candidate("shared-profile")

    registry.record_failure("alice", candidate, LLMRateLimitError("429"))

    assert registry.is_available("alice", candidate) is False
    # Bob's own key is unaffected by Alice's quota.
    assert registry.is_available("bob", candidate) is True


def test_success_clears_the_history() -> None:
    registry = failover.ProviderHealthRegistry(clock=_Clock())
    candidate = _candidate("primary")
    registry.record_failure("u1", candidate, LLMRateLimitError("429"))

    registry.record_success("u1", candidate)

    assert registry.is_available("u1", candidate) is True


def test_ordering_puts_the_active_model_first_and_skips_duplicates() -> None:
    llm = {"active_profile_id": "active", "active_model_id": "m1"}
    declared = [
        {"profile_id": "active", "model_id": "m1"},
        {"profile_id": "backup", "model_id": "m2"},
    ]

    assert failover.active_and_declared(llm, declared) == [
        {"profile_id": "active", "model_id": "m1"},
        {"profile_id": "backup", "model_id": "m2"},
    ]


def test_foreign_replay_state_is_dropped_per_candidate() -> None:
    messages = [
        {"role": "assistant", "content": "hi", "thinking_blocks": [{"type": "thinking"}]},
        {"role": "assistant", "content": "yo", "reasoning_content": "because"},
        {"role": "user", "content": "next", "_provider_response_state": {"x": 1}},
    ]

    cleaned = failover.drop_foreign_message_state(messages)

    assert [set(item) for item in cleaned] == [
        {"role", "content"},
        {"role", "content", "reasoning_content"},
        {"role", "content"},
    ]


@pytest.mark.asyncio
async def test_failover_switches_and_reports(monkeypatch) -> None:
    primary, backup = _candidate("primary"), _candidate("backup")
    monkeypatch.setattr(failover, "resolve_candidates", lambda owner_id="": [primary, backup])
    reports: list[failover.SwitchReport] = []
    calls: list[str] = []

    async def call(candidate):
        calls.append(candidate.profile_id)
        if candidate is primary:
            raise LLMRateLimitError("429", retry_after=30)
        return "answer"

    async def on_switch(report):
        reports.append(report)

    result = await failover.call_with_failover(call, owner_id="u1", on_switch=on_switch)

    assert result == "answer"
    assert calls == ["primary", "backup"]
    assert reports[0].failed is primary
    assert reports[0].next_candidate is backup
    assert reports[0].reason == "rate_limit"


@pytest.mark.asyncio
async def test_cooling_candidate_is_skipped_without_waiting(monkeypatch) -> None:
    primary, backup = _candidate("primary"), _candidate("backup")
    monkeypatch.setattr(failover, "resolve_candidates", lambda owner_id="": [primary, backup])
    failover.REGISTRY.record_failure("u1", primary, LLMRateLimitError("429"))
    calls: list[str] = []

    async def call(candidate):
        calls.append(candidate.profile_id)
        return "answer"

    try:
        assert await failover.call_with_failover(call, owner_id="u1") == "answer"
        assert calls == ["backup"]
    finally:
        failover.REGISTRY.reset()


@pytest.mark.asyncio
async def test_all_candidates_failing_raises_with_the_attempt_list(monkeypatch) -> None:
    primary, backup = _candidate("primary"), _candidate("backup")
    monkeypatch.setattr(failover, "resolve_candidates", lambda owner_id="": [primary, backup])

    async def call(candidate):
        raise LLMProviderTransportError("down")

    with pytest.raises(failover.AllProvidersUnavailable) as raised:
        await failover.call_with_failover(call, owner_id="u2")

    assert len(raised.value.attempted) == 2
    failover.REGISTRY.reset()


@pytest.mark.asyncio
async def test_non_provider_errors_are_not_swallowed(monkeypatch) -> None:
    primary, backup = _candidate("primary"), _candidate("backup")
    monkeypatch.setattr(failover, "resolve_candidates", lambda owner_id="": [primary, backup])
    calls: list[str] = []

    async def call(candidate):
        calls.append(candidate.profile_id)
        raise ValueError("a bug in the caller")

    with pytest.raises(ValueError):
        await failover.call_with_failover(call, owner_id="u3")

    assert calls == ["primary"]
