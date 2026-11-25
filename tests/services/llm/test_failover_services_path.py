"""Services path fails over through the factory (#2693 P2 integration)."""

from __future__ import annotations

import contextlib

import pytest

from deeptutor.services.llm import factory, failover
from deeptutor.services.llm.config import LLMConfig
from deeptutor.services.llm.exceptions import LLMRateLimitError
from deeptutor.services.llm.provider_core.base import LLMResponse


def _config(model: str) -> LLMConfig:
    return LLMConfig(model=model, api_key="sk-test", base_url="http://127.0.0.1:9/v1")


class _Provider:
    """Fails on the primary, answers on the backup."""

    def __init__(self, *, fail: bool) -> None:
        self.fail = fail
        self.calls = 0

    async def chat_with_retry(self, **kwargs):  # noqa: ANN003
        self.calls += 1
        if self.fail:
            raise LLMRateLimitError("429")
        return LLMResponse(content="answer from backup", finish_reason="stop")

    async def aclose(self) -> None:
        return None


@pytest.fixture(autouse=True)
def _reset_registry():
    failover.REGISTRY.reset()
    yield
    failover.REGISTRY.reset()


@pytest.mark.asyncio
async def test_complete_falls_back_to_the_declared_candidate(monkeypatch) -> None:
    primary = failover.Candidate("primary", "m1", _config("m1"))
    backup = failover.Candidate("backup", "m2", _config("m2"))
    providers = {"m1": _Provider(fail=True), "m2": _Provider(fail=False)}

    # The factory imported these names at module scope, so patch its namespace.
    monkeypatch.setattr(factory, "chain_configured", lambda: True)
    # The factory builds the chain from the caller's resolved config plus the
    # catalog's declared fallbacks; stand that in with the two fakes.
    monkeypatch.setattr(
        factory,
        "chain_from_config",
        lambda config, owner_id="anonymous": [primary, backup],
    )

    # The factory resolves a provider per candidate; hand out the matching fake.
    def _acquire(config):
        return contextlib.nullcontext(providers[config.model])

    monkeypatch.setattr(factory, "acquire_runtime_provider", _acquire)

    answer = await factory.complete("hello", model="m1")

    assert answer == "answer from backup" or answer.content == "answer from backup"
    assert providers["m1"].calls == 1
    assert providers["m2"].calls == 1
    # Cooling lasts, so the next call starts on the backup without touching m1.
    answer = await factory.complete("again", model="m1")
    assert providers["m1"].calls == 1
    assert providers["m2"].calls == 2
