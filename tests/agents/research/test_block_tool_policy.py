"""Research-specific tool execution policy propagation."""

from __future__ import annotations

import pytest

from deeptutor.agents.research.data_structures import DynamicTopicQueue, TopicBlock
from deeptutor.agents.research.pipeline import ResearchPipeline, _BlockLoopHost
from deeptutor.core.context import UnifiedContext
from deeptutor.runtime.agentic.tool_dispatch import DispatchOutcome
from deeptutor.runtime.stream_bus import StreamBus


class _FakeLLM:
    binding = "openai"
    model = "gpt-x"
    api_key = "k"
    base_url = "u"
    api_version = None
    extra_headers = {}


class _FakeRegistry:
    def build_openai_schemas(self, _names):
        return []

    def build_prompt_text(self, _names, **_kwargs):
        return "- none"

    def get(self, _name):
        return None

    def get_enabled(self, _names):
        return []


@pytest.mark.asyncio
async def test_block_host_passes_tool_policy_to_dispatcher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_dispatch_tool_calls(**kwargs):
        captured.update(kwargs)
        return DispatchOutcome()

    monkeypatch.setattr("deeptutor.agents.research.pipeline.get_llm_config", lambda: _FakeLLM())
    monkeypatch.setattr(
        "deeptutor.agents.research.pipeline.get_tool_registry", lambda: _FakeRegistry()
    )
    monkeypatch.setattr(
        "deeptutor.agents.research.pipeline.dispatch_tool_calls",
        fake_dispatch_tool_calls,
    )

    pipeline = ResearchPipeline(
        language="en",
        runtime_config={
            "researching": {"tool_timeout": 7, "tool_max_retries": 2},
        },
    )
    queue = DynamicTopicQueue("topic", max_length=1)
    host = _BlockLoopHost(
        pipeline=pipeline,
        block=TopicBlock(block_id="block_1", sub_topic="topic", overview=""),
        queue=queue,
        citations=object(),
        topic="topic",
        stream=StreamBus(),
        context=UnifiedContext(session_id="s1", user_message="m"),
        client=None,
    )

    await host.dispatch_tools(
        iteration=0,
        tool_calls=[{"id": "c1", "name": "web_search", "arguments": "{}"}],
    )

    assert captured["tool_timeout"] == 7
    assert captured["tool_max_retries"] == 2


def test_tool_policy_defaults_bound_a_stall_without_multiplying_a_slow_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shipped pair is deliberate, so pin it.

    A research tool is slow by nature — one ``rag`` call against a LightRAG or
    GraphRAG index makes its own LLM calls first, and search-then-fetch waits
    on someone else's site — so the ceiling has to be one only a stalled
    provider reaches, and a retry must not re-pay it for a tool that was going
    to succeed. Neither number is pinned anywhere else: the policy tests above
    pass whatever they configure.
    """
    monkeypatch.setattr("deeptutor.agents.research.pipeline.get_llm_config", lambda: _FakeLLM())
    monkeypatch.setattr(
        "deeptutor.agents.research.pipeline.get_tool_registry", lambda: _FakeRegistry()
    )

    pipeline = ResearchPipeline(language="en", runtime_config={})

    assert pipeline.tool_timeout == 240
    assert pipeline.tool_max_retries == 0


def test_settings_layer_defaults_match_the_pipeline_defaults() -> None:
    """The two layers that can decide the tool policy must not disagree.

    ``_MAIN_YAML_RUNTIME_DEFAULTS`` is the fallback applied when a research
    settings payload is written to main.yaml. If it holds different numbers
    than ``ResearchPipeline`` reads as its own defaults, then saving settings
    once — without touching either field — persists the table's values and the
    pipeline default becomes unreachable, which is how #1316 hid a 4096 token
    budget no user could raise.
    """
    from deeptutor.services.config.capabilities_settings import (
        _MAIN_YAML_RUNTIME_DEFAULTS,
    )

    researching = _MAIN_YAML_RUNTIME_DEFAULTS["research"]["researching"]
    assert researching["tool_timeout"] == 240
    assert researching["tool_max_retries"] == 0
