"""Tests for NotebookSummarizeAgent — extra_headers forwarding."""

from __future__ import annotations

import pytest

from deeptutor.services.llm.config import LLMConfig


def _make_cfg(**overrides):
    defaults = dict(
        model="gpt-4o-mini",
        api_key="test-key",
        base_url="https://api.example.com/v1",
        binding="openai",
        provider_name="openai",
        provider_mode="standard",
    )
    defaults.update(overrides)
    return LLMConfig(**defaults)


def test_summarize_agent_stores_extra_headers(monkeypatch) -> None:
    """Agent should pick up extra_headers from LLMConfig."""
    cfg = _make_cfg(extra_headers={"X-Gateway": "prod"})
    monkeypatch.setattr(
        "deeptutor.agents.notebook.summarize_agent.get_llm_config", lambda: cfg,
    )

    from deeptutor.agents.notebook.summarize_agent import NotebookSummarizeAgent

    agent = NotebookSummarizeAgent(language="en")
    assert agent.extra_headers == {"X-Gateway": "prod"}


def test_summarize_agent_empty_extra_headers(monkeypatch) -> None:
    """Agent should default to empty dict when config has no extra_headers."""
    cfg = _make_cfg()
    monkeypatch.setattr(
        "deeptutor.agents.notebook.summarize_agent.get_llm_config", lambda: cfg,
    )

    from deeptutor.agents.notebook.summarize_agent import NotebookSummarizeAgent

    agent = NotebookSummarizeAgent(language="en")
    assert agent.extra_headers == {}


@pytest.mark.asyncio
async def test_summarize_agent_forwards_extra_headers(monkeypatch) -> None:
    """extra_headers must reach the underlying llm_stream call."""
    cfg = _make_cfg(extra_headers={"X-Gateway": "prod"})
    monkeypatch.setattr(
        "deeptutor.agents.notebook.summarize_agent.get_llm_config", lambda: cfg,
    )
    captured: dict[str, object] = {}

    async def _fake_llm_stream(**kwargs):
        captured.update(kwargs)
        yield "summary text"

    monkeypatch.setattr(
        "deeptutor.agents.notebook.summarize_agent.llm_stream", _fake_llm_stream,
    )

    from deeptutor.agents.notebook.summarize_agent import NotebookSummarizeAgent

    agent = NotebookSummarizeAgent(language="en")
    chunks: list[str] = []
    async for c in agent.stream_summary(
        title="Test",
        record_type="chat",
        user_query="What is X?",
        output="X is Y.",
    ):
        chunks.append(c)

    assert "".join(chunks) == "summary text"
    assert captured.get("extra_headers") == {"X-Gateway": "prod"}


@pytest.mark.asyncio
async def test_summarize_agent_omits_extra_headers_when_empty(monkeypatch) -> None:
    """When no extra_headers configured, they should not appear in kwargs."""
    cfg = _make_cfg()
    monkeypatch.setattr(
        "deeptutor.agents.notebook.summarize_agent.get_llm_config", lambda: cfg,
    )
    captured: dict[str, object] = {}

    async def _fake_llm_stream(**kwargs):
        captured.update(kwargs)
        yield "ok"

    monkeypatch.setattr(
        "deeptutor.agents.notebook.summarize_agent.llm_stream", _fake_llm_stream,
    )

    from deeptutor.agents.notebook.summarize_agent import NotebookSummarizeAgent

    agent = NotebookSummarizeAgent(language="en")
    async for _ in agent.stream_summary(
        title="T", record_type="chat", user_query="q", output="o",
    ):
        pass

    assert "extra_headers" not in captured
