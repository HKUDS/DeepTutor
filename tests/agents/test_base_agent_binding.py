"""Tests for BaseAgent runtime binding behavior."""

from __future__ import annotations

import pytest

from deeptutor.agents.base_agent import BaseAgent
from deeptutor.services.llm.config import LLMConfig


class _DummyAgent(BaseAgent):
    async def process(self, **_kwargs):  # noqa: ANN003
        return {}


@pytest.fixture
def resolved_llm(monkeypatch) -> LLMConfig:  # noqa: ANN001
    resolved = LLMConfig(
        model="google/gemini-3-flash-preview",
        api_key="sk-test",
        base_url="https://openrouter.ai/api/v1",
        binding="openrouter",
        provider_name="openrouter",
        provider_mode="gateway",
    )
    monkeypatch.setattr("deeptutor.agents.base_agent.get_llm_config", lambda: resolved)
    monkeypatch.setattr(
        "deeptutor.agents.base_agent.get_agent_params",
        lambda _module: {"temperature": 0.2, "max_tokens": 128},
    )
    return resolved


def test_base_agent_defaults_to_resolved_binding(resolved_llm) -> None:
    """When binding is not explicitly provided, use resolved runtime binding."""
    agent = _DummyAgent(
        module_name="question",
        agent_name="idea_agent",
        language="en",
    )

    assert agent.binding == resolved_llm.binding


@pytest.mark.asyncio
async def test_stream_llm_appends_german_language_directive(resolved_llm, monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_stream(**kwargs):  # noqa: ANN003
        captured.update(kwargs)
        yield "ok"

    monkeypatch.setattr("deeptutor.agents.base_agent.llm_stream", fake_stream)
    agent = _DummyAgent(module_name="chat", agent_name="chat_agent", language="de")

    chunks = [chunk async for chunk in agent.stream_llm("User prompt", "System prompt")]

    assert chunks == ["ok"]
    system_prompt = str(captured["system_prompt"])
    assert "System prompt" in system_prompt
    assert "Write ALL reader-facing text strictly in Deutsch" in system_prompt


@pytest.mark.asyncio
async def test_stream_llm_appends_directive_to_system_message(resolved_llm, monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_stream(**kwargs):  # noqa: ANN003
        captured.update(kwargs)
        yield "ok"

    monkeypatch.setattr("deeptutor.agents.base_agent.llm_stream", fake_stream)
    agent = _DummyAgent(module_name="chat", agent_name="chat_agent", language="de")
    messages = [
        {"role": "system", "content": "System prompt"},
        {"role": "user", "content": "User prompt"},
    ]

    chunks = [
        chunk
        async for chunk in agent.stream_llm(
            "ignored",
            "Fallback system",
            messages=messages,
        )
    ]

    assert chunks == ["ok"]
    directed_messages = captured["messages"]
    assert isinstance(directed_messages, list)
    assert "Write ALL reader-facing text strictly in Deutsch" in directed_messages[0]["content"]
    assert "Deutsch" not in messages[0]["content"]


@pytest.mark.asyncio
async def test_call_llm_appends_german_language_directive(resolved_llm, monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_complete(**kwargs):  # noqa: ANN003
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr("deeptutor.agents.base_agent.llm_complete", fake_complete)
    agent = _DummyAgent(module_name="chat", agent_name="chat_agent", language="de")

    response = await agent.call_llm("User prompt", "System prompt")

    assert response == "ok"
    system_prompt = str(captured["system_prompt"])
    assert "System prompt" in system_prompt
    assert "Write ALL reader-facing text strictly in Deutsch" in system_prompt
