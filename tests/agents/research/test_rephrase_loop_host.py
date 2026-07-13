"""Unit tests for ``_RephraseLoopHost``.

Covers the two pieces unique to the rephrase mini-loop:

* Non-``ask_user`` tool calls inside this phase are rejected inline (the
  LLM gets a synthetic tool message telling it ``ask_user`` is the only
  available tool).
* Once the ``max_rounds`` budget for ``ask_user`` calls is exhausted,
  further requests are answered with a synthetic tool message telling
  the model to FINISH with the best refined topic it can produce.
"""

from __future__ import annotations

import pytest

from deeptutor.agents.research.pipeline import ResearchPipeline, _RephraseLoopHost
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream_bus import StreamBus


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


def _make_pipeline(monkeypatch: pytest.MonkeyPatch) -> ResearchPipeline:
    monkeypatch.setattr("deeptutor.agents.research.pipeline.get_llm_config", lambda: _FakeLLM())
    monkeypatch.setattr(
        "deeptutor.agents.research.pipeline.get_tool_registry", lambda: _FakeRegistry()
    )
    return ResearchPipeline(language="en", runtime_config={})


def _make_host(pipeline: ResearchPipeline, *, max_rounds: int = 3) -> _RephraseLoopHost:
    return _RephraseLoopHost(
        pipeline=pipeline,
        stream=StreamBus(),
        context=UnifiedContext(session_id="s1", user_message="m"),
        client=None,
        max_rounds=max_rounds,
    )


@pytest.mark.asyncio
async def test_rephrase_rejects_non_ask_user_tool_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An LLM that tries to call a non-``ask_user`` tool inside the
    rephrase phase should get a synthetic tool message back instead of
    actually executing the call. No real dispatch happens."""
    pipeline = _make_pipeline(monkeypatch)
    host = _make_host(pipeline, max_rounds=3)

    tool_calls = [
        {"id": "call_1", "name": "rag", "arguments": '{"query": "x"}'},
    ]
    outcome = await host.dispatch_tools(iteration=0, tool_calls=tool_calls)

    assert outcome.tool_messages
    assert outcome.tool_messages[0]["tool_call_id"] == "call_1"
    assert outcome.tool_messages[0]["name"] == "rag"
    assert "ask_user" in outcome.tool_messages[0]["content"].lower()


@pytest.mark.asyncio
async def test_rephrase_round_cap_short_circuits_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After max_rounds ``ask_user`` calls, the next ``ask_user`` is
    answered with a synthetic FINISH directive rather than being
    dispatched."""
    pipeline = _make_pipeline(monkeypatch)
    host = _make_host(pipeline, max_rounds=2)
    host._rounds_used = 2  # simulate already consumed budget

    tool_calls = [
        {"id": "call_x", "name": "ask_user", "arguments": "{}"},
    ]
    outcome = await host.dispatch_tools(iteration=3, tool_calls=tool_calls)

    assert outcome.tool_messages
    assert outcome.tool_messages[0]["tool_call_id"] == "call_x"
    content = outcome.tool_messages[0]["content"].lower()
    assert "finish" in content or "limit" in content
    # Round counter unchanged — the cap-reply doesn't consume another
    # round (and dispatch_tool_calls was never invoked).
    assert host._rounds_used == 2


@pytest.mark.asyncio
async def test_rephrase_force_finalize_returns_empty_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the inner loop runs out of iterations the host's force_finalize
    yields an empty result so the caller falls back to the raw topic."""
    pipeline = _make_pipeline(monkeypatch)
    host = _make_host(pipeline, max_rounds=3)

    text, completed, calls = await host.force_finalize(messages=[], start_iteration=10)
    assert text == ""
    assert completed is False
    assert calls == 0
