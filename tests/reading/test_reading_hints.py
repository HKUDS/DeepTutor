"""Focused tests for Immersive Reading's dynamic composer question."""

from __future__ import annotations

import asyncio

import pytest

from deeptutor.services import reading_hints


@pytest.fixture(autouse=True)
def clear_hint_state() -> None:
    reading_hints._cache.clear()
    reading_hints._inflight.clear()


def _material() -> reading_hints._Material:
    return reading_hints._Material(
        material_id="material-1",
        title="Residual Networks",
        render_mode="pdf",
        locator=7,
        unit_text="A residual block adds its input to the transformed signal.",
        selection="",
        transcript=[],
        transcript_length=2,
    )


def test_sanitize_rejects_non_question_output() -> None:
    assert reading_hints._sanitize("Residual connections stabilize gradients.", "en") == ""
    assert (
        reading_hints._sanitize(
            "Why do I need residual connections?",
            "en",
            "Residual connections are needed to stabilize gradients.",
        )
        == ""
    )
    assert reading_hints._sanitize("Why do I need a residual connection here?", "en")


@pytest.mark.asyncio
async def test_cache_hit_does_not_invoke_llm_again(monkeypatch: pytest.MonkeyPatch) -> None:
    material = _material()
    calls = 0

    async def collect(*_args: object) -> reading_hints._Material:
        return material

    async def call_llm(_material: reading_hints._Material, _language: str) -> str:
        nonlocal calls
        calls += 1
        return "Why do I need a residual connection here?"

    monkeypatch.setattr(reading_hints, "_collect", collect)
    monkeypatch.setattr(reading_hints, "_call_llm", call_llm)
    monkeypatch.setattr(reading_hints, "_response_language", lambda: "en")

    first = await reading_hints.get_ask_hint("workspace-1", locator=7)
    second = await reading_hints.get_ask_hint("workspace-1", locator=7)

    assert first == second
    assert first["hint"] == "Why do I need a residual connection here?"
    assert calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [asyncio.TimeoutError(), RuntimeError("model unavailable")],
    ids=["timeout", "failure"],
)
async def test_llm_failure_returns_empty_hint(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    async def collect(*_args: object) -> reading_hints._Material:
        return _material()

    async def fail_llm(_material: reading_hints._Material, _language: str) -> str:
        raise error

    monkeypatch.setattr(reading_hints, "_collect", collect)
    monkeypatch.setattr(reading_hints, "_call_llm", fail_llm)
    monkeypatch.setattr(reading_hints, "_response_language", lambda: "en")

    result = await reading_hints.get_ask_hint("workspace-1", locator=7)

    assert result["hint"] == ""
    assert result["material_id"] == "material-1"


def test_openers_reject_lines_that_refer_back_to_the_tutor() -> None:
    """An opener is the first thing said, so nothing can be referred back to."""
    assert (
        reading_hints._sanitize_opener("你引入的‘工具调用协议’和普通函数调用差在哪？", True) == ""
    )
    assert reading_hints._sanitize_opener("你提到的状态机比喻能再拆一下吗？", True) == ""
    assert (
        reading_hints._sanitize_opener("You mentioned the planner — how does it back off?", False)
        == ""
    )
    # ...while a line that points at the material itself is exactly right.
    assert reading_hints._sanitize_opener("视频里说的‘规划与执行分离’，执行层怎么回退？", True)
    assert reading_hints._sanitize_opener("What does section 3 mean by a planning loop?", False)


def test_openers_allow_more_than_a_placeholder_worth_of_text() -> None:
    """Openers are wrapped buttons, not a single-line placeholder."""
    # The real generation that this bound used to drop on the floor.
    line = "视频里说 LLM 只是‘概率预测’，那 Agent Skill 到底是在哪一层上改变了这种预测的性质？"
    assert len(line) > reading_hints._MAX_HINT_CHARS["zh"]
    assert reading_hints._sanitize_opener(line, True) == line
