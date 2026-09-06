"""Frame extraction utilities for visual quality review."""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from typing import Awaitable, Callable

from deeptutor.core.context import Attachment
from deeptutor.services.path_service import get_path_service

from .models import RenderResult
from .renderer import ManimRenderError


class VisualReviewService:
    def __init__(
        self,
        turn_id: str,
        progress_callback: Callable[[str, bool], Awaitable[None]] | None = None,
        *,
        output_dir: str | Path | None = None,
    ) -> None:
        self.turn_id = turn_id
        self.progress_callback = progress_callback
        self.base_dir = (
            Path(output_dir).resolve()
            if output_dir
            else get_path_service().get_agent_dir("math_animator") / turn_id
        )
        self.artifacts_dir = self.base_dir / "artifacts"
        self.review_dir = self.base_dir / "review"
        self.review_dir.mkdir(parents=True, exist_ok=True)

    async def build_attachments(self, render_result: RenderResult) -> list[Attachment]:
        if render_result.output_mode == "image":
            await self._emit_progress(
                f"Preparing {len(render_result.artifacts)} rendered image(s) for visual review."
            )
            return [
                self._path_to_attachment(self.artifacts_dir / artifact.filename)
                for artifact in render_result.artifacts
            ]

        video_artifact = next(
            (artifact for artifact in render_result.artifacts if artifact.type == "video"), None
        )
        if video_artifact is None:
            return []

        video_path = self.artifacts_dir / video_artifact.filename
        frame_paths = await self._extract_video_frames(video_path)
        await self._emit_progress(
            f"Prepared {len(frame_paths)} review frame(s) from rendered video."
        )
        return [self._path_to_attachment(path) for path in frame_paths]

    async def _extract_video_frames(self, video_path: Path) -> list[Path]:
        if not video_path.exists():
            raise ManimRenderError("Rendered video artifact missing for visual review.")

        duration = await self._probe_duration(video_path)
        timestamps = self._choose_timestamps(duration)
        frame_paths: list[Path] = []
        for idx, timestamp in enumerate(timestamps, start=1):
            frame_path = self.review_dir / f"review_frame_{idx:02d}.png"
            command = [
                "ffmpeg",
                "-y",
                "-ss",
                f"{timestamp:.3f}",
                "-i",
                str(video_path),
                "-frames:v",
                "1",
                str(frame_path),
            ]
            await self._emit_progress(
                f"Extracting review frame {idx}/{len(timestamps)} at {timestamp:.1f}s.",
                raw=True,
            )
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _stdout, stderr = await process.communicate()
            if process.returncode != 0 or not frame_path.exists():
                raise ManimRenderError(
                    "Failed to extract review frames: " + stderr.decode(errors="ignore").strip()
                )
            frame_paths.append(frame_path)
        return frame_paths

    async def _probe_duration(self, video_path: Path) -> float:
        command = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ]
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            raise ManimRenderError(
                "Failed to inspect rendered video duration: "
                + stderr.decode(errors="ignore").strip()
            )
        try:
            return max(float(stdout.decode().strip() or "0"), 0.0)
        except ValueError as exc:
            raise ManimRenderError(
                "Rendered video duration could not be parsed for visual review."
            ) from exc

    @staticmethod
    def _choose_timestamps(duration: float) -> list[float]:
        if duration <= 0:
            return [0.0]
        if duration < 2:
            return [0.0, min(duration / 2, duration), max(duration - 0.05, 0.0)]
        return [
            max(duration * 0.15, 0.0),
            min(duration * 0.5, duration),
            max(duration * 0.85, 0.0),
        ]

    @staticmethod
    def _path_to_attachment(path: Path) -> Attachment:
        suffix = path.suffix.lower()
        mime_type = "image/jpeg" if suffix in {".jpg", ".jpeg"} else "image/png"
        return Attachment(
            type="image",
            filename=path.name,
            mime_type=mime_type,
            base64=base64.b64encode(path.read_bytes()).decode("utf-8"),
        )

    async def _emit_progress(self, message: str, raw: bool = False) -> None:
        if self.progress_callback is None:
            return
        await self.progress_callback(message, raw)


__all__ = ["VisualReviewService"]
