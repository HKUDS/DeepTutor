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
