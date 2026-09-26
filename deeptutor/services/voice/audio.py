"""Audio containers and bounded normalization shared by native speech adapters."""

from __future__ import annotations

import asyncio
import io
from pathlib import Path
import tempfile
import wave

from .base import VoiceProviderError


def pcm_to_wav(audio: bytes, sample_rate: int = 24000) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(audio)
    return output.getvalue()


async def normalize_wav(audio: bytes) -> bytes:
    """16 kHz mono signed PCM WAV; ffmpeg handles browser WebM/Opus too."""
    try:
        with wave.open(io.BytesIO(audio), "rb") as wav:
            if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getcomptype()) == (
                1,
                2,
                16000,
                "NONE",
            ):
                return audio
    except (wave.Error, EOFError):
        pass
    with tempfile.TemporaryDirectory(prefix="deeptutor-voice-") as directory:
        source, target = Path(directory) / "input", Path(directory) / "output.wav"
        source.write_bytes(audio)
        try:
            process = await asyncio.create_subprocess_exec(
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(source),
                "-vn",
                "-acodec",
                "pcm_s16le",
                "-ar",
                "16000",
                "-ac",
                "1",
                str(target),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            raise VoiceProviderError(
                "ffmpeg is required to convert this recording to WAV."
            ) from exc
        try:
            _, stderr = await asyncio.wait_for(process.communicate(), timeout=60)
        except (TimeoutError, asyncio.CancelledError) as exc:
            if process.returncode is None:
                process.kill()
            await process.wait()
            if isinstance(exc, TimeoutError):
                raise VoiceProviderError("Audio conversion timed out.") from exc
            raise
        if process.returncode:
            raise VoiceProviderError(
                "Audio conversion failed: " + stderr.decode(errors="replace")[:200]
            )
        return target.read_bytes()


def _parse_pcm_content_type(content_type: str) -> tuple[int, int] | None:
    """Return ``(sample_rate, channels)`` when a provider sent raw PCM audio."""
    media_type, *params = (content_type or "").split(";")
    if media_type.strip().lower() not in {"audio/pcm", "audio/x-pcm", "audio/l16"}:
        return None
    sample_rate = 24000
    channels = 1
    for item in params:
        key, sep, value = item.strip().partition("=")
        if not sep:
            continue
        key = key.strip().lower()
        value = value.strip().strip('"')
        try:
            parsed = int(value)
        except ValueError:
            continue
        if key in {"rate", "sample-rate", "samplerate"} and parsed > 0:
            sample_rate = parsed
        elif key in {"channels", "channel"} and parsed > 0:
            channels = parsed
    return sample_rate, channels


def _pcm16_to_wav(audio: bytes, *, sample_rate: int, channels: int) -> bytes:
    """Wrap provider PCM16 bytes in a WAV container browsers can play."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(audio)
    return buffer.getvalue()
