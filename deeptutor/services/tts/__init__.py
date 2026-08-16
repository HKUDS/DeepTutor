from __future__ import annotations

"""TTS service package exports."""

from .config import TTSConfig
from .providers import get_tts_provider

__all__ = ["TTSConfig", "get_tts_provider"]
