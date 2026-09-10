"""Post-render stages must degrade instead of discarding a finished render.

``summary`` and ``visual_review`` both run *after* Manim produced an artifact,
so a thinking model that streams ``content: null`` there must not take the
video down with it (issue #1202).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from deeptutor.agents.math_animator.agents import visual_review_agent
from deeptutor.agents.math_animator.agents.summary_agent import SummaryAgent
from deeptutor.agents.math_animator.agents.visual_review_agent import VisualReviewAgent
from deeptutor.agents.math_animator.models import (
    ConceptAnalysis,
    RenderedArtifact,
    RenderResult,
    SceneDesign,
)
from deeptutor.core.context import Attachment


@pytest.fixture(autouse=True)
def _no_runtime_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the test independent of ``data/user/settings/agents.yaml``."""
    monkeypatch.setattr("deeptutor.agents.base_agent.get_agent_params", lambda _module: {})


def _replay_stream(replies: list[str]) -> tuple[Any, list[str]]:
    """Build a ``stream_llm`` stub that replays *replies*, one per call.

    An empty string models a reasoning-only reply: the stream yields nothing,
    so the caller joins an empty response.
    """
    prompts: list[str] = []

    async def _stream(*, user_prompt: str, **_kwargs: Any) -> AsyncIterator[str]:
        prompts.append(user_prompt)
        reply = replies[min(len(prompts) - 1, len(replies) - 1)]
        if reply:
            yield reply

    return _stream, prompts


def _summary_agent(replies: list[str]) -> tuple[SummaryAgent, list[str]]:
    agent = SummaryAgent(language="en")
    agent.prompts = {
        "system": "Summarize the render.",
        "user_template": "Request: {user_input}",
    }
    stream, prompts = _replay_stream(replies)
    agent.stream_llm = stream
    return agent, prompts


def _review_agent(
    replies: list[str], monkeypatch: pytest.MonkeyPatch
) -> tuple[VisualReviewAgent, list[str]]:
    agent = VisualReviewAgent(language="en")
    agent.prompts = {
        "system": "Review the rendered frames.",
        "user_template": "Request: {user_input}, frames: {reviewed_frames}",
    }
    agent.get_model = lambda: "vision-model"
    monkeypatch.setattr(visual_review_agent, "supports_vision", lambda _binding, _model: True)
    stream, prompts = _replay_stream(replies)
    agent.stream_llm = stream
    return agent, prompts


def _render_result() -> RenderResult:
    return RenderResult(
        output_mode="video",
        artifacts=[RenderedArtifact(type="video", url="/f/v.mp4", filename="v.mp4")],
    )


def _attachments(count: int) -> list[Attachment]:
    return [Attachment(type="image", url=f"/f/frame-{i}.png") for i in range(count)]


async def _summarize(agent: SummaryAgent) -> Any:
    return await agent.process(
        user_input="Animate a sine wave",
        output_mode="video",
        analysis=ConceptAnalysis(learning_goal="Wave basics"),
        design=SceneDesign(title="Sine"),
        render_result=_render_result(),
    )


async def _review(agent: VisualReviewAgent, frame_count: int) -> Any:
    return await agent.process(
        user_input="Animate a sine wave",
        output_mode="video",
        current_code="class MainScene(Scene): pass",
        render_result=_render_result(),
        attachments=_attachments(frame_count),
    )


@pytest.mark.asyncio
async def test_summary_recovers_from_null_content() -> None:
    agent, prompts = _summary_agent(["", '{"summary_text": "Sine wave rendered."}'])

    payload = await _summarize(agent)

    assert payload.summary_text == "Sine wave rendered."
    assert len(prompts) == 2
    assert "IMPORTANT" in prompts[1]


@pytest.mark.asyncio
async def test_summary_falls_back_on_text_that_earlier_stages_produced() -> None:
    agent, prompts = _summary_agent([""])

    payload = await _summarize(agent)

    assert len(prompts) == 3
    assert payload.summary_text == "Wave basics"
    assert payload.user_request == "Animate a sine wave"


@pytest.mark.asyncio
async def test_visual_review_recovers_and_backfills_frame_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent, prompts = _review_agent(
        ["", '{"passed": false, "summary": "Labels overlap the curve."}'],
        monkeypatch,
    )

    result = await _review(agent, 3)

    assert result.passed is False
    assert result.summary == "Labels overlap the curve."
    assert result.reviewed_frames == 3
    assert len(prompts) == 2


@pytest.mark.asyncio
async def test_visual_review_keeps_the_render_when_no_verdict_arrives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent, prompts = _review_agent([""], monkeypatch)

    result = await _review(agent, 2)

    assert result.passed is True
    assert result.summary
    assert result.reviewed_frames == 2
    assert len(prompts) == 2
