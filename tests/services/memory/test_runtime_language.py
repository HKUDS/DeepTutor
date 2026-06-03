from __future__ import annotations

import pytest

from deeptutor.services.llm.config import LLMConfig
from deeptutor.services.memory.consolidator.modes import _runtime


def _make_cfg() -> LLMConfig:
    return LLMConfig(
        model="gpt-test",
        api_key="sk-test",
        base_url="https://api.example.com/v1",
        binding="openai",
        provider_name="openai",
        provider_mode="standard",
    )


def test_memory_prompt_language_falls_german_back_to_english() -> None:
    prompt = _runtime.load_prompt("dedup", "de")

    assert "system" in prompt
    assert "user" in prompt


@pytest.mark.asyncio
async def test_memory_call_llm_appends_german_language_directive(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_stream(**kwargs):  # noqa: ANN003
        captured.update(kwargs)
        yield "ok"

    monkeypatch.setattr(
        "deeptutor.services.memory.consolidator.modes._runtime.llm_stream",
        fake_stream,
    )
    monkeypatch.setattr("deeptutor.services.llm.get_llm_config", _make_cfg)

    response = await _runtime.call_llm(
        system_prompt="Memory system",
        user_prompt="Memory user",
        language="de",
    )

    assert response == "ok"
    system_prompt = str(captured["system_prompt"])
    assert "Memory system" in system_prompt
    assert "Write ALL reader-facing text strictly in Deutsch" in system_prompt
