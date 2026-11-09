"""A visual review that never produced a verdict must not read as a passed review."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from deeptutor.agents.math_animator.agents import visual_review_agent as module
from deeptutor.agents.math_animator.agents.visual_review_agent import VisualReviewAgent
from deeptutor.agents.math_animator.models import RenderResult
from deeptutor.core.context import Attachment
from deeptutor.services.llm.reasoning_params import RETRY_REASONING_EFFORT

_VERDICT = '{"passed": true, "summary": "Visuals are clear.", "issues": []}'
_FRAMES = 3


def _agent() -> VisualReviewAgent:
    agent = VisualReviewAgent()
    agent.prompts = {
        "system": "Review the rendered frames.",
        "user_template": "{user_input} {output_mode} {reviewed_frames} {render_json} {current_code}",
    }
    return agent


async def _review(
    agent: VisualReviewAgent,
    replies: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[object, list[dict[str, object]]]:
    monkeypatch.setattr(module, "supports_vision", lambda *_args: True)
    monkeypatch.setattr(agent, "get_model", lambda: "vision-model")
    calls: list[dict[str, object]] = []

    async def fake_provider(**kwargs) -> AsyncIterator[str]:
        calls.append(kwargs)
        yield replies[min(len(calls) - 1, len(replies) - 1)]

    monkeypatch.setattr(agent, "stream_llm", fake_provider)
    result = await agent.process(
        user_input="Animate a circle",
        output_mode="video",
        current_code="from manim import *",
        render_result=RenderResult(output_mode="video"),
        attachments=[
            Attachment(type="image", url=f"/frame_{index}.png") for index in range(_FRAMES)
        ],
    )
    return result, calls


@pytest.mark.asyncio
async def test_visual_review_reports_no_verdict_instead_of_a_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty reply after the retry keeps the render but admits it went unviewed."""
    result, calls = await _review(_agent(), ["", ""], monkeypatch)

    assert [entry["reasoning_effort"] for entry in calls] == [None, RETRY_REASONING_EFFORT]
    assert result.reviewed_frames == 0, "the record must not claim frames it never reviewed"
    assert "skipped" in result.summary, "the report has to say why there is no verdict"
    # Rendering already succeeded, so an unanswered review must not discard it.
    assert result.passed is True


@pytest.mark.asyncio
async def test_visual_review_survives_a_reply_that_is_not_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prose instead of JSON used to raise out of the render loop after a success."""
    result, calls = await _review(
        _agent(),
        ["The animation looks great, nothing to fix.", "The animation looks great."],
        monkeypatch,
    )

    assert len(calls) == 2
    assert result.reviewed_frames == 0
    assert "skipped" in result.summary


@pytest.mark.asyncio
async def test_visual_review_retries_a_reasoning_only_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, calls = await _review(
        _agent(),
        ["<think>Let me look at each frame first.</think>", _VERDICT],
        monkeypatch,
    )

    assert [entry["reasoning_effort"] for entry in calls] == [None, RETRY_REASONING_EFFORT]
    assert result.summary == "Visuals are clear."
    assert result.reviewed_frames == _FRAMES


@pytest.mark.asyncio
async def test_failed_verdict_on_the_first_reply_is_used_without_a_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ "The reviewer found a problem" is an answer, not a missing one."""
    result, calls = await _review(
        _agent(),
        ['{"passed": false, "summary": "Labels overlap.", "suggested_fix": "Move them out"}'],
        monkeypatch,
    )

    assert len(calls) == 1
    assert result.passed is False
    assert result.suggested_fix == "Move them out"
    assert result.reviewed_frames == _FRAMES
