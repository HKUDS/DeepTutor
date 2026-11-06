from __future__ import annotations

import asyncio
import contextlib
from typing import Any

import pytest
import pytest_asyncio

from deeptutor.services.llm import provider_factory
from deeptutor.services.llm.config import LLMConfig
from deeptutor.services.llm.provider_core.base import LLMResponse


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


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["complete", "stream"])
@pytest.mark.parametrize("invalidation", ["evict", "reset", "close"])
@pytest.mark.parametrize("outcome", ["success", "error", "cancel"])
async def test_invalidation_preserves_inflight_factory_request(
    monkeypatch, mode, invalidation, outcome
) -> None:
    from deeptutor.services.llm import factory

    started = asyncio.Event()
    release = asyncio.Event()

    class BlockingProvider(_FakeProvider):
        async def chat_with_retry(self, **kwargs):
            started.set()
            await release.wait()
            assert self.closed == 0
            if outcome == "error":
                raise RuntimeError("request failed")
            return LLMResponse(content="answer")

        async def chat_stream_with_retry(self, **kwargs):
            await kwargs["on_content_delta"]("first ")
            response = await self.chat_with_retry(**kwargs)
            await kwargs["on_content_delta"](response.content)
            return response

    provider = BlockingProvider()
    monkeypatch.setattr(factory, "get_llm_config", _config)
    monkeypatch.setattr(
        provider_factory,
        "_build_runtime_provider",
        lambda config: provider if config.model == "test-model" else _FakeProvider(),
    )

    async def request():
        if mode == "complete":
            return await factory.complete("hello")
        return "".join([part async for part in factory.stream("hello")])

    task = asyncio.create_task(request())
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        if invalidation == "evict":
            for index in range(provider_factory._PROVIDER_POOL_MAXSIZE):
                provider_factory.get_runtime_provider(_config(model=f"other-{index}"))
        elif invalidation == "reset":
            provider_factory.reset_runtime_provider_pool()
        else:
            await provider_factory.close_runtime_provider_pool()
        await asyncio.sleep(0)
        assert provider.closed == 0, "in-flight request lost its SDK client"
        assert (
            provider_factory.runtime_provider_pool_size() <= provider_factory._PROVIDER_POOL_MAXSIZE
        )

        if outcome == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            release.set()
            if outcome == "error":
                from deeptutor.services.llm.exceptions import LLMAPIError

                with pytest.raises(LLMAPIError, match="request failed"):
                    await asyncio.wait_for(task, timeout=5)
            else:
                assert await asyncio.wait_for(task, timeout=5) == (
                    "answer" if mode == "complete" else "first answer"
                )
        await asyncio.sleep(0)
        assert provider.closed == 1
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_retired_provider_closes_after_last_lease_and_new_request_gets_fresh_client(
    monkeypatch,
) -> None:
    monkeypatch.setattr(provider_factory, "_build_runtime_provider", lambda _: _FakeProvider())

    with provider_factory.acquire_runtime_provider(_config()) as first:
        with provider_factory.acquire_runtime_provider(_config()) as second:
            assert first is second
            provider_factory.reset_runtime_provider_pool()
            with provider_factory.acquire_runtime_provider(_config()) as replacement:
                assert replacement is not first
            await asyncio.sleep(0)
            assert first.closed == replacement.closed == 0
        await asyncio.sleep(0)
        assert first.closed == 0
    await asyncio.sleep(0)
    assert first.closed == 1
    assert replacement.closed == 0
    await provider_factory.close_runtime_provider_pool()
    assert first.closed == replacement.closed == 1


@pytest.mark.asyncio
async def test_closing_stream_reader_releases_retired_provider(monkeypatch) -> None:
    from deeptutor.services.llm import factory

    class StreamingProvider(_FakeProvider):
        async def chat_stream_with_retry(self, **kwargs):
            await kwargs["on_content_delta"]("partial")
            await asyncio.Event().wait()

    provider = StreamingProvider()
    monkeypatch.setattr(factory, "get_llm_config", _config)
    monkeypatch.setattr(provider_factory, "_build_runtime_provider", lambda _: provider)
    async with contextlib.aclosing(factory.stream("hello")) as reader:
        assert await asyncio.wait_for(anext(reader), timeout=5) == "partial"
        provider_factory.reset_runtime_provider_pool()
        await asyncio.sleep(0)
        assert provider.closed == 0
    await asyncio.sleep(0)
    assert provider.closed == 1


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
