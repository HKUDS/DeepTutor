# -*- coding: utf-8 -*-
"""
TTS Configuration
=================

Configuration management for Text-to-Speech services.
Simplified version - loads from unified config service or falls back to .env.
"""

import logging
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load environment variables
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
load_dotenv(PROJECT_ROOT / "DeepTutor.env", override=False)
load_dotenv(PROJECT_ROOT / ".env", override=False)


def _strip_value(value: Optional[str]) -> Optional[str]:
    """Remove leading/trailing whitespace and quotes from string."""
    if value is None:
        return None
    return value.strip().strip("\"'")


def get_tts_config() -> dict:
    """
    Return complete configuration for TTS (Text-to-Speech).

    Priority:
    1. Active configuration from unified config service
    2. Environment variables (.env)

    Returns:
        dict: Dictionary containing the following keys:
            - model: TTS model name
            - api_key: TTS API key
            - base_url: TTS API endpoint URL
            - api_version: TTS API version (for Azure OpenAI)
            - voice: Default voice character

    Raises:
        ValueError: If required configuration is missing
    """
    # 1. Try to get active config from unified config service
    try:
        from src.services.config import get_active_tts_config

        config = get_active_tts_config()
        if config and config.get("model"):
            return {
                "model": config["model"],
                "api_key": config.get("api_key", ""),
                "base_url": config.get("base_url", ""),
                "api_version": config.get("api_version"),
                "voice": config.get("voice", "alloy"),
            }
    except ImportError:
        # Unified config service not yet available, fall back to env
        pass
    except Exception as e:
        logger.warning(f"Failed to load from unified config: {e}")

    # 2. Fallback to environment variables
    model = _strip_value(os.getenv("TTS_MODEL"))
    api_key = _strip_value(os.getenv("TTS_API_KEY"))
    base_url = _strip_value(os.getenv("TTS_URL"))
    api_version = _strip_value(os.getenv("TTS_BINDING_API_VERSION"))
    voice = _strip_value(os.getenv("TTS_VOICE", "alloy"))

    # Validate required configuration
    if not model:
        raise ValueError(
            "TTS_MODEL not set. Please configure it in .env file or add a configuration in Settings"
        )
    if not api_key:
        raise ValueError(
            "TTS_API_KEY not set. Please configure it in .env file or add a configuration in Settings"
        )
    if not base_url:
        raise ValueError(
            "TTS_URL not set. Please configure it in .env file or add a configuration in Settings"
        )

    return {
        "model": model,
        "api_key": api_key,
        "base_url": base_url,
        "api_version": api_version,
        "voice": voice,
    }


__all__ = ["get_tts_config"]
