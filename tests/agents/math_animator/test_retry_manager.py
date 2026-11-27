from __future__ import annotations

import asyncio

import pytest

from deeptutor.agents.math_animator.models import GeneratedCode, RenderResult, VisualReviewResult
from deeptutor.agents.math_animator.renderer import ManimRenderError
from deeptutor.agents.math_animator.retry_manager import CodeRetryManager


class _FakeRenderer:
    def __init__(self) -> None:
        self.calls = 0

    async def render(self, *, code: str, output_mode: str, quality: str) -> RenderResult:
        self.calls += 1
        if self.calls == 1:
            raise ManimRenderError("first render failed")
        return RenderResult(output_mode=output_mode, artifacts=[], quality=quality)


@pytest.mark.asyncio
async def test_retry_manager_emits_status_and_recovers() -> None:
    renderer = _FakeRenderer()
    status_messages: list[str] = []

    async def _on_status(message: str) -> None:
        status_messages.append(message)

    async def _repair_callback(code: str, error_message: str, attempt: int) -> GeneratedCode:
        assert "failed" in error_message
        assert attempt == 1
        return GeneratedCode(code=code + "\n# repaired", rationale="patched")

    manager = CodeRetryManager(
        renderer=renderer,
        repair_callback=_repair_callback,
        on_status=_on_status,
        max_retries=2,
    )

    final_code, result = await manager.render_with_retries(
        initial_code="from manim import *",
        output_mode="video",
        quality="medium",
    )

    assert final_code.endswith("# repaired")
    assert result.retry_attempts == 1
    assert status_messages == [
        "Starting render attempt 1/3.",
        "Generating repaired code for retry #1.",
        "Retry #1 code generated. Re-rendering now.",
        "Starting render attempt 2/3.",
    ]


@pytest.mark.asyncio
async def test_retry_manager_times_out_repair() -> None:
    class _AlwaysFailRenderer:
        async def render(self, *, code: str, output_mode: str, quality: str) -> RenderResult:
            raise ManimRenderError("render failed")

    async def _slow_repair(_code: str, _error_message: str, _attempt: int) -> GeneratedCode:
        await asyncio.sleep(0.05)
        return GeneratedCode(code="pass", rationale="slow")

    manager = CodeRetryManager(
        renderer=_AlwaysFailRenderer(),
        repair_callback=_slow_repair,
        max_retries=1,
        repair_timeout_seconds=0.01,
    )

    with pytest.raises(ManimRenderError, match="timed out"):
        await manager.render_with_retries(
            initial_code="from manim import *",
            output_mode="video",
            quality="medium",
        )


@pytest.mark.asyncio
async def test_retry_manager_retries_on_visual_review_failure() -> None:
    class _PassRenderer:
        def __init__(self) -> None:
            self.calls = 0

        async def render(self, *, code: str, output_mode: str, quality: str) -> RenderResult:
            self.calls += 1
            return RenderResult(output_mode=output_mode, artifacts=[], quality=quality)

    renderer = _PassRenderer()
    review_calls = 0

    async def _review_callback(code: str, _render_result: RenderResult) -> VisualReviewResult:
        nonlocal review_calls
        review_calls += 1
        if review_calls == 1:
            assert "# repaired" not in code
            return VisualReviewResult(
                passed=False,
                summary="Labels overlap with the triangle edges.",
                suggested_fix="Move labels outward and increase spacing.",
                reviewed_frames=3,
            )
        assert code.endswith("# repaired")
        return VisualReviewResult(
            passed=True,
            summary="Visuals are clear.",
            reviewed_frames=3,
        )

    async def _repair_callback(code: str, error_message: str, attempt: int) -> GeneratedCode:
        assert "Visual review failed" in error_message
        assert "Move labels outward" in error_message
        assert attempt == 1
        return GeneratedCode(code=code + "\n# repaired", rationale="layout fix")

    manager = CodeRetryManager(
        renderer=renderer,
        repair_callback=_repair_callback,
        review_callback=_review_callback,
        max_retries=2,
    )

    final_code, result = await manager.render_with_retries(
        initial_code="from manim import *",
        output_mode="video",
        quality="medium",
    )

    assert review_calls == 2
    assert renderer.calls == 2
    assert final_code.endswith("# repaired")
    assert result.visual_review is not None
    assert result.visual_review.passed is True
    assert result.retry_attempts == 1


@pytest.mark.asyncio
async def test_retry_manager_returns_best_effort_result_when_visual_review_still_fails() -> None:
    class _PassRenderer:
        async def render(self, *, code: str, output_mode: str, quality: str) -> RenderResult:
            return RenderResult(output_mode=output_mode, artifacts=[], quality=quality)

    status_messages: list[str] = []

    async def _on_status(message: str) -> None:
        status_messages.append(message)

    async def _review_callback(_code: str, _render_result: RenderResult) -> VisualReviewResult:
        return VisualReviewResult(
            passed=False,
            summary="Camera framing still cuts off labels.",
            suggested_fix="Zoom out and keep labels inside frame.",
            reviewed_frames=3,
        )

    async def _repair_callback(code: str, _error_message: str, _attempt: int) -> GeneratedCode:
        return GeneratedCode(code=code + "\n# repaired", rationale="frame fix")

    manager = CodeRetryManager(
        renderer=_PassRenderer(),
        repair_callback=_repair_callback,
        review_callback=_review_callback,
        on_status=_on_status,
        max_retries=1,
    )

    final_code, result = await manager.render_with_retries(
        initial_code="from manim import *",
        output_mode="video",
        quality="medium",
    )

    assert final_code.endswith("# repaired")
    assert result.visual_review is not None
    assert result.visual_review.passed is False
    assert result.visual_review.summary == "Camera framing still cuts off labels."
    assert result.retry_attempts == 1
    assert status_messages[-1] == (
        "Visual review still found issues after all retries. Returning the best available result with a warning."
    )


@pytest.mark.asyncio
async def test_visual_review_timeout_respects_retry_limit() -> None:
    class Renderer:
        async def render(self, *, code, output_mode, quality):
            return RenderResult(output_mode=output_mode, quality=quality)

    review_calls = 0
    repair_calls = 0

    async def slow_review(code, result):
        nonlocal review_calls
        review_calls += 1
        await asyncio.sleep(1)

    async def repair(code, error, attempt):
        nonlocal repair_calls
        repair_calls += 1
        assert "Visual quality review timed out" in error
        return GeneratedCode(code=code)

    manager = CodeRetryManager(
        renderer=Renderer(),
        repair_callback=repair,
        review_callback=slow_review,
        review_timeout_seconds=0.01,
        max_retries=1,
    )
    with pytest.raises(ManimRenderError, match="Visual quality review timed out"):
        await manager.render_with_retries(
            initial_code="pass", output_mode="video", quality="medium"
        )
    assert review_calls == 2
    assert repair_calls == 1


@pytest.mark.asyncio
async def test_unavailable_review_is_not_recorded_as_passed():
    class Renderer:
        async def render(self, **kwargs):
            return RenderResult(output_mode="video", quality="low")

    async def repair(*args):
        raise AssertionError("unavailable review is not a layout failure")

    async def review(*args):
        return None

    manager = CodeRetryManager(renderer=Renderer(), repair_callback=repair, review_callback=review)
    _, result = await manager.render_with_retries(
        initial_code="scene", output_mode="video", quality="low"
    )
    assert result.visual_review is None


@pytest.mark.asyncio
async def test_geometry_probe_reaps_cancelled_process(monkeypatch):
    from deeptutor.agents.math_animator import layout_probe

    class Process:
        returncode = None
        killed = waited = False

        async def communicate(self):
            raise asyncio.CancelledError

        def kill(self):
            self.killed = True

        async def wait(self):
            self.waited = True

    proc = Process()

    async def create(*args, **kwargs):
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)
    with pytest.raises(asyncio.CancelledError):
        await layout_probe.geometry_review("class Demo(Scene): pass")
    assert proc.killed and proc.waited


@pytest.mark.asyncio
async def test_geometry_probe_unsupported_subprocess_transport_is_unavailable(monkeypatch):
    from deeptutor.agents.math_animator import layout_probe

    async def unsupported(*args, **kwargs):
        raise NotImplementedError("SelectorEventLoop subprocess transport")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", unsupported)
    assert await layout_probe.geometry_review("class Demo(Scene): pass") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_geometry_probe_reaps_real_process_on_timeout_or_cancel(monkeypatch, cancel):
    import sys

    from deeptutor.agents.math_animator import layout_probe

    if sys.platform == "win32":
        pytest.skip("Asyncio subprocess transport is loop-dependent on Windows")
    create_subprocess = asyncio.create_subprocess_exec
    started = asyncio.Event()
    processes = []

    async def create(*args, **kwargs):
        process = await create_subprocess(
            sys.executable, "-c", "import time; time.sleep(30)", **kwargs
        )
        processes.append(process)
        started.set()
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)
    monkeypatch.setattr(layout_probe, "PROBE_TIMEOUT_S", 30 if cancel else 0.05)
    task = asyncio.create_task(layout_probe.geometry_review("class Demo(Scene): pass"))
    await asyncio.wait_for(started.wait(), timeout=5)
    if cancel:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=5)
    else:
        assert await asyncio.wait_for(task, timeout=5) is None
    assert processes[0].returncode is not None


@pytest.mark.asyncio
async def test_geometry_probe_timeout_preserves_rendered_video(monkeypatch):
    from deeptutor.agents.math_animator import layout_probe

    class Renderer:
        async def render(self, **kwargs):
            return RenderResult(output_mode="video", quality="low")

    async def repair(*args):
        raise AssertionError("An unavailable advisory check must not repair a valid render")

    async def review(code, result):
        return await layout_probe.geometry_review(code)

    class Process:
        returncode = None

        async def communicate(self):
            await asyncio.sleep(30)

        def kill(self):
            self.returncode = -9

        async def wait(self):
            return self.returncode

    async def create(*args, **kwargs):
        return Process()

    manager = CodeRetryManager(
        renderer=Renderer(), repair_callback=repair, review_callback=review, max_retries=0
    )
    # Keep the real production timeout ordering, at a faster test scale.
    assert layout_probe.PROBE_TIMEOUT_S < manager.review_timeout_seconds
    manager.review_timeout_seconds /= 1000
    monkeypatch.setattr(layout_probe, "PROBE_TIMEOUT_S", layout_probe.PROBE_TIMEOUT_S / 1000)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)
    _, result = await manager.render_with_retries(
        initial_code="class Demo(Scene): pass", output_mode="video", quality="low"
    )
    assert result.visual_review is None
    assert result.retry_attempts == 0
