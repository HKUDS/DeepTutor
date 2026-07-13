from __future__ import annotations

import pytest

from deeptutor.book.blocks import _llm_writer


@pytest.mark.asyncio
async def test_llm_json_normalizes_array_to_expected_key(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_llm_text(**_: object) -> str:
        return '[{"front": "A", "back": "B"}]'

    monkeypatch.setattr(_llm_writer, "llm_text", fake_llm_text)

    data = await _llm_writer.llm_json(
        user_prompt="cards",
        system_prompt="system",
        expected_key="cards",
    )

    assert data == {"cards": [{"front": "A", "back": "B"}]}


@pytest.mark.asyncio
async def test_llm_json_uses_single_object_from_array(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_llm_text(**_: object) -> str:
        return '[{"code": "print(1)", "language": "python"}]'

    monkeypatch.setattr(_llm_writer, "llm_text", fake_llm_text)

    data = await _llm_writer.llm_json(user_prompt="code", system_prompt="system")

    assert data["code"] == "print(1)"
    assert data["language"] == "python"


@pytest.mark.asyncio
async def test_llm_json_retries_structured_calls_with_low_reasoning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The retry uses "low" reasoning effort rather than "minimal": vLLM-served
    # local models (e.g. Qwen) reject "minimal" and only accept low/medium/high.
    calls: list[str | None] = []

    async def fake_llm_text(**kwargs: object) -> str:
        effort = kwargs.get("reasoning_effort")
        calls.append(effort if isinstance(effort, str) else None)
        if effort == "low":
            return '{"events": [{"date": "2026", "title": "Ready"}]}'
        return ""

    monkeypatch.setattr(_llm_writer, "llm_text", fake_llm_text)

    data = await _llm_writer.llm_json(
        user_prompt="timeline",
        system_prompt="system",
        expected_key="events",
    )

    assert calls == [None, "low"]
    assert data["events"][0]["title"] == "Ready"
    assert data["_metadata"]["reasoning_retry"] == "low"
