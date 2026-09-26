"""The spine synthesizer must reach the LLM through its own agent seam.

``_call_json`` collects the whole stream before parsing so a capped partial
spine cannot masquerade as a usable JSON payload. It stays on
``BaseAgent.stream_llm``: calling the factory directly drops
the trace event the Book Activity panel renders and the per-agent
api_key / base_url / binding routing.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from deeptutor.agents.base_agent import BaseAgent
from deeptutor.book.agents.spine_synthesizer import SpineSynthesizer


@pytest.mark.asyncio
async def test_call_json_goes_through_stream_llm_with_its_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: dict[str, Any] = {}

    async def _stream_llm(self: BaseAgent, **kwargs: Any):
        recorded.update(kwargs)
        yield json.dumps({"chapters": [{"title": "Vectors"}]})

    monkeypatch.setattr(BaseAgent, "stream_llm", _stream_llm)

    payload = await SpineSynthesizer(language="ja")._call_json(
        system_prompt="Design a spine.",
        user_prompt="About linear algebra.",
        stage="spine_draft",
    )

    assert payload == {"chapters": [{"title": "Vectors"}]}
    assert recorded["stage"] == "spine_draft"
    assert recorded["response_format"] == {"type": "json_object"}
    assert recorded["outcome"] is not None
    # The language directive rides on the system prompt, so a non-en/zh book
    # still tells the model which language to write in (#712).
    assert "日本語" in recorded["system_prompt"]


@pytest.mark.asyncio
async def test_call_json_returns_an_empty_payload_when_the_call_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _boom(self: BaseAgent, **_kwargs: Any):
        yield ""
        raise RuntimeError("provider down")

    monkeypatch.setattr(BaseAgent, "stream_llm", _boom)

    payload = await SpineSynthesizer()._call_json(
        system_prompt="Design a spine.",
        user_prompt="About linear algebra.",
        stage="spine_draft",
    )

    assert payload == {}


@pytest.mark.asyncio
async def test_call_json_retries_at_low_effort_when_reasoning_ate_the_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A thinking-only first response must not settle the spine.

    A reasoning model pays for its hidden tokens out of the same ``max_tokens``
    as its answer; on the spine prompt it can spend the lot and return nothing
    to parse. That used to reach ``_materialise`` as ``{}`` and collapse a
    whole book into one placeholder "Overview" chapter (#1316). The second
    attempt asks for the same JSON with thinking turned down.
    """
    efforts: list[str | None] = []

    async def _stream_llm(self: BaseAgent, **kwargs: Any):
        efforts.append(kwargs.get("reasoning_effort"))
        if len(efforts) == 1:
            yield ""
        else:
            yield json.dumps({"chapters": [{"title": "Vectors"}, {"title": "Matrices"}]})

    monkeypatch.setattr(BaseAgent, "stream_llm", _stream_llm)

    payload = await SpineSynthesizer()._call_json(
        system_prompt="Design a spine.",
        user_prompt="About linear algebra.",
        stage="spine_draft",
        expected_key="chapters",
    )

    assert efforts == [None, "low"]
    assert len(payload["chapters"]) == 2


@pytest.mark.asyncio
async def test_call_json_retries_when_the_payload_lost_its_chapters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """json-repair closing a truncated object is not a usable spine.

    A budget that runs out mid-JSON leaves a repairable fragment, so parsing
    succeeds and hands back an object whose ``chapters`` never arrived — the
    shape behind "the spine has chapters but every learning objective and
    summary is empty".
    """
    calls: list[str | None] = []

    async def _stream_llm(self: BaseAgent, **kwargs: Any):
        calls.append(kwargs.get("reasoning_effort"))
        if len(calls) == 1:
            yield json.dumps({"concept_graph": {"nodes": [], "edges": []}})
        else:
            yield json.dumps({"chapters": [{"title": "Vectors"}]})

    monkeypatch.setattr(BaseAgent, "stream_llm", _stream_llm)

    payload = await SpineSynthesizer()._call_json(
        system_prompt="Design a spine.",
        user_prompt="About linear algebra.",
        stage="spine_draft",
        expected_key="chapters",
    )

    assert calls == [None, "low"]
    assert payload["chapters"] == [{"title": "Vectors"}]


@pytest.mark.asyncio
async def test_call_json_does_not_retry_a_good_first_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str | None] = []

    async def _stream_llm(self: BaseAgent, **kwargs: Any):
        calls.append(kwargs.get("reasoning_effort"))
        yield json.dumps({"chapters": [{"title": "Vectors"}]})

    monkeypatch.setattr(BaseAgent, "stream_llm", _stream_llm)

    await SpineSynthesizer()._call_json(
        system_prompt="Design a spine.",
        user_prompt="About linear algebra.",
        stage="spine_draft",
        expected_key="chapters",
    )

    assert calls == [None]
