"""A missing generated source must not hide Manim's actual failure."""

from __future__ import annotations

from io import BytesIO

import pytest

from deeptutor.agents.math_animator.renderer import ManimRenderError, ManimRenderService


@pytest.mark.asyncio
async def test_failed_manim_preserves_stderr_when_source_disappears(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    class FailedProcess:
        stdout = BytesIO(b"")
        stderr = BytesIO(b"FileNotFoundError: latex compiler missing\n")

        def wait(self) -> int:
            return 1

    monkeypatch.setattr(
        "deeptutor.agents.math_animator.renderer.subprocess.Popen",
        lambda *_args, **_kwargs: FailedProcess(),
    )
    service = ManimRenderService("test", output_dir=tmp_path)

    with pytest.raises(ManimRenderError, match="latex compiler missing"):
        await service._run_manim(
            code_path=tmp_path / "missing_scene.py",
            scene_name="TestScene",
            quality="low",
            save_last_frame=False,
        )
