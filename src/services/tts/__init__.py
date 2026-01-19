# -*- coding: utf-8 -*-
"""
TTS Service
===========

Text-to-Speech configuration for DeepTutor.

Usage:
    from src.services.tts import get_tts_config

    config = get_tts_config()
    # config = {"model": "tts-1", "api_key": "...", "base_url": "...", "voice": "alloy"}
"""

from .config import get_tts_config

__all__ = ["get_tts_config"]
