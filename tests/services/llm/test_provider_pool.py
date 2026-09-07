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


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["github_copilot", "github-copilot"])
async def test_copilot_pool_separates_owners_and_runtime_homes(tmp_path, monkeypatch, name) -> None:
    from deeptutor.multi_user.models import CurrentUser, UserScope
    from deeptutor.multi_user.paths import user_context

    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path / "home-one"))
    monkeypatch.setattr(provider_factory, "_build_runtime_provider", lambda _: _FakeProvider())
    config = _config(binding=name, provider_name=name, api_key="")
    admin = provider_factory.get_runtime_provider(config)
    assert admin is provider_factory.get_runtime_provider(config)
    user = CurrentUser(
        id="u_alice",
        username="alice",
        role="user",
        scope=UserScope(kind="user", user_id="u_alice", root=tmp_path / "alice"),
    )
    with user_context(user):
        alice = provider_factory.get_runtime_provider(config)
        assert alice is provider_factory.get_runtime_provider(config)
        assert alice is not admin
    assert admin is provider_factory.get_runtime_provider(config)
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path / "home-two"))
    assert provider_factory.get_runtime_provider(config) is not admin
