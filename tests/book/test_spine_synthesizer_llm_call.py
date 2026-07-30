"""The spine synthesizer must reach the LLM through its own agent seam.

``_call_json`` is blocking on purpose — nothing consumes a partial spine, and a
reasoning model's ``<think>`` prelude never reaches the parser this way (#707).
But it has to stay on ``BaseAgent.call_llm``: calling the factory directly drops
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
async def test_call_json_goes_through_call_llm_with_its_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: dict[str, Any] = {}

    async def _call_llm(self: BaseAgent, **kwargs: Any) -> str:
        recorded.update(kwargs)
        return json.dumps({"chapters": [{"title": "Vectors"}]})

    monkeypatch.setattr(BaseAgent, "call_llm", _call_llm)

    payload = await SpineSynthesizer(language="ja")._call_json(
        system_prompt="Design a spine.",
        user_prompt="About linear algebra.",
        stage="spine_draft",
    )

    assert payload == {"chapters": [{"title": "Vectors"}]}
    assert recorded["stage"] == "spine_draft"
    assert recorded["response_format"] == {"type": "json_object"}
    # The language directive rides on the system prompt, so a non-en/zh book
    # still tells the model which language to write in (#712).
    assert "日本語" in recorded["system_prompt"]


@pytest.mark.asyncio
async def test_call_json_returns_an_empty_payload_when_the_call_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _boom(self: BaseAgent, **_kwargs: Any) -> str:
        raise RuntimeError("provider down")

    monkeypatch.setattr(BaseAgent, "call_llm", _boom)

    payload = await SpineSynthesizer()._call_json(
        system_prompt="Design a spine.",
        user_prompt="About linear algebra.",
        stage="spine_draft",
    )

    assert payload == {}
