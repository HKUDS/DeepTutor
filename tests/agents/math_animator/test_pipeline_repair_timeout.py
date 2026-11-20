"""The configured repair deadline must reach the render-fix loop (#2767).

``run_render`` is the single construction site shared by all three callers (the
math_animator capability, the visualize Manim route, and the book
AnimationGenerator), so wiring the knob here covers every path. These tests pin
that the configured value is forwarded, the shipped default is preserved when
unset, the timeout error names the local deadline, and cancellation still works.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
import yaml

from deeptutor.agents.math_animator.models import GeneratedCode, RenderResult
from deeptutor.agents.math_animator.pipeline import MathAnimatorPipeline
from deeptutor.agents.math_animator.renderer import ManimRenderError
from deeptutor.agents.math_animator.request_config import MathAnimatorRequestConfig
from deeptutor.agents.math_animator.retry_manager import CodeRetryManager
from deeptutor.services.config import loader as loader_module
from deeptutor.services.setup.init import DEFAULT_AGENTS_SETTINGS
from deeptutor.utils.config_manager import ConfigManager


@pytest.fixture(autouse=True)
def _reset_config_manager_singleton():
    ConfigManager.reset_for_tests()
    yield
    ConfigManager.reset_for_tests()


def _seed_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, main_content: dict[str, Any] | None
) -> None:
    """Isolate both config files so the test needs no ambient runtime state.

    Pipeline construction reads agents.yaml via ``loader.PROJECT_ROOT``; the
    repair-timeout getter reads main.yaml via the ``ConfigManager`` singleton.
    Point both at tmp and seed the shipped agents defaults.
    """
    settings_dir = tmp_path / "data" / "user" / "settings"
    settings_dir.mkdir(parents=True, exist_ok=True)
    (settings_dir / "agents.yaml").write_text(yaml.dump(DEFAULT_AGENTS_SETTINGS), encoding="utf-8")
    if main_content is not None:
        (settings_dir / "main.yaml").write_text(yaml.dump(main_content), encoding="utf-8")
    monkeypatch.setattr(loader_module, "PROJECT_ROOT", tmp_path)
    ConfigManager(project_root=tmp_path)


class _Renderer:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def render(self, *, code: str, output_mode: str, quality: str) -> RenderResult:
        return RenderResult(output_mode=output_mode, quality=quality)


async def _run_render_capturing_manager(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, main_content: dict[str, Any] | None
) -> dict[str, Any]:
    """Drive run_render with a fake retry manager that records its kwargs."""
    _seed_settings(monkeypatch, tmp_path, main_content)
    captured: dict[str, Any] = {}

    class _CapturingRetryManager:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

        async def render_with_retries(
            self, *, initial_code: str, output_mode: str, quality: str
        ) -> tuple[str, RenderResult]:
            return initial_code, RenderResult(output_mode=output_mode, quality=quality)

    monkeypatch.setattr("deeptutor.agents.math_animator.pipeline.ManimRenderService", _Renderer)
    monkeypatch.setattr(
        "deeptutor.agents.math_animator.pipeline.CodeRetryManager", _CapturingRetryManager
    )

    pipeline = MathAnimatorPipeline(
        api_key="test", base_url=None, api_version=None, enable_visual_review=False
    )
    # output_mode="image" skips the video geometry-probe branch, so no subprocess.
    await pipeline.run_render(
        turn_id="test-repair-timeout",
        user_input="Explain a circle",
        request_config=MathAnimatorRequestConfig(output_mode="image"),
        initial_code="pass",
    )
    return captured


@pytest.mark.asyncio
async def test_run_render_forwards_the_configured_repair_deadline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured = await _run_render_capturing_manager(
        monkeypatch, tmp_path, {"capabilities": {"math_animator": {"repair_timeout": 7}}}
    )

    assert captured.get("repair_timeout_seconds") == 7
    # The retry budget is unchanged by this fix.
    assert captured.get("max_retries") == 4


@pytest.mark.asyncio
async def test_run_render_keeps_the_default_deadline_when_unset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured = await _run_render_capturing_manager(monkeypatch, tmp_path, None)

    assert captured.get("repair_timeout_seconds") == 180


@pytest.mark.asyncio
async def test_repair_timeout_error_names_the_local_deadline_and_setting() -> None:
    class _AlwaysFailRenderer:
        async def render(self, *, code: str, output_mode: str, quality: str) -> RenderResult:
            raise ManimRenderError("render failed")

    async def _slow_repair(_code: str, _error: str, _attempt: int) -> GeneratedCode:
        await asyncio.sleep(1)
        return GeneratedCode(code="pass")

    manager = CodeRetryManager(
        renderer=_AlwaysFailRenderer(),
        repair_callback=_slow_repair,
        max_retries=1,
        repair_timeout_seconds=0.01,
    )

    with pytest.raises(ManimRenderError) as excinfo:
        await manager.render_with_retries(
            initial_code="from manim import *", output_mode="image", quality="medium"
        )

    message = str(excinfo.value)
    # The existing "timed out" contract is preserved.
    assert "timed out" in message
    # The error now names the stage, the effective seconds, and that this is a
    # local overall deadline the user can raise — not a provider connection fault.
    assert "Code repair" in message
    assert "local" in message
    assert "capabilities.math_animator.repair_timeout" in message
    assert "not a provider connection failure" in message


@pytest.mark.asyncio
async def test_repair_timeout_cancels_the_running_repair_coroutine() -> None:
    """A timed-out repair must be cancelled, not left running in the background."""

    class _AlwaysFailRenderer:
        async def render(self, *, code: str, output_mode: str, quality: str) -> RenderResult:
            raise ManimRenderError("render failed")

    cancelled = False

    async def _slow_repair(_code: str, _error: str, _attempt: int) -> GeneratedCode:
        nonlocal cancelled
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled = True
            raise
        return GeneratedCode(code="pass")

    manager = CodeRetryManager(
        renderer=_AlwaysFailRenderer(),
        repair_callback=_slow_repair,
        max_retries=1,
        repair_timeout_seconds=0.01,
    )

    with pytest.raises(ManimRenderError, match="timed out"):
        await manager.render_with_retries(
            initial_code="from manim import *", output_mode="image", quality="medium"
        )

    assert cancelled is True
