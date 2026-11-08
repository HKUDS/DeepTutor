from __future__ import annotations

import pytest

from deeptutor.agents.math_animator.models import (
    GeneratedCode,
    RenderResult,
    VisualReviewResult,
)
from deeptutor.agents.math_animator.pipeline import _record_only_review
from deeptutor.agents.math_animator.retry_manager import CodeRetryManager


def test_record_only_review_keeps_the_report_without_forcing_passed() -> None:
    review = VisualReviewResult(
        passed=False,
        summary="text overlaps text",
        suggested_fix="move the label",
    )

    result = _record_only_review(review)

    assert result is review
    # The UI warning depends on this staying false.
    assert result.passed is False
    assert result.summary == "Layout issues remain after repair rounds: text overlaps text"
    assert result.suggested_fix == "move the label"


def test_record_only_review_passes_through_an_unavailable_probe() -> None:
    assert _record_only_review(None) is None


@pytest.mark.asyncio
async def test_advisory_review_returns_the_warning_without_repairing() -> None:
    class _Renderer:
        async def render(self, *, code: str, output_mode: str, quality: str) -> RenderResult:
            return RenderResult(output_mode=output_mode, artifacts=[], quality=quality)

    repair_calls = 0

    async def _repair(code: str, _error_message: str, _attempt: int) -> GeneratedCode:
        nonlocal repair_calls
        repair_calls += 1
        return GeneratedCode(code=code + "\n# repaired", rationale="should not run")

    async def _review(_code: str, _result: RenderResult) -> VisualReviewResult:
        return VisualReviewResult(
            passed=False,
            summary="Layout issues remain after repair rounds: text overlaps text",
            suggested_fix="move the label",
        )

    manager = CodeRetryManager(
        renderer=_Renderer(),
        repair_callback=_repair,
        review_callback=_review,
        max_retries=1,
        review_is_advisory=True,
    )

    final_code, result = await manager.render_with_retries(
        initial_code="from manim import *",
        output_mode="video",
        quality="medium",
    )

    assert repair_calls == 0
    assert final_code == "from manim import *"
    assert result.visual_review is not None
    assert result.visual_review.passed is False
    assert result.retry_attempts == 0


@pytest.mark.asyncio
async def test_non_advisory_review_still_repairs() -> None:
    class _Renderer:
        async def render(self, *, code: str, output_mode: str, quality: str) -> RenderResult:
            return RenderResult(output_mode=output_mode, artifacts=[], quality=quality)

    repair_calls = 0

    async def _repair(code: str, _error_message: str, _attempt: int) -> GeneratedCode:
        nonlocal repair_calls
        repair_calls += 1
        return GeneratedCode(code=code + "\n# repaired", rationale="layout fix")

    async def _review(_code: str, _result: RenderResult) -> VisualReviewResult:
        return VisualReviewResult(
            passed=False,
            summary="Labels overlap.",
            suggested_fix="Move labels.",
        )

    manager = CodeRetryManager(
        renderer=_Renderer(),
        repair_callback=_repair,
        review_callback=_review,
        max_retries=1,
    )

    final_code, result = await manager.render_with_retries(
        initial_code="from manim import *",
        output_mode="video",
        quality="medium",
    )

    assert repair_calls == 1
    assert final_code.endswith("# repaired")
    assert result.visual_review is not None
    assert result.visual_review.passed is False
    assert result.retry_attempts == 1
