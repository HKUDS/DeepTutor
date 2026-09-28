"""A capped reasoning response must not become a partial book plan."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from deeptutor.agents.base_agent import BaseAgent
from deeptutor.book.agents.ideation_agent import IdeationAgent
from deeptutor.book.agents.source_explorer import SourceExplorer
from deeptutor.book.agents.spine_synthesizer import SpineSynthesizer
from deeptutor.book.blocks import _llm_writer
from deeptutor.book.inputs import IdeationContext
from deeptutor.book.models import BookInputs, BookProposal


@pytest.mark.asyncio
async def test_ideation_retries_capped_json_with_a_repairable_title(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    efforts: list[str | None] = []

    async def fake_stream(self: BaseAgent, **kwargs: Any):
        efforts.append(kwargs.get("reasoning_effort"))
        outcome = kwargs.get("outcome")
        if len(efforts) == 1:
            if outcome is not None:
                outcome.finish_reason = "length"
            yield '{"title":"Partial","estimated_chapters":'
        else:
            if outcome is not None:
                outcome.finish_reason = "stop"
            yield '{"title":"Complete","estimated_chapters":4}'

    monkeypatch.setattr(BaseAgent, "stream_llm", fake_stream)

    proposal = await IdeationAgent().process(ideation_context=IdeationContext(user_intent="Math"))

    assert proposal.title == "Complete"
    assert efforts == [None, "low"]


@pytest.mark.asyncio
async def test_source_exploration_retries_capped_queries_before_summarising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str | None]] = []

    async def fake_stream(self: BaseAgent, **kwargs: Any):
        stage = kwargs["stage"]
        effort = kwargs.get("reasoning_effort")
        calls.append((stage, effort))
        outcome = kwargs["outcome"]
        if stage == "explore_queries" and effort is None:
            outcome.finish_reason = "length"
            yield '{"queries":["partial"],"unfinished":'
        elif stage == "explore_queries":
            outcome.finish_reason = "stop"
            yield '{"queries":["complete first","complete second"]}'
        else:
            outcome.finish_reason = "stop"
            yield '{"summary":"Source summary","candidate_concepts":["math"]}'

    monkeypatch.setattr(BaseAgent, "stream_llm", fake_stream)

    report = await SourceExplorer().explore(
        book_id="book-1",
        proposal=BookProposal(title="Math"),
        inputs=BookInputs(user_intent="Math", source_context="A source about mathematics."),
    )

    assert report.queries == ["complete first", "complete second"]
    assert report.summary == "Source summary"
    assert calls == [
        ("explore_queries", None),
        ("explore_queries", "low"),
        ("explore_summary", None),
    ]


@pytest.mark.asyncio
async def test_spine_retries_capped_json_with_a_repairable_chapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    efforts: list[str | None] = []

    async def fake_stream(self: BaseAgent, **kwargs: Any):
        efforts.append(kwargs.get("reasoning_effort"))
        outcome = kwargs.get("outcome")
        if len(efforts) == 1:
            if outcome is not None:
                outcome.finish_reason = "max_tokens"
            yield '{"chapters":[{"title":"Partial"}],"concept_graph":'
        else:
            if outcome is not None:
                outcome.finish_reason = "stop"
            yield '{"chapters":[{"title":"First"},{"title":"Second"}]}'

    async def fake_call_llm(self: BaseAgent, **_kwargs: Any) -> str:
        return '{"chapters":[{"title":"Partial"}],"concept_graph":'

    monkeypatch.setattr(BaseAgent, "stream_llm", fake_stream)
    monkeypatch.setattr(BaseAgent, "call_llm", fake_call_llm)

    payload = await SpineSynthesizer()._call_json(
        system_prompt="Design a spine.",
        user_prompt="About mathematics.",
        stage="spine_draft",
        expected_key="chapters",
    )

    assert [chapter["title"] for chapter in payload["chapters"]] == ["First", "Second"]
    assert efforts == [None, "low"]


@pytest.mark.asyncio
async def test_spine_stream_does_not_parse_json_inside_hidden_reasoning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_stream(self: BaseAgent, **kwargs: Any):
        kwargs["outcome"].finish_reason = "stop"
        yield '<think>{"chapters":[{"title":"Internal draft"}]}</think>'
        yield '{"chapters":[{"title":"Reader draft"}]}'

    monkeypatch.setattr(BaseAgent, "stream_llm", fake_stream)

    payload = await SpineSynthesizer()._call_json(
        system_prompt="Design a spine.",
        user_prompt="About mathematics.",
        stage="spine_draft",
        expected_key="chapters",
    )

    assert payload["chapters"] == [{"title": "Reader draft"}]


@pytest.mark.asyncio
async def test_book_block_json_retries_capped_partial_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    efforts: list[str | None] = []

    async def fake_llm_text(**kwargs: Any) -> str:
        efforts.append(kwargs.get("reasoning_effort"))
        outcome = kwargs.get("outcome")
        if len(efforts) == 1:
            if outcome is not None:
                outcome.finish_reason = "max_output_tokens"
            return '{"events":[{"date":"2026"}],"notes":'
        if outcome is not None:
            outcome.finish_reason = "stop"
        return '{"events":[{"date":"2026"},{"date":"2027"}]}'

    monkeypatch.setattr(_llm_writer, "llm_text", fake_llm_text)

    payload = await _llm_writer.llm_json(
        user_prompt="Make a timeline.", system_prompt="system", expected_key="events"
    )

    assert len(payload["events"]) == 2
    assert efforts == [None, "low"]


@pytest.mark.asyncio
async def test_book_block_json_uses_stream_terminal_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    async def fake_stream(**kwargs: Any):
        calls.append(kwargs)
        kwargs["outcome"].finish_reason = "length"
        yield "<think>private reasoning</think>"
        yield '{"events":['

    async def unexpected_complete(**_kwargs: Any) -> str:
        raise AssertionError("structured block calls need the terminal stream status")

    monkeypatch.setattr(
        _llm_writer,
        "get_llm_config",
        lambda: SimpleNamespace(
            model="reasoning-model",
            binding="openai",
            api_key="test",
            base_url="https://test.invalid",
            api_version=None,
        ),
    )
    monkeypatch.setattr(_llm_writer, "llm_complete", unexpected_complete)
    monkeypatch.setattr(_llm_writer, "llm_stream", fake_stream, raising=False)

    from deeptutor.services.llm.types import StreamOutcome

    outcome = StreamOutcome()
    text = await _llm_writer.llm_text(
        user_prompt="Make a timeline.", system_prompt="system", outcome=outcome
    )

    assert text == '{"events":['
    assert outcome.truncated
    assert len(calls) == 1
