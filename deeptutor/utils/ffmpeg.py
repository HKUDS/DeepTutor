"""FFmpeg utilities for audio/video muxing."""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)


class FFmpegError(RuntimeError):
    """Raised when FFmpeg operation fails."""

    pass


async def mux_audio_video(
    video_path: str | Path,
    audio_path: str | Path,
    output_path: str | Path | None = None,
    audio_offset_ms: int = 0,
    video_codec: str = "copy",
    audio_codec: str = "aac",
    audio_bitrate: str = "192k",
    progress_callback: Callable[[str], None] | None = None,
) -> Path:
    """Mux audio and video into a single file using FFmpeg.

    Args:
        video_path: Path to video file (MP4)
        audio_path: Path to audio file (MP3/WAV)
        output_path: Output path (default: temp file)
        audio_offset_ms: Audio delay in milliseconds (positive = delay)
        video_codec: Video codec ("copy" = no re-encode)
        audio_codec: Audio codec ("aac" recommended)
        audio_bitrate: Audio bitrate ("192k" recommended)
        progress_callback: Progress callback

    Returns:
        Path to output file

    Raises:
        FFmpegError: If FFmpeg fails
    """
    video_path = Path(video_path)
    audio_path = Path(audio_path)

    if not video_path.exists():
        raise FFmpegError(f"Video file not found: {video_path}")
    if not audio_path.exists():
        raise FFmpegError(f"Audio file not found: {audio_path}")

    # Generate output path if not provided
    if output_path is None:
        output_path = Path(tempfile.gettempdir()) / f"muxed_{video_path.stem}.mp4"
    else:
        output_path = Path(output_path)

    # Build FFmpeg command
    command = [
        "ffmpeg",
        "-y",  # Overwrite output
        "-i", str(video_path),
        "-i", str(audio_path),
    ]

    # Audio offset (delay)
    if audio_offset_ms != 0:
        command.extend(["-itsoffset", str(audio_offset_ms / 1000)])

    # Codecs
    command.extend([
        "-c:v", video_codec,
        "-c:a", audio_codec,
        "-b:a", audio_bitrate,
    ])

    # Ensure output matches shortest input
    command.append("-shortest")

    # Optimize for web streaming
    command.extend(["-movflags", "+faststart"])

    # Output file
    command.append(str(output_path))

    if progress_callback:
        progress_callback(f"Running FFmpeg: {' '.join(command)}")

    logger.info(f"FFmpeg command: {' '.join(command)}")

    # Run FFmpeg
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error_msg = stderr.decode("utf-8", errors="ignore")
            logger.error(f"FFmpeg failed: {error_msg}")
            raise FFmpegError(f"FFmpeg failed (code {process.returncode}): {error_msg[:500]}")

        if not output_path.exists():
            raise FFmpegError("FFmpeg completed but output file not created")

        logger.info(f"Successfully muxed to {output_path}")
        return output_path

    except FileNotFoundError:
        raise FFmpegError("FFmpeg not found. Please install FFmpeg.")


async def get_media_duration(path: str | Path) -> float:
    """Get media file duration using ffprobe.

    Args:
        path: Path to media file

    Returns:
        Duration in seconds
    """
    path = Path(path)
    if not path.exists():
        raise FFmpegError(f"File not found: {path}")

    command = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]

    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            raise FFmpegError(f"ffprobe failed: {stderr.decode()}")

        duration = float(stdout.decode().strip())
        return duration

    except FileNotFoundError:
        raise FFmpegError("ffprobe not found. Please install FFmpeg.")


def check_ffmpeg_available() -> bool:
    """Check if FFmpeg is installed and available."""
    return shutil.which("ffmpeg") is not None


def check_ffprobe_available() -> bool:
    """Check if ffprobe is installed and available."""
    return shutil.which("ffprobe") is not None


__all__ = [
    "FFmpegError",
    "mux_audio_video",
    "get_media_duration",
    "check_ffmpeg_available",
    "check_ffprobe_available",
]
