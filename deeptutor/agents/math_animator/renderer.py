"""Manim rendering service for the math animator capability."""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path
from typing import Awaitable, Callable

from deeptutor.services.path_service import get_path_service

from .models import RenderResult, RenderedArtifact
from .utils import slugify_filename, trim_error_message

YON_IMAGE_PATTERN = re.compile(
    r"###\s*YON_IMAGE_(\d+)_START\s*###\s*(.*?)\s*###\s*YON_IMAGE_\1_END\s*###",
    re.DOTALL | re.IGNORECASE,
)
SCENE_PATTERN = re.compile(r"class\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(\s*.*?Scene.*?\)\s*:")

QUALITY_FLAG_MAP = {
    "low": "-ql",
    "medium": "-qm",
    "high": "-qh",
}


class ManimRenderError(RuntimeError):
    """Raised when Manim rendering fails."""


class ManimRenderService:
    def __init__(
        self,
        turn_id: str,
        progress_callback: Callable[[str, bool], Awaitable[None]] | None = None,
    ) -> None:
        self.turn_id = turn_id
        self.path_service = get_path_service()
        self.progress_callback = progress_callback
        self.base_dir = self.path_service.get_agent_dir("math_animator") / turn_id
        self.source_dir = self.base_dir / "source"
        self.artifacts_dir = self.base_dir / "artifacts"
        self.media_dir = self.base_dir / "media"
        self.meta_dir = self.base_dir / "meta"
        for path in (self.source_dir, self.artifacts_dir, self.media_dir, self.meta_dir):
            path.mkdir(parents=True, exist_ok=True)

    async def render(self, *, code: str, output_mode: str, quality: str) -> RenderResult:
        await self._emit_progress(
            f"Preparing {output_mode} render workspace (quality={quality})."
        )
        source_name = "scene.py" if output_mode == "video" else "scene_image.py"
        source_path = self.source_dir / source_name
        source_path.write_text(code, encoding="utf-8")
        await self._emit_progress(f"Saved generated code to {source_name}.", raw=True)

        if output_mode == "image":
            artifacts = await self._render_image_blocks(code=code, quality=quality)
        else:
            artifacts = [await self._render_video(code_path=source_path, quality=quality)]

        return RenderResult(
            output_mode=output_mode,
            artifacts=artifacts,
            source_code_path=str(source_path),
            quality=quality,
        )

    async def _render_video(self, *, code_path: Path, quality: str) -> RenderedArtifact:
        scene_name = self._extract_scene_name(code_path.read_text(encoding="utf-8"))
        await self._emit_progress(f"Launching Manim scene `{scene_name}`.")
        await self._run_manim(code_path=code_path, scene_name=scene_name, quality=quality, save_last_frame=False)
        video_file = self._find_rendered_file(".mp4")
        target_name = slugify_filename(f"{self.turn_id}-{scene_name}.mp4", f"{self.turn_id}.mp4")
        artifact_path = self.artifacts_dir / target_name
        artifact_path.write_bytes(video_file.read_bytes())
        await self._emit_progress(f"Saved rendered video as {artifact_path.name}.")
        return self._build_artifact(artifact_path, "video", "video/mp4", "Animation video")

    async def _render_image_blocks(self, *, code: str, quality: str) -> list[RenderedArtifact]:
        matches = list(YON_IMAGE_PATTERN.finditer(code))
        if not matches:
            raise ManimRenderError(
                "Image mode requires code blocks wrapped in ### YON_IMAGE_n_START ### / END ###."
            )

        residual = YON_IMAGE_PATTERN.sub("", code).strip()
        if residual:
            raise ManimRenderError("Image mode code must only contain YON_IMAGE anchor blocks.")

        artifacts: list[RenderedArtifact] = []
        for idx, match in enumerate(matches, start=1):
            block_code = match.group(2).strip()
            block_path = self.source_dir / f"image_block_{idx:02d}.py"
            block_path.write_text(block_code, encoding="utf-8")
            scene_name = self._extract_scene_name(block_code)
            await self._emit_progress(
                f"Rendering image block {idx}/{len(matches)} with scene `{scene_name}`."
            )
            await self._run_manim(
                code_path=block_path,
                scene_name=scene_name,
                quality=quality,
                save_last_frame=True,
            )
            image_file = self._find_rendered_file(".png")
            artifact_path = self.artifacts_dir / f"image-{idx:02d}.png"
            artifact_path.write_bytes(image_file.read_bytes())
            await self._emit_progress(f"Saved image artifact {artifact_path.name}.")
            artifacts.append(
                self._build_artifact(
                    artifact_path,
                    "image",
                    "image/png",
                    f"Image {idx}",
                )
            )
        return artifacts

    async def _run_manim(
        self,
        *,
        code_path: Path,
        scene_name: str,
        quality: str,
        save_last_frame: bool,
    ) -> None:
        quality_flag = QUALITY_FLAG_MAP.get(quality, "-qm")
        command = [
            sys.executable,
            "-m",
            "manim",
            quality_flag,
            str(code_path),
            scene_name,
            "--media_dir",
            str(self.media_dir),
            "--progress_bar",
            "none",
        ]
        if save_last_frame:
            command.append("-s")
        else:
            command.extend(["--format", "mp4"])

        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await self._emit_progress(
            f"Started Manim process for `{scene_name}` with command: {' '.join(command)}",
            raw=True,
        )
        stdout_lines: list[str] = []
        stderr_lines: list[str] = []

        async def _drain_stream(
            stream: asyncio.StreamReader | None,
            sink: list[str],
            *,
            prefix: str,
        ) -> None:
            if stream is None:
                return
            while True:
                raw_line = await stream.readline()
                if not raw_line:
                    break
                line = raw_line.decode(errors="ignore").strip()
                if not line:
                    continue
                sink.append(line)
                await self._emit_progress(f"[{prefix}] {line}", raw=True)

        await asyncio.gather(
            _drain_stream(process.stdout, stdout_lines, prefix="stdout"),
            _drain_stream(process.stderr, stderr_lines, prefix="stderr"),
        )
        await process.wait()
        await self._emit_progress(f"Manim process finished with exit code {process.returncode}.", raw=True)
        if process.returncode != 0:
            raise ManimRenderError(
                trim_error_message(
                    "\n".join(part for part in ["\n".join(stdout_lines), "\n".join(stderr_lines)] if part)
                )
            )

    async def _emit_progress(self, message: str, raw: bool = False) -> None:
        if self.progress_callback is None:
            return
        await self.progress_callback(message, raw)

    def _find_rendered_file(self, suffix: str) -> Path:
        # Manim stores many transient chunks under ``partial_movie_files``.
        # We only want the final exported artifact for the scene.
        matches = [
            path
            for path in self.media_dir.rglob(f"*{suffix}")
            if "partial_movie_files" not in path.parts
        ]
        if not matches:
            matches = list(self.media_dir.rglob(f"*{suffix}"))
        if not matches:
            raise ManimRenderError(f"Rendered {suffix} artifact not found.")
        return max(matches, key=lambda path: path.stat().st_mtime)

    @staticmethod
    def _extract_scene_name(code: str) -> str:
        match = SCENE_PATTERN.search(code)
        if not match:
            raise ManimRenderError("Generated code does not define a renderable Manim Scene class.")
        return match.group(1)

    def _build_artifact(
        self,
        artifact_path: Path,
        artifact_type: str,
        content_type: str,
        label: str,
    ) -> RenderedArtifact:
        rel_path = artifact_path.resolve().relative_to(self.path_service.user_data_dir.resolve())
        return RenderedArtifact(
            type=artifact_type,
            filename=artifact_path.name,
            url=f"/api/outputs/{rel_path.as_posix()}",
            content_type=content_type,
            label=label,
        )


__all__ = [
    "ManimRenderError",
    "ManimRenderService",
    "YON_IMAGE_PATTERN",
]
