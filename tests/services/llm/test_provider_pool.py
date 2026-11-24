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


class _LoopRecordingProvider(_FakeProvider):
    """Remembers the event loop each ``aclose`` ran on."""

    def __init__(self) -> None:
        super().__init__()
        self.closed_on: list[asyncio.AbstractEventLoop] = []

    async def aclose(self) -> None:
        self.closed_on.append(asyncio.get_running_loop())
        await super().aclose()


def _lease_on_private_loop(config: LLMConfig) -> None:
    """Use the pool the way synchronous worker-thread callers do (``asyncio.run``)."""

    async def _lease() -> None:
        with provider_factory.acquire_runtime_provider(config):
            await asyncio.sleep(0)

    asyncio.run(_lease())


@pytest.mark.asyncio
async def test_worker_loop_eviction_closes_provider_on_its_own_loop(monkeypatch) -> None:
    built: list[_LoopRecordingProvider] = []

    def _build(_config: LLMConfig) -> _LoopRecordingProvider:
        built.append(_LoopRecordingProvider())
        return built[-1]

    monkeypatch.setattr(provider_factory, "_build_runtime_provider", _build)
    server_loop = asyncio.get_running_loop()
    for index in range(provider_factory._PROVIDER_POOL_MAXSIZE):
        provider_factory.get_runtime_provider(_config(model=f"server-{index}"))

    # A worker thread with its own loop evicts the oldest server-loop client.
    await asyncio.wait_for(
        asyncio.to_thread(_lease_on_private_loop, _config(model="worker")), timeout=5
    )
    for _ in range(3):
        await asyncio.sleep(0)

    evicted = built[0]
    assert evicted.closed_on == [server_loop]


@pytest.mark.asyncio
async def test_finished_worker_loop_does_not_push_server_clients_out(monkeypatch) -> None:
    built: list[_LoopRecordingProvider] = []

    def _build(_config: LLMConfig) -> _LoopRecordingProvider:
        built.append(_LoopRecordingProvider())
        return built[-1]

    monkeypatch.setattr(provider_factory, "_build_runtime_provider", _build)
    server_client = provider_factory.get_runtime_provider(_config())
    await asyncio.wait_for(asyncio.to_thread(_lease_on_private_loop, _config()), timeout=5)
    other_server_client = provider_factory.get_runtime_provider(_config(model="other"))
    await asyncio.sleep(0)

    # The worker's loop is closed, so its entry is dropped instead of evicting
    # the server loop's live client (which may hold warm CLI sessions).
    assert provider_factory.get_runtime_provider(_config()) is server_client
    assert provider_factory.get_runtime_provider(_config(model="other")) is other_server_client
    assert server_client.closed == 0
    assert provider_factory.runtime_provider_pool_size() == 2


@contextlib.contextmanager
def _loop_in_thread():
    """A long-lived loop on its own thread, like the LightRAG worker loop."""
    import threading

    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    try:
        yield loop
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)
        loop.close()


async def _wait_closed(provider: _LoopRecordingProvider) -> None:
    for _ in range(500):
        if provider.closed_on:
            return
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
@pytest.mark.parametrize("how", ["close", "reset", "reset_off_loop"])
async def test_bulk_close_runs_each_provider_on_its_own_loop(monkeypatch, how) -> None:
    monkeypatch.setattr(
        provider_factory, "_build_runtime_provider", lambda _config: _LoopRecordingProvider()
    )
    server_loop = asyncio.get_running_loop()
    server_client = provider_factory.get_runtime_provider(_config())

    async def _lookup_on_worker() -> _LoopRecordingProvider:
        return provider_factory.get_runtime_provider(_config(model="worker"))

    with _loop_in_thread() as worker_loop:
        worker_client = asyncio.run_coroutine_threadsafe(_lookup_on_worker(), worker_loop).result(
            timeout=5
        )
        if how == "close":
            await provider_factory.close_runtime_provider_pool()
        elif how == "reset":
            provider_factory.reset_runtime_provider_pool()
        else:  # a synchronous settings reload from a plain thread
            await asyncio.to_thread(provider_factory.reset_runtime_provider_pool)
        await asyncio.wait_for(_wait_closed(server_client), timeout=5)
        await asyncio.wait_for(_wait_closed(worker_client), timeout=5)

    assert server_client.closed_on == [server_loop]
    assert worker_client.closed_on == [worker_loop]
    assert provider_factory.runtime_provider_pool_size() == 0
