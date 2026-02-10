"""
TTS Configuration
=================

Configuration management for Text-to-Speech services.
"""

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

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
    Return complete environment configuration for TTS (Text-to-Speech).

    Returns:
        dict: Dictionary containing the following keys:
            - model: TTS model name
            - api_key: TTS API key
            - base_url: TTS API endpoint URL
            - voice: Default voice character

    Raises:
        ValueError: If required configuration is missing
    """
    model = _strip_value(os.getenv("TTS_MODEL"))
    api_key = _strip_value(os.getenv("TTS_API_KEY"))
    base_url = _strip_value(os.getenv("TTS_URL"))
    voice = _strip_value(os.getenv("TTS_VOICE", "alloy"))

    provider = _strip_value(os.getenv("TTS_PROVIDER", "openai"))
    
    # Common config
    config = {
        "provider": provider,
        "voice": voice,
    }

    if provider == "doubao":
        app_id = _strip_value(os.getenv("TTS_DOUBAO_APP_ID"))
        access_token = _strip_value(os.getenv("TTS_DOUBAO_ACCESS_TOKEN"))
        cluster = _strip_value(os.getenv("TTS_DOUBAO_CLUSTER", "volc_ttos_samantha"))
        base_url = _strip_value(os.getenv("TTS_DOUBAO_URL", "wss://openspeech.bytedance.com/api/v3/sami/podcasttts"))
        
        if not app_id or not access_token:
             # Fallback to check if user put them in standard fields? Or just raise error
             # Let's enforce specific env vars for clarity, or reuse API_KEY as token?
             # To avoid confusion, let's keep them separate as per plan.
             pass

        # We allow partial config if just checking status, but validation should happen on usage or here if strict.
        # Let's be permissive here and validate in agent or client if needed, 
        # but the original code raised ValueErrors. Let's maintain that for "openai" but for new provider we need conditional validation.
        
        if not app_id:
             raise ValueError("Error: TTS_DOUBAO_APP_ID not set for Doubao provider")
        if not access_token:
             raise ValueError("Error: TTS_DOUBAO_ACCESS_TOKEN not set for Doubao provider")
             
        config.update({
            "app_id": app_id,
            "access_token": access_token,
            "cluster": cluster,
            "base_url": base_url,
            "model": "doubao-podcast",
        })
        
    else:
        # Default OpenAI compatible
        
        # Validate required configuration only if provider is openai (default)
        if not model:
            raise ValueError(
                "Error: TTS_MODEL not set, please configure it in .env file (e.g., tts-1 or tts-1-hd)"
            )
        if not api_key:
            raise ValueError("Error: TTS_API_KEY not set, please configure it in .env file")
        if not base_url:
            raise ValueError(
                "Error: TTS_URL not set, please configure it in .env file (e.g., https://api.openai.com/v1)"
            )

        config.update({
            "model": model,
            "api_key": api_key,
            "base_url": base_url,
        })

    return config


__all__ = ["get_tts_config"]
