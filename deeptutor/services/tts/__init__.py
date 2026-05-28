"""TTS Service Layer

Text-to-Speech service providers for generating narration audio.

Usage:
    from deeptutor.services.tts import get_tts_client
    from deeptutor.services.tts.models import TTSAudioResult

    tts = get_tts_client(provider="edge")
    result: TTSAudioResult = await tts.synthesize("Hello, world!")
    print(result.audio_path)
    print(result.duration_seconds)
    for boundary in result.sentence_boundaries:
        print(f"{boundary.start_ms}ms - {boundary.end_ms}ms: {boundary.text}")
"""

from .client import TTSClient, get_tts_client
from .models import SentenceBoundary, TTSAudioResult

__all__ = [
    "TTSClient",
    "get_tts_client",
    "TTSAudioResult",
    "SentenceBoundary",
]
