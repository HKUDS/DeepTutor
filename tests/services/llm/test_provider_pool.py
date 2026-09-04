from __future__ import annotations

from typing import Any

import pytest
import pytest_asyncio

from deeptutor.services.llm import provider_factory
from deeptutor.services.llm.config import LLMConfig


class _FakeProvider:
    def __init__(self) -> None:
        self.generation: Any = None
        self.closed = 0

    async def aclose(self) -> None:
        self.closed += 1


def _config(**overrides: Any) -> LLMConfig:
    values = {
        "model": "test-model",
        "api_key": "secret",
        "base_url": "https://api.example.test/v1",
        "effective_url": "https://api.example.test/v1",
        "binding": "openai",
        "provider_name": "openai",
        "provider_mode": "standard",
        "extra_headers": {},
    }
    values.update(overrides)
    return LLMConfig(**values)


@pytest_asyncio.fixture(autouse=True)
async def _empty_pool():
    await provider_factory.close_runtime_provider_pool()
    yield
    await provider_factory.close_runtime_provider_pool()


@pytest.mark.asyncio
async def test_runtime_provider_reuses_identical_config(monkeypatch) -> None:
    built: list[_FakeProvider] = []

    def _build(_config: LLMConfig) -> _FakeProvider:
        provider = _FakeProvider()
        built.append(provider)
        return provider

    monkeypatch.setattr(provider_factory, "_build_runtime_provider", _build)

    first = provider_factory.get_runtime_provider(_config())
    second = provider_factory.get_runtime_provider(_config())

    assert first is second
    assert len(built) == 1
    assert provider_factory.runtime_provider_pool_size() == 1


def test_isolated_provider_disables_environment_setup_and_skips_pool(monkeypatch) -> None:
    captured: dict[str, Any] = {}
    provider = _FakeProvider()

    def _build(config: LLMConfig, *, configure_env: bool = True) -> _FakeProvider:
        captured["config"] = config
        captured["configure_env"] = configure_env
        return provider

    monkeypatch.setattr(provider_factory, "_build_runtime_provider", _build)

    result = provider_factory.build_isolated_provider(_config())

    assert result is provider
    assert captured["configure_env"] is False
    assert provider_factory.runtime_provider_pool_size() == 0


@pytest.mark.asyncio
async def test_runtime_provider_pool_is_bounded_and_closes_evictions(monkeypatch) -> None:
    built: list[_FakeProvider] = []

    def _build(_config: LLMConfig) -> _FakeProvider:
        provider = _FakeProvider()
        built.append(provider)
        return provider

    monkeypatch.setattr(provider_factory, "_build_runtime_provider", _build)

    for index in range(provider_factory._PROVIDER_POOL_MAXSIZE + 1):
        provider_factory.get_runtime_provider(_config(model=f"model-{index}"))

    # Eviction closes asynchronously on the owning server loop.
    import asyncio

    await asyncio.sleep(0)
    assert provider_factory.runtime_provider_pool_size() == provider_factory._PROVIDER_POOL_MAXSIZE
    assert built[0].closed == 1


@pytest.mark.asyncio
async def test_reset_closes_all_cached_providers(monkeypatch) -> None:
    built: list[_FakeProvider] = []

    def _build(_config: LLMConfig) -> _FakeProvider:
        provider = _FakeProvider()
        built.append(provider)
        return provider

    monkeypatch.setattr(provider_factory, "_build_runtime_provider", _build)
    provider_factory.get_runtime_provider(_config())

    provider_factory.reset_runtime_provider_pool()
    import asyncio

    await asyncio.sleep(0)
    assert provider_factory.runtime_provider_pool_size() == 0
    assert built[0].closed == 1
