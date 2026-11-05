"""Microsoft Edge read-aloud voices through the ``edge-tts`` package.

Edge's online voices need no account or API key, which makes them a usable
default when no paid speech provider is configured. The service is not an
official API, so it can be rate limited or change without notice.
Package: https://github.com/rany2/edge-tts
"""

from __future__ import annotations

import math

from deeptutor.services.voice.base import BaseTTSAdapter, VoiceProviderError
from deeptutor.services.voice.config import TTSConfig

EDGE_DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"


def edge_rate(speed: float | None) -> str:
    """Map a 0.5–2 speed multiplier onto edge-tts's signed percentage."""
    if speed is None:
        return "+0%"
    if not math.isfinite(speed) or not 0.5 <= speed <= 2:
        raise VoiceProviderError("Edge speech speed must be between 0.5 and 2.")
    return f"{round((speed - 1) * 100):+d}%"


class EdgeTTSAdapter(BaseTTSAdapter):
    """Stream mp3 audio from Edge's read-aloud service."""

    async def synthesize(self, text: str, config: TTSConfig) -> tuple[bytes, str]:
        try:
            import edge_tts
        except ImportError as exc:
            raise VoiceProviderError(
                "Edge speech needs the edge-tts package: pip install 'deeptutor[edge-tts]'."
            ) from exc
        if (config.response_format or "mp3") != "mp3":
            raise VoiceProviderError("Edge TTS only produces mp3 audio.")
        communicate = edge_tts.Communicate(
            text, config.voice or EDGE_DEFAULT_VOICE, rate=edge_rate(config.speed)
        )
        audio = bytearray()
        try:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio += chunk["data"]
        except Exception as exc:  # edge-tts raises its own and aiohttp errors
            raise VoiceProviderError(f"Edge TTS request failed: {type(exc).__name__}.") from exc
        if not audio:
            raise VoiceProviderError("Edge TTS returned no audio.")
        return bytes(audio), "audio/mpeg"


async def list_edge_voices() -> list[dict]:
    """Every public Edge voice, as voice-discovery rows."""
    import edge_tts

    return [
        {
            "id": row["ShortName"],
            "label": f"{row['ShortName']} ({row.get('Gender', '')})".replace(" ()", ""),
            "languages": [row["Locale"]],
        }
        for row in await edge_tts.list_voices()
        if row.get("ShortName") and row.get("Locale")
    ]
