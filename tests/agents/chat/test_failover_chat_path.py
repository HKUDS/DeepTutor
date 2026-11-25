"""Chat path fails over to the next candidate (#2693 P1 integration)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline
from deeptutor.core.context import UnifiedContext
from deeptutor.runtime.agentic.chain_client import ChainClient
from deeptutor.runtime.stream_bus import StreamBus
from deeptutor.services.llm import failover
from deeptutor.services.llm.exceptions import LLMRateLimitError


def _chunk(text: str = "", *, finish: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(content=text, tool_calls=None, reasoning_content=None),
                finish_reason=finish,
                provider_specific_fields=None,
            )
        ],
        usage=None,
    )


class _StreamingClient:
    def __init__(self) -> None:
        self.calls = 0

        async def _stream():
            yield _chunk("Hello ")
            yield _chunk("from the backup.", finish="stop")

        parent = self

        class _Completions:
            async def create(self, **kwargs):  # noqa: ANN003
                parent.calls += 1
                return _stream()

        self.chat = SimpleNamespace(completions=_Completions())


class _FailingClient:
    def __init__(self, exc: Exception) -> None:
        self.calls = 0
        self._exc = exc
        parent = self

        class _Completions:
            async def create(self, **kwargs):  # noqa: ANN003
                parent.calls += 1
                raise parent._exc

        self.chat = SimpleNamespace(completions=_Completions())


class _Registry:
    def deferred_tools(self):
        return []

    def build_prompt_text(self, _enabled, **_kwargs):
        return ""

    def build_openai_schemas(self, _enabled):
        return []

    async def execute(self, *_args, **_kwargs):  # pragma: no cover - no tools here
        raise AssertionError("no tool should run")


@pytest.fixture(autouse=True)
def _clean_registry():
    failover.REGISTRY.reset()
    yield
    failover.REGISTRY.reset()


@pytest.mark.asyncio
async def test_rate_limited_primary_continues_on_the_declared_backup() -> None:
    primary = failover.Candidate("primary", "m1", None)  # type: ignore[arg-type]
    backup = failover.Candidate("backup", "m2", None)  # type: ignore[arg-type]
    failing, working = _FailingClient(LLMRateLimitError("429")), _StreamingClient()
    client = ChainClient([primary, backup], [failing, working], owner_id="u1")

    pipeline = AgenticChatPipeline(language="en")
    pipeline.registry = _Registry()
    pipeline._compose_enabled_tools = lambda _context: []  # type: ignore[method-assign]
    pipeline._build_openai_client = lambda: client  # type: ignore[method-assign]

    bus = StreamBus()
    events: list[Any] = []

    async def consume():
        async for event in bus.subscribe():
            events.append(event)

    # StreamBus needs a subscriber before the run starts.
    import asyncio

    consumer = asyncio.create_task(consume())
    result = await pipeline.run(
        UnifiedContext(session_id="s1", user_message="hi", enabled_tools=[]), bus
    )
    await bus.close()
    await consumer

    streamed = "".join(str(getattr(event, "content", "") or "") for event in events)
    assert "Hello " in streamed and "from the backup." in streamed
    assert failing.calls == 1 and working.calls == 1
    # The failed candidate is cooling down, so the next turn starts on the backup.
    assert failover.REGISTRY.is_available("u1", primary) is False
    codes = [getattr(e, "metadata", {}).get("error_code") for e in events]
    assert "provider_failover" in codes


def test_chain_starts_from_the_turn_model_not_the_catalog_default(monkeypatch) -> None:
    """A per-turn model choice must stay the primary of the chain.

    The user can pick a model in the composer; that turn's client template is
    built from the pick. Seeding the chain from the catalog's active model would
    silently run the turn on the wrong model.
    """
    from deeptutor.runtime.agentic import chain_client as chain_module
    from deeptutor.runtime.agentic.client import LLMClientConfig

    backup = failover.Candidate("backup", "backup-model", None)  # type: ignore[arg-type]
    monkeypatch.setattr(chain_module.failover, "declared_candidates", lambda owner: [backup])
    built: list[object] = []
    monkeypatch.setattr(
        chain_module,
        "build_openai_client",
        lambda config: built.append(config) or object(),
    )

    template = LLMClientConfig(
        binding="openai", model="user-picked-model", api_key="k", base_url="http://x"
    )
    client = chain_module.build_chain_client(template, owner_id="u1")

    assert isinstance(client, chain_module.ChainClient)
    assert client.current.model_id == "user-picked-model"
    assert client.remaining == 1
