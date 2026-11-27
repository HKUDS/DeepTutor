from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from deeptutor.agents.math_animator.agents.visual_review_agent import VisualReviewAgent
from deeptutor.agents.math_animator.models import GeneratedCode, RenderResult, VisualReviewResult
from deeptutor.agents.math_animator.pipeline import MathAnimatorPipeline
from deeptutor.agents.math_animator.request_config import MathAnimatorRequestConfig
from deeptutor.core.context import Attachment


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_pipeline_only_reviews_when_enabled(monkeypatch, enabled) -> None:
    pipeline = MathAnimatorPipeline(
        api_key="test", base_url=None, api_version=None, enable_visual_review=enabled
    )
    renders = []

    class Renderer:
        def __init__(self, *args, **kwargs):
            pass

        async def render(self, *, code, output_mode, quality):
            renders.append(code)
            return RenderResult(output_mode=output_mode, quality=quality)

    frame = Attachment(type="image", url="/test-frame.png")
    frames = AsyncMock(return_value=[frame])
    review = AsyncMock(
        side_effect=[
            VisualReviewResult(passed=False, summary="Labels overlap", suggested_fix="Move labels"),
            VisualReviewResult(passed=True, summary="Clear", reviewed_frames=1),
        ]
    )
    repair = AsyncMock(return_value=GeneratedCode(code="# repaired"))
    monkeypatch.setattr("deeptutor.agents.math_animator.pipeline.ManimRenderService", Renderer)
    monkeypatch.setattr(
        "deeptutor.agents.math_animator.pipeline.VisualReviewService.build_attachments", frames
    )
    monkeypatch.setattr(VisualReviewAgent, "process", review)
    monkeypatch.setattr(pipeline.code_agent, "repair", repair)

    code, result = await pipeline.run_render(
        turn_id="test-review",
        user_input="Explain a circle",
        request_config=MathAnimatorRequestConfig(enable_visual_review=enabled),
        initial_code="pass",
    )

    if enabled:
        assert renders == ["pass", "# repaired"]
        assert code == "# repaired"
        assert review.await_count == frames.await_count == 2
        assert review.call_args.kwargs["attachments"] == [frame]
        assert "Move labels" in repair.call_args.kwargs["error_message"]
        assert result.retry_attempts == 1
        assert result.visual_review.passed is True
    else:
        assert pipeline.visual_review_agent is None
        assert renders == ["pass"]
        assert result.visual_review is None
        review.assert_not_called()
        frames.assert_not_called()
        repair.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("has_frames", [False, True])
async def test_review_skips_without_frames_or_vision_model(monkeypatch, has_frames) -> None:
    agent = VisualReviewAgent()
    provider = AsyncMock(side_effect=AssertionError("Skipped review must not call a model"))
    monkeypatch.setattr(agent, "stream_llm", provider)
    monkeypatch.setattr(
        "deeptutor.agents.math_animator.agents.visual_review_agent.supports_vision",
        lambda *args: False,
    )
    result = await agent.process(
        user_input="Explain a circle",
        output_mode="video",
        current_code="pass",
        render_result=RenderResult(output_mode="video"),
        attachments=[Attachment(type="image", url="/frame.png")] if has_frames else [],
    )
    assert result.passed is True
    assert "skipped" in result.summary
    assert (
        "does not support image inspection" if has_frames else "no review frames"
    ) in result.summary
    provider.assert_not_called()
